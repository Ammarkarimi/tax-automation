"""FastAPI application factory.

Run locally:  uvicorn app.main:app --reload
With TLS:     uvicorn app.main:app --ssl-keyfile ../certs/dev-key.pem --ssl-certfile ../certs/dev-cert.pem
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.api.routes import account, admin, auth, bookkeeping, documents, tax
from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_ctx
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_engine, session_factory
from app.models import User
from app.models.enums import Role

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


def init_db() -> None:
    """Create tables if missing (dev convenience; use Alembic migrations for schema changes)."""
    Base.metadata.create_all(get_engine())


def bootstrap_admin() -> None:
    s = get_settings()
    if not (s.bootstrap_admin_email and s.bootstrap_admin_password):
        return
    with session_factory()() as db:
        email = s.bootstrap_admin_email.lower()
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            db.add(User(email=email, password_hash=hash_password(s.bootstrap_admin_password),
                        role=Role.ADMIN.value, email_verified=True, full_name="Administrator"))
            db.commit()
            log.info("bootstrap admin account created")
        elif user.role != Role.ADMIN.value:
            user.role = Role.ADMIN.value
            db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    init_db()
    bootstrap_admin()
    log.info("TaxPilot API started (AI %s)", "enabled" if get_settings().ai_enabled else "disabled")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="TaxPilot API",
        version="1.0.0",
        description=(
            "AI-assisted tax preparation & planning for U.S. freelancers, gig workers and "
            "small shopkeepers (Schedule C). Prepares and explains returns — never files them."
        ),
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.environment != "production" else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Client-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id")
        if not rid or len(rid) > 64 or not rid.replace("-", "").isalnum():
            rid = uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = rid
        # Security headers (defense in depth; the SPA dev server sets its own CSP).
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith(API_PREFIX):
            response.headers.setdefault("Cache-Control", "no-store")
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if not request.url.path.startswith("/docs"):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        # Strip submitted values from validation errors so PII isn't echoed/logged.
        errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "detail": "Internal server error", "request_id": request_id_ctx.get()})

    for r in (auth.router, account.router, documents.router, bookkeeping.router, tax.router, admin.router):
        app.include_router(r, prefix=API_PREFIX)

    @app.get("/health", tags=["system"])
    def health() -> dict:
        db_ok = True
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "database": db_ok, "ai_enabled": settings.ai_enabled}

    return app


app = create_app()
