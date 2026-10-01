"""AI pipeline tests with a fake OpenAI client (no network)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai import client as ai_client
from app.ai.classifier import TxnIn, classify_by_rules, classify_transactions
from app.ai.document_extractor import extract_from_text
from app.core.redaction import redact_text
from app.models.enums import Category, Direction, DocumentType
from app.services import parsing

SAMPLES = Path(__file__).parent.parent / "sample_data"


class FakeCompletions:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.payload(kwargs) if callable(self.payload) else self.payload
        msg = SimpleNamespace(content=content if isinstance(content, str) else json.dumps(content), refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


@pytest.fixture
def fake_openai(monkeypatch):
    def install(payload):
        completions = FakeCompletions(payload)
        fake = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        monkeypatch.setattr(ai_client, "_get_client", lambda: fake)
        return completions
    return install


def test_redaction():
    text = "SSN 123-45-6789 EIN 12-3456789 acct 000123456789 mail a.b@x.com call (555) 123-4567"
    red = redact_text(text)
    for secret in ("123-45-6789", "12-3456789", "000123456789", "a.b@x.com", "123-4567"):
        assert secret not in red


def test_rules_classifier():
    c = classify_by_rules(TxnIn(0, "IRS USATAXPYMT 1040ES", Decimal("100"), Direction.EXPENSE))
    assert c.category == Category.ESTIMATED_TAX_PAYMENT and not c.needs_review
    c = classify_by_rules(TxnIn(1, "SQUARE INC DEPOSIT", Decimal("100"), Direction.INCOME))
    assert c.category == Category.BUSINESS_INCOME
    c = classify_by_rules(TxnIn(2, "JOE'S TAILORING", Decimal("64"), Direction.EXPENSE))
    assert c.category == Category.UNCATEGORIZED and c.needs_review


def test_ai_classifier_used_for_uncertain_items_and_redacts(fake_openai):
    calls = fake_openai({"items": [{
        "ref": 1, "category": "supplies", "direction": "expense", "business_use_pct": 100,
        "confidence": 0.9, "merchant": "Joe's", "rationale": "Uniform alterations for staff",
    }, {"ref": 99, "category": "travel", "direction": "expense", "business_use_pct": 100,
        "confidence": 1, "merchant": None, "rationale": "hallucinated ref"}]})
    items = [
        TxnIn(0, "IRS USATAXPYMT 1040ES", Decimal("100"), Direction.EXPENSE),
        TxnIn(1, "JOE'S TAILORING card 4111 1111 1111 1111", Decimal("64"), Direction.EXPENSE),
    ]
    result = classify_transactions(items, "corner shop", use_ai=True)
    assert result[0].category == Category.ESTIMATED_TAX_PAYMENT  # rules handled it; not sent
    assert result[1].category == Category.SUPPLIES and result[1].classified_by.value == "ai"
    sent = calls.calls[0]["messages"][1]["content"]
    assert "4111" not in sent and "IRS USATAXPYMT" not in sent
    assert calls.calls[0]["store"] is False
    assert calls.calls[0]["response_format"]["json_schema"]["strict"] is True


def test_ai_failure_falls_back_to_rules(monkeypatch):
    def boom():
        raise ai_client.AIUnavailable("down")
    monkeypatch.setattr(ai_client, "_get_client", boom)
    res = classify_transactions([TxnIn(0, "mystery", Decimal("5"), Direction.EXPENSE)], use_ai=True)
    assert res[0].category == Category.UNCATEGORIZED


def test_regex_extraction_of_sample_1099():
    text = parsing.extract_pdf_text((SAMPLES / "sample_1099_nec_2025.pdf").read_bytes())
    ex = extract_from_text(text, "1099.pdf", use_ai=False)
    assert ex.doc_type == DocumentType.F1099_NEC
    assert ex.amounts["nonemployee_compensation"] == 8450.00


def test_ai_document_extraction(fake_openai):
    calls = fake_openai({
        "doc_type": "1099_nec", "tax_year": 2025, "payer_name": "Sunrise Catering LLC",
        "amounts": {k: None for k in [
            "wages", "federal_withholding", "social_security_wages", "medicare_wages", "gross_payments",
            "rents", "royalties", "other_income", "interest_income", "ordinary_dividends", "qualified_dividends"]}
        | {"nonemployee_compensation": 8450.0},
        "line_items": [], "total_amount": None, "counterparty": None, "confidence": 0.95, "notes": "",
    })
    text = parsing.extract_pdf_text((SAMPLES / "sample_1099_nec_2025.pdf").read_bytes())
    ex = extract_from_text(text, "1099.pdf", use_ai=True)
    assert ex.method == "ai" and ex.amounts == {"nonemployee_compensation": 8450.0}
    sent = calls.calls[0]["messages"][1]["content"]
    assert "123-45-6789" not in sent and "12-3456789" not in sent


def test_invoice_regex_total():
    text = parsing.extract_pdf_text((SAMPLES / "sample_invoice.pdf").read_bytes())
    ex = extract_from_text(text, "invoice.pdf", use_ai=False)
    assert ex.doc_type == DocumentType.INVOICE
    assert ex.line_items[0]["amount"] == 990.00 and ex.line_items[0]["direction"] == "income"


def test_csv_parser_debit_credit_columns():
    raw = b"Account 1234\nPosting Date,Payee,Debit,Credit\n01/05/2025,ACME,12.50,\n01/06/2025,CLIENT,,100.00\n"
    rows = parsing.parse_bank_csv(raw)
    assert [(r.direction.value, str(r.amount)) for r in rows] == [("expense", "12.50"), ("income", "100.00")]
