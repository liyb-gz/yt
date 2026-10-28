"""Thinking controls and bounded fallback through the native HTTP adapters."""

import json
from unittest.mock import MagicMock

import httpx
import pytest
import yaml

from yt.config import Config, LLMConfig
from yt.llm import build_request
from yt.transcript import TranscriptFetcher
from yt.translate import TranslationClient, TranslationError


RESULTS = {
    "chat_completions": {"choices": [{"message": {"content": "Final text"}}]},
    "responses": {"output": [
        {"type": "reasoning", "summary": [{"text": "Private thoughts"}]},
        {"type": "message", "content": [{"type": "output_text", "text": "Final text"}]},
    ]},
    "anthropic": {"content": [
        {"type": "thinking", "thinking": "Private thoughts"},
        {"type": "text", "text": "Final text"},
    ]},
    "gemini": {"candidates": [{"content": {"parts": [
        {"thought": True, "text": "Private thoughts"}, {"text": "Final text"},
    ]}}]},
}

REJECTIONS = {
    "chat_completions": {"error": {
        "message": "Unsupported value for reasoning_effort: max",
        "param": "reasoning_effort", "code": "unsupported_value",
    }},
    "responses": {"error": {
        "message": "This model does not support the requested reasoning effort.",
        "param": "reasoning.effort",
    }},
    "anthropic": {"error": {
        "type": "invalid_request_error",
        "message": "output_config.effort: Input should be 'low', 'medium' or 'high'",
    }},
    "gemini": {"error": {
        "code": 400, "status": "INVALID_ARGUMENT",
        "message": 'Invalid JSON payload received. Unknown name "thinkingLevel"',
    }},
}


def mock_http(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(
        "yt.translate.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.parametrize("setting,expected", [
    (None, "auto"), ("", "auto"), ("  ", "auto"), ("AUTO", "auto"),
    (" off ", "off"), (False, "off"), ("Low", "low"), ("Medium", "medium"),
    ("HIGH", "high"), ("xHigh", "xhigh"), (" Max ", "max"),
])
def test_config_normalization(setting, expected):
    assert Config.from_dict({"llm": {"thinking": setting}}).llm.thinking == expected


@pytest.mark.parametrize("setting,expected", [
    ("thinking:", "auto"), ("thinking: null", "auto"),
    ('thinking: ""', "auto"), ("thinking: off", "off"),
    ('thinking: "off"', "off"), ("thinking: Max", "max"),
])
def test_yaml_thinking(setting, expected):
    assert Config.from_dict(yaml.safe_load(f"llm:\n  {setting}\n")).llm.thinking == expected


@pytest.mark.parametrize("setting", [True, 0, 1, [], {}, "extreme", "none"])
def test_invalid_thinking(setting):
    with pytest.raises(ValueError, match="llm.thinking"):
        Config.from_dict({"llm": {"thinking": setting}})


@pytest.mark.parametrize("api_format", RESULTS)
@pytest.mark.parametrize("effort", ["auto", "off", "low", "medium", "high", "xhigh", "max"])
def test_native_thinking_controls(api_format, effort):
    config = LLMConfig(api_format=api_format, thinking=effort, max_tokens=8192)
    _, _, payload = build_request(config, "key", "system", "source")
    _, _, baseline = build_request(
        LLMConfig(api_format=api_format, max_tokens=8192), "key", "system", "source",
    )
    if effort == "auto":
        assert not {"reasoning_effort", "reasoning", "thinking", "output_config"} & payload.keys()
        assert "thinkingConfig" not in payload.get("generationConfig", {})
        return
    if api_format == "chat_completions":
        assert payload.pop("reasoning_effort") == ("none" if effort == "off" else effort)
    elif api_format == "responses":
        assert payload.pop("reasoning") == {"effort": "none" if effort == "off" else effort}
    elif api_format == "anthropic":
        assert payload.pop("thinking") == {"type": "disabled" if effort == "off" else "adaptive"}
        if effort != "off":
            assert payload.pop("output_config") == {"effort": effort}
    else:
        assert payload["generationConfig"].pop("thinkingConfig") == (
            {"thinkingBudget": 0} if effort == "off" else {"thinkingLevel": effort.upper()}
        )
    assert payload == baseline  # Preserve tokens, prompts, and all other controls.


@pytest.mark.parametrize("api_format", RESULTS)
@pytest.mark.parametrize("operation", ["translation", "article", "test"])
@pytest.mark.parametrize("status", [200, 400, 422])
def test_rejected_effort_falls_back_once(monkeypatch, capsys, api_format, operation, status):
    payloads = []
    config = Config.from_dict({"llm": {"api_format": api_format, "thinking": "Max", "max_tokens": 8192}})
    monkeypatch.setenv(config.llm.api_key_env, "key")
    client = TranscriptFetcher(config, MagicMock()).translation_client

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(status, json=REJECTIONS[api_format]) if len(payloads) == 1 else (
            httpx.Response(200, json=RESULTS[api_format])
        )

    mock_http(monkeypatch, handler)

    def run():
        if operation == "translation":
            return client.translate_plain_text("source", "en", "zh-TW")
        if operation == "article":
            return client.generate_article("source", language="zh-TW")
        return client.test_connection()

    assert run() == "Final text"
    assert len(payloads) == 2
    assert run() == "Final text"
    assert len(payloads) == 3
    assert client.config.thinking == config.llm.thinking == "max"
    assert client.effective_thinking == "auto"
    assert payloads[0] != payloads[1]
    assert payloads[1] == payloads[2]
    assert not {"thinking", "output_config", "reasoning", "reasoning_effort"} & payloads[1].keys()
    assert "thinkingConfig" not in payloads[1].get("generationConfig", {})
    warning = capsys.readouterr().err
    assert warning.count("Warning:") == 1
    assert "llm.thinking='max'" in warning
    assert "retrying with auto" in warning


@pytest.mark.parametrize("api_format", RESULTS)
def test_supported_effort_is_retained(monkeypatch, capsys, api_format):
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=RESULTS[api_format])
    mock_http(monkeypatch, handler)
    client = TranslationClient(LLMConfig(api_format=api_format).base_url, "key", thinking="high")
    assert client.test_connection() == "Final text"
    assert client.test_connection() == "Final text"
    assert client.effective_thinking == "high"
    assert calls[0] == calls[1]
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("status,error", [
    (400, {"message": "max_tokens must be positive"}),
    (400, {"message": "Model was not found"}),
    (400, {"message": "Unknown model: thinking-model"}),
    (400, {"message": "Model 'thinking-model' does not exist"}),
    (400, {"message": "Invalid API key for reasoning model"}),
    (401, REJECTIONS["responses"]["error"]),
    (429, REJECTIONS["responses"]["error"]),
    (500, REJECTIONS["responses"]["error"]),
    (200, {"code": 401, "message": "Invalid API key for thinking"}),
    (200, {"type": "rate_limit_error", "message": "Thinking requests not allowed"}),
])
def test_other_errors_do_not_trigger_fallback(monkeypatch, capsys, status, error):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": error})
    mock_http(monkeypatch, handler)
    client = TranslationClient("https://proxy.example/v1/responses", "key", thinking="high", max_retries=1)
    with pytest.raises(TranslationError):
        client.generate_article("source")
    assert len(calls) == 1
    assert client.effective_thinking == "high"
    assert "Warning:" not in capsys.readouterr().err


@pytest.mark.parametrize("thinking,expected_calls", [("max", 2), ("auto", 1)])
def test_failed_auto_request_is_not_retried_again(monkeypatch, capsys, thinking, expected_calls):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(400, json=REJECTIONS["responses"])
    mock_http(monkeypatch, handler)
    client = TranslationClient("https://proxy.example/v1/responses", "key", thinking=thinking)
    with pytest.raises(TranslationError, match="does not support"):
        client.generate_article("source")
    assert len(calls) == expected_calls
    assert capsys.readouterr().err.count("Warning:") == expected_calls - 1


def test_successful_text_cannot_trigger_fallback(monkeypatch, capsys):
    text = "This article explains why thinking is not supported by older models."
    mock_http(monkeypatch, lambda _: httpx.Response(200, json={"choices": [{"message": {"content": text}}]}))
    client = TranslationClient("https://proxy.example/v1/chat/completions", "key", thinking="high")
    assert client.generate_article("source") == text
    assert client.effective_thinking == "high"
    assert capsys.readouterr().err == ""


def test_disabled_thinking_can_fall_back_to_model_defaults(monkeypatch, capsys):
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(400, json={"error": {
                "message": "reasoning.effort cannot be none for this model",
            }})
        return httpx.Response(200, json=RESULTS["responses"])
    mock_http(monkeypatch, handler)
    client = TranslationClient("https://proxy.example/v1/responses", "key", thinking="off")
    assert client.test_connection() == "Final text"
    assert payloads[0]["reasoning"] == {"effort": "none"}
    assert "reasoning" not in payloads[1]
    assert client.effective_thinking == "auto"
    assert "llm.thinking='off'" in capsys.readouterr().err
