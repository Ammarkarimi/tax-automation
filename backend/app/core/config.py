"""Application settings.

All configuration (and every secret) comes from environment variables or a
local `.env` file. Nothing sensitive is hard-coded: if a required secret is
missing the app refuses to start rather than silently using a default.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_PREFIX = "change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "TaxPilot"

    # --- Database ---
    database_url: str = "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot"

    # --- Secrets ---
    jwt_secret: str = Field(min_length=32)
    data_encryption_key: str
    hmac_secret: str = Field(min_length=32)

    # --- Tokens ---
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    mfa_token_minutes: int = 10

    # --- OTP / login hardening ---
    otp_ttl_minutes: int = 5
    otp_max_attempts: int = 5
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # --- OpenAI ---
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 45.0
    ai_redact_pii: bool = True

    # --- Email ---
    email_backend: Literal["console", "smtp"] = "console"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = False
    email_from: str = "TaxPilot <no-reply@taxpilot.local>"

    # --- Web ---
    cors_origins: str = "http://localhost:5173"
    cookie_secure: bool = False

    # --- Storage ---
    storage_dir: str = "./storage"
    max_upload_mb: int = 15

    # --- Bootstrap ---
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    @field_validator("jwt_secret", "hmac_secret", "data_encryption_key")
    @classmethod
    def _reject_placeholders(cls, value: str) -> str:
        if value.startswith(_PLACEHOLDER_PREFIX):
            raise ValueError(
                "secret still has its placeholder value; run `python scripts/generate_secrets.py`"
            )
        return value

    @field_validator("data_encryption_key")
    @classmethod
    def _validate_encryption_key(cls, value: str) -> str:
        try:
            raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError("DATA_ENCRYPTION_KEY must be urlsafe base64") from exc
        if len(raw) != 32:
            raise ValueError("DATA_ENCRYPTION_KEY must decode to exactly 32 bytes (AES-256)")
        return value

    @field_validator("openai_api_key")
    @classmethod
    def _blank_key_is_none(cls, value: str | None) -> str | None:
        return value or None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def encryption_key_bytes(self) -> bytes:
        v = self.data_encryption_key
        return base64.urlsafe_b64decode(v + "=" * (-len(v) % 4))


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
