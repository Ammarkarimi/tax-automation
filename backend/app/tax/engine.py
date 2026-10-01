"""Deterministic federal tax engine for sole proprietors (Schedule C filers).

Design rules:
* Pure functions over `Decimal` — no I/O, no AI. The LLM never does tax math;
  it only explains numbers this module produced.
* Every intermediate value is returned (line-by-line) so results are auditable
  and can be rendered onto Form 1040 / Schedule C / Schedule SE worksheets.

Scope (v1): federal income tax, self-employment tax, Additional Medicare Tax,
QBI deduction (sole prop, no W-2 wages/UBIA), standard deduction, OBBBA senior
and tips deductions, Child Tax Credit / ODC / ACTC. Out of scope (flagged as
warnings): itemized deductions, capital gains rates, AMT, NIIT, EITC, state tax.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.models.enums import FilingStatus
from app.tax import tables as T

ENGINE_VERSION = "1.0.0"
ZERO = Decimal("0")
CENT = Decimal("0.01")


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def pos(value: Decimal) -> Decimal:
    return value if value > 0 else ZERO


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass
class TaxInput:
    tax_year: int
    filing_status: FilingStatus = FilingStatus.SINGLE

    # Schedule C income
    gross_receipts: Decimal = ZERO
    returns_allowances: Decimal = ZERO
    other_business_income: Decimal = ZERO

    # Schedule C Part III — cost of goods sold (shopkeepers / resellers)
    beginning_inventory: Decimal = ZERO
    inventory_purchases: Decimal = ZERO
    ending_inventory: Decimal = ZERO

    # Business expenses keyed by Schedule C line ("8", "9", ..., "27b").
    # Amounts are already multiplied by business-use %. Meals (24b) are entered
    # at 100%; the 50% limit is applied here.
    expenses: dict[str, Decimal] = field(default_factory=dict)
    business_miles: int = 0
    home_office_sqft: int = 0
    is_sstb: bool = False  # specified service trade or business (QBI rules)

    # Other income
    w2_wages: Decimal = ZERO  # W-2 box 1
    w2_ss_wages: Decimal = ZERO  # W-2 box 3 (reduces SE social-security base)
    w2_medicare_wages: Decimal = ZERO  # W-2 box 5
    interest_income: Decimal = ZERO
    dividend_income: Decimal = ZERO
    other_income: Decimal = ZERO

    # Adjustments
    se_health_insurance: Decimal = ZERO
    retirement_contributions: Decimal = ZERO

    # Household
    age_65_or_older: bool = False
    spouse_age_65_or_older: bool = False
    qualifying_children: int = 0
    other_dependents: int = 0
    qualified_tips: Decimal = ZERO

    # Payments
    federal_withholding: Decimal = ZERO
    estimated_payments: Decimal = ZERO


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def bracket_tax(taxable_income: Decimal, brackets: T.Brackets) -> Decimal:
    """Progressive tax using exact bracket math (not the IRS tax table)."""
    tax = ZERO
    lower = ZERO
    for upper, rate in brackets:
        if taxable_income <= lower:
            break
        span = min(taxable_income, upper) - lower
        tax += span * rate
        lower = upper
    return money(tax)


def marginal_rate(taxable_income: Decimal, brackets: T.Brackets) -> Decimal:
    for upper, rate in brackets:
        if taxable_income < upper:
            return rate
    return brackets[-1][1]


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------


def compute_tax(inp: TaxInput) -> dict[str, Any]:
    p = T.get_year_params(inp.tax_year)
    fs = FilingStatus(inp.filing_status)
    warnings: list[str] = []

    # ---------------- Schedule C ----------------
    line1 = money(inp.gross_receipts)
    line2 = money(inp.returns_allowances)
    line3 = line1 - line2
    cogs_raw = inp.beginning_inventory + inp.inventory_purchases - inp.ending_inventory
    if cogs_raw < 0:
        warnings.append("Ending inventory exceeds beginning inventory + purchases; COGS set to 0.")
    line4 = money(pos(cogs_raw))
    line5 = line3 - line4
    line6 = money(inp.other_business_income)
    line7 = line5 + line6

    exp: dict[str, Decimal] = {k: money(v) for k, v in inp.expenses.items() if v}
    meals_full = exp.pop("24b", ZERO)
    meals_deductible = money(meals_full * T.MEALS_DEDUCTIBLE_PCT)
    if meals_deductible:
        exp["24b"] = meals_deductible

    mileage_deduction = ZERO
    if inp.business_miles > 0:
        mileage_deduction = money(Decimal(inp.business_miles) * p.mileage_rate)
        if exp.get("9"):
            warnings.append(
                "Both business miles and actual car expenses were provided. The standard "
                "mileage rate was used and actual car expenses were excluded (you can't "
                "claim both for the same vehicle)."
            )
        exp["9"] = mileage_deduction

    line28 = money(sum(exp.values(), ZERO))
    line29 = line7 - line28

    # Simplified home-office method: $5/sqft up to 300 sqft; can't create a loss.
    sqft = min(max(inp.home_office_sqft, 0), T.HOME_OFFICE_MAX_SQFT)
    home_office_tentative = money(T.HOME_OFFICE_RATE_PER_SQFT * sqft)
    line30 = min(home_office_tentative, pos(line29))
    if home_office_tentative > line30:
        warnings.append(
            "Home-office deduction limited by business income (simplified method can't create a loss)."
        )
    line31 = line29 - line30  # net profit (loss)
    if line31 < 0:
        warnings.append(
            "Schedule C shows a net loss. Losses are allowed only if you're at risk and "
            "materially participate; repeated losses can trigger hobby-loss scrutiny."
        )

    schedule_c = {
        "line1_gross_receipts": line1,
        "line2_returns_allowances": line2,
        "line3": line3,
        "line4_cogs": line4,
        "line5_gross_profit": line5,
        "line6_other_income": line6,
        "line7_gross_income": line7,
        "expenses_by_line": dict(sorted(exp.items(), key=lambda kv: _line_sort_key(kv[0]))),
        "meals_before_50pct_limit": money(meals_full),
        "mileage_deduction": mileage_deduction,
        "line28_total_expenses": line28,
        "line29_tentative_profit": line29,
        "line30_home_office": line30,
        "line31_net_profit": line31,
        "cogs": {
            "line35_beginning_inventory": money(inp.beginning_inventory),
            "line36_purchases": money(inp.inventory_purchases),
            "line41_ending_inventory": money(inp.ending_inventory),
            "line42_cogs": line4,
        },
    }

    # ---------------- Schedule SE ----------------
    se_earnings = money(pos(line31) * T.SE_EARNINGS_FACTOR)
    if se_earnings < T.SE_MIN_EARNINGS:
        se_earnings_taxed = ZERO
    else:
        se_earnings_taxed = se_earnings
    ss_base_remaining = pos(p.ss_wage_base - inp.w2_ss_wages)
    se_ss_tax = money(min(se_earnings_taxed, ss_base_remaining) * T.SE_SS_RATE)
    se_medicare_tax = money(se_earnings_taxed * T.SE_MEDICARE_RATE)
    se_tax = se_ss_tax + se_medicare_tax
    half_se_tax = money(se_tax / 2)
    schedule_se = {
        "line4a_net_earnings": se_earnings,
        "social_security_wage_base": p.ss_wage_base,
        "w2_social_security_wages": money(inp.w2_ss_wages),
        "social_security_portion": se_ss_tax,
        "medicare_portion": se_medicare_tax,
        "line12_se_tax": se_tax,
        "line13_deductible_half": half_se_tax,
    }

    # ---------------- Form 8959: Additional Medicare Tax ----------------
    amt_threshold = T.ADDITIONAL_MEDICARE_THRESHOLD[fs]
    addl_on_wages = pos(inp.w2_medicare_wages - amt_threshold)
    addl_on_se = pos(se_earnings_taxed - pos(amt_threshold - inp.w2_medicare_wages))
    additional_medicare = money((addl_on_wages + addl_on_se) * T.ADDITIONAL_MEDICARE_RATE)

    # ---------------- Adjustments (Schedule 1 Part II) ----------------
    net_se_after_half = pos(line31 - half_se_tax)
    retirement = money(min(inp.retirement_contributions, net_se_after_half))
    if inp.retirement_contributions > retirement:
        warnings.append("Retirement contribution limited to net self-employment earnings.")
    sep_limit = min(money(net_se_after_half * Decimal("0.20")), p.sep_max_contribution)
    if retirement > sep_limit:
        warnings.append(
            f"Retirement contribution exceeds the SEP-IRA limit (~${sep_limit:,.0f}). That's "
            "only allowed with a Solo 401(k) employee deferral — verify your plan type."
        )
    se_health = money(min(inp.se_health_insurance, pos(line31 - half_se_tax - retirement)))
    if inp.se_health_insurance > se_health:
        warnings.append("Self-employed health insurance deduction limited to business net profit.")
    adjustments = half_se_tax + retirement + se_health

    # ---------------- Form 1040 income ----------------
    wages = money(inp.w2_wages)
    interest = money(inp.interest_income)
    dividends = money(inp.dividend_income)
    other_income = money(inp.other_income)
    if dividends:
        warnings.append(
            "Dividends are taxed at ordinary rates in this estimate; qualified dividends "
            "may be taxed lower on your actual return."
        )
    schedule1_additional_income = line31 + other_income
    total_income = wages + interest + dividends + schedule1_additional_income
    agi = total_income - adjustments
    magi = agi  # no foreign-income exclusions in scope

    # ---------------- Deductions ----------------
    std = p.standard_deduction[fs]
    married = fs in (FilingStatus.MARRIED_JOINT, FilingStatus.MARRIED_SEPARATE)
    add65 = p.additional_std_65_married if married else p.additional_std_65_single
    seniors = int(inp.age_65_or_older) + (
        int(inp.spouse_age_65_or_older) if fs == FilingStatus.MARRIED_JOINT else 0
    )
    standard_deduction = std + add65 * seniors

    # OBBBA Schedule 1-A (2025-2028). Not available to married-filing-separately.
    senior_deduction = ZERO
    tips_deduction = ZERO
    if fs != FilingStatus.MARRIED_SEPARATE:
        if p.senior_deduction and seniors:
            phaseout = pos(magi - T.SENIOR_PHASEOUT_THRESHOLD[fs]) * T.SENIOR_PHASEOUT_RATE
            senior_deduction = money(pos(p.senior_deduction * seniors - phaseout))
        if p.tips_deduction_cap and inp.qualified_tips > 0:
            # Self-employed tips are capped at the net income of the trade.
            tips = min(inp.qualified_tips, p.tips_deduction_cap, pos(line31) + wages)
            excess = pos(magi - T.TIPS_PHASEOUT_THRESHOLD[fs])
            reduction = Decimal(math.floor(excess / 1000)) * 100
            tips_deduction = money(pos(tips - reduction))
    elif inp.qualified_tips > 0 or seniors:
        warnings.append("Senior and tips deductions are not available when married filing separately.")
    schedule_1a = senior_deduction + tips_deduction

    # ---------------- QBI deduction (Form 8995 / 8995-A, no W-2 wages/UBIA) ------
    taxable_before_qbi = pos(agi - standard_deduction - schedule_1a)
    qbi = line31 - half_se_tax - se_health - retirement
    qbi_deduction = ZERO
    qbi_note = None
    if qbi > 0:
        tentative = qbi * T.QBI_RATE
        threshold = p.qbi_threshold[fs]
        if taxable_before_qbi > threshold:
            phase = min(Decimal(1), (taxable_before_qbi - threshold) / p.qbi_phase_in_range[fs])
            # With no W-2 wages/UBIA the wage limitation is zero, so the deduction
            # phases out linearly; an SSTB additionally shrinks QBI by the same factor.
            factor = (1 - phase) * (1 - phase) if inp.is_sstb else (1 - phase)
            tentative = tentative * factor
            qbi_note = f"Income above QBI threshold (${threshold:,.0f}); deduction phased by {phase:.0%}."
        if p.qbi_minimum_deduction and qbi >= 1000:
            tentative = max(tentative, p.qbi_minimum_deduction)
        qbi_deduction = money(min(tentative, taxable_before_qbi * T.QBI_RATE))
    elif qbi < 0:
        qbi_note = "Negative QBI carries forward to next year (track it)."
    if qbi_note:
        warnings.append(qbi_note)

    taxable_income = pos(taxable_before_qbi - qbi_deduction)

    # ---------------- Tax & credits ----------------
    brackets = p.brackets[fs]
    income_tax = bracket_tax(taxable_income, brackets)

    tentative_ctc = p.ctc_per_child * inp.qualifying_children
    tentative_odc = p.odc_per_dependent * inp.other_dependents
    excess = pos(magi - T.CTC_PHASEOUT_THRESHOLD[fs])
    ctc_reduction = Decimal(math.ceil(excess / 1000)) * 50 if excess > 0 else ZERO
    total_child_credit = pos(tentative_ctc + tentative_odc - ctc_reduction)
    nonrefundable_credit = money(min(total_child_credit, income_tax))
    # Refundable ACTC (Schedule 8812 lines 16a/16b/19): unused credit, capped per child
    # and at 15% of earned income above $2,500.
    unused_credit = total_child_credit - nonrefundable_credit
    earned_income = wages + pos(line31 - half_se_tax)
    actc = money(
        min(
            unused_credit,
            p.actc_refundable_cap * inp.qualifying_children,
            pos(earned_income - T.ACTC_EARNED_INCOME_FLOOR) * T.ACTC_RATE,
        )
    )

    tax_after_credits = income_tax - nonrefundable_credit
    other_taxes = se_tax + additional_medicare
    total_tax = tax_after_credits + other_taxes

    withholding = money(inp.federal_withholding)
    estimated = money(inp.estimated_payments)
    total_payments = withholding + estimated + actc
    balance = total_tax - total_payments

    marginal = marginal_rate(taxable_income, brackets)
    se_marginal = (
        T.SE_EARNINGS_FACTOR * (T.SE_SS_RATE + T.SE_MEDICARE_RATE)
        if se_earnings_taxed and se_earnings_taxed < ss_base_remaining
        else T.SE_EARNINGS_FACTOR * T.SE_MEDICARE_RATE if se_earnings_taxed else ZERO
    )

    warnings.append(
        "Itemized deductions, capital-gain rates, AMT, NIIT, EITC and state taxes are not "
        "included in this estimate."
    )

    form_1040 = {
        "line1z_wages": wages,
        "line2b_taxable_interest": interest,
        "line3b_ordinary_dividends": dividends,
        "line8_additional_income": schedule1_additional_income,
        "line9_total_income": total_income,
        "line10_adjustments": adjustments,
        "line11_agi": agi,
        "line12_standard_deduction": standard_deduction,
        "line13a_qbi_deduction": qbi_deduction,
        "line13b_schedule_1a_deductions": schedule_1a,
        "line14_total_deductions": standard_deduction + qbi_deduction + schedule_1a,
        "line15_taxable_income": taxable_income,
        "line16_tax": income_tax,
        "line19_child_tax_credit": nonrefundable_credit,
        "line22_tax_after_credits": tax_after_credits,
        "line23_other_taxes": other_taxes,
        "line24_total_tax": total_tax,
        "line25_withholding": withholding,
        "line26_estimated_payments": estimated,
        "line28_actc": actc,
        "line33_total_payments": total_payments,
        "line34_overpaid": pos(-balance),
        "line37_amount_owed": pos(balance),
    }
    schedule_1 = {
        "line3_business_income": line31,
        "line8z_other_income": other_income,
        "line10_total_additional_income": schedule1_additional_income,
        "line15_half_se_tax": half_se_tax,
        "line16_retirement": retirement,
        "line17_se_health_insurance": se_health,
        "line26_total_adjustments": adjustments,
    }
    schedule_2 = {
        "line4_se_tax": se_tax,
        "line11_additional_medicare": additional_medicare,
        "line21_total_other_taxes": other_taxes,
    }
    schedule_1a_detail = {
        "qualified_tips_deduction": tips_deduction,
        "senior_deduction": senior_deduction,
        "total": schedule_1a,
    }

    return _jsonable(
        {
            "engine_version": ENGINE_VERSION,
            "tax_year": inp.tax_year,
            "filing_status": fs.value,
            "schedule_c": schedule_c,
            "schedule_se": schedule_se,
            "schedule_1": schedule_1,
            "schedule_1a": schedule_1a_detail,
            "schedule_2": schedule_2,
            "form_1040": form_1040,
            "qbi": {"qualified_business_income": money(qbi), "deduction": qbi_deduction},
            "credits": {
                "child_tax_credit_tentative": tentative_ctc,
                "other_dependent_credit_tentative": tentative_odc,
                "phaseout_reduction": ctc_reduction,
                "nonrefundable_used": nonrefundable_credit,
                "additional_child_tax_credit": actc,
            },
            "summary": {
                "gross_income": line7 + wages + interest + dividends + other_income,
                "business_net_profit": line31,
                "agi": agi,
                "taxable_income": taxable_income,
                "income_tax": tax_after_credits,
                "self_employment_tax": se_tax,
                "additional_medicare_tax": additional_medicare,
                "total_tax": total_tax,
                "total_payments": total_payments,
                "balance_due": pos(balance),
                "refund": pos(-balance),
                "effective_rate": (
                    float((total_tax / total_income).quantize(Decimal("0.0001")))
                    if total_income > 0
                    else 0.0
                ),
                "marginal_income_rate": float(marginal),
                "marginal_se_rate": float(se_marginal.quantize(Decimal("0.0001"))),
            },
            "warnings": warnings,
            "inputs": asdict(inp),
        }
    )


def _line_sort_key(line: str) -> tuple[int, str]:
    digits = "".join(c for c in line if c.isdigit())
    return (int(digits or 0), line)


def _jsonable(value: Any) -> Any:
    """Convert Decimals to floats (2dp) and enums to strings for JSON output."""
    if isinstance(value, Decimal):
        return float(value.quantize(CENT)) if value.is_finite() else None
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if hasattr(value, "value") and isinstance(getattr(value, "value"), str):
        return value.value
    return value
