"""Hand-verified tax engine scenarios. Expected values are worked out in comments."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.models.enums import FilingStatus
from app.tax.audit_risk import assess_audit_risk
from app.tax.context import AnalysisContext
from app.tax.deductions import find_deductions
from app.tax.engine import TaxInput, bracket_tax, compute_tax
from app.tax.quarterly import compute_quarterly, due_dates
from app.tax.tables import get_year_params


def test_bracket_tax_single_2025():
    brackets = get_year_params(2025).brackets[FilingStatus.SINGLE]
    # 11,925 * 10% + (50,000 - 11,925) * 12%... capped at 48,475 then 22%
    expected = D("1192.50") + (D("48475") - D("11925")) * D("0.12") + (D("50000") - D("48475")) * D("0.22")
    assert bracket_tax(D("50000"), brackets) == expected.quantize(D("0.01"))
    assert bracket_tax(D("0"), brackets) == D("0.00")


def test_simple_freelancer_2025():
    inp = TaxInput(tax_year=2025, gross_receipts=D("80000"), expenses={"22": D("20000")})
    r = compute_tax(inp)
    # Net profit 60,000 -> SE earnings 55,410 -> SE tax 8,477.73
    assert r["schedule_c"]["line31_net_profit"] == 60000.00
    assert r["schedule_se"]["line4a_net_earnings"] == 55410.00
    assert r["schedule_se"]["line12_se_tax"] == 8477.73
    assert r["schedule_se"]["line13_deductible_half"] == 4238.87
    # AGI = 60,000 - 4,238.87
    assert r["form_1040"]["line11_agi"] == 55761.13
    # Taxable before QBI = 55,761.13 - 15,750 = 40,011.13; QBI limited to 20% of that
    assert r["form_1040"]["line13a_qbi_deduction"] == 8002.23
    assert r["form_1040"]["line15_taxable_income"] == 32008.90
    # 1,192.50 + (32,008.90 - 11,925) * 12% = 3,602.57
    assert r["form_1040"]["line16_tax"] == 3602.57
    assert r["form_1040"]["line24_total_tax"] == pytest.approx(3602.57 + 8477.73)
    assert r["form_1040"]["line37_amount_owed"] == pytest.approx(12080.30)


def test_meals_limited_to_50_percent_and_mileage():
    inp = TaxInput(
        tax_year=2025,
        gross_receipts=D("30000"),
        expenses={"24b": D("1000"), "9": D("999")},
        business_miles=1000,
    )
    r = compute_tax(inp)
    lines = r["schedule_c"]["expenses_by_line"]
    assert lines["24b"] == 500.00
    assert lines["9"] == 700.00  # 1,000 miles x $0.70; actual car costs dropped
    assert any("mileage" in w for w in r["warnings"])


def test_cogs_for_shopkeeper():
    inp = TaxInput(
        tax_year=2025,
        gross_receipts=D("120000"),
        beginning_inventory=D("10000"),
        inventory_purchases=D("60000"),
        ending_inventory=D("15000"),
    )
    r = compute_tax(inp)
    assert r["schedule_c"]["line4_cogs"] == 55000.00
    assert r["schedule_c"]["line5_gross_profit"] == 65000.00


def test_home_office_cannot_create_loss():
    inp = TaxInput(tax_year=2025, gross_receipts=D("1000"), expenses={"22": D("800")}, home_office_sqft=300)
    r = compute_tax(inp)
    assert r["schedule_c"]["line30_home_office"] == 200.00
    assert r["schedule_c"]["line31_net_profit"] == 0.00


def test_no_se_tax_under_400():
    r = compute_tax(TaxInput(tax_year=2025, gross_receipts=D("400")))
    assert r["schedule_se"]["line12_se_tax"] == 0.0


def test_ss_wage_base_reduced_by_w2_wages():
    # W-2 social security wages already at the wage base -> only Medicare on SE income
    inp = TaxInput(
        tax_year=2025,
        gross_receipts=D("50000"),
        w2_wages=D("180000"),
        w2_ss_wages=D("176100"),
        w2_medicare_wages=D("180000"),
    )
    r = compute_tax(inp)
    assert r["schedule_se"]["social_security_portion"] == 0.0
    assert r["schedule_se"]["medicare_portion"] == round(50000 * 0.9235 * 0.029, 2)
    # Additional Medicare: wages 180k under 200k; SE 46,175 over remaining 20k threshold
    assert r["schedule_2"]["line11_additional_medicare"] == 235.58  # 26,175 x 0.9% = 235.575, rounded half-up


def test_child_tax_credit_and_actc():
    inp = TaxInput(
        tax_year=2025,
        filing_status=FilingStatus.HEAD_OF_HOUSEHOLD,
        gross_receipts=D("30000"),
        qualifying_children=2,
    )
    r = compute_tax(inp)
    c = r["credits"]
    assert c["child_tax_credit_tentative"] == 4400.0
    # Income tax is small, so most of the credit is unused -> ACTC applies
    assert c["nonrefundable_used"] == r["form_1040"]["line16_tax"]
    assert 0 < c["additional_child_tax_credit"] <= 3400.0


def test_senior_deduction_2025():
    base = TaxInput(tax_year=2025, gross_receipts=D("50000"))
    senior = TaxInput(tax_year=2025, gross_receipts=D("50000"), age_65_or_older=True)
    r0, r1 = compute_tax(base), compute_tax(senior)
    assert r1["schedule_1a"]["senior_deduction"] == 6000.0
    assert r1["form_1040"]["line12_standard_deduction"] == 15750 + 2000
    assert r1["form_1040"]["line15_taxable_income"] < r0["form_1040"]["line15_taxable_income"]
    # Not available before 2025
    r2024 = compute_tax(TaxInput(tax_year=2024, gross_receipts=D("50000"), age_65_or_older=True))
    assert r2024["schedule_1a"]["senior_deduction"] == 0.0


def test_qbi_phaseout_sstb_above_range():
    inp = TaxInput(tax_year=2025, gross_receipts=D("400000"), is_sstb=True)
    r = compute_tax(inp)
    assert r["form_1040"]["line13a_qbi_deduction"] == 0.0


def test_refund_when_overwithheld():
    inp = TaxInput(tax_year=2025, w2_wages=D("40000"), w2_ss_wages=D("40000"),
                   w2_medicare_wages=D("40000"), federal_withholding=D("6000"))
    r = compute_tax(inp)
    assert r["summary"]["refund"] > 0
    assert r["summary"]["balance_due"] == 0


def test_unsupported_year():
    with pytest.raises(ValueError):
        compute_tax(TaxInput(tax_year=2019))


def test_due_dates_roll_weekends():
    # 2026-01-15 is a Thursday; 2025-06-15 is a Sunday -> Monday 16th
    d = due_dates(2025)
    assert d[1] == date(2025, 6, 16)
    assert d[3] == date(2026, 1, 15)


def test_quarterly_safe_harbor_uses_prior_year():
    ytd = TaxInput(tax_year=2026, gross_receipts=D("50000"), expenses={"22": D("5000")})
    q = compute_quarterly(ytd, date(2026, 6, 30), payments=[], prior_year_tax=D("8000"),
                          prior_year_agi=D("90000"))
    assert q["safe_harbor_basis"].startswith("100%")
    assert q["required_annual_payment"] == 8000.0
    assert q["installment_amount"] == 2000.0
    assert q["quarters"][0]["status"] == "underpaid"  # Q1 already past, nothing paid
    assert q["next_payment"]["quarter"] == 3


def test_quarterly_marks_paid():
    ytd = TaxInput(tax_year=2026, gross_receipts=D("20000"))
    q = compute_quarterly(ytd, date(2026, 5, 1), payments=[(1, D("100000"), date(2026, 4, 1))])
    assert q["quarters"][0]["status"] == "paid"
    assert q["quarters"][3]["status"] == "covered"


def _ctx(**kw):
    inp = kw.pop("inp")
    return AnalysisContext(inp=inp, result=compute_tax(inp), **kw)


def test_audit_risk_flags_1099_mismatch_and_cash():
    ctx = _ctx(inp=TaxInput(tax_year=2025, gross_receipts=D("20000")),
               reported_1099_income=D("35000"), is_cash_intensive=True, has_documents=True)
    risk = assess_audit_risk(ctx)
    ids = [f["id"] for f in risk["factors"]]
    assert ids[0] == "1099-mismatch"
    assert "cash-business" in ids
    assert risk["level"] == "high"


def test_audit_risk_low_for_clean_return():
    ctx = _ctx(inp=TaxInput(tax_year=2025, gross_receipts=D("60000"), expenses={"22": D("10000")}),
               has_documents=True)
    assert assess_audit_risk(ctx)["level"] == "low"


def test_deduction_suggestions():
    ctx = _ctx(inp=TaxInput(tax_year=2025, gross_receipts=D("90000")), form_1099k_gross=D("90000"))
    ids = {s["id"] for s in find_deductions(ctx)}
    assert {"home-office", "mileage", "sep-ira", "processing-fees", "qbi"} <= ids


def test_expense_ratio_uses_sales_not_gross_profit():
    # Shop: 100k sales, 60k COGS, 20k expenses -> 80% of sales (not 50% of 40k gross profit)
    inp = TaxInput(tax_year=2025, gross_receipts=D("100000"), inventory_purchases=D("60000"), expenses={"20b": D("20000")})
    ids = [f["id"] for f in assess_audit_risk(_ctx(inp=inp, has_documents=True))["factors"]]
    assert "expense-ratio" not in ids
    inp.expenses = {"20b": D("30000")}  # 90% of sales
    ids = [f["id"] for f in assess_audit_risk(_ctx(inp=inp, has_documents=True))["factors"]]
    assert "expense-ratio" in ids
