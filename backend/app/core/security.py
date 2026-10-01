"""Password hashing and JWT issuance/verification."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

# Argon2id with library defaults (OWASP-recommended memory-hard KDF).
_hasher = PasswordHasher()

TokenType = Literal["access", "mfa"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# A pre-computed hash used to equalize timing when the user does not exist,
# so login response time doesn't reveal which emails are registered.
DUMMY_PASSWORD_HASH = _hasher.hash("timing-equalizer-not-a-real-password")


def validate_password_strength(password: str) -> list[str]:
    """Return a list of problems (empty list == acceptable)."""
    problems: list[str] = []
    if len(password) < 12:
        problems.append("must be at least 12 characters")
    if len(password) > 128:
        problems.append("must be at most 128 characters")
    if not any(c.islower() for c in password):
        problems.append("must contain a lowercase letter")
    if not any(c.isupper() for c in password):
        problems.append("must contain an uppercase letter")
    if not any(c.isdigit() for c in password):
        problems.append("must contain a digit")
    return problems


def create_token(
    subject: uuid.UUID | str,
    token_type: TokenType,
    extra: dict[str, Any] | None = None,
    minutes: int | None = None,
) -> str:
    settings = get_settings()
    if minutes is None:
        minutes = (
            settings.access_token_minutes if token_type == "access" else settings.mfa_token_minutes
        )
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=minutes),
        "jti": uuid.uuid4().hex,
        "iss": settings.app_name,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a JWT; raises jwt.PyJWTError on any problem."""
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],  # pin algorithm: blocks alg=none / confusion
        issuer=settings.app_name,
        options={"require": ["exp", "iat", "sub", "type"]},
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload
