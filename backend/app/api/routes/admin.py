"""Admin & monitoring. Admins/support see operational data only — never tax data,
documents or unmasked emails (least privilege; PII stays with its owner)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.config import get_settings
from app.core.redaction import mask_email
from app.db.session import get_db
from app.models import AuditLog, Document, GeneratedReport, TaxCalculation, Transaction, User
from app.models.enums import Role
from app.schemas import AdminUserOut, AdminUserUpdate, AuditLogOut
from app.services import audit

router = APIRouter(prefix="/admin", tags=["admin"])

staff = require_roles(Role.ADMIN, Role.SUPPORT)
admin_only = require_roles(Role.ADMIN)


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


@router.get("/stats")
def stats(_: User = Depends(staff), db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    def count(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    doc_status = dict(db.execute(select(Document.status, func.count()).group_by(Document.status)).all())
    tx_by_source = dict(db.execute(select(Transaction.classified_by, func.count()).group_by(Transaction.classified_by)).all())
    actions_24h = dict(db.execute(
        select(AuditLog.action, func.count()).where(AuditLog.created_at >= day_ago).group_by(AuditLog.action)
    ).all())
    return {
        "generated_at": now.isoformat(),
        "users": {
            "total": count(User),
            "active": count(User, User.is_active.is_(True)),
            "verified": count(User, User.email_verified.is_(True)),
            "ai_consented": count(User, User.ai_consent.is_(True)),
            "locked": count(User, User.locked_until > now),
        },
        "documents": {"total": count(Document), "by_status": doc_status},
        "transactions": {"total": count(Transaction), "by_classifier": tx_by_source,
                         "needs_review": count(Transaction, Transaction.needs_review.is_(True))},
        "calculations": count(TaxCalculation),
        "reports": count(GeneratedReport),
        "last_24h": {
            "logins": actions_24h.get("auth.login", 0),
            "failed_logins": actions_24h.get("auth.login_failed", 0),
            "failed_otps": actions_24h.get("auth.otp_failed", 0),
            "uploads": actions_24h.get("document.uploaded", 0),
            "refresh_reuse_alerts": actions_24h.get("auth.refresh_reuse_detected", 0),
        },
        "system": {"ai_enabled": get_settings().ai_enabled, "ai_model": get_settings().openai_model,
                   "environment": get_settings().environment},
    }


@router.get("/users", response_model=list[AdminUserOut])
def list_users(_: User = Depends(staff), db: Session = Depends(get_db),
               limit: int = Query(default=100, le=500), offset: int = Query(default=0, ge=0)) -> list[AdminUserOut]:
    users = db.scalars(select(User).order_by(User.created_at.desc()).offset(offset).limit(limit))
    return [_user_out(db, u) for u in users]


def _user_out(db: Session, u: User) -> AdminUserOut:
    now = datetime.now(timezone.utc)
    docs = db.scalar(select(func.count()).select_from(Document).where(Document.user_id == u.id)) or 0
    txns = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.user_id == u.id)) or 0
    return AdminUserOut(
        id=u.id, email_masked=mask_email(u.email), role=u.role, is_active=u.is_active,
        email_verified=u.email_verified, locked=bool(u.locked_until and _aware(u.locked_until) > now),
        created_at=u.created_at, last_login_at=u.last_login_at, document_count=docs, transaction_count=txns,
    )


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(user_id: uuid.UUID, body: AdminUserUpdate, request: Request, actor: User = Depends(admin_only),
                db: Session = Depends(get_db)) -> AdminUserOut:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    if u.id == actor.id and (body.role not in (None, Role.ADMIN) or body.is_active is False):
        raise HTTPException(status_code=400, detail="You can't demote or deactivate yourself")
    changes = body.model_dump(exclude_unset=True)
    if body.role is not None:
        u.role = body.role.value
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.unlock:
        u.locked_until = None
        u.failed_login_attempts = 0
    db.commit()
    audit.record(db, "admin.user_updated", request=request, actor_id=actor.id, actor_role=actor.role,
                 resource_type="user", resource_id=u.id,
                 details={k: (v.value if hasattr(v, "value") else v) for k, v in changes.items()})
    return _user_out(db, u)


@router.get("/audit-logs", response_model=list[AuditLogOut])
def audit_logs(
    _: User = Depends(staff),
    db: Session = Depends(get_db),
    action: str | None = Query(default=None, max_length=64),
    actor_id: uuid.UUID | None = None,
    success: bool | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[AuditLog]:
    q = select(AuditLog).order_by(AuditLog.id.desc())
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    if actor_id:
        q = q.where(AuditLog.actor_id == actor_id)
    if success is not None:
        q = q.where(AuditLog.success.is_(success))
    return list(db.scalars(q.offset(offset).limit(limit)))
