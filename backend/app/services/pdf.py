"""PDF generation (ReportLab): Form 1040 + Schedules 1, 2, C and SE worksheets.

The output mirrors the line numbers of the official IRS forms so it can be
transcribed into the official PDFs or any filing software. It is clearly marked
as a preparer worksheet: this product never e-files or transmits returns.
SSNs are masked to the last four digits by design.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.enums import FilingStatus

_styles = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=_styles["Heading1"], fontSize=16, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=_styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("body", parent=_styles["BodyText"], fontSize=9, leading=12)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=7.5, leading=9, textColor=colors.HexColor("#555555"))

FILING_STATUS_LABEL = {
    FilingStatus.SINGLE.value: "Single",
    FilingStatus.MARRIED_JOINT.value: "Married filing jointly",
    FilingStatus.MARRIED_SEPARATE.value: "Married filing separately",
    FilingStatus.HEAD_OF_HOUSEHOLD.value: "Head of household",
}

SCHEDULE_C_LABELS = {
    "8": "Advertising", "9": "Car and truck expenses", "10": "Commissions and fees",
    "11": "Contract labor", "13": "Depreciation and section 179", "14": "Employee benefit programs",
    "15": "Insurance (other than health)", "16a": "Interest: mortgage", "16b": "Interest: other",
    "17": "Legal and professional services", "18": "Office expense", "19": "Pension and profit-sharing plans",
    "20a": "Rent or lease: vehicles, machinery, equipment", "20b": "Rent or lease: other business property",
    "21": "Repairs and maintenance", "22": "Supplies", "23": "Taxes and licenses", "24a": "Travel",
    "24b": "Deductible meals", "25": "Utilities", "26": "Wages", "27b": "Other expenses",
}


def _usd(v: Any) -> str:
    if v is None:
        return ""
    v = float(v)
    return f"({abs(v):,.0f})" if v < 0 else f"{v:,.0f}"


def _mask_ssn(ssn: str | None) -> str:
    digits = "".join(c for c in (ssn or "") if c.isdigit())
    return f"XXX-XX-{digits[-4:]}" if len(digits) >= 4 else "(enter SSN)"


def _table(rows: list[tuple[str, str, Any]], col_widths=(0.6 * inch, 5.1 * inch, 1.3 * inch)) -> Table:
    data = [["Line", "Description", "Amount ($)"]] + [[a, Paragraph(b, BODY), _usd(c)] for a, b, c in rows]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c4d6")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")]),
        ("FONTNAME", (2, 1), (2, -1), "Courier"),
    ]))
    return t


def _header_block(profile: dict[str, Any], result: dict[str, Any]) -> Table:
    rows = [
        ["Taxpayer", profile.get("taxpayer_name") or "(enter name)", "SSN", _mask_ssn(profile.get("ssn"))],
        ["Filing status", FILING_STATUS_LABEL.get(result["filing_status"], result["filing_status"]),
         "Tax year", str(result["tax_year"])],
        ["Address", profile.get("address") or "(enter address)", "", ""],
    ]
    t = Table(rows, colWidths=(1.1 * inch, 3.4 * inch, 0.9 * inch, 1.6 * inch))
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#1f3a5f")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8c4d6")),
    ]))
    return t


def _on_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(
        0.6 * inch, 0.45 * inch,
        "PREPARER WORKSHEET — not an official IRS form. Transcribe onto official forms or filing "
        "software. Not transmitted to the IRS.",
    )
    canvas.drawRightString(LETTER[0] - 0.6 * inch, 0.45 * inch, f"Page {doc.page}")
    canvas.restoreState()


def render_return_pdf(result: dict[str, Any], profile: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.7 * inch,
        title=f"Form 1040 & Schedule C worksheet — {result['tax_year']}", author="TaxPilot",
    )
    f, s1, s2, sc, se = (result["form_1040"], result["schedule_1"], result["schedule_2"],
                         result["schedule_c"], result["schedule_se"])
    summ = result["summary"]
    story: list[Any] = []

    # ---------------- Summary ----------------
    story += [
        Paragraph(f"Tax Return Summary — {result['tax_year']}", H1),
        Paragraph(f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} · engine v{result['engine_version']}", SMALL),
        Spacer(1, 8), _header_block(profile, result), Spacer(1, 10),
        _table([
            ("", "Business net profit (Schedule C line 31)", summ["business_net_profit"]),
            ("", "Adjusted gross income", summ["agi"]),
            ("", "Taxable income", summ["taxable_income"]),
            ("", "Income tax after credits", summ["income_tax"]),
            ("", "Self-employment tax", summ["self_employment_tax"]),
            ("", "Total tax", summ["total_tax"]),
            ("", "Total payments & refundable credits", summ["total_payments"]),
            ("", "<b>Amount you owe</b>" if summ["balance_due"] else "<b>Refund</b>",
             summ["balance_due"] or summ["refund"]),
        ]),
        Spacer(1, 10),
        Paragraph("Notes &amp; warnings", H2),
    ]
    for w in result.get("warnings", []):
        story.append(Paragraph(f"• {w}", BODY))
    story.append(PageBreak())

    # ---------------- Form 1040 ----------------
    story += [
        Paragraph(f"Form 1040 — U.S. Individual Income Tax Return ({result['tax_year']})", H1),
        _header_block(profile, result), Spacer(1, 8),
        _table([
            ("1z", "Wages, salaries, tips (W-2)", f["line1z_wages"]),
            ("2b", "Taxable interest", f["line2b_taxable_interest"]),
            ("3b", "Ordinary dividends", f["line3b_ordinary_dividends"]),
            ("8", "Additional income from Schedule 1, line 10", f["line8_additional_income"]),
            ("9", "Total income", f["line9_total_income"]),
            ("10", "Adjustments to income from Schedule 1, line 26", f["line10_adjustments"]),
            ("11", "Adjusted gross income", f["line11_agi"]),
            ("12", "Standard deduction", f["line12_standard_deduction"]),
            ("13a", "Qualified business income deduction (Form 8995)", f["line13a_qbi_deduction"]),
            ("13b", "Schedule 1-A deductions (tips, seniors)", f["line13b_schedule_1a_deductions"]),
            ("14", "Total deductions", f["line14_total_deductions"]),
            ("15", "Taxable income", f["line15_taxable_income"]),
            ("16", "Tax", f["line16_tax"]),
            ("19", "Child tax credit / credit for other dependents", f["line19_child_tax_credit"]),
            ("22", "Tax after credits", f["line22_tax_after_credits"]),
            ("23", "Other taxes, incl. self-employment tax (Schedule 2, line 21)", f["line23_other_taxes"]),
            ("24", "Total tax", f["line24_total_tax"]),
            ("25", "Federal income tax withheld (W-2 / 1099)", f["line25_withholding"]),
            ("26", "Estimated tax payments", f["line26_estimated_payments"]),
            ("28", "Additional child tax credit (Schedule 8812)", f["line28_actc"]),
            ("33", "Total payments", f["line33_total_payments"]),
            ("34", "Amount overpaid (refund)", f["line34_overpaid"]),
            ("37", "Amount you owe", f["line37_amount_owed"]),
        ]),
        Spacer(1, 6),
        Paragraph("Line numbers follow the current Form 1040 layout; verify against the final "
                  "IRS form for the tax year before transcribing.", SMALL),
        PageBreak(),
    ]

    # ---------------- Schedules 1 & 2 ----------------
    story += [
        Paragraph("Schedule 1 — Additional Income and Adjustments", H1),
        _table([
            ("3", "Business income or (loss) — Schedule C", s1["line3_business_income"]),
            ("8z", "Other income", s1["line8z_other_income"]),
            ("10", "Total additional income", s1["line10_total_additional_income"]),
            ("15", "Deductible part of self-employment tax", s1["line15_half_se_tax"]),
            ("16", "Self-employed SEP, SIMPLE and qualified plans", s1["line16_retirement"]),
            ("17", "Self-employed health insurance deduction", s1["line17_se_health_insurance"]),
            ("26", "Total adjustments to income", s1["line26_total_adjustments"]),
        ]),
        Spacer(1, 12),
        Paragraph("Schedule 2 — Additional Taxes", H1),
        _table([
            ("4", "Self-employment tax (Schedule SE)", s2["line4_se_tax"]),
            ("11", "Additional Medicare Tax (Form 8959)", s2["line11_additional_medicare"]),
            ("21", "Total other taxes", s2["line21_total_other_taxes"]),
        ]),
        PageBreak(),
    ]

    # ---------------- Schedule C ----------------
    biz = [
        ["A  Principal business", profile.get("business_description") or ""],
        ["B  Business code (NAICS)", profile.get("business_code") or ""],
        ["C  Business name", profile.get("business_name") or ""],
        ["F  Accounting method", "Cash"],
    ]
    bt = Table(biz, colWidths=(2.0 * inch, 5.0 * inch))
    bt.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#1f3a5f")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8c4d6"))]))
    exp_rows = [(line, SCHEDULE_C_LABELS.get(line, "Other"), amt) for line, amt in sc["expenses_by_line"].items()]
    cogs = sc["cogs"]
    story += [
        Paragraph("Schedule C — Profit or Loss From Business (Sole Proprietorship)", H1),
        bt, Spacer(1, 8),
        Paragraph("Part I — Income", H2),
        _table([
            ("1", "Gross receipts or sales", sc["line1_gross_receipts"]),
            ("2", "Returns and allowances", sc["line2_returns_allowances"]),
            ("3", "Subtract line 2 from line 1", sc["line3"]),
            ("4", "Cost of goods sold (Part III, line 42)", sc["line4_cogs"]),
            ("5", "Gross profit", sc["line5_gross_profit"]),
            ("6", "Other income", sc["line6_other_income"]),
            ("7", "Gross income", sc["line7_gross_income"]),
        ]),
        Paragraph("Part II — Expenses", H2),
        _table(exp_rows or [("—", "No expenses recorded", 0)]),
        Spacer(1, 4),
        _table([
            ("28", "Total expenses", sc["line28_total_expenses"]),
            ("29", "Tentative profit or (loss)", sc["line29_tentative_profit"]),
            ("30", "Business use of home (simplified method)", sc["line30_home_office"]),
            ("31", "Net profit or (loss)", sc["line31_net_profit"]),
        ]),
        KeepTogether([
            Paragraph("Part III — Cost of Goods Sold", H2),
            _table([
                ("35", "Inventory at beginning of year", cogs["line35_beginning_inventory"]),
                ("36", "Purchases", cogs["line36_purchases"]),
                ("41", "Inventory at end of year", cogs["line41_ending_inventory"]),
                ("42", "Cost of goods sold", cogs["line42_cogs"]),
            ]),
        ]),
    ]
    if sc.get("mileage_deduction"):
        story.append(Paragraph(f"Line 9 uses the standard mileage rate (Part IV: keep your mileage log). "
                               f"Meals shown at 50% of ${sc['meals_before_50pct_limit']:,.0f}.", SMALL))
    story.append(PageBreak())

    # ---------------- Schedule SE ----------------
    story += [
        Paragraph("Schedule SE — Self-Employment Tax", H1),
        _table([
            ("2", "Net profit from Schedule C, line 31", sc["line31_net_profit"]),
            ("4a", "Net earnings (line 2 × 92.35%)", se["line4a_net_earnings"]),
            ("7", "Maximum earnings subject to social security", se["social_security_wage_base"]),
            ("8a", "Social security wages from W-2", se["w2_social_security_wages"]),
            ("10", "Social security portion (12.4%)", se["social_security_portion"]),
            ("11", "Medicare portion (2.9%)", se["medicare_portion"]),
            ("12", "Self-employment tax", se["line12_se_tax"]),
            ("13", "Deduction for one-half of self-employment tax", se["line13_deductible_half"]),
        ]),
        Spacer(1, 10),
        Paragraph("Form 8995 — Qualified Business Income Deduction (summary)", H2),
        _table([
            ("1", "Qualified business income", result["qbi"]["qualified_business_income"]),
            ("15", "Qualified business income deduction", result["qbi"]["deduction"]),
        ]),
    ]

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
