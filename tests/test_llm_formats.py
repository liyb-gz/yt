"""HTTP contract tests for translations and articles across native LLM APIs."""

import json
from unittest.mock import MagicMock

import httpx
import pytest
import yaml

from yt.cli import DEFAULT_CONFIG_CONTENT
from yt.config import Config, LLMConfig
from yt.transcript import TranscriptFetcher
from yt.translate import TranslationClient, TranslationError


RESPONSES = {
    "chat_completions": {
        "choices": [{"finish_reason": "stop", "message": {"content": "Translated text"}}],
    },
    "responses": {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": [{"text": "Private reasoning"}]},
            {"type": "message", "content": [
                {"type": "output_text", "text": "Translated "},
                {"type": "output_text", "text": "text"},
            ]},
        ],
    },
    "anthropic": {
        "stop_reason": "end_turn",
        "content": [
            {"type": "thinking", "thinking": "Private reasoning"},
            {"type": "text", "text": "Translated "},
            {"type": "text", "text": "text"},
        ],
    },
    "gemini": {
        "candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"thought": True, "text": "Private reasoning"},
            {"text": "Translated "},
            {"text": "text"},
        ]}}],
    },
}


def mock_http(monkeypatch, handler):
    """Use the real httpx request machinery with an in-memory transport."""
    real_client = httpx.Client
    monkeypatch.setattr(
        "yt.translate.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.parametrize("api_format", RESPONSES)
@pytest.mark.parametrize("operation", ["translate", "article"])
@pytest.mark.parametrize("format_setting", ["explicit", "omitted", "auto", None, "", "  "])
def test_native_api_request_and_response(monkeypatch, api_format, operation, format_setting):
    llm_settings = {"max_tokens": 8192}
    if format_setting == "explicit":
        llm_settings["api_format"] = api_format
    else:
        llm_settings["base_url"] = LLMConfig(api_format=api_format).base_url
        if format_setting != "omitted":
            llm_settings["api_format"] = format_setting
    config = Config.from_dict({"llm": llm_settings})
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=RESPONSES[api_format])

    mock_http(monkeypatch, handler)
    monkeypatch.setenv(config.llm.api_key_env, "test-key")
    client = TranscriptFetcher(config, MagicMock()).translation_client
    if operation == "translate":
        output = client.translate_plain_text("Source text", "en", "ja")
    else:
        output = client.generate_article("Source text", language="ja", length="short")

    assert output == "Translated text"
    assert len(requests) == 1
    request = requests[0]
    payload = json.loads(request.content)
    assert "temperature" not in payload
    assert "temperature" not in payload.get("generationConfig", {})
    assert request.method == "POST"
    assert request.headers["Content-Type"] == "application/json"
    if api_format == "gemini":
        assert str(request.url) == (
            "https://generativelanguage.googleapis.com/v1beta/"
            "models/gemini-2.5-flash:generateContent"
        )
        assert request.headers["x-goog-api-key"] == "test-key"
        assert "Authorization" not in request.headers
        assert payload["contents"] == [{"role": "user", "parts": [{"text": "Source text"}]}]
        assert payload["generationConfig"]["maxOutputTokens"] == 8192
        prompt = payload["systemInstruction"]["parts"][0]["text"]
    else:
        assert str(request.url) == config.llm.base_url
        assert payload["model"] == config.llm.model
        if api_format == "anthropic":
            assert request.headers["x-api-key"] == "test-key"
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert "Authorization" not in request.headers
            assert payload["messages"] == [{"role": "user", "content": "Source text"}]
            assert payload["max_tokens"] == 8192
            assert "temperature" not in payload
            prompt = payload["system"]
        elif api_format == "responses":
            assert request.headers["Authorization"] == "Bearer test-key"
            assert payload["input"] == "Source text"
            assert payload["max_output_tokens"] == 8192
            assert "temperature" not in payload
            assert "messages" not in payload
            prompt = payload["instructions"]
        else:
            assert request.headers["Authorization"] == "Bearer test-key"
            assert payload["messages"][1] == {"role": "user", "content": "Source text"}
            assert payload["max_tokens"] == 8192
            prompt = payload["messages"][0]["content"]
    assert "Japanese" in prompt
    if operation == "article":
        assert "short" in prompt
        assert "{{length}}" not in prompt
    else:
        assert "translator" in prompt


def test_existing_openrouter_config_and_request(monkeypatch):
    config = Config.from_dict({"llm": {
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "custom/model",
        "api_key_env": "CUSTOM_KEY",
    }})

    def handler(request):
        assert str(request.url) == config.llm.base_url
        assert json.loads(request.content) == {
            "model": "custom/model",
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "source"},
            ],
        }
        return httpx.Response(200, json=RESPONSES["chat_completions"])

    from yt.llm import build_request
    url, headers, payload = build_request(config.llm, "key", "system", "source")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        client.post(url, headers=headers, json=payload).raise_for_status()
    assert config.llm.api_format == "auto"
    assert config.llm.resolved_api_format == "chat_completions"
    assert config.llm.api_key_env == "CUSTOM_KEY"


@pytest.mark.parametrize("api_format", RESPONSES)
def test_optional_token_limit(monkeypatch, api_format):
    config = LLMConfig(api_format=api_format)

    def handler(request):
        payload = json.loads(request.content)
        if api_format == "anthropic":
            assert payload["max_tokens"] == 16384
        else:
            assert "max_tokens" not in payload
            assert "max_output_tokens" not in payload
            assert "maxOutputTokens" not in payload.get("generationConfig", {})
        return httpx.Response(200, json=RESPONSES[api_format])

    mock_http(monkeypatch, handler)
    client = TranslationClient(config.base_url, "key", config.model, api_format=api_format)
    assert client.translate_plain_text("text", "en", "ja") == "Translated text"


@pytest.mark.parametrize("endpoint,model,expected", [
    ("https://proxy.example/v1beta/models/{model}:generateContent", "models/custom-model",
     "https://proxy.example/v1beta/models/custom-model:generateContent"),
    ("https://proxy.example/custom:generateContent", "custom-model",
     "https://proxy.example/custom:generateContent"),
])
def test_custom_gemini_endpoint(monkeypatch, endpoint, model, expected):
    def handler(request):
        assert str(request.url) == expected
        return httpx.Response(200, json=RESPONSES["gemini"])
    mock_http(monkeypatch, handler)
    client = TranslationClient(endpoint, "key", model, api_format="gemini")
    assert client.translate_plain_text("text", "en", "ja") == "Translated text"


FAILURES = [
    ("chat_completions", {"choices": [{"finish_reason": "content_filter"}]}, "rejected"),
    ("chat_completions", {"choices": [{"message": {"refusal": "No"}}]}, "refused"),
    ("chat_completions", {"choices": [{"finish_reason": "length", "message": {"content": "Partial"}}]}, "incomplete"),
    ("responses", {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}, "incomplete"),
    ("responses", {"status": "failed", "error": {"message": "Generation failed"}}, "Generation failed"),
    ("responses", {"output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}]}, "refused"),
    ("anthropic", {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "Partial"}]}, "incomplete"),
    ("anthropic", {"stop_reason": "refusal"}, "refused"),
    ("gemini", {"promptFeedback": {"blockReason": "SAFETY"}}, "rejected"),
    ("gemini", {"candidates": [{"finishReason": "SAFETY"}]}, "rejected"),
    ("gemini", {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "Partial"}]}}]}, "incomplete"),
] + [(fmt, {}, "empty") for fmt in RESPONSES]


@pytest.mark.parametrize("api_format,result,message", FAILURES)
@pytest.mark.parametrize("operation", ["translate", "article"])
def test_invalid_output_fails_without_retry(monkeypatch, api_format, result, message, operation):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=result)
    mock_http(monkeypatch, handler)
    config = LLMConfig(api_format=api_format)
    client = TranslationClient(config.base_url, "key", config.model, api_format=api_format)
    with pytest.raises(TranslationError, match=message):
        if operation == "translate":
            client.translate_plain_text("text", "en", "ja")
        else:
            client.generate_article("text")
    assert len(calls) == 1


@pytest.mark.parametrize("api_format", RESPONSES)
@pytest.mark.parametrize("status,expected_calls", [(401, 1), (429, 2), (503, 2)])
def test_http_error_retry_policy(monkeypatch, api_format, status, expected_calls):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "API unavailable"}})
    mock_http(monkeypatch, handler)
    monkeypatch.setattr("yt.translate.time.sleep", lambda _: None)
    config = LLMConfig(api_format=api_format)
    client = TranslationClient(
        config.base_url, "key", config.model, max_retries=2, api_format=api_format,
    )
    with pytest.raises(TranslationError, match=f"API error \\({status}\\)"):
        client.translate_plain_text("text", "en", "ja")
    assert len(calls) == expected_calls


@pytest.mark.parametrize("api_format", ["wrong", [], {}, True, False, 0])
def test_invalid_api_format(api_format):
    with pytest.raises(ValueError, match="llm.api_format"):
        Config.from_dict({"llm": {"api_format": api_format}})


@pytest.mark.parametrize("limit", [0, -1, True, "1024", 1.5])
def test_invalid_token_limit(limit):
    with pytest.raises(ValueError, match="llm.max_tokens"):
        Config.from_dict({"llm": {"max_tokens": limit}})


def test_config_template_loads_and_old_defaults_are_unchanged():
    config = Config.from_dict(yaml.safe_load(DEFAULT_CONFIG_CONTENT))
    assert config.llm == LLMConfig()
    assert config.llm.base_url == "https://api.openai.com/v1/chat/completions"
    assert config.llm.model == "gpt-4o"
    assert config.llm.api_key_env == "OPENAI_API_KEY"
    assert config.llm.api_format == "auto"
    assert config.llm.resolved_api_format == "chat_completions"


@pytest.mark.parametrize("endpoint,expected", [
    ("https://proxy.example/v1/chat/completions", "chat_completions"),
    ("https://proxy.example/v1/chat/completion/", "chat_completions"),
    ("https://proxy.example/v1/responses", "responses"),
    ("https://proxy.example/v1/response/", "responses"),
    ("https://proxy.example/v1/responses/?api-version=test#fragment", "responses"),
    ("https://proxy.example/v1/Responses", "responses"),
    ("https://proxy.example/v1/messages", "anthropic"),
    ("https://proxy.example/v1/message/?custom=value", "anthropic"),
    ("https://proxy.example/v1beta/models/{model}:generateContent", "gemini"),
    ("https://proxy.example/v1beta/models/gemini-2.5-flash:generateContent/?alt=json#text", "gemini"),
    ("https://proxy.example/custom", "chat_completions"),
    ("https://proxy.example/responses/other", "chat_completions"),
    ("https://proxy.example/custom?path=/messages", "chat_completions"),
    ("https://messages.example/custom#responses", "chat_completions"),
    ("", "chat_completions"),
    (None, "chat_completions"),
])
def test_detect_api_format_from_endpoint_path(endpoint, expected):
    config = Config.from_dict({"llm": {"base_url": endpoint}}).llm
    assert config.api_format == "auto"
    assert config.resolved_api_format == expected
    defaults = LLMConfig(api_format=expected)
    assert config.model == defaults.model
    assert config.api_key_env == defaults.api_key_env


@pytest.mark.parametrize("setting", ["api_format:", "api_format: null", 'api_format: ""', "api_format: auto"])
def test_yaml_empty_format_is_auto(setting):
    data = yaml.safe_load(f"llm:\n  base_url: https://proxy.example/v1/messages\n  {setting}\n")
    config = Config.from_dict(data).llm
    assert config.api_format == "auto"
    assert config.resolved_api_format == "anthropic"
    assert config.api_key_env == "ANTHROPIC_API_KEY"


def test_explicit_format_overrides_url_and_preserves_settings(monkeypatch):
    def handler(request):
        assert str(request.url) == "https://proxy.example/v1/messages"
        assert request.headers["Authorization"] == "Bearer custom-key"
        assert "x-api-key" not in request.headers
        payload = json.loads(request.content)
        assert payload["model"] == "custom-model"
        assert payload["input"] == "source"
        assert "messages" not in payload
        return httpx.Response(200, json=RESPONSES["responses"])
    mock_http(monkeypatch, handler)
    config = Config.from_dict({"llm": {
        "api_format": "responses",
        "base_url": "https://proxy.example/v1/messages",
        "model": "custom-model",
        "api_key_env": "CUSTOM_KEY",
    }})
    assert config.llm.resolved_api_format == "responses"
    monkeypatch.setenv("CUSTOM_KEY", "custom-key")
    client = TranscriptFetcher(config, MagicMock()).translation_client
    assert client.translate_plain_text("source", "en", "ja") == "Translated text"


@pytest.mark.parametrize("format_setting", [None, "", "auto"])
def test_direct_client_auto_detects_format(monkeypatch, format_setting):
    def handler(request):
        assert request.headers["x-api-key"] == "key"
        assert "system" in json.loads(request.content)
        return httpx.Response(200, json=RESPONSES["anthropic"])
    mock_http(monkeypatch, handler)
    client = TranslationClient(
        "https://proxy.example/v1/messages", "key", "custom-model", api_format=format_setting,
    )
    assert client.translate_plain_text("source", "en", "ja") == "Translated text"


@pytest.mark.parametrize("operation", ["translate", "article"])
@pytest.mark.parametrize("api_format", RESPONSES)
def test_model_requiring_default_temperature(monkeypatch, operation, api_format):
    requests = []

    def handler(request):
        requests.append(request)
        payload = json.loads(request.content)
        if api_format != "gemini":
            assert payload["model"] == "claude-haiku-5-5"
        if "temperature" in payload or "temperature" in payload.get("generationConfig", {}):
            return httpx.Response(400, json={"error": {
                "message": "claude-haiku-5-5 does not support non-default temperature",
            }})
        return httpx.Response(200, json=RESPONSES[api_format])

    mock_http(monkeypatch, handler)
    client = TranslationClient(
        LLMConfig(api_format=api_format).base_url, "key", "claude-haiku-5-5",
    )
    if operation == "article":
        result = client.generate_article("source", language="zh-TW")
    else:
        result = client.translate_plain_text("source", "en", "zh-TW")
    assert result == "Translated text"
    assert len(requests) == 1
