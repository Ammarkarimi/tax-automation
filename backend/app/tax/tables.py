"""Year-specific federal tax parameters.

Sources: IRS Rev. Proc. 2023-34 (TY2024), Rev. Proc. 2024-40 as amended by the
One Big Beautiful Bill Act (P.L. 119-21) (TY2025), Rev. Proc. 2025-32 (TY2026),
SSA wage-base announcements, and IRS standard-mileage notices.

!!! Verify these numbers against the current IRS publications each season.
Every value lives here (and nowhere else) so an annual update is one diff.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal as D

from app.models.enums import FilingStatus as FS

INF = D("Infinity")

# (upper bound of bracket, marginal rate)
Brackets = list[tuple[D, D]]


def _brackets(*uppers: int) -> Brackets:
    rates = [D("0.10"), D("0.12"), D("0.22"), D("0.24"), D("0.32"), D("0.35"), D("0.37")]
    bounds = [D(u) for u in uppers] + [INF]
    return list(zip(bounds, rates, strict=True))


@dataclass(frozen=True)
class YearParams:
    year: int
    brackets: dict[FS, Brackets]
    standard_deduction: dict[FS, D]
    additional_std_65_single: D  # single / head of household, per person 65+
    additional_std_65_married: D  # married (joint or separate), per person 65+
    ss_wage_base: D
    mileage_rate: D  # business standard mileage rate per mile
    qbi_threshold: dict[FS, D]
    qbi_phase_in_range: dict[FS, D]
    qbi_minimum_deduction: D  # OBBBA: $400 minimum from 2026 if QBI >= $1,000
    ctc_per_child: D
    actc_refundable_cap: D
    odc_per_dependent: D = D("500")
    sep_max_contribution: D = D("0")
    # OBBBA Schedule 1-A deductions (TY2025-2028)
    senior_deduction: D = D("0")
    tips_deduction_cap: D = D("0")
    notes: list[str] = field(default_factory=list)


def _married_split(single: D, mfj: D) -> dict[FS, D]:
    return {
        FS.SINGLE: single,
        FS.HEAD_OF_HOUSEHOLD: single,
        FS.MARRIED_JOINT: mfj,
        FS.MARRIED_SEPARATE: single,
    }


YEARS: dict[int, YearParams] = {
    2024: YearParams(
        year=2024,
        brackets={
            FS.SINGLE: _brackets(11600, 47150, 100525, 191950, 243725, 609350),
            FS.MARRIED_JOINT: _brackets(23200, 94300, 201050, 383900, 487450, 731200),
            FS.MARRIED_SEPARATE: _brackets(11600, 47150, 100525, 191950, 243725, 365600),
            FS.HEAD_OF_HOUSEHOLD: _brackets(16550, 63100, 100500, 191950, 243700, 609350),
        },
        standard_deduction={
            FS.SINGLE: D("14600"),
            FS.MARRIED_JOINT: D("29200"),
            FS.MARRIED_SEPARATE: D("14600"),
            FS.HEAD_OF_HOUSEHOLD: D("21900"),
        },
        additional_std_65_single=D("1950"),
        additional_std_65_married=D("1550"),
        ss_wage_base=D("168600"),
        mileage_rate=D("0.67"),
        qbi_threshold=_married_split(D("191950"), D("383900")),
        qbi_phase_in_range=_married_split(D("50000"), D("100000")),
        qbi_minimum_deduction=D("0"),
        ctc_per_child=D("2000"),
        actc_refundable_cap=D("1700"),
        sep_max_contribution=D("69000"),
    ),
    2025: YearParams(
        year=2025,
        brackets={
            FS.SINGLE: _brackets(11925, 48475, 103350, 197300, 250525, 626350),
            FS.MARRIED_JOINT: _brackets(23850, 96950, 206700, 394600, 501050, 751600),
            FS.MARRIED_SEPARATE: _brackets(11925, 48475, 103350, 197300, 250525, 375800),
            FS.HEAD_OF_HOUSEHOLD: _brackets(17000, 64850, 103350, 197300, 250500, 626350),
        },
        # OBBBA raised the 2025 standard deduction.
        standard_deduction={
            FS.SINGLE: D("15750"),
            FS.MARRIED_JOINT: D("31500"),
            FS.MARRIED_SEPARATE: D("15750"),
            FS.HEAD_OF_HOUSEHOLD: D("23625"),
        },
        additional_std_65_single=D("2000"),
        additional_std_65_married=D("1600"),
        ss_wage_base=D("176100"),
        mileage_rate=D("0.70"),
        qbi_threshold=_married_split(D("197300"), D("394600")),
        qbi_phase_in_range=_married_split(D("50000"), D("100000")),
        qbi_minimum_deduction=D("0"),
        ctc_per_child=D("2200"),
        actc_refundable_cap=D("1700"),
        sep_max_contribution=D("70000"),
        senior_deduction=D("6000"),
        tips_deduction_cap=D("25000"),
    ),
    2026: YearParams(
        year=2026,
        brackets={
            FS.SINGLE: _brackets(12400, 50400, 105700, 201775, 256225, 640600),
            FS.MARRIED_JOINT: _brackets(24800, 100800, 211400, 403550, 512450, 768700),
            FS.MARRIED_SEPARATE: _brackets(12400, 50400, 105700, 201775, 256225, 384350),
            FS.HEAD_OF_HOUSEHOLD: _brackets(17700, 67450, 105700, 201750, 256200, 640600),
        },
        standard_deduction={
            FS.SINGLE: D("16100"),
            FS.MARRIED_JOINT: D("32200"),
            FS.MARRIED_SEPARATE: D("16100"),
            FS.HEAD_OF_HOUSEHOLD: D("24150"),
        },
        additional_std_65_single=D("2050"),
        additional_std_65_married=D("1650"),
        ss_wage_base=D("184500"),
        mileage_rate=D("0.725"),
        qbi_threshold=_married_split(D("201750"), D("403500")),
        # OBBBA widened the phase-in range starting in 2026.
        qbi_phase_in_range=_married_split(D("75000"), D("150000")),
        qbi_minimum_deduction=D("400"),
        ctc_per_child=D("2200"),
        actc_refundable_cap=D("1700"),
        sep_max_contribution=D("72000"),
        senior_deduction=D("6000"),
        tips_deduction_cap=D("25000"),
    ),
}

SUPPORTED_YEARS = sorted(YEARS)

# --- Constants that don't change year to year ---
SE_EARNINGS_FACTOR = D("0.9235")  # Schedule SE line 4a
SE_SS_RATE = D("0.124")
SE_MEDICARE_RATE = D("0.029")
SE_MIN_EARNINGS = D("400")
ADDITIONAL_MEDICARE_RATE = D("0.009")
ADDITIONAL_MEDICARE_THRESHOLD = {
    FS.SINGLE: D("200000"),
    FS.HEAD_OF_HOUSEHOLD: D("200000"),
    FS.MARRIED_JOINT: D("250000"),
    FS.MARRIED_SEPARATE: D("125000"),
}
QBI_RATE = D("0.20")
MEALS_DEDUCTIBLE_PCT = D("0.50")
HOME_OFFICE_RATE_PER_SQFT = D("5")
HOME_OFFICE_MAX_SQFT = 300
CTC_PHASEOUT_THRESHOLD = _married_split(D("200000"), D("400000"))
ACTC_EARNED_INCOME_FLOOR = D("2500")
ACTC_RATE = D("0.15")
SENIOR_PHASEOUT_THRESHOLD = _married_split(D("75000"), D("150000"))
SENIOR_PHASEOUT_RATE = D("0.06")
TIPS_PHASEOUT_THRESHOLD = _married_split(D("150000"), D("300000"))
# Safe harbor: prior-year AGI above this requires 110% of prior-year tax.
SAFE_HARBOR_HIGH_AGI = {
    FS.SINGLE: D("150000"),
    FS.HEAD_OF_HOUSEHOLD: D("150000"),
    FS.MARRIED_JOINT: D("150000"),
    FS.MARRIED_SEPARATE: D("75000"),
}


def get_year_params(year: int) -> YearParams:
    try:
        return YEARS[year]
    except KeyError as exc:
        raise ValueError(
            f"tax year {year} is not supported (supported: {', '.join(map(str, SUPPORTED_YEARS))})"
        ) from exc
