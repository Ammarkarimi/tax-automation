"""Deterministic document parsing: bank CSVs, PDF text, and regex form extraction.

AI is layered on top of this (app.ai.document_extractor); everything here works
offline and is used as the fallback when AI is disabled or fails.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.models.enums import Direction, DocumentType

MAX_CSV_ROWS = 10_000

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y", "%Y/%m/%d", "%m-%d-%Y")


@dataclass
class ParsedTxn:
    txn_date: date
    description: str
    amount: Decimal  # positive
    direction: Direction


class ParseError(ValueError):
    pass


def parse_date(value: str) -> date | None:
    value = (value or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(value: str) -> Decimal | None:
    """'$1,234.56' -> 1234.56; '(45.00)' -> -45.00; '' -> None."""
    v = (value or "").strip().replace("$", "").replace(",", "").replace(" ", "")
    if not v:
        return None
    negative = v.startswith("(") and v.endswith(")")
    v = v.strip("()")
    if v.endswith("-"):  # some banks write "45.00-"
        negative, v = True, v[:-1]
    try:
        d = Decimal(v)
    except InvalidOperation:
        return None
    return -d if negative else d


def _find_col(headers: list[str], *candidates: str) -> int | None:
    lowered = [h.strip().lower() for h in headers]
    for cand in candidates:
        for i, h in enumerate(lowered):
            if h == cand:
                return i
    for cand in candidates:
        for i, h in enumerate(lowered):
            if cand in h:
                return i
    return None


def parse_bank_csv(raw: bytes) -> list[ParsedTxn]:
    """Parse common bank/card CSV exports.

    Supports either a signed `Amount` column or separate `Debit`/`Credit`
    (or `Withdrawal`/`Deposit`) columns. Positive amounts are treated as money
    in (income) and negative as money out (expense).
    """
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        raise ParseError("CSV is empty")

    # Find the header row (some banks put account info lines on top).
    header_idx = next(
        (i for i, r in enumerate(rows[:15]) if any("date" in c.lower() for c in r)), None
    )
    if header_idx is None:
        raise ParseError("Could not find a header row with a 'Date' column")
    headers = rows[header_idx]
    c_date = _find_col(headers, "date", "transaction date", "posting date", "posted date")
    c_desc = _find_col(headers, "description", "payee", "merchant", "name", "memo", "details")
    c_amt = _find_col(headers, "amount", "transaction amount")
    c_debit = _find_col(headers, "debit", "withdrawal", "withdrawals", "money out")
    c_credit = _find_col(headers, "credit", "deposit", "deposits", "money in")
    if c_date is None or c_desc is None or (c_amt is None and c_debit is None and c_credit is None):
        raise ParseError("CSV needs Date, Description and Amount (or Debit/Credit) columns")

    # Card exports sometimes have a "Type" column with Sale/Payment; amounts may be
    # negative for purchases (Chase) or positive (Amex). We follow the sign.
    out: list[ParsedTxn] = []
    for r in rows[header_idx + 1 : header_idx + 1 + MAX_CSV_ROWS]:
        if not r or all(not c.strip() for c in r):
            continue
        get = lambda i: r[i] if i is not None and i < len(r) else ""  # noqa: E731
        d = parse_date(get(c_date))
        if d is None:
            continue
        signed: Decimal | None = None
        if c_amt is not None:
            signed = parse_money(get(c_amt))
        else:
            debit, credit = parse_money(get(c_debit)), parse_money(get(c_credit))
            if credit:
                signed = abs(credit)
            elif debit:
                signed = -abs(debit)
        if signed is None or signed == 0:
            continue
        out.append(
            ParsedTxn(
                txn_date=d,
                description=get(c_desc).strip()[:500] or "(no description)",
                amount=abs(signed).quantize(Decimal("0.01")),
                direction=Direction.INCOME if signed > 0 else Direction.EXPENSE,
            )
        )
    if not out:
        raise ParseError("No transactions found in CSV")
    return out


def extract_pdf_text(raw: bytes, max_pages: int = 20) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ParseError("PDF is password protected") from exc
    parts = []
    for page in reader.pages[:max_pages]:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Regex fallback for tax forms
# ---------------------------------------------------------------------------

_TYPE_PATTERNS: list[tuple[str, DocumentType]] = [
    (r"1099-?NEC|nonemployee compensation", DocumentType.F1099_NEC),
    (r"1099-?K|payment card and third party network", DocumentType.F1099_K),
    (r"1099-?MISC|miscellaneous (information|income)", DocumentType.F1099_MISC),
    (r"1099-?INT|interest income", DocumentType.F1099_INT),
    (r"1099-?DIV|dividends and distributions", DocumentType.F1099_DIV),
    (r"\bW-?2\b|wage and tax statement", DocumentType.W2),
    (r"\binvoice\b", DocumentType.INVOICE),
    (r"\breceipt\b|\bsubtotal\b", DocumentType.RECEIPT),
]

_AMOUNT = r"[^\d\n]{0,60}?\$?\s*([\d,]+\.\d{2})"

_FIELD_PATTERNS: dict[DocumentType, dict[str, str]] = {
    DocumentType.W2: {
        "wages": r"wages,? tips,? other comp(?:ensation)?" + _AMOUNT,
        "federal_withholding": r"federal income tax withheld" + _AMOUNT,
        "social_security_wages": r"social security wages" + _AMOUNT,
        "medicare_wages": r"medicare wages and tips" + _AMOUNT,
    },
    DocumentType.F1099_NEC: {
        "nonemployee_compensation": r"nonemployee compensation" + _AMOUNT,
        "federal_withholding": r"federal income tax withheld" + _AMOUNT,
    },
    DocumentType.F1099_K: {
        "gross_payments": r"gross amount of payment card(?:/third party network)? transactions" + _AMOUNT,
        "federal_withholding": r"federal income tax withheld" + _AMOUNT,
    },
    DocumentType.F1099_MISC: {
        "rents": r"\brents\b" + _AMOUNT,
        "royalties": r"\broyalties\b" + _AMOUNT,
        "other_income": r"other income" + _AMOUNT,
        "federal_withholding": r"federal income tax withheld" + _AMOUNT,
    },
    DocumentType.F1099_INT: {
        "interest_income": r"interest income" + _AMOUNT,
        "federal_withholding": r"federal income tax withheld" + _AMOUNT,
    },
    DocumentType.F1099_DIV: {
        "ordinary_dividends": r"total ordinary dividends" + _AMOUNT,
        "qualified_dividends": r"qualified dividends" + _AMOUNT,
        "federal_withholding": r"federal income tax withheld" + _AMOUNT,
    },
}


def detect_doc_type(text: str, filename: str = "") -> DocumentType:
    haystack = f"{filename}\n{text[:5000]}"
    for pattern, dtype in _TYPE_PATTERNS:
        if re.search(pattern, haystack, re.I):
            return dtype
    return DocumentType.OTHER


def regex_extract(text: str, doc_type: DocumentType) -> dict[str, float | None]:
    amounts: dict[str, float | None] = {}
    for field, pattern in _FIELD_PATTERNS.get(doc_type, {}).items():
        m = re.search(pattern, text, re.I)
        amounts[field] = float(m.group(1).replace(",", "")) if m else None
    return amounts


def regex_total(text: str) -> float | None:
    """Best-effort 'Total' amount from an invoice/receipt."""
    matches = re.findall(r"(?:amount due|balance due|grand total|total)[^\d\n]{0,20}\$?\s*([\d,]+\.\d{2})", text, re.I)
    if not matches:
        return None
    return max(float(m.replace(",", "")) for m in matches)
