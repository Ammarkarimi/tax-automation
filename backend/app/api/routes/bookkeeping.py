"""Transactions, W-2/1099 income forms and estimated tax payments."""

from __future__ import annotations

import csv
import io
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, tax_year_param
from app.db.session import get_db
from app.models import EstimatedPayment, IncomeForm, Transaction, User
from app.models.enums import Category, ClassifiedBy, Direction
from app.schemas import (
    BulkCategorize,
    EstimatedPaymentIn,
    EstimatedPaymentOut,
    IncomeFormIn,
    IncomeFormOut,
    ReclassifyRequest,
    TransactionIn,
    TransactionOut,
    TransactionPage,
    TransactionUpdate,
)
from app.services import audit
from app.services.document_service import create_transactions, reclassify
from app.services.rate_limit import ai_limiter, client_key

router = APIRouter(tags=["bookkeeping"])


def _owned(db: Session, model, user: User, obj_id: uuid.UUID):
    obj = db.get(model, obj_id)
    if obj is None or obj.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    return obj


# ----------------------------- Transactions -----------------------------


@router.get("/transactions", response_model=TransactionPage)
def list_transactions(
    year: int = Depends(tax_year_param),
    category: Category | None = None,
    direction: Direction | None = None,
    needs_review: bool | None = None,
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionPage:
    q = select(Transaction).where(Transaction.user_id == user.id, Transaction.tax_year == year)
    if category:
        q = q.where(Transaction.category == category.value)
    if direction:
        q = q.where(Transaction.direction == direction.value)
    if needs_review is not None:
        q = q.where(Transaction.needs_review == needs_review)
    q = q.order_by(Transaction.txn_date.desc(), Transaction.created_at.desc())
    if search:
        # Descriptions are encrypted at rest, so search happens after decryption.
        needle = search.lower()
        rows = [t for t in db.scalars(q) if needle in t.description.lower() or needle in (t.merchant or "").lower()]
        total = len(rows)
        items = rows[(page - 1) * page_size : page * page_size]
    else:
        total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
        items = list(db.scalars(q.offset((page - 1) * page_size).limit(page_size)))
    return TransactionPage(items=items, total=total, page=page, page_size=page_size)


@router.post("/transactions", response_model=TransactionOut, status_code=201)
def create_transaction(body: TransactionIn, request: Request, year: int = Depends(tax_year_param),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Transaction:
    if body.txn_date.year != year:
        raise HTTPException(status_code=422, detail=f"Date must be in tax year {year}")
    if body.category:
        t = Transaction(
            user_id=user.id, tax_year=year, txn_date=body.txn_date, description=body.description,
            amount=body.amount, direction=body.direction.value, category=body.category.value,
            business_use_pct=body.business_use_pct, classified_by=ClassifiedBy.USER.value,
            confidence=1.0, needs_review=False, notes=body.notes,
        )
        db.add(t)
    else:
        (t,) = create_transactions(db, user, None, year,
                                   [(body.txn_date, body.description, body.amount, body.direction)])
        t.notes = body.notes
    db.commit()
    db.refresh(t)
    audit.record(db, "transaction.created", request=request, actor_id=user.id, resource_type="transaction",
                 resource_id=t.id)
    return t


@router.patch("/transactions/{txn_id}", response_model=TransactionOut)
def update_transaction(txn_id: uuid.UUID, body: TransactionUpdate, request: Request,
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Transaction:
    t = _owned(db, Transaction, user, txn_id)
    changes = body.model_dump(exclude_unset=True)
    if "txn_date" in changes and changes["txn_date"].year != t.tax_year:
        raise HTTPException(status_code=422, detail=f"Date must be in tax year {t.tax_year}")
    for k, v in changes.items():
        setattr(t, k, v.value if hasattr(v, "value") else v)
    if {"category", "direction", "business_use_pct"} & changes.keys():
        t.classified_by = ClassifiedBy.USER.value
        t.confidence = 1.0
        if "needs_review" not in changes:
            t.needs_review = t.category == Category.UNCATEGORIZED.value
    db.commit()
    db.refresh(t)
    audit.record(db, "transaction.updated", request=request, actor_id=user.id, resource_type="transaction",
                 resource_id=t.id, details={"fields": sorted(changes)})
    return t


@router.delete("/transactions/{txn_id}", status_code=204)
def delete_transaction(txn_id: uuid.UUID, request: Request, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> Response:
    t = _owned(db, Transaction, user, txn_id)
    db.delete(t)
    db.commit()
    audit.record(db, "transaction.deleted", request=request, actor_id=user.id, resource_type="transaction",
                 resource_id=txn_id)
    return Response(status_code=204)


@router.post("/transactions/bulk-categorize")
def bulk_categorize(body: BulkCategorize, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> dict:
    txns = list(db.scalars(select(Transaction).where(Transaction.user_id == user.id, Transaction.id.in_(body.ids))))
    for t in txns:
        t.category = body.category.value
        if body.business_use_pct is not None:
            t.business_use_pct = body.business_use_pct
        t.classified_by = ClassifiedBy.USER.value
        t.confidence = 1.0
        t.needs_review = body.category == Category.UNCATEGORIZED
    db.commit()
    audit.record(db, "transaction.bulk_categorized", request=request, actor_id=user.id,
                 details={"count": len(txns), "category": body.category.value})
    return {"updated": len(txns)}


@router.post("/transactions/reclassify")
def reclassify_transactions(body: ReclassifyRequest, request: Request, year: int = Depends(tax_year_param),
                            user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Re-run AI/rule classification (never overrides user-confirmed categories)."""
    ai_limiter.check(client_key(request, f"reclassify:{user.id}"))
    q = select(Transaction).where(Transaction.user_id == user.id, Transaction.tax_year == year,
                                  Transaction.classified_by != ClassifiedBy.USER.value)
    if body.only_needs_review:
        q = q.where(Transaction.needs_review.is_(True))
    txns = list(db.scalars(q.limit(1000)))
    n = reclassify(db, user, txns, year) if txns else 0
    audit.record(db, "transaction.reclassified", request=request, actor_id=user.id, details={"count": n})
    return {"reclassified": n}


@router.get("/transactions/export.csv")
def export_transactions(request: Request, year: int = Depends(tax_year_param), user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "description", "direction", "amount", "category", "business_use_pct", "deductible_amount"])
    for t in db.scalars(select(Transaction).where(Transaction.user_id == user.id, Transaction.tax_year == year)
                        .order_by(Transaction.txn_date)):
        desc = t.description
        if desc[:1] in ("=", "+", "-", "@"):
            desc = "'" + desc  # neutralize spreadsheet formula injection
        w.writerow([t.txn_date.isoformat(), desc, t.direction, f"{t.amount:.2f}", t.category, t.business_use_pct,
                    f"{Decimal(t.amount) * t.business_use_pct / 100:.2f}"])
    audit.record(db, "transaction.exported", request=request, actor_id=user.id, details={"year": year})
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="transactions-{year}.csv"'})


# ----------------------------- Income forms -----------------------------


@router.get("/income-forms", response_model=list[IncomeFormOut])
def list_forms(year: int = Depends(tax_year_param), user: User = Depends(get_current_user),
               db: Session = Depends(get_db)) -> list[IncomeForm]:
    return list(db.scalars(select(IncomeForm).where(IncomeForm.user_id == user.id, IncomeForm.tax_year == year)))


@router.post("/income-forms", response_model=IncomeFormOut, status_code=201)
def create_form(body: IncomeFormIn, request: Request, year: int = Depends(tax_year_param),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> IncomeForm:
    f = IncomeForm(user_id=user.id, tax_year=year, form_type=body.form_type.value, payer_name=body.payer_name,
                   amounts={k: float(v) for k, v in body.amounts.items()}, confirmed=body.confirmed)
    db.add(f)
    db.commit()
    db.refresh(f)
    audit.record(db, "income_form.created", request=request, actor_id=user.id, resource_type="income_form",
                 resource_id=f.id)
    return f


@router.put("/income-forms/{form_id}", response_model=IncomeFormOut)
def update_form(form_id: uuid.UUID, body: IncomeFormIn, request: Request, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> IncomeForm:
    f = _owned(db, IncomeForm, user, form_id)
    f.form_type = body.form_type.value
    f.payer_name = body.payer_name
    f.amounts = {k: float(v) for k, v in body.amounts.items()}
    f.confirmed = body.confirmed
    db.commit()
    db.refresh(f)
    audit.record(db, "income_form.updated", request=request, actor_id=user.id, resource_type="income_form",
                 resource_id=f.id)
    return f


@router.delete("/income-forms/{form_id}", status_code=204)
def delete_form(form_id: uuid.UUID, request: Request, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> Response:
    f = _owned(db, IncomeForm, user, form_id)
    db.delete(f)
    db.commit()
    audit.record(db, "income_form.deleted", request=request, actor_id=user.id, resource_type="income_form",
                 resource_id=form_id)
    return Response(status_code=204)


# ----------------------------- Estimated payments -----------------------------


@router.get("/estimated-payments", response_model=list[EstimatedPaymentOut])
def list_payments(year: int = Depends(tax_year_param), user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)) -> list[EstimatedPayment]:
    return list(db.scalars(select(EstimatedPayment).where(EstimatedPayment.user_id == user.id,
                                                          EstimatedPayment.tax_year == year)
                           .order_by(EstimatedPayment.quarter)))


@router.post("/estimated-payments", response_model=EstimatedPaymentOut, status_code=201)
def add_payment(body: EstimatedPaymentIn, request: Request, year: int = Depends(tax_year_param),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> EstimatedPayment:
    p = EstimatedPayment(user_id=user.id, tax_year=year, **body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    audit.record(db, "estimated_payment.created", request=request, actor_id=user.id,
                 resource_type="estimated_payment", resource_id=p.id)
    return p


@router.delete("/estimated-payments/{payment_id}", status_code=204)
def delete_payment(payment_id: uuid.UUID, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> Response:
    p = _owned(db, EstimatedPayment, user, payment_id)
    db.delete(p)
    db.commit()
    audit.record(db, "estimated_payment.deleted", request=request, actor_id=user.id,
                 resource_type="estimated_payment", resource_id=payment_id)
    return Response(status_code=204)
