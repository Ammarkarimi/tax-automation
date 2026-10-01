"""Account settings, tax profile, and privacy controls (export / delete my data)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, tax_year_param
from app.core.security import verify_password
from app.db.session import get_db
from app.models import Document, EstimatedPayment, GeneratedReport, IncomeForm, Transaction, User
from app.schemas import DeleteAccountRequest, TaxProfileIn, TaxProfileOut, UserOut, UserSettingsUpdate
from app.services import audit, storage
from app.services.tax_service import get_or_create_profile
from app.tax.tables import SUPPORTED_YEARS

router = APIRouter(tags=["account"])


@router.patch("/me/settings", response_model=UserOut)
def update_settings(body: UserSettingsUpdate, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> User:
    changed = body.model_dump(exclude_unset=True)
    for k, v in changed.items():
        setattr(user, k, v)
    db.commit()
    audit.record(db, "account.settings_updated", request=request, actor_id=user.id, actor_role=user.role,
                 details={"fields": sorted(changed)})
    return user


@router.get("/meta")
def meta() -> dict:
    """Static metadata for clients (supported years, categories)."""
    from app.models.enums import CATEGORY_DESCRIPTIONS, SCHEDULE_C_LINE

    today = date.today()
    return {
        "supported_years": SUPPORTED_YEARS,
        "today": today.isoformat(),
        "categories": [
            {"id": c.value, "description": d, "schedule_c_line": SCHEDULE_C_LINE.get(c)}
            for c, d in CATEGORY_DESCRIPTIONS.items()
        ],
    }


def _profile_out(profile) -> TaxProfileOut:
    out = TaxProfileOut.model_validate(profile)
    digits = "".join(c for c in (profile.ssn or "") if c.isdigit())
    out.ssn_last4 = digits[-4:] if digits else None
    return out


@router.get("/profile", response_model=TaxProfileOut)
def get_profile(year: int = Depends(tax_year_param), user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> TaxProfileOut:
    return _profile_out(get_or_create_profile(db, user, year))


@router.put("/profile", response_model=TaxProfileOut)
def update_profile(body: TaxProfileIn, request: Request, year: int = Depends(tax_year_param),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TaxProfileOut:
    profile = get_or_create_profile(db, user, year)
    changed = body.model_dump(exclude_unset=True)
    for k, v in changed.items():
        if k == "ssn" and v:
            v = f"{v.replace('-', '')[:3]}-{v.replace('-', '')[3:5]}-{v.replace('-', '')[5:]}"
        setattr(profile, k, v)
    db.commit()
    db.refresh(profile)
    audit.record(db, "profile.updated", request=request, actor_id=user.id, actor_role=user.role,
                 resource_type="tax_profile", resource_id=profile.id, details={"fields": sorted(changed), "year": year})
    return _profile_out(profile)


@router.get("/me/export")
def export_my_data(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Privacy: download everything we hold about you (decrypted) as JSON."""
    def rows(model):
        return list(db.scalars(select(model).where(model.user_id == user.id)))

    data = {
        "user": UserOut.model_validate(user).model_dump(mode="json"),
        "profiles": [_profile_out(p).model_dump(mode="json") for p in user.profiles],
        "transactions": [
            {"date": t.txn_date.isoformat(), "description": t.description, "amount": str(t.amount),
             "direction": t.direction, "category": t.category, "business_use_pct": t.business_use_pct,
             "tax_year": t.tax_year, "notes": t.notes}
            for t in rows(Transaction)
        ],
        "income_forms": [
            {"tax_year": f.tax_year, "form_type": f.form_type, "payer_name": f.payer_name, "amounts": f.amounts}
            for f in rows(IncomeForm)
        ],
        "estimated_payments": [
            {"tax_year": p.tax_year, "quarter": p.quarter, "amount": str(p.amount), "paid_on": p.paid_on.isoformat()}
            for p in rows(EstimatedPayment)
        ],
        "documents": [
            {"filename": d.original_filename, "doc_type": d.doc_type, "tax_year": d.tax_year,
             "uploaded": d.created_at.isoformat()}
            for d in rows(Document)
        ],
    }
    audit.record(db, "account.data_exported", request=request, actor_id=user.id, actor_role=user.role)
    return data


@router.post("/me/delete", status_code=204)
def delete_account(body: DeleteAccountRequest, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> Response:
    """Privacy: permanently delete the account, all data and all encrypted files."""
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect")
    keys = [d.storage_key for d in db.scalars(select(Document).where(Document.user_id == user.id))]
    keys += [r.storage_key for r in db.scalars(select(GeneratedReport).where(GeneratedReport.user_id == user.id))]
    user_id = user.id
    db.delete(user)  # FK cascades remove dependent rows
    db.commit()
    for k in keys:
        storage.delete(k)
    # Audit entry keeps only the opaque id.
    audit.record(db, "account.deleted", request=request, actor_id=user_id, details={"files_deleted": len(keys)})
    return Response(status_code=204)
