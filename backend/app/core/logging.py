"""Structured JSON logging with PII redaction.

Every log record passes through `PIIRedactingFilter`, which masks SSNs, EINs,
emails, card/account numbers and phone numbers. Even if a developer logs a raw
value by mistake, it won't land in log files in clear text.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

from app.core.redaction import redact_text

request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class PIIRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed record
            return True
        record.msg = redact_text(message)
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_ctx.get()
        if rid:
            entry["request_id"] = rid
        if record.exc_info:
            entry["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(entry)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(PIIRedactingFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Uvicorn's access log includes query strings; route it through our filter too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False
