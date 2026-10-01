"""Generate demo data for a fictional corner shop (no real people or accounts).

Writes:
  sample_data/bank_statement_2025.csv  - a year of bank activity
  sample_data/sample_1099_nec_2025.pdf - a text-layer 1099-NEC lookalike for testing extraction
  sample_data/sample_invoice.pdf       - a customer invoice

Run from backend/:  python scripts/make_sample_data.py
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent.parent / "sample_data"
OUT.mkdir(exist_ok=True)
rng = random.Random(2025)


def bank_csv() -> None:
    rows: list[tuple[date, str, float]] = []
    for month in range(1, 13):
        first = date(2025, month, 1)
        # Weekly card settlements and cash deposits
        for week in range(4):
            d = first + timedelta(days=week * 7 + 2)
            rows.append((d, "SQUARE INC DEPOSIT SETTLEMENT", round(rng.uniform(2200, 3400), 2)))
            rows.append((d + timedelta(days=1), "CASH DEPOSIT BRANCH", round(rng.uniform(600, 1100), 2)))
        rows.append((first + timedelta(days=4), "SQUARE FEES MONTHLY", -round(rng.uniform(250, 330), 2)))
        rows.append((first + timedelta(days=5), "RESTAURANT DEPOT PURCHASE", -round(rng.uniform(3000, 4200), 2)))
        rows.append((first + timedelta(days=12), "SYSCO FOOD SERVICES", -round(rng.uniform(1500, 2400), 2)))
        rows.append((first + timedelta(days=1), "MAIN ST PROPERTIES SHOP RENT", -2400.00))
        rows.append((first + timedelta(days=9), "CON ED ELECTRIC BILL", -round(rng.uniform(180, 320), 2)))
        rows.append((first + timedelta(days=10), "VERIZON WIRELESS", -95.40))
        rows.append((first + timedelta(days=14), "NEXT INSURANCE BUSINESS POLICY", -86.00))
        rows.append((first + timedelta(days=16), "SHELL OIL 5521", -round(rng.uniform(45, 80), 2)))
        rows.append((first + timedelta(days=18), "KROGER GROCERY HOME", -round(rng.uniform(90, 160), 2)))
        rows.append((first + timedelta(days=20), "NETFLIX.COM", -15.49))
        rows.append((first + timedelta(days=21), "ONLINE TRANSFER TO SAVINGS", -500.00))
        rows.append((first + timedelta(days=25), "MONTHLY SERVICE FEE", -15.00))
        if month in (2, 5, 8, 11):
            rows.append((first + timedelta(days=6), "FACEBOOK ADS META PLATFORMS", -round(rng.uniform(120, 240), 2)))
        if month in (3, 9):
            rows.append((first + timedelta(days=7), "HOME DEPOT SHELVING REPAIR", -round(rng.uniform(150, 400), 2)))
        if month == 1:
            rows.append((date(2025, 1, 20), "CITY CLERK BUSINESS LICENSE", -350.00))
            rows.append((date(2025, 1, 15), "IRS USATAXPYMT 1040ES", -1800.00))
        if month == 4:
            rows.append((date(2025, 4, 15), "IRS USATAXPYMT 1040ES", -1800.00))
        if month == 6:
            rows.append((date(2025, 6, 16), "IRS USATAXPYMT 1040ES", -1800.00))
            rows.append((date(2025, 6, 22), "JOE'S TAILORING", -64.00))  # ambiguous -> review
        if month == 9:
            rows.append((date(2025, 9, 15), "IRS USATAXPYMT 1040ES", -1800.00))
            rows.append((date(2025, 9, 3), "QUICKBOOKS INTUIT", -35.00))
        if month == 12:
            rows.append((date(2025, 12, 10), "STAPLES OFFICE SUPPLIES", -76.31))
            rows.append((date(2025, 12, 30), "INTEREST EARNED", 12.44))
    rows.sort()
    with open(OUT / "bank_statement_2025.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Date", "Description", "Amount"])
        for d, desc, amt in rows:
            w.writerow([d.strftime("%m/%d/%Y"), desc, f"{amt:.2f}"])


def form_1099_nec() -> None:
    c = canvas.Canvas(str(OUT / "sample_1099_nec_2025.pdf"), pagesize=LETTER)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, 740, "Form 1099-NEC  Nonemployee Compensation   (SAMPLE - 2025)")
    c.setFont("Helvetica", 11)
    lines = [
        "PAYER'S name: Sunrise Catering LLC, 100 Example Ave, Springfield, IL",
        "PAYER'S TIN: 12-3456789        RECIPIENT'S TIN: 123-45-6789",
        "RECIPIENT'S name: Demo Shopkeeper",
        "1 Nonemployee compensation  $ 8,450.00",
        "4 Federal income tax withheld  $ 0.00",
        "For calendar year 2025",
    ]
    for i, line in enumerate(lines):
        c.drawString(72, 700 - i * 22, line)
    c.save()


def invoice() -> None:
    c = canvas.Canvas(str(OUT / "sample_invoice.pdf"), pagesize=LETTER)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, 740, "INVOICE #1042")
    c.setFont("Helvetica", 11)
    lines = [
        "From: Corner Market (Demo)        To: Sunrise Catering LLC",
        "Date: 2025-07-14",
        "Party platters x 10 ............ $ 650.00",
        "Beverage cases x 20 ............ $ 340.00",
        "Total due: $ 990.00",
    ]
    for i, line in enumerate(lines):
        c.drawString(72, 700 - i * 22, line)
    c.save()


if __name__ == "__main__":
    bank_csv()
    form_1099_nec()
    invoice()
    print(f"Sample data written to {OUT}")
