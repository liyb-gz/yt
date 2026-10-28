"""Request and response adapters for supported LLM HTTP APIs."""

from typing import Any
from urllib.parse import quote

from yt.config import LLMConfig


class LLMResponseError(ValueError):
    """The API returned a refusal, incomplete output, or no usable text."""


def build_request(
    config: LLMConfig,
    api_key: str,
    system_prompt: str,
    text: str,
    temperature: float,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build a non-streaming request using the selected wire format."""
    url = config.base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    payload: dict[str, Any]
    api_format = config.resolved_api_format

    if api_format == "gemini":
        model = quote(config.model.removeprefix("models/"), safe="")
        url = url.replace("{model}", model)
        headers["x-goog-api-key"] = api_key
        generation_config: dict[str, Any] = {"temperature": temperature}
        if config.max_tokens is not None:
            generation_config["maxOutputTokens"] = config.max_tokens
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": generation_config,
        }
    elif api_format == "anthropic":
        headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
        payload = {
            "model": config.model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": text}],
            "max_tokens": config.max_tokens or 16384,
            "temperature": temperature,
        }
    elif api_format == "responses":
        headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": config.model,
            "instructions": system_prompt,
            "input": text,
        }
        # Reasoning models may reject temperature; let the model use its default.
        if config.max_tokens is not None:
            payload["max_output_tokens"] = config.max_tokens
    else:
        headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": temperature,
        }
        if config.max_tokens is not None:
            payload["max_tokens"] = config.max_tokens

    return url, headers, payload


def extract_text(result: dict[str, Any], api_format: str) -> str:
    """Extract final text, excluding reasoning and rejecting partial output."""
    if result.get("error"):
        error = result["error"]
        detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        raise LLMResponseError(f"LLM API error: {detail}")

    if api_format == "responses":
        if result.get("status") == "incomplete":
            reason = (result.get("incomplete_details") or {}).get("reason", "unknown")
            _raise_incomplete(reason)
        if result.get("status") in ("failed", "cancelled", "queued", "in_progress"):
            raise LLMResponseError(f"LLM response status: {result['status']}")
        blocks = [
            block
            for item in result.get("output", [])
            if item.get("type") == "message"
            for block in item.get("content", [])
        ]
        if any(block.get("type") == "refusal" for block in blocks):
            raise LLMResponseError("LLM refused to process content")
        content = "".join(
            block.get("text", "") for block in blocks if block.get("type") == "output_text"
        )
    elif api_format == "anthropic":
        if result.get("stop_reason") == "max_tokens":
            _raise_incomplete("max_tokens")
        if result.get("stop_reason") == "refusal":
            raise LLMResponseError("LLM refused to process content")
        content = "".join(
            block.get("text", "")
            for block in result.get("content", [])
            if block.get("type") == "text"
        )
    elif api_format == "gemini":
        blocked = (result.get("promptFeedback") or {}).get("blockReason")
        if blocked and blocked != "BLOCK_REASON_UNSPECIFIED":
            raise LLMResponseError(f"LLM rejected prompt: {blocked}")
        candidate = (result.get("candidates") or [{}])[0]
        reason = candidate.get("finishReason")
        if reason == "MAX_TOKENS":
            _raise_incomplete(reason)
        if reason and reason != "STOP":
            raise LLMResponseError(f"LLM rejected or stopped content: {reason}")
        content = "".join(
            part.get("text", "")
            for part in (candidate.get("content") or {}).get("parts", [])
            if not part.get("thought")
        )
    else:
        choice = (result.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "content_filter":
            raise LLMResponseError("LLM rejected content due to content policy")
        if choice.get("finish_reason") == "length":
            _raise_incomplete("length")
        message = choice.get("message") or {}
        if message.get("refusal"):
            raise LLMResponseError("LLM refused to process content")
        content = message.get("content") or ""

    if not isinstance(content, str) or not content.strip():
        raise LLMResponseError("LLM returned empty response")
    return content


def _raise_incomplete(reason: str) -> None:
    raise LLMResponseError(
        f"LLM returned incomplete output ({reason}); "
        "check llm.max_tokens and the model's output limit"
    )
