"""Audit-risk heuristics.

These are transparent, explainable red flags drawn from publicly discussed IRS
examination patterns (information-return mismatches, Schedule C losses, high
expense ratios, vehicle/meals claims, cash businesses, round numbers...).
They are NOT the IRS's (secret) DIF score — they're a checklist to help users
fix errors and keep documentation before filing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from app.tax.context import AnalysisContext

D = Decimal


@dataclass
class RiskFactor:
    id: str
    title: str
    severity: str  # low | medium | high
    points: int
    detail: str
    recommendation: str


def assess_audit_risk(ctx: AnalysisContext) -> dict[str, Any]:
    res = ctx.result
    sc = res["schedule_c"]
    gross = D(str(sc["line7_gross_income"]))
    receipts = D(str(sc["line1_gross_receipts"]))
    net = D(str(sc["line31_net_profit"]))
    total_exp = D(str(sc["line28_total_expenses"])) + D(str(sc["line4_cogs"]))
    agi = D(str(res["form_1040"]["line11_agi"]))
    factors: list[RiskFactor] = []

    # 1. Information-return mismatch (the #1 automated trigger: IRS CP2000 matching)
    if ctx.recorded_receipts is not None:
        receipts = ctx.recorded_receipts
    if ctx.reported_1099_income > 0 and receipts + D(1) < ctx.reported_1099_income:
        gap = ctx.reported_1099_income - receipts
        factors.append(RiskFactor(
            "1099-mismatch", "Income lower than your 1099s", "high", 35,
            f"Your 1099 forms total ${ctx.reported_1099_income:,.0f} but the income recorded from "
            f"your transactions is ${receipts:,.0f} (gap ${gap:,.0f}). The IRS matches every 1099 "
            "automatically.",
            "Make sure all 1099 income is recorded as business income. If a 1099 is wrong, "
            "ask the payer for a corrected form.",
        ))

    # 2. Schedule C loss
    if net < 0:
        big = gross > 0 and -net > gross * D("0.5")
        factors.append(RiskFactor(
            "schedule-c-loss", "Business shows a loss", "high" if big else "medium", 20 if big else 12,
            f"Net loss of ${-net:,.0f}. Losses that offset other income draw scrutiny, "
            "especially if repeated (hobby-loss rules: profit in 3 of 5 years).",
            "Keep a business plan, separate bank account and records showing profit motive.",
        ))

    # 3. High expense ratio
    net_sales = D(str(sc["line3"])) + D(str(sc["line6_other_income"]))
    if net_sales > 0 and net >= 0:
        # Compare expenses + COGS with sales (line 7 already has COGS subtracted).
        ratio = total_exp / net_sales
        if ratio > D("0.85"):
            factors.append(RiskFactor(
                "expense-ratio", "Very high expenses vs income", "medium", 12,
                f"Expenses (incl. cost of goods sold) are {ratio:.0%} of sales.",
                "Double-check that personal spending isn't categorized as business.",
            ))

    # 4. Meals & travel
    meals_travel = ctx.cat("meals") + ctx.cat("travel")
    if gross > 0 and meals_travel > gross * D("0.10"):
        factors.append(RiskFactor(
            "meals-travel", "Large meals & travel claims", "medium", 10,
            f"Meals and travel are ${meals_travel:,.0f} ({meals_travel / gross:.0%} of gross income).",
            "Keep receipts with attendee names and the business purpose of each trip/meal.",
        ))

    # 5. Vehicle at 100% business use
    if ctx.car_expense_full_business_use or ctx.inp.business_miles > 25000:
        factors.append(RiskFactor(
            "vehicle-100", "Vehicle claimed at 100% business use", "medium", 8,
            "100% business use of a vehicle (or very high mileage) is rarely accepted without a log.",
            "Keep a contemporaneous mileage log (date, destination, purpose, miles).",
        ))

    # 6. Round numbers
    if ctx.round_number_expense_ratio > 0.4 and ctx.total_transactions >= 10:
        factors.append(RiskFactor(
            "round-numbers", "Many round-number expenses", "low", 6,
            f"{ctx.round_number_expense_ratio:.0%} of expenses are exact multiples of $100 — "
            "this can look estimated rather than documented.",
            "Use the exact amounts from receipts or bank statements.",
        ))

    # 7. Cash-intensive business
    if ctx.is_cash_intensive:
        factors.append(RiskFactor(
            "cash-business", "Cash-intensive business", "medium", 10,
            "Retail shops, restaurants and salons that take cash are a known IRS focus "
            "(unreported cash receipts).",
            "Record every day's cash sales (Z-tape / POS report) and deposit them consistently.",
        ))

    # 8. Home office
    if ctx.inp.home_office_sqft > 0:
        factors.append(RiskFactor(
            "home-office", "Home office deduction", "low", 4,
            "Legitimate, but must be regular and exclusive business use.",
            "Keep a floor plan and photos of the dedicated space.",
        ))

    # 9. High income
    if agi > D(1_000_000):
        factors.append(RiskFactor("high-income", "Income above $1M", "medium", 12,
            "Examination rates rise sharply at high incomes.", "Keep thorough records."))
    elif agi > D(200_000):
        factors.append(RiskFactor("high-income", "Income above $200k", "low", 5,
            "Slightly higher examination rates.", "Keep thorough records."))

    # 10. Uncategorized / unreviewed items
    if ctx.needs_review_count > 0:
        factors.append(RiskFactor(
            "unreviewed", "Unreviewed transactions", "low", min(10, 2 + ctx.needs_review_count // 10),
            f"{ctx.needs_review_count} transactions haven't been confirmed.",
            "Review them so personal and business items are separated.",
        ))

    # 11. No source documents at all
    if not ctx.has_documents and gross > 0:
        factors.append(RiskFactor(
            "no-documents", "No supporting documents uploaded", "low", 5,
            "Figures without source documents are harder to defend.",
            "Upload 1099s, bank statements and key receipts (keep them for 3+ years).",
        ))

    score = min(100, sum(f.points for f in factors))
    level = "high" if score >= 45 else "medium" if score >= 20 else "low"
    sev_order = {"high": 0, "medium": 1, "low": 2}
    factors.sort(key=lambda f: (sev_order[f.severity], -f.points))
    return {
        "score": score,
        "level": level,
        "factors": [asdict(f) for f in factors],
        "disclaimer": (
            "Heuristic indicators only — not a prediction of whether you will be audited. "
            "Accurate, documented returns are the best protection."
        ),
    }
