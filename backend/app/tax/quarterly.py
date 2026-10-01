"""Quarterly estimated tax (Form 1040-ES) planning.

Approach:
1. Project the full-year return by annualizing year-to-date activity.
2. Required annual payment = the smaller of
     * 90% of the projected current-year tax, or
     * 100% of last year's tax (110% if last year's AGI > $150k / $75k MFS),
   which is the IRS safe harbor that avoids the underpayment penalty.
3. Subtract projected withholding, split into four equal installments and
   compare with what has been paid by each due date.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.models.enums import FilingStatus
from app.tax import tables as T
from app.tax.engine import ZERO, TaxInput, compute_tax, money, pos

ANNUALIZABLE_FIELDS = (
    "gross_receipts",
    "returns_allowances",
    "other_business_income",
    "inventory_purchases",
    "w2_wages",
    "w2_ss_wages",
    "w2_medicare_wages",
    "interest_income",
    "dividend_income",
    "federal_withholding",
    "se_health_insurance",
)


def _next_business_day(d: date) -> date:
    # Weekends roll to Monday. (Federal holidays like Emancipation Day can push
    # dates further — always confirm on irs.gov.)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def due_dates(tax_year: int) -> list[date]:
    raw = [
        date(tax_year, 4, 15),
        date(tax_year, 6, 15),
        date(tax_year, 9, 15),
        date(tax_year + 1, 1, 15),
    ]
    return [_next_business_day(d) for d in raw]


def annualization_factor(tax_year: int, as_of: date) -> Decimal:
    start = date(tax_year, 1, 1)
    end = date(tax_year, 12, 31)
    if as_of >= end:
        return Decimal(1)
    days = max((as_of - start).days + 1, 30)  # avoid wild extrapolation in early January
    return (Decimal(366 if _is_leap(tax_year) else 365) / Decimal(days)).quantize(Decimal("0.0001"))


def _is_leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def annualize(inp: TaxInput, factor: Decimal) -> TaxInput:
    data = dataclasses.replace(inp)
    for name in ANNUALIZABLE_FIELDS:
        setattr(data, name, money(getattr(inp, name) * factor))
    data.expenses = {k: money(v * factor) for k, v in inp.expenses.items()}
    data.business_miles = int(inp.business_miles * factor)
    # Payments are compared installment by installment, not projected.
    data.estimated_payments = ZERO
    return data


def compute_quarterly(
    ytd: TaxInput,
    as_of: date,
    payments: list[tuple[int, Decimal, date]],
    prior_year_tax: Decimal | None = None,
    prior_year_agi: Decimal | None = None,
) -> dict[str, Any]:
    """`payments` is a list of (quarter, amount, paid_on)."""
    factor = annualization_factor(ytd.tax_year, as_of)
    projected_input = annualize(ytd, factor)
    projection = compute_tax(projected_input)
    fs = FilingStatus(ytd.filing_status)

    projected_total_tax = Decimal(str(projection["form_1040"]["line24_total_tax"]))
    # Refundable credits reduce what must be prepaid.
    projected_actc = Decimal(str(projection["form_1040"]["line28_actc"]))
    projected_tax_net = pos(projected_total_tax - projected_actc)
    projected_withholding = Decimal(str(projection["form_1040"]["line25_withholding"]))

    current_year_target = money(projected_tax_net * Decimal("0.90"))
    safe_harbor_basis = "90% of projected current-year tax"
    required_annual = current_year_target
    if prior_year_tax is not None:
        multiplier = Decimal("1.00")
        if prior_year_agi is not None and prior_year_agi > T.SAFE_HARBOR_HIGH_AGI[fs]:
            multiplier = Decimal("1.10")
        prior_target = money(prior_year_tax * multiplier)
        if prior_target < required_annual:
            required_annual = prior_target
            safe_harbor_basis = f"{int(multiplier * 100)}% of last year's tax"

    required_from_estimates = pos(required_annual - projected_withholding)
    installment = money(required_from_estimates / 4)

    dates = due_dates(ytd.tax_year)
    total_paid = money(sum((amt for _, amt, _ in payments), ZERO))
    quarters = []
    for q, due in enumerate(dates, start=1):
        paid_by_due = money(sum((amt for _, amt, paid_on in payments if paid_on <= due), ZERO))
        paid_for_quarter = money(sum((amt for qq, amt, _ in payments if qq == q), ZERO))
        cumulative_required = installment * q
        if as_of > due:
            # Past due date: judged on what had been paid by that date.
            amount_due = pos(cumulative_required - paid_by_due)
            status = "paid" if amount_due == 0 else "underpaid"
        else:
            amount_due = pos(cumulative_required - total_paid)
            status = "covered" if amount_due == 0 else "upcoming"
        quarters.append(
            {
                "quarter": q,
                "due_date": due.isoformat(),
                "installment": installment,
                "cumulative_required": money(cumulative_required),
                "paid_by_due_date": paid_by_due,
                "paid_for_quarter": paid_for_quarter,
                "amount_due": money(amount_due),
                "status": status,
            }
        )

    next_q = next((q for q in quarters if q["status"] == "upcoming"), None)
    full_year_safe = money(projected_tax_net - projected_withholding - total_paid)

    def f(x: Decimal) -> float:
        return float(money(x))

    return {
        "tax_year": ytd.tax_year,
        "as_of": as_of.isoformat(),
        "annualization_factor": float(factor),
        "projected": projection["summary"],
        "projected_total_tax": f(projected_total_tax),
        "projected_withholding": f(projected_withholding),
        "required_annual_payment": f(required_annual),
        "safe_harbor_basis": safe_harbor_basis,
        "required_from_estimates": f(required_from_estimates),
        "installment_amount": f(installment),
        "total_estimated_paid": f(total_paid),
        "projected_balance_at_filing": f(full_year_safe),
        "quarters": [
            {k: (f(v) if isinstance(v, Decimal) else v) for k, v in q.items()} for q in quarters
        ],
        "next_payment": (
            {"quarter": next_q["quarter"], "due_date": next_q["due_date"], "amount": f(next_q["amount_due"])}
            if next_q
            else None
        ),
        "notes": [
            "Projection annualizes your year-to-date income and expenses; seasonal "
            "businesses should review installments as the year progresses.",
            "Pay via IRS Direct Pay or EFTPS — this app never transmits payments or returns.",
        ],
    }
