"""Pydantic request/response schemas (the API contract)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import Category, Direction, DocumentType, FilingStatus, Role

# ----------------------------- Auth -----------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class MFAChallenge(BaseModel):
    mfa_required: bool = True
    mfa_token: str
    delivery: str = "email"
    masked_email: str
    expires_in: int


class VerifyOTPRequest(BaseModel):
    mfa_token: str
    code: str = Field(pattern=r"^\d{6}$")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = None  # only returned to mobile clients
    user: UserOut


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class ResendOTPRequest(BaseModel):
    mfa_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=128)


# ----------------------------- Users -----------------------------


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: Role
    email_verified: bool
    ai_consent: bool
    created_at: datetime


class DeleteAccountRequest(BaseModel):
    password: str = Field(max_length=128)


class UserSettingsUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    ai_consent: bool | None = None


# ----------------------------- Profile -----------------------------


class TaxProfileIn(BaseModel):
    filing_status: FilingStatus | None = None
    taxpayer_name: str | None = Field(default=None, max_length=200)
    ssn: str | None = Field(default=None, pattern=r"^\d{3}-?\d{2}-?\d{4}$")
    address: str | None = Field(default=None, max_length=300)
    business_name: str | None = Field(default=None, max_length=200)
    business_description: str | None = Field(default=None, max_length=200)
    business_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    is_cash_intensive: bool | None = None
    is_sstb: bool | None = None
    age_65_or_older: bool | None = None
    spouse_age_65_or_older: bool | None = None
    qualifying_children: int | None = Field(default=None, ge=0, le=20)
    other_dependents: int | None = Field(default=None, ge=0, le=20)
    home_office_sqft: int | None = Field(default=None, ge=0, le=10000)
    business_miles: int | None = Field(default=None, ge=0, le=200000)
    beginning_inventory: Decimal | None = Field(default=None, ge=0, le=100_000_000)
    ending_inventory: Decimal | None = Field(default=None, ge=0, le=100_000_000)
    qualified_tips: Decimal | None = Field(default=None, ge=0, le=10_000_000)
    other_income: Decimal | None = Field(default=None, ge=-100_000_000, le=100_000_000)
    prior_year_tax: Decimal | None = Field(default=None, ge=0, le=100_000_000)
    prior_year_agi: Decimal | None = Field(default=None, ge=-100_000_000, le=1_000_000_000)


class TaxProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tax_year: int
    filing_status: FilingStatus
    taxpayer_name: str | None
    ssn_last4: str | None = None
    address: str | None
    business_name: str | None
    business_description: str | None
    business_code: str | None
    is_cash_intensive: bool
    is_sstb: bool
    age_65_or_older: bool
    spouse_age_65_or_older: bool
    qualifying_children: int
    other_dependents: int
    home_office_sqft: int
    business_miles: int
    beginning_inventory: Decimal
    ending_inventory: Decimal
    qualified_tips: Decimal
    other_income: Decimal
    prior_year_tax: Decimal | None
    prior_year_agi: Decimal | None


# ----------------------------- Documents -----------------------------


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tax_year: int
    original_filename: str
    content_type: str
    size_bytes: int
    doc_type: DocumentType
    status: str
    error: str | None
    extracted_data: dict[str, Any] | None
    created_at: datetime
    processed_at: datetime | None


# ----------------------------- Transactions -----------------------------


class TransactionIn(BaseModel):
    txn_date: date
    description: str = Field(min_length=1, max_length=500)
    amount: Decimal = Field(gt=0, le=100_000_000, decimal_places=2)
    direction: Direction
    category: Category | None = None
    business_use_pct: int = Field(default=100, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=1000)


class TransactionUpdate(BaseModel):
    txn_date: date | None = None
    description: str | None = Field(default=None, min_length=1, max_length=500)
    amount: Decimal | None = Field(default=None, gt=0, le=100_000_000, decimal_places=2)
    direction: Direction | None = None
    category: Category | None = None
    business_use_pct: int | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=1000)
    needs_review: bool | None = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID | None
    tax_year: int
    txn_date: date
    description: str
    merchant: str | None
    amount: Decimal
    direction: Direction
    category: Category
    business_use_pct: int
    confidence: float | None
    classified_by: str
    ai_rationale: str | None
    needs_review: bool
    notes: str | None


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    page_size: int


class BulkCategorize(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    category: Category
    business_use_pct: int | None = Field(default=None, ge=0, le=100)


class ReclassifyRequest(BaseModel):
    only_needs_review: bool = True


# ----------------------------- Income forms / payments -----------------------------


class IncomeFormIn(BaseModel):
    form_type: DocumentType
    payer_name: str | None = Field(default=None, max_length=200)
    amounts: dict[str, Decimal] = Field(default_factory=dict)
    confirmed: bool = True

    @field_validator("form_type")
    @classmethod
    def _tax_form_only(cls, v: DocumentType) -> DocumentType:
        if v.value not in {"w2", "1099_nec", "1099_misc", "1099_k", "1099_int", "1099_div"}:
            raise ValueError("form_type must be a W-2 or 1099 type")
        return v

    @field_validator("amounts")
    @classmethod
    def _bounded(cls, v: dict[str, Decimal]) -> dict[str, Decimal]:
        from app.ai.document_extractor import AMOUNT_FIELDS

        for k, amt in v.items():
            if k not in AMOUNT_FIELDS:
                raise ValueError(f"unknown amount field: {k}")
            if amt < 0 or amt > 100_000_000:
                raise ValueError(f"{k} out of range")
        return v


class IncomeFormOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID | None
    tax_year: int
    form_type: DocumentType
    payer_name: str | None
    amounts: dict[str, Any]
    confirmed: bool


class EstimatedPaymentIn(BaseModel):
    quarter: int = Field(ge=1, le=4)
    amount: Decimal = Field(gt=0, le=100_000_000)
    paid_on: date


class EstimatedPaymentOut(EstimatedPaymentIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tax_year: int


# ----------------------------- AI -----------------------------


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class Explanation(BaseModel):
    source: str  # ai | template
    markdown: str


# ----------------------------- Admin -----------------------------


class AdminUserOut(BaseModel):
    id: uuid.UUID
    email_masked: str
    role: Role
    is_active: bool
    email_verified: bool
    locked: bool
    created_at: datetime
    last_login_at: datetime | None
    document_count: int
    transaction_count: int


class AdminUserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    unlock: bool | None = None


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    success: bool
    ip_address: str | None
    request_id: str | None
    details: dict[str, Any] | None


TokenResponse.model_rebuild()
