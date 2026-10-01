"""Thin, safe wrapper around the OpenAI Python SDK.

Guarantees:
* The API key is read from the OPENAI_API_KEY environment variable only.
* Text is PII-redacted before it leaves the server (configurable, on by default).
* Responses are requested as strict JSON Schema (Structured Outputs) and
  validated, so downstream code never parses free-form model prose for numbers.
* `store=False`: we ask OpenAI not to retain completions for later retrieval.
* Every call is optional: callers must handle `AIUnavailable` and fall back to
  deterministic logic, so the product works fully offline.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import get_settings
from app.core.redaction import redact_text

log = logging.getLogger(__name__)


class AIUnavailable(RuntimeError):
    """Raised when AI is disabled, not consented to, or the API call failed."""


_client = None


def _get_client():
    global _client
    settings = get_settings()
    if not settings.ai_enabled:
        raise AIUnavailable("OPENAI_API_KEY is not configured")
    if _client is None:
        from openai import OpenAI  # imported lazily so tests/offline mode don't need it

        _client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_seconds,
            max_retries=2,
        )
    return _client


def prepare_text(text: str, max_chars: int = 24000) -> str:
    """Redact PII (if enabled) and truncate to keep token usage bounded."""
    if get_settings().ai_redact_pii:
        text = redact_text(text)
    return text[:max_chars]


def structured_completion(
    *,
    system: str,
    user: str | list[dict[str, Any]],
    schema_name: str,
    schema: dict[str, Any],
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """Call the chat completions API and return JSON matching `schema`.

    `user` may be a string or a list of content parts (for images).
    """
    client = _get_client()
    try:
        response = client.chat.completions.create(
            model=get_settings().openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema, "strict": True},
            },
            max_completion_tokens=max_tokens,
            store=False,
        )
    except Exception as exc:  # network, auth, rate limit, ...
        log.warning("OpenAI call failed (%s): %s", schema_name, type(exc).__name__)
        raise AIUnavailable(str(type(exc).__name__)) from exc

    choice = response.choices[0]
    if getattr(choice.message, "refusal", None):
        raise AIUnavailable("model refused the request")
    try:
        return json.loads(choice.message.content or "{}")
    except json.JSONDecodeError as exc:
        raise AIUnavailable("model returned invalid JSON") from exc


def text_completion(*, system: str, user: str, max_tokens: int = 900) -> str:
    client = _get_client()
    try:
        response = client.chat.completions.create(
            model=get_settings().openai_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_completion_tokens=max_tokens,
            store=False,
        )
    except Exception as exc:
        log.warning("OpenAI call failed (text): %s", type(exc).__name__)
        raise AIUnavailable(str(type(exc).__name__)) from exc
    return (response.choices[0].message.content or "").strip()
