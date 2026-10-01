"""Authentication: password + email OTP (MFA), JWT access tokens, rotating refresh tokens.

Flow
----
1. POST /auth/register or /auth/login  -> password checked, 6-digit code emailed,
   response carries a short-lived `mfa_token` (JWT, type=mfa) identifying the challenge.
2. POST /auth/verify-otp {mfa_token, code} -> access token (15 min) + refresh token
   (7 days; httpOnly cookie for web, JSON body for mobile clients).
3. POST /auth/refresh -> rotates the refresh token. Reusing an old refresh token
   revokes the entire token family (stolen-token detection).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, token_version
from app.core.config import get_settings
from app.core.crypto import constant_time_equals, generate_otp, generate_token, keyed_hash
from app.core.redaction import mask_email
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_token,
    decode_token,
    hash_password,
    password_needs_rehash,
    validate_password_strength,
    verify_password,
)
from app.db.session import get_db
from app.models import OTPCode, RefreshToken, User
from app.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MFAChallenge,
    RefreshRequest,
    RegisterRequest,
    ResendOTPRequest,
    TokenResponse,
    UserOut,
    VerifyOTPRequest,
)
from app.services import audit
from app.services.email import send_email, send_otp_email
from app.services.rate_limit import client_key, login_limiter, otp_limiter, register_limiter

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "tp_refresh"
_GENERIC_LOGIN_ERROR = HTTPException(status_code=401, detail="Invalid email or password")
_GENERIC_OTP_ERROR = HTTPException(status_code=401, detail="Invalid or expired code")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite (tests) returns naive datetimes; Postgres returns aware ones.
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _is_mobile(request: Request) -> bool:
    return request.headers.get("x-client-type", "").lower() == "mobile"


def _issue_challenge(db: Session, user: User, purpose: str) -> MFAChallenge:
    s = get_settings()
    challenge_id = uuid.uuid4().hex
    code = generate_otp()
    db.add(OTPCode(
        user_id=user.id, code_hash=keyed_hash(f"{challenge_id}:{code}"), purpose=purpose,
        challenge_id=challenge_id, expires_at=_now() + timedelta(minutes=s.otp_ttl_minutes),
    ))
    db.commit()
    send_otp_email(user.email, code, purpose, s.otp_ttl_minutes)
    token = create_token(user.id, "mfa", extra={"cid": challenge_id, "purpose": purpose})
    return MFAChallenge(mfa_token=token, masked_email=mask_email(user.email), expires_in=s.mfa_token_minutes * 60)


def _decoy_challenge(email: str) -> MFAChallenge:
    """Indistinguishable response for unknown/duplicate emails (anti-enumeration)."""
    s = get_settings()
    token = create_token(uuid.uuid4(), "mfa", extra={"cid": uuid.uuid4().hex, "purpose": "login"})
    return MFAChallenge(mfa_token=token, masked_email=mask_email(email), expires_in=s.mfa_token_minutes * 60)


def _set_refresh_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE, token, max_age=s.refresh_token_days * 86400, httponly=True,
        secure=s.cookie_secure, samesite="strict", path="/api/v1/auth",
    )


def _issue_session(
    db: Session, request: Request, response: Response, user: User, family_id: uuid.UUID | None = None
) -> TokenResponse:
    s = get_settings()
    raw_refresh = generate_token()
    rt = RefreshToken(
        user_id=user.id, token_hash=keyed_hash(raw_refresh), family_id=family_id or uuid.uuid4(),
        expires_at=_now() + timedelta(days=s.refresh_token_days),
        user_agent=request.headers.get("user-agent", "")[:255],
        ip_address=request.client.host if request.client else None,
    )
    db.add(rt)
    db.commit()
    access = create_token(user.id, "access", extra={"role": user.role, "ver": token_version(user)})
    mobile = _is_mobile(request)
    if not mobile:
        _set_refresh_cookie(response, raw_refresh)
    return TokenResponse(
        access_token=access, expires_in=s.access_token_minutes * 60,
        refresh_token=raw_refresh if mobile else None, user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=MFAChallenge, status_code=status.HTTP_202_ACCEPTED)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> MFAChallenge:
    register_limiter.check(client_key(request, "register"))
    problems = validate_password_strength(body.password)
    if problems:
        raise HTTPException(status_code=422, detail="Password " + "; ".join(problems))
    email = body.email.lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        # Don't reveal that the account exists; tell the real owner instead.
        send_email(email, "TaxPilot sign-up attempt",
                   "Someone tried to create a TaxPilot account with your email. If this was you, "
                   "just sign in instead. Otherwise you can ignore this message.")
        audit.record(db, "auth.register_duplicate", request=request, actor_id=existing.id, success=False)
        return _decoy_challenge(email)
    user = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    audit.record(db, "auth.register", request=request, actor_id=user.id, actor_role=user.role,
                 resource_type="user", resource_id=user.id)
    return _issue_challenge(db, user, "verify_email")


@router.post("/login", response_model=MFAChallenge)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> MFAChallenge:
    login_limiter.check(client_key(request, "login"))
    s = get_settings()
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        verify_password(body.password, DUMMY_PASSWORD_HASH)  # equalize timing
        audit.record(db, "auth.login_failed", request=request, success=False, details={"reason": "unknown_user"})
        raise _GENERIC_LOGIN_ERROR
    locked_until = _aware(user.locked_until)
    if locked_until and locked_until > _now():
        audit.record(db, "auth.login_locked", request=request, actor_id=user.id, success=False)
        raise HTTPException(status_code=423, detail="Account temporarily locked. Try again later.")
    if not verify_password(body.password, user.password_hash) or not user.is_active:
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= s.max_failed_logins:
            user.locked_until = _now() + timedelta(minutes=s.lockout_minutes)
            user.failed_login_attempts = 0
        db.commit()
        audit.record(db, "auth.login_failed", request=request, actor_id=user.id, success=False,
                     details={"reason": "bad_password" if user.is_active else "inactive"})
        raise _GENERIC_LOGIN_ERROR
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.failed_login_attempts = 0
    db.commit()
    audit.record(db, "auth.password_ok", request=request, actor_id=user.id, actor_role=user.role)
    return _issue_challenge(db, user, "login" if user.email_verified else "verify_email")


def _decode_mfa(token: str) -> tuple[uuid.UUID, str, str]:
    try:
        payload = decode_token(token, "mfa")
        return uuid.UUID(payload["sub"]), payload["cid"], payload["purpose"]
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _GENERIC_OTP_ERROR from None


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp(body: VerifyOTPRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    otp_limiter.check(client_key(request, "otp"))
    s = get_settings()
    user_id, challenge_id, purpose = _decode_mfa(body.mfa_token)
    otp = db.scalar(select(OTPCode).where(
        OTPCode.user_id == user_id, OTPCode.challenge_id == challenge_id, OTPCode.consumed_at.is_(None)
    ))
    if otp is None or _aware(otp.expires_at) < _now() or otp.attempts >= s.otp_max_attempts:
        audit.record(db, "auth.otp_failed", request=request, actor_id=user_id if otp else None, success=False,
                     details={"reason": "missing_or_expired"})
        raise _GENERIC_OTP_ERROR
    otp.attempts += 1
    if not constant_time_equals(otp.code_hash, keyed_hash(f"{challenge_id}:{body.code}")):
        db.commit()
        audit.record(db, "auth.otp_failed", request=request, actor_id=user_id, success=False,
                     details={"attempt": otp.attempts})
        raise _GENERIC_OTP_ERROR
    otp.consumed_at = _now()
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        db.commit()
        raise _GENERIC_OTP_ERROR
    if purpose == "verify_email":
        user.email_verified = True
    user.last_login_at = _now()
    db.commit()
    audit.record(db, "auth.login", request=request, actor_id=user.id, actor_role=user.role,
                 details={"mfa": "email_otp", "client": "mobile" if _is_mobile(request) else "web"})
    return _issue_session(db, request, response, user)


@router.post("/resend-otp", response_model=MFAChallenge)
def resend_otp(body: ResendOTPRequest, request: Request, db: Session = Depends(get_db)) -> MFAChallenge:
    otp_limiter.check(client_key(request, "resend"))
    user_id, challenge_id, purpose = _decode_mfa(body.mfa_token)
    user = db.get(User, user_id)
    if user is None:
        return _decoy_challenge("unknown@unknown")
    # Invalidate the previous code for this challenge.
    db.execute(update(OTPCode).where(OTPCode.challenge_id == challenge_id).values(consumed_at=_now()))
    db.commit()
    return _issue_challenge(db, user, purpose)


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response, body: RefreshRequest | None = None,
            db: Session = Depends(get_db)) -> TokenResponse:
    raw = (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="No refresh token")
    if not (body and body.refresh_token) and request.headers.get("x-requested-with") != "XMLHttpRequest":
        # Cookie-based refresh must come from our JS client (CSRF defense in depth).
        raise HTTPException(status_code=403, detail="Missing X-Requested-With header")
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == keyed_hash(raw)))
    if rt is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if rt.revoked_at is not None:
        # Reuse of a rotated token => likely theft. Kill the whole family.
        db.execute(update(RefreshToken).where(RefreshToken.family_id == rt.family_id,
                                              RefreshToken.revoked_at.is_(None)).values(revoked_at=_now()))
        db.commit()
        audit.record(db, "auth.refresh_reuse_detected", request=request, actor_id=rt.user_id, success=False)
        raise HTTPException(status_code=401, detail="Session revoked. Please sign in again.")
    if _aware(rt.expires_at) < _now():
        raise HTTPException(status_code=401, detail="Session expired")
    user = db.get(User, rt.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    rt.revoked_at = _now()
    session = _issue_session(db, request, response, user, family_id=rt.family_id)
    new_rt = db.scalar(select(RefreshToken).where(RefreshToken.family_id == rt.family_id,
                                                  RefreshToken.revoked_at.is_(None)))
    rt.replaced_by = new_rt.id if new_rt else None
    db.commit()
    return session


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, body: RefreshRequest | None = None,
           db: Session = Depends(get_db)) -> Response:
    raw = (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)
    if raw:
        rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == keyed_hash(raw)))
        if rt:
            db.execute(update(RefreshToken).where(RefreshToken.family_id == rt.family_id,
                                                  RefreshToken.revoked_at.is_(None)).values(revoked_at=_now()))
            db.commit()
            audit.record(db, "auth.logout", request=request, actor_id=rt.user_id)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/change-password", status_code=204)
def change_password(body: ChangePasswordRequest, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> Response:
    if not verify_password(body.current_password, user.password_hash):
        audit.record(db, "auth.change_password", request=request, actor_id=user.id, success=False)
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    problems = validate_password_strength(body.new_password)
    if problems:
        raise HTTPException(status_code=422, detail="Password " + "; ".join(problems))
    user.password_hash = hash_password(body.new_password)  # also invalidates access tokens (ver)
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id,
                                          RefreshToken.revoked_at.is_(None)).values(revoked_at=_now()))
    db.commit()
    audit.record(db, "auth.change_password", request=request, actor_id=user.id, actor_role=user.role)
    return Response(status_code=204)
