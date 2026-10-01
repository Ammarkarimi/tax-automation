"""Rule-based deduction detection.

Produces concrete, explainable suggestions with an estimated tax saving.
The AI layer (app.ai.deductions) can add personalized suggestions on top,
but these rules are deterministic and always available offline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from app.tax import tables as T
from app.tax.context import AnalysisContext
from app.tax.engine import money

D = Decimal


@dataclass
class Suggestion:
    id: str
    title: str
    description: str
    estimated_deduction: float
    estimated_savings: float
    confidence: str  # high | medium | low
    action: str
    status: str = "opportunity"  # opportunity | applied | warning | info

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _combined_rate(ctx: AnalysisContext, schedule_c: bool = True) -> D:
    """Tax saved per $1 deducted: income-tax marginal rate (+ SE tax if on Schedule C)."""
    rate = D(str(ctx.summary["marginal_income_rate"]))
    if schedule_c:
        rate += D(str(ctx.summary["marginal_se_rate"]))
    return rate


def _s(ctx: AnalysisContext, deduction: D, schedule_c: bool = True) -> tuple[float, float]:
    return float(money(deduction)), float(money(deduction * _combined_rate(ctx, schedule_c)))


def find_deductions(ctx: AnalysisContext) -> list[dict[str, Any]]:
    inp, res = ctx.inp, ctx.result
    p = T.get_year_params(inp.tax_year)
    sc = res["schedule_c"]
    net_profit = D(str(sc["line31_net_profit"]))
    gross = D(str(sc["line7_gross_income"]))
    has_business = gross > 0
    out: list[Suggestion] = []

    if not has_business:
        return [
            Suggestion(
                id="no-business-income",
                title="Add your business income",
                description="No business income recorded yet. Upload 1099s, invoices or a bank CSV so we can find deductions.",
                estimated_deduction=0, estimated_savings=0, confidence="high",
                action="Upload documents", status="info",
            ).to_dict()
        ]

    # --- Home office (simplified method) ---
    if inp.home_office_sqft <= 0:
        ded, sav = _s(ctx, min(D(T.HOME_OFFICE_MAX_SQFT * 5), net_profit if net_profit > 0 else D(0)) * D("0.5"))
        out.append(Suggestion(
            id="home-office",
            title="Home office deduction",
            description=(
                "If you regularly and exclusively use part of your home for the business "
                "(e.g. bookkeeping area, storage of stock), you can deduct $5 per sq ft up "
                "to 300 sq ft with the simplified method. Estimate shown for 150 sq ft."
            ),
            estimated_deduction=ded, estimated_savings=sav, confidence="medium",
            action="Enter your office square footage in Tax Profile",
        ))
    else:
        ded, sav = _s(ctx, D(str(sc["line30_home_office"])))
        out.append(Suggestion(
            id="home-office", title="Home office deduction applied",
            description=f"{inp.home_office_sqft} sq ft using the simplified method.",
            estimated_deduction=ded, estimated_savings=sav, confidence="high",
            action="Keep a floor plan/photo as support", status="applied",
        ))

    # --- Vehicle ---
    car_actual = ctx.cat("car_truck")
    if inp.business_miles <= 0 and car_actual <= 0:
        ded, sav = _s(ctx, D(2000) * p.mileage_rate)
        out.append(Suggestion(
            id="mileage",
            title="Track business mileage",
            description=(
                f"Driving for supplies, deliveries, bank runs or client visits is deductible at "
                f"{p.mileage_rate * 100:.1f}¢/mile for {inp.tax_year}. Estimate shown for 2,000 miles. "
                "Commuting from home to a regular workplace doesn't count."
            ),
            estimated_deduction=ded, estimated_savings=sav, confidence="medium",
            action="Log trips (date, purpose, miles) and enter total miles in Tax Profile",
        ))
    elif inp.business_miles > 0:
        mileage_ded = D(inp.business_miles) * p.mileage_rate
        if car_actual > mileage_ded:
            ded, sav = _s(ctx, car_actual - mileage_ded)
            out.append(Suggestion(
                id="vehicle-method",
                title="Actual car expenses may beat the mileage rate",
                description=(
                    f"Your actual car costs (${car_actual:,.0f}) exceed the standard mileage "
                    f"deduction (${mileage_ded:,.0f}). Compare both methods — but note you "
                    "generally must use the standard rate in the first year to switch later."
                ),
                estimated_deduction=ded, estimated_savings=sav, confidence="low",
                action="Review vehicle method with your records", status="warning",
            ))

    # --- Self-employed retirement (SEP-IRA) ---
    half_se = D(str(res["schedule_se"]["line13_deductible_half"]))
    sep_room = min((net_profit - half_se) * D("0.20"), p.sep_max_contribution) - inp.retirement_contributions
    if net_profit > 5000 and sep_room > 500:
        ded, sav = _s(ctx, sep_room, schedule_c=False)
        out.append(Suggestion(
            id="sep-ira",
            title="SEP-IRA contribution",
            description=(
                f"You could contribute up to about ${sep_room:,.0f} more to a SEP-IRA for "
                f"{inp.tax_year} (deadline: your filing due date incl. extensions). It's deducted "
                "from income tax (not SE tax) and grows tax-deferred."
            ),
            estimated_deduction=ded, estimated_savings=sav, confidence="high",
            action="Open/fund a SEP-IRA and record it as a retirement contribution",
        ))

    # --- Self-employed health insurance ---
    if inp.se_health_insurance <= 0 and net_profit > 0:
        out.append(Suggestion(
            id="se-health",
            title="Self-employed health insurance",
            description=(
                "Premiums you pay for medical, dental or qualifying long-term-care insurance "
                "for yourself, spouse and dependents are deductible if you weren't eligible "
                "for an employer-subsidized plan."
            ),
            estimated_deduction=0, estimated_savings=0, confidence="medium",
            action="Categorize premium payments as 'health_insurance'", status="info",
        ))

    # --- Phone/internet ---
    if ctx.cat("utilities") <= 0:
        ded, sav = _s(ctx, D(600))
        out.append(Suggestion(
            id="phone-internet",
            title="Business share of phone & internet",
            description="The business-use percentage of your cell phone and internet bills is deductible. Estimate: $50/month.",
            estimated_deduction=ded, estimated_savings=sav, confidence="medium",
            action="Categorize phone/internet bills as 'utilities' with a business-use %",
        ))

    # --- Payment processing fees vs 1099-K ---
    if ctx.form_1099k_gross > 0 and ctx.cat("commissions_fees") <= 0:
        est = ctx.form_1099k_gross * D("0.03")
        ded, sav = _s(ctx, est)
        out.append(Suggestion(
            id="processing-fees",
            title="Card/platform processing fees",
            description=(
                "Your 1099-K reports GROSS payments before fees. Card processors and "
                "marketplaces typically keep ~3%; those fees are deductible (Sch. C line 10)."
            ),
            estimated_deduction=ded, estimated_savings=sav, confidence="high",
            action="Download your processor's annual fee summary and add it",
        ))

    # --- Inventory / COGS for shops ---
    if inp.inventory_purchases <= 0 and (ctx.is_cash_intensive or inp.beginning_inventory or inp.ending_inventory):
        out.append(Suggestion(
            id="cogs",
            title="Cost of goods sold (inventory)",
            description=(
                "If you sell products, the cost of stock you sold is subtracted from sales "
                "(Schedule C Part III). Record supplier purchases as 'inventory_purchases' and "
                "enter beginning/ending inventory counts."
            ),
            estimated_deduction=0, estimated_savings=0, confidence="high",
            action="Categorize supplier invoices as inventory purchases", status="info",
        ))

    # --- Meals are 50% ---
    meals = ctx.cat("meals")
    if meals > 0:
        out.append(Suggestion(
            id="meals-50",
            title="Business meals are 50% deductible",
            description=f"${meals:,.0f} of meals recorded; ${meals / 2:,.0f} is deductible. Keep receipts noting who you met and the business purpose.",
            estimated_deduction=float(money(meals / 2)), estimated_savings=_s(ctx, meals / 2)[1],
            confidence="high", action="Document attendees & purpose", status="applied",
        ))

    # --- QBI ---
    qbi_ded = D(str(res["qbi"]["deduction"]))
    if qbi_ded > 0:
        ded, sav = _s(ctx, qbi_ded, schedule_c=False)
        out.append(Suggestion(
            id="qbi", title="Qualified Business Income deduction applied",
            description="Up to 20% of your business profit is deducted automatically (Section 199A).",
            estimated_deduction=ded, estimated_savings=sav, confidence="high",
            action="Nothing to do", status="applied",
        ))

    # --- OBBBA tips deduction ---
    if p.tips_deduction_cap and inp.qualified_tips <= 0:
        out.append(Suggestion(
            id="tips",
            title="No tax on tips (2025–2028)",
            description=(
                "If customers tip you in an occupation that customarily receives tips (e.g. "
                "delivery, rideshare, hospitality), up to $25,000 of qualified tips may be "
                "deductible. Not available for specified service businesses."
            ),
            estimated_deduction=0, estimated_savings=0, confidence="low",
            action="Enter qualified tips in Tax Profile if applicable", status="info",
        ))

    # --- Review queue ---
    if ctx.needs_review_count:
        out.append(Suggestion(
            id="review-queue",
            title=f"{ctx.needs_review_count} transactions need review",
            description="Uncategorized or low-confidence transactions may hide deductible expenses.",
            estimated_deduction=0, estimated_savings=0, confidence="high",
            action="Open Transactions → filter 'Needs review'", status="warning",
        ))

    order = {"warning": 0, "opportunity": 1, "info": 2, "applied": 3}
    out.sort(key=lambda s: (order.get(s.status, 9), -s.estimated_savings))
    return [s.to_dict() for s in out]
