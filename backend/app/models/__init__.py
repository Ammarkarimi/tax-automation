"""SQLAlchemy ORM models. See docs/schema.sql for the equivalent PostgreSQL DDL."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    EncryptedJSON,
    EncryptedString,
    TimestampMixin,
    UUIDPKMixin,
    enum_str,
    utcnow,
)
from app.models.enums import (
    Category,
    ClassifiedBy,
    Direction,
    DocumentStatus,
    DocumentType,
    FilingStatus,
    Role,
)

Money = Numeric(14, 2)


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(EncryptedString)
    role: Mapped[str] = mapped_column(enum_str(16), default=Role.USER.value)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Explicit consent before any document text is sent to OpenAI.
    ai_consent: Mapped[bool] = mapped_column(Boolean, default=False)

    profiles: Mapped[list[TaxProfile]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class OTPCode(UUIDPKMixin, Base):
    __tablename__ = "otp_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))  # HMAC-SHA256, never the code itself
    purpose: Mapped[str] = mapped_column(enum_str(16))  # login | verify_email
    # Binds the OTP to the specific login attempt (jti of the MFA token).
    challenge_id: Mapped[str] = mapped_column(String(64), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefreshToken(UUIDPKMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # All tokens produced by rotating one login share a family; reuse of a
    # rotated token revokes the whole family (token-theft detection).
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column()
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TaxProfile(UUIDPKMixin, TimestampMixin, Base):
    """Per-year facts about the taxpayer that aren't transactions."""

    __tablename__ = "tax_profiles"
    __table_args__ = (UniqueConstraint("user_id", "tax_year", name="uq_profile_user_year"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tax_year: Mapped[int] = mapped_column(Integer)
    filing_status: Mapped[str] = mapped_column(enum_str(24), default=FilingStatus.SINGLE.value)

    # Identity — encrypted. Only used when rendering the PDF worksheet.
    taxpayer_name: Mapped[str | None] = mapped_column(EncryptedString)
    ssn: Mapped[str | None] = mapped_column(EncryptedString)
    address: Mapped[str | None] = mapped_column(EncryptedString)

    # Business (Schedule C header)
    business_name: Mapped[str | None] = mapped_column(String(200))
    business_description: Mapped[str | None] = mapped_column(String(200))
    business_code: Mapped[str | None] = mapped_column(String(6))  # NAICS principal business code
    is_cash_intensive: Mapped[bool] = mapped_column(Boolean, default=False)

    # Household
    age_65_or_older: Mapped[bool] = mapped_column(Boolean, default=False)
    spouse_age_65_or_older: Mapped[bool] = mapped_column(Boolean, default=False)
    qualifying_children: Mapped[int] = mapped_column(Integer, default=0)  # under 17, for CTC
    other_dependents: Mapped[int] = mapped_column(Integer, default=0)

    # Deduction inputs not derivable from transactions
    home_office_sqft: Mapped[int] = mapped_column(Integer, default=0)
    business_miles: Mapped[int] = mapped_column(Integer, default=0)
    beginning_inventory: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    ending_inventory: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    qualified_tips: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    other_income: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))

    # Safe-harbor inputs for quarterly estimates
    prior_year_tax: Mapped[Decimal | None] = mapped_column(Money)
    prior_year_agi: Mapped[Decimal | None] = mapped_column(Money)

    user: Mapped[User] = relationship(back_populates="profiles")


class Document(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tax_year: Mapped[int] = mapped_column(Integer)
    original_filename: Mapped[str] = mapped_column(EncryptedString)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))  # of the plaintext; detects duplicates
    storage_key: Mapped[str] = mapped_column(String(128))  # random name, no PII in paths
    doc_type: Mapped[str] = mapped_column(enum_str(24), default=DocumentType.OTHER.value)
    status: Mapped[str] = mapped_column(enum_str(16), default=DocumentStatus.UPLOADED.value)
    extracted_data: Mapped[dict[str, Any] | None] = mapped_column(EncryptedJSON)
    error: Mapped[str | None] = mapped_column(String(500))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IncomeForm(UUIDPKMixin, TimestampMixin, Base):
    """Structured W-2 / 1099 data (from AI extraction or manual entry)."""

    __tablename__ = "income_forms"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    tax_year: Mapped[int] = mapped_column(Integer)
    form_type: Mapped[str] = mapped_column(enum_str(24))
    payer_name: Mapped[str | None] = mapped_column(String(200))
    # Box amounts, e.g. {"wages": 1000, "federal_withholding": 100, ...}
    amounts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class Transaction(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_tx_user_year", "user_id", "tax_year"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    tax_year: Mapped[int] = mapped_column(Integer)
    txn_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(EncryptedString)
    merchant: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Money)  # always positive; see direction
    direction: Mapped[str] = mapped_column(enum_str(8), default=Direction.EXPENSE.value)
    category: Mapped[str] = mapped_column(enum_str(32), default=Category.UNCATEGORIZED.value)
    business_use_pct: Mapped[int] = mapped_column(Integer, default=100)
    confidence: Mapped[float | None] = mapped_column()
    classified_by: Mapped[str] = mapped_column(enum_str(8), default=ClassifiedBy.IMPORT.value)
    ai_rationale: Mapped[str | None] = mapped_column(String(500))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(EncryptedString)


class EstimatedPayment(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "estimated_payments"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tax_year: Mapped[int] = mapped_column(Integer)
    quarter: Mapped[int] = mapped_column(Integer)  # 1-4
    amount: Mapped[Decimal] = mapped_column(Money)
    paid_on: Mapped[date] = mapped_column(Date)


class TaxCalculation(UUIDPKMixin, Base):
    """Immutable snapshot of each computation — part of the audit trail."""

    __tablename__ = "tax_calculations"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tax_year: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(enum_str(16))  # annual | quarterly
    engine_version: Mapped[str] = mapped_column(String(16))
    result: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GeneratedReport(UUIDPKMixin, Base):
    __tablename__ = "generated_reports"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tax_year: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(enum_str(32))  # form_1040_schedule_c
    storage_key: Mapped[str] = mapped_column(String(128))
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Append-only audit trail. Never stores raw PII — only ids and safe metadata."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    actor_role: Mapped[str | None] = mapped_column(enum_str(16))
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)


__all__ = [
    "AuditLog",
    "Base",
    "Document",
    "EstimatedPayment",
    "GeneratedReport",
    "IncomeForm",
    "OTPCode",
    "RefreshToken",
    "TaxCalculation",
    "TaxProfile",
    "Transaction",
    "User",
]
