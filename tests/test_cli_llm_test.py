"""Exercise --test through the CLI and real HTTP serialization and parsing."""

import json

import httpx
import pytest
import yaml

from yt.cli import main
from yt.config import LLMConfig


RESULTS = {
    "chat_completions": {"choices": [{"message": {"content": "OK"}}]},
    "responses": {"status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": "OK"}]},
    ]},
    "anthropic": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "OK"}]},
    "gemini": {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "OK"}]}}]},
}


@pytest.fixture
def make_config(tmp_path, monkeypatch):
    monkeypatch.setenv("YT_TEST_KEY", "secret-test-key")

    def make(provider_format="chat_completions", **overrides):
        llm = {
            "api_format": "auto",
            "base_url": LLMConfig(api_format=provider_format).base_url,
            "model": "test-model",
            "api_key_env": "YT_TEST_KEY",
            "max_tokens": 4096,
        }
        llm.update(overrides)
        config = {
            "llm": llm,
            "languages": ["zh-TW", "ko"],
            "output": {"format": "article", "pipe_mode": True},
            "storage": {
                "audio_dir": str(tmp_path / "audio"),
                "transcript_dir": str(tmp_path / "transcripts"),
                "article_dir": str(tmp_path / "articles"),
            },
            "logging": {"file": str(tmp_path / "logs" / "yt.log")},
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(config))
        return path

    return make


def mock_http(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(
        "yt.translate.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.parametrize("api_format", RESULTS)
def test_live_request_through_cli(monkeypatch, capsys, tmp_path, make_config, api_format):
    path = make_config(api_format)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert "temperature" not in payload
        if api_format == "gemini":
            assert "/models/test-model:generateContent" in str(request.url)
            assert request.headers["x-goog-api-key"] == "secret-test-key"
            assert payload["generationConfig"] == {"maxOutputTokens": 4096}
        else:
            assert payload["model"] == "test-model"
            limit = "max_output_tokens" if api_format == "responses" else "max_tokens"
            assert payload[limit] == 4096
            if api_format == "anthropic":
                assert request.headers["x-api-key"] == "secret-test-key"
            else:
                assert request.headers["Authorization"] == "Bearer secret-test-key"
        assert "API connection test" in request.content.decode()
        return httpx.Response(200, json=RESULTS[api_format])

    def no_youtube(*args, **kwargs):
        pytest.fail("--test must not instantiate a YouTube client")

    mock_http(monkeypatch, handler)
    monkeypatch.setattr("yt.cli.YouTubeClient", no_youtube)
    assert main(["--test", "--config", str(path)]) == 0
    output = capsys.readouterr().out
    assert f"API format: {api_format} (auto)" in output
    assert "Model: test-model" in output
    assert "API key: YT_TEST_KEY (set)" in output
    assert "LLM test passed (" in output
    assert "Response: OK" in output
    assert "secret-test-key" not in output
    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == [path]


def test_default_config_path(monkeypatch, capsys, make_config):
    path = make_config()
    monkeypatch.setattr("yt.cli.DEFAULT_CONFIG_PATH", path)
    mock_http(monkeypatch, lambda _: httpx.Response(200, json=RESULTS["chat_completions"]))
    assert main(["--test"]) == 0
    assert str(path) in capsys.readouterr().out


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_api_key_stops_before_network(monkeypatch, capsys, make_config, key):
    path = make_config()
    if key is None:
        monkeypatch.delenv("YT_TEST_KEY")
    else:
        monkeypatch.setenv("YT_TEST_KEY", key)
    mock_http(monkeypatch, lambda _: pytest.fail("Must not send a request without a key"))
    assert main(["--test", "--config", str(path)]) == 1
    assert "Set YT_TEST_KEY" in capsys.readouterr().out


def test_missing_explicit_config_does_not_test_defaults(monkeypatch, capsys, tmp_path):
    mock_http(monkeypatch, lambda _: pytest.fail("Must not fall back to default config"))
    assert main(["--test", "--config", str(tmp_path / "missing.yaml")]) == 1
    assert "Configuration file not found" in capsys.readouterr().out


def test_invalid_config_is_reported(capsys, make_config):
    path = make_config(api_format="chat_completions", max_tokens=-1)
    assert main(["--test", "--config", str(path)]) == 1
    assert "llm.max_tokens" in capsys.readouterr().out


def test_invalid_yaml_is_reported_without_echoing_contents(capsys, tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("llm: [\napi_key: secret-value\n")
    assert main(["--test", "--config", str(path)]) == 1
    output = capsys.readouterr().out
    assert "Invalid YAML configuration at line" in output
    assert "secret-value" not in output


@pytest.mark.parametrize("status", [400, 401, 404, 429, 503])
def test_http_errors_fail_without_retry(monkeypatch, capsys, make_config, status):
    path = make_config()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "Provider rejected test"}})

    mock_http(monkeypatch, handler)
    assert main(["--test", "--config", str(path)]) == 1
    output = capsys.readouterr().out
    assert f"API error ({status}): Provider rejected test" in output
    assert len(calls) == 1


@pytest.mark.parametrize("response,message", [
    (httpx.Response(200, json={}), "empty response"),
    (httpx.Response(200, content=b"<html>Not an API</html>"), "invalid JSON"),
    (httpx.Response(200, json=[]), "expected an object"),
    (httpx.Response(200, json={"choices": [{"finish_reason": "length"}]}), "incomplete output"),
    (httpx.Response(200, json={"choices": [{"finish_reason": "content_filter"}]}), "rejected content"),
    (httpx.Response(502, content=b"<html>Bad gateway</html>"), "API error (502): Bad Gateway"),
])
def test_invalid_responses(monkeypatch, capsys, make_config, response, message):
    path = make_config()
    mock_http(monkeypatch, lambda _: response)
    assert main(["--test", "--config", str(path)]) == 1
    assert message in capsys.readouterr().out


@pytest.mark.parametrize("error,message", [
    (httpx.ReadTimeout("timeout"), "Request timed out"),
    (httpx.ConnectError("Cannot connect"), "Connection error: Cannot connect"),
])
def test_network_errors(monkeypatch, capsys, make_config, error, message):
    path = make_config()

    def handler(_):
        raise error

    mock_http(monkeypatch, handler)
    assert main(["--test", "--config", str(path)]) == 1
    assert message in capsys.readouterr().out


@pytest.mark.parametrize("failure", [False, True])
def test_credentials_are_hidden_in_diagnostics(monkeypatch, capsys, make_config, failure):
    endpoint = "https://username:url-password@proxy.example/v1/responses?key=url-secret#private-fragment"
    path = make_config(base_url=endpoint)

    def handler(request):
        if failure:
            return httpx.Response(401, json={"error": {"message": (
                f"Rejected secret-test-key at {endpoint}"
            )}})
        return httpx.Response(200, json={"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "secret-test-key " + endpoint},
        ]}]})

    mock_http(monkeypatch, handler)
    assert main(["--test", "--config", str(path)]) == (1 if failure else 0)
    output = capsys.readouterr().out
    for secret in ("secret-test-key", "username", "url-password", "url-secret", "private-fragment"):
        assert secret not in output
    assert "https://proxy.example/v1/responses" in output


def test_explicit_api_format_override_is_used(monkeypatch, capsys, make_config):
    path = make_config(api_format="responses", base_url="https://proxy.example/custom")

    def handler(request):
        assert "input" in json.loads(request.content)
        return httpx.Response(200, json=RESULTS["responses"])

    mock_http(monkeypatch, handler)
    assert main(["--test", "--config", str(path)]) == 0
    assert "API format: responses (responses)" in capsys.readouterr().out


@pytest.mark.parametrize("extra", [["https://youtu.be/test"], ["--input", "urls.txt"]])
def test_video_arguments_are_rejected_before_network(monkeypatch, capsys, extra):
    mock_http(monkeypatch, lambda _: pytest.fail("Usage error must not make a request"))
    with pytest.raises(SystemExit) as error:
        main(["--test", *extra])
    assert error.value.code == 2
    assert "--test cannot be combined" in capsys.readouterr().err
