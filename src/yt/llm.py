"""Request and response adapters for supported LLM HTTP APIs."""

import re
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
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build a non-streaming request, leaving sampling to the model's defaults."""
    url = config.base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    payload: dict[str, Any]
    api_format = config.resolved_api_format

    if api_format == "gemini":
        model = quote(config.model.removeprefix("models/"), safe="")
        url = url.replace("{model}", model)
        headers["x-goog-api-key"] = api_key
        generation_config: dict[str, Any] = {}
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
        }
    elif api_format == "responses":
        headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": config.model,
            "instructions": system_prompt,
            "input": text,
        }
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
        }
        if config.max_tokens is not None:
            payload["max_tokens"] = config.max_tokens

    effort = config.thinking
    if effort != "auto":
        if api_format == "gemini":
            payload["generationConfig"]["thinkingConfig"] = (
                {"thinkingBudget": 0} if effort == "off" else {"thinkingLevel": effort.upper()}
            )
        elif api_format == "anthropic":
            if effort == "off":
                payload["thinking"] = {"type": "disabled"}
            else:
                payload["thinking"] = {"type": "adaptive"}
                payload["output_config"] = {"effort": effort}
        elif api_format == "responses":
            payload["reasoning"] = {"effort": "none" if effort == "off" else effort}
        else:
            payload["reasoning_effort"] = "none" if effort == "off" else effort

    return url, headers, payload


def is_thinking_rejection(result: Any) -> bool:
    """Recognize validation errors about thinking controls, never successful text."""
    if not isinstance(result, dict) or not result.get("error"):
        return False
    error = result["error"]
    if isinstance(error, str):
        detail = error
    elif isinstance(error, dict):
        category = f"{error.get('type', '')} {error.get('code', '')}".lower()
        if re.search(r"auth|permission|rate.?limit|quota|not.?found|server", category):
            return False
        if str(error.get("code", "")) in {"401", "403", "404", "429", "500", "502", "503"}:
            return False
        # Include structured validation details (e.g. Google's fieldViolations),
        # but never use this backend text in the warning shown to users.
        detail = str({key: error[key] for key in ("message", "param", "type", "code", "details") if key in error})
    else:
        return False
    if re.search(
        r"(?:invalid|incorrect|missing|expired)[ _-]+(?:api[ _-]*)?key|"
        r"unauthorized|authentication[ _-]+failed|permission[ _-]+denied|"
        r"quota[ _-]+(?:exceeded|exhausted)|rate[ _-]+limit|"
        r"(?:unknown|unsupported)[ _-]+model|"
        r"model[^\n]*?(?:not[ _-]+found|does[ _-]+not[ _-]+exist)",
        detail, re.IGNORECASE,
    ):
        return False
    mentions_control = re.search(
        r"\b(?:reasoning(?:[_.\s-]*effort)?|thinking(?:[_.\s-]*(?:config|level|budget))?|effort)\b",
        detail, re.IGNORECASE,
    )
    rejects_control = re.search(
        r"unsupported|not[ _-]+supported|does(?:[ _-]+not|n't)[ _-]+support|"
        r"unknown|unrecognized|invalid|not[ _-]+(?:allowed|permitted)|"
        r"must[ _-]+be|only[ _-]+(?:supports?|accepts?|allowed)|"
        r"extra[ _-]+(?:inputs?|fields?)|input[ _-]+should[ _-]+be|"
        r"unexpected|cannot|can't|requires?|expected",
        detail, re.IGNORECASE,
    )
    return bool(mentions_control and rejects_control)


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
