"""Bridges the database and the pure tax engine.

Aggregates a user's transactions, W-2/1099 data, profile and payments for a tax
year into a `TaxInput`, runs the engine, and stores an immutable snapshot.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Document,
    EstimatedPayment,
    IncomeForm,
    TaxCalculation,
    TaxProfile,
    Transaction,
    User,
)
from app.models.enums import SCHEDULE_C_LINE, Category, Direction, DocumentType, FilingStatus
from app.tax.audit_risk import assess_audit_risk
from app.tax.context import AnalysisContext
from app.tax.deductions import find_deductions
from app.tax.engine import ENGINE_VERSION, ZERO, TaxInput, compute_tax, money
from app.tax.quarterly import compute_quarterly

D = Decimal


@dataclass
class Aggregate:
    inp: TaxInput
    ctx_fields: dict[str, Any]
    profile: TaxProfile


def get_or_create_profile(db: Session, user: User, year: int) -> TaxProfile:
    profile = db.scalar(
        select(TaxProfile).where(TaxProfile.user_id == user.id, TaxProfile.tax_year == year)
    )
    if profile is None:
        # Carry forward stable facts from the most recent prior profile.
        prev = db.scalar(
            select(TaxProfile)
            .where(TaxProfile.user_id == user.id, TaxProfile.tax_year < year)
            .order_by(TaxProfile.tax_year.desc())
        )
        profile = TaxProfile(user_id=user.id, tax_year=year)
        if prev:
            for attr in (
                "filing_status", "taxpayer_name", "ssn", "address", "business_name",
                "business_description", "business_code", "is_cash_intensive", "is_sstb",
                "age_65_or_older", "spouse_age_65_or_older", "qualifying_children",
                "other_dependents", "home_office_sqft",
            ):
                setattr(profile, attr, getattr(prev, attr))
            profile.beginning_inventory = prev.ending_inventory
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def aggregate(db: Session, user: User, year: int, as_of: date | None = None) -> Aggregate:
    profile = get_or_create_profile(db, user, year)
    q = select(Transaction).where(Transaction.user_id == user.id, Transaction.tax_year == year)
    if as_of:
        q = q.where(Transaction.txn_date <= as_of)
    txns = list(db.scalars(q))

    sums: dict[str, D] = defaultdict(lambda: ZERO)  # signed business amounts per category
    counts: dict[str, int] = defaultdict(int)
    needs_review = 0
    expense_count = 0
    round_count = 0
    car_all_full = True
    car_seen = False

    for t in txns:
        cat = t.category
        counts[cat] += 1
        if t.needs_review:
            needs_review += 1
        biz_amount = money(D(t.amount) * D(t.business_use_pct) / D(100))
        try:
            category = Category(cat)
        except ValueError:
            category = Category.UNCATEGORIZED
        is_income_cat = category in (
            Category.BUSINESS_INCOME, Category.OTHER_BUSINESS_INCOME, Category.INTEREST_INCOME
        )
        # Income categories grow with income; expense categories grow with expenses.
        # A transaction in the "opposite" direction (e.g. supplier refund) nets against it.
        natural = Direction.INCOME if is_income_cat else Direction.EXPENSE
        sign = D(1) if t.direction == natural else D(-1)
        sums[cat] += sign * biz_amount
        if t.direction == Direction.EXPENSE and category in SCHEDULE_C_LINE:
            expense_count += 1
            if D(t.amount) >= 100 and D(t.amount) % 100 == 0:
                round_count += 1
        if category == Category.CAR_TRUCK and t.direction == Direction.EXPENSE:
            car_seen = True
            car_all_full = car_all_full and t.business_use_pct >= 100

    expenses: dict[str, D] = defaultdict(lambda: ZERO)
    for cat, line in SCHEDULE_C_LINE.items():
        if sums.get(cat.value):
            expenses[line] += sums[cat.value]

    # ---- W-2 / 1099 data ----
    forms = list(db.scalars(select(IncomeForm).where(IncomeForm.user_id == user.id, IncomeForm.tax_year == year)))
    w2 = defaultdict(lambda: ZERO)
    reported_1099 = ZERO
    k_gross = ZERO
    form_interest = ZERO
    form_dividends = ZERO
    withholding = ZERO
    for f in forms:
        a = {k: D(str(v)) for k, v in (f.amounts or {}).items() if v is not None}
        withholding += a.get("federal_withholding", ZERO)
        if f.form_type == DocumentType.W2:
            for k in ("wages", "social_security_wages", "medicare_wages"):
                w2[k] += a.get(k, ZERO)
        elif f.form_type == DocumentType.F1099_NEC:
            reported_1099 += a.get("nonemployee_compensation", ZERO)
        elif f.form_type == DocumentType.F1099_MISC:
            reported_1099 += a.get("other_income", ZERO)
        elif f.form_type == DocumentType.F1099_K:
            k_gross += a.get("gross_payments", ZERO)
            reported_1099 += a.get("gross_payments", ZERO)
        elif f.form_type == DocumentType.F1099_INT:
            form_interest += a.get("interest_income", ZERO)
        elif f.form_type == DocumentType.F1099_DIV:
            form_dividends += a.get("ordinary_dividends", ZERO)

    recorded_receipts = money(max(sums.get(Category.BUSINESS_INCOME.value, ZERO), ZERO))
    gross_receipts = recorded_receipts
    used_1099_floor = False
    if as_of is None and reported_1099 > recorded_receipts:
        # Never report less than the IRS already knows about from 1099s.
        gross_receipts = money(reported_1099)
        used_1099_floor = True

    est_table = db.scalar(
        select(func.coalesce(func.sum(EstimatedPayment.amount), 0)).where(
            EstimatedPayment.user_id == user.id, EstimatedPayment.tax_year == year
        )
    )
    est_txn = max(sums.get(Category.ESTIMATED_TAX_PAYMENT.value, ZERO), ZERO)
    # Prefer explicitly recorded payments; fall back to categorized bank transactions.
    estimated = D(est_table) if D(est_table) > 0 else est_txn

    inp = TaxInput(
        tax_year=year,
        filing_status=FilingStatus(profile.filing_status),
        gross_receipts=gross_receipts,
        returns_allowances=max(sums.get(Category.RETURNS_ALLOWANCES.value, ZERO), ZERO),
        other_business_income=max(sums.get(Category.OTHER_BUSINESS_INCOME.value, ZERO), ZERO),
        beginning_inventory=D(profile.beginning_inventory or 0),
        inventory_purchases=max(sums.get(Category.INVENTORY_PURCHASES.value, ZERO), ZERO),
        ending_inventory=D(profile.ending_inventory or 0) if as_of is None else D(profile.beginning_inventory or 0),
        expenses={k: max(v, ZERO) for k, v in expenses.items()},
        business_miles=profile.business_miles or 0,
        home_office_sqft=profile.home_office_sqft or 0,
        is_sstb=profile.is_sstb,
        w2_wages=w2["wages"],
        w2_ss_wages=w2["social_security_wages"],
        w2_medicare_wages=w2["medicare_wages"],
        interest_income=max(sums.get(Category.INTEREST_INCOME.value, ZERO), form_interest),
        dividend_income=form_dividends,
        other_income=D(profile.other_income or 0),
        se_health_insurance=max(sums.get(Category.HEALTH_INSURANCE.value, ZERO), ZERO),
        retirement_contributions=max(sums.get(Category.RETIREMENT_CONTRIBUTION.value, ZERO), ZERO),
        age_65_or_older=profile.age_65_or_older,
        spouse_age_65_or_older=profile.spouse_age_65_or_older,
        qualifying_children=profile.qualifying_children or 0,
        other_dependents=profile.other_dependents or 0,
        qualified_tips=D(profile.qualified_tips or 0),
        federal_withholding=withholding,
        estimated_payments=estimated,
    )

    has_docs = bool(
        db.scalar(select(func.count(Document.id)).where(Document.user_id == user.id, Document.tax_year == year))
    )
    ctx_fields = {
        "category_totals": {k: money(v) for k, v in sums.items()},
        "category_counts": dict(counts),
        "total_transactions": len(txns),
        "needs_review_count": needs_review,
        "round_number_expense_ratio": (round_count / expense_count) if expense_count else 0.0,
        "car_expense_full_business_use": car_seen and car_all_full and sums.get("car_truck", ZERO) > 1000,
        "recorded_receipts": recorded_receipts,
        "reported_1099_income": money(reported_1099),
        "form_1099k_gross": money(k_gross),
        "is_cash_intensive": profile.is_cash_intensive,
        "has_documents": has_docs,
        "used_1099_floor": used_1099_floor,
    }
    return Aggregate(inp=inp, ctx_fields=ctx_fields, profile=profile)


def _context(agg: Aggregate, result: dict[str, Any]) -> AnalysisContext:
    fields = {k: v for k, v in agg.ctx_fields.items() if k != "used_1099_floor"}
    return AnalysisContext(inp=agg.inp, result=result, **fields)


def _snapshot(db: Session, user_id: uuid.UUID, year: int, kind: str, result: dict[str, Any]) -> None:
    db.add(TaxCalculation(user_id=user_id, tax_year=year, kind=kind, engine_version=ENGINE_VERSION, result=result))
    db.commit()


def annual(db: Session, user: User, year: int, save: bool = True) -> dict[str, Any]:
    agg = aggregate(db, user, year)
    result = compute_tax(agg.inp)
    if agg.ctx_fields["used_1099_floor"]:
        result["warnings"].insert(
            0,
            f"Gross receipts were raised to your 1099 total (${agg.ctx_fields['reported_1099_income']:,.2f}) "
            f"because recorded business income was lower (${agg.ctx_fields['recorded_receipts']:,.2f}). "
            "Import all deposits so income isn't under- or double-counted.",
        )
    result["data_quality"] = {
        "transactions": agg.ctx_fields["total_transactions"],
        "needs_review": agg.ctx_fields["needs_review_count"],
        "reported_1099_income": float(agg.ctx_fields["reported_1099_income"]),
        "recorded_receipts": float(agg.ctx_fields["recorded_receipts"]),
    }
    if save:
        _snapshot(db, user.id, year, "annual", result)
    return result


def quarterly(db: Session, user: User, year: int, as_of: date | None = None) -> dict[str, Any]:
    today = as_of or date.today()
    if today.year > year:
        today = date(year, 12, 31)
    agg = aggregate(db, user, year, as_of=today)
    payments = [
        (p.quarter, D(p.amount), p.paid_on)
        for p in db.scalars(
            select(EstimatedPayment).where(EstimatedPayment.user_id == user.id, EstimatedPayment.tax_year == year)
        )
    ]
    prof = agg.profile
    result = compute_quarterly(
        agg.inp,
        today,
        payments,
        prior_year_tax=D(prof.prior_year_tax) if prof.prior_year_tax is not None else None,
        prior_year_agi=D(prof.prior_year_agi) if prof.prior_year_agi is not None else None,
    )
    _snapshot(db, user.id, year, "quarterly", result)
    return result


def analysis(db: Session, user: User, year: int) -> tuple[dict[str, Any], AnalysisContext, Aggregate]:
    agg = aggregate(db, user, year)
    result = compute_tax(agg.inp)
    return result, _context(agg, result), agg


def deductions(db: Session, user: User, year: int) -> tuple[list[dict[str, Any]], AnalysisContext, Aggregate]:
    _, ctx, agg = analysis(db, user, year)
    return find_deductions(ctx), ctx, agg


def audit_risk(db: Session, user: User, year: int) -> dict[str, Any]:
    _, ctx, _ = analysis(db, user, year)
    return assess_audit_risk(ctx)
