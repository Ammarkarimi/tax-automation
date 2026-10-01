"""PII detection/redaction used for logs and before any text is sent to OpenAI."""

from __future__ import annotations

import re

# Order matters: more specific patterns first.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # SSN / ITIN: 123-45-6789 or 123 45 6789
    (re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b"), "[SSN]"),
    # EIN: 12-3456789
    (re.compile(r"\b\d{2}-\d{7}\b"), "[EIN]"),
    # Emails
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    # Card / bank account numbers: 9-19 digits, optionally grouped by spaces/dashes
    (re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), "[ACCOUNT]"),
    (re.compile(r"\b\d{9,17}\b"), "[ACCOUNT]"),
    # US phone numbers
    (re.compile(r"(?:\+1[ .-]?)?\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b"), "[PHONE]"),
]


def redact_text(text: str) -> str:
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def mask_email(email: str) -> str:
    """j***@example.com — for admin views and logs that need a hint, not the value."""
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"
