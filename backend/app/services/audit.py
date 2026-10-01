"""Audit-trail writer. Records who did what, when, from where — never raw PII."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.logging import request_id_ctx
from app.models import AuditLog

log = logging.getLogger("audit")

_SENSITIVE_KEYS = {"password", "otp", "code", "token", "ssn", "secret", "refresh_token"}


def _client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def record(
    db: Session,
    action: str,
    *,
    request: Request | None = None,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    resource_type: str | None = None,
    resource_id: Any = None,
    success: bool = True,
    details: dict[str, Any] | None = None,
    commit: bool = True,
) -> None:
    safe_details = {k: v for k, v in (details or {}).items() if k.lower() not in _SENSITIVE_KEYS}
    entry = AuditLog(
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        success=success,
        ip_address=_client_ip(request),
        user_agent=(request.headers.get("user-agent", "")[:255] if request else None),
        request_id=request_id_ctx.get(),
        details=safe_details or None,
    )
    db.add(entry)
    if commit:
        db.commit()
    log.info("audit action=%s success=%s resource=%s:%s", action, success, resource_type, resource_id)
