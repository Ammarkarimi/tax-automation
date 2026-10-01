"""FastAPI dependencies: DB session, current user, RBAC, tax-year validation."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date

import jwt
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models import User
from app.models.enums import Role
from app.tax.tables import SUPPORTED_YEARS

bearer = HTTPBearer(auto_error=False)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _CREDENTIALS_ERROR
    try:
        payload = decode_token(creds.credentials, "access")
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise _CREDENTIALS_ERROR from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR
    # Tokens issued before a password change / forced logout are rejected.
    if payload.get("ver") != _token_version(user):
        raise _CREDENTIALS_ERROR
    request.state.user = user
    return user


def _token_version(user: User) -> str:
    # Changes whenever the password hash changes -> invalidates old access tokens.
    return user.password_hash[-12:]


def token_version(user: User) -> str:
    return _token_version(user)


def require_roles(*roles: Role) -> Callable[[User], User]:
    """RBAC guard: `Depends(require_roles(Role.ADMIN))`."""
    allowed = {r.value for r in roles}

    def guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return guard


def tax_year_param(year: int | None = Query(default=None, description="Tax year, e.g. 2025")) -> int:
    if year is None:
        # Default: the year currently being filed until mid-October, then the current year.
        today = date.today()
        year = today.year - 1 if today.month < 10 or (today.month == 10 and today.day <= 15) else today.year
        if year not in SUPPORTED_YEARS:
            year = SUPPORTED_YEARS[-1]
    if year not in SUPPORTED_YEARS:
        raise HTTPException(status_code=422, detail=f"Supported tax years: {SUPPORTED_YEARS}")
    return year
