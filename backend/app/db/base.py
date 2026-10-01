"""Declarative base and reusable column types."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String, Text, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.crypto import decrypt_str, encrypt_str


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UUIDPKMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EncryptedString(TypeDecorator):
    """Transparently AES-256-GCM encrypts a string column at the application layer.

    The database (and its backups) only ever sees ciphertext. Encrypted columns
    cannot be searched/indexed by value — use a keyed-hash "blind index" column
    alongside if lookups are needed.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else encrypt_str(value)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else decrypt_str(value)


class EncryptedJSON(TypeDecorator):
    """JSON document encrypted at rest (used for OCR/AI extraction results)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        return None if value is None else encrypt_str(json.dumps(value, default=str))

    def process_result_value(self, value: str | None, dialect: Any) -> Any:
        return None if value is None else json.loads(decrypt_str(value))


# Short alias used for enum-like string columns (validated in the app layer and
# with CHECK constraints in docs/schema.sql).
def enum_str(length: int = 32) -> String:
    return String(length)
