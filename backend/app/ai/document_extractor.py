"""Document understanding: PDF/image -> structured tax data.

Strategy:
* PDFs: extract the text layer locally (pypdf), redact PII, send TEXT to OpenAI.
* Images (phone photos of receipts/forms): sent to the vision model only when
  the user has opted in to AI processing — images can't be text-redacted, so
  the UI explains this before consent.
* Fallback: regex extraction from the PDF text layer.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any

from app.ai import prompts
from app.ai.client import AIUnavailable, prepare_text, structured_completion
from app.models.enums import DocumentType
from app.services import parsing

log = logging.getLogger(__name__)

AMOUNT_FIELDS = [
    "wages",
    "federal_withholding",
    "social_security_wages",
    "medicare_wages",
    "nonemployee_compensation",
    "gross_payments",
    "rents",
    "royalties",
    "other_income",
    "interest_income",
    "ordinary_dividends",
    "qualified_dividends",
]

_NULLABLE_NUMBER = {"type": ["number", "null"]}

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "doc_type", "tax_year", "payer_name", "amounts", "line_items",
        "total_amount", "counterparty", "confidence", "notes",
    ],
    "properties": {
        "doc_type": {"type": "string", "enum": [d.value for d in DocumentType if d != DocumentType.BANK_CSV]},
        "tax_year": {"type": ["integer", "null"]},
        "payer_name": {"type": ["string", "null"]},
        "amounts": {
            "type": "object",
            "additionalProperties": False,
            "required": AMOUNT_FIELDS,
            "properties": {k: _NULLABLE_NUMBER for k in AMOUNT_FIELDS},
        },
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["date", "description", "amount", "direction"],
                "properties": {
                    "date": {"type": ["string", "null"]},
                    "description": {"type": "string"},
                    "amount": {"type": "number"},
                    "direction": {"type": "string", "enum": ["income", "expense"]},
                },
            },
        },
        "total_amount": _NULLABLE_NUMBER,
        "counterparty": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "notes": {"type": "string"},
    },
}


@dataclass
class Extraction:
    doc_type: DocumentType
    method: str  # ai | regex
    tax_year: int | None = None
    payer_name: str | None = None
    amounts: dict[str, float | None] = field(default_factory=dict)
    line_items: list[dict[str, Any]] = field(default_factory=list)
    total_amount: float | None = None
    counterparty: str | None = None
    confidence: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_type": self.doc_type.value,
            "method": self.method,
            "tax_year": self.tax_year,
            "payer_name": self.payer_name,
            "amounts": {k: v for k, v in self.amounts.items() if v is not None},
            "line_items": self.line_items,
            "total_amount": self.total_amount,
            "counterparty": self.counterparty,
            "confidence": self.confidence,
            "notes": self.notes,
            "prompt_version": prompts.PROMPT_VERSION,
        }


def _from_ai(data: dict[str, Any]) -> Extraction:
    return Extraction(
        doc_type=DocumentType(data["doc_type"]),
        method="ai",
        tax_year=data.get("tax_year"),
        payer_name=(data.get("payer_name") or None),
        amounts={k: v for k, v in (data.get("amounts") or {}).items() if v is not None},
        line_items=[li for li in data.get("line_items", []) if li.get("amount", 0) > 0][:200],
        total_amount=data.get("total_amount"),
        counterparty=data.get("counterparty"),
        confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
        notes=(data.get("notes") or "")[:500],
    )


def extract_from_text(text: str, filename: str, use_ai: bool, hint: DocumentType | None = None) -> Extraction:
    if use_ai and text.strip():
        try:
            user = (
                f"User-selected type hint: {hint.value if hint else 'none'}\n"
                f"Document text:\n---\n{prepare_text(text)}\n---"
            )
            data = structured_completion(
                system=prompts.DOCUMENT_EXTRACTION,
                user=user,
                schema_name="tax_document",
                schema=EXTRACTION_SCHEMA,
            )
            return _from_ai(data)
        except AIUnavailable as exc:
            log.info("AI extraction unavailable, falling back to regex: %s", exc)

    doc_type = hint if hint and hint != DocumentType.OTHER else parsing.detect_doc_type(text, filename)
    amounts = parsing.regex_extract(text, doc_type)
    found = sum(1 for v in amounts.values() if v is not None)
    total = parsing.regex_total(text) if doc_type in (DocumentType.INVOICE, DocumentType.RECEIPT) else None
    line_items = []
    if total:
        line_items.append({
            "date": None,
            "description": f"{doc_type.value.title()} total ({filename})"[:200],
            "amount": total,
            "direction": "income" if doc_type == DocumentType.INVOICE else "expense",
        })
    confidence = 0.6 if found or total else 0.1
    return Extraction(
        doc_type=doc_type, method="regex", amounts=amounts, line_items=line_items,
        total_amount=total, confidence=confidence,
        notes="Extracted with pattern matching; please verify the amounts.",
    )


def extract_from_image(raw: bytes, content_type: str, use_ai: bool, hint: DocumentType | None = None) -> Extraction:
    if not use_ai:
        return Extraction(
            doc_type=hint or DocumentType.OTHER, method="none", confidence=0.0,
            notes="Image stored. Enable AI processing (Settings) to read photos automatically, or enter amounts manually.",
        )
    b64 = base64.b64encode(raw).decode("ascii")
    content = [
        {"type": "text", "text": f"Extract this document. Type hint: {hint.value if hint else 'none'}."},
        {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}", "detail": "high"}},
    ]
    try:
        data = structured_completion(
            system=prompts.DOCUMENT_EXTRACTION, user=content,
            schema_name="tax_document", schema=EXTRACTION_SCHEMA,
        )
        return _from_ai(data)
    except AIUnavailable as exc:
        return Extraction(doc_type=hint or DocumentType.OTHER, method="none",
                          notes=f"AI extraction failed ({exc}); enter amounts manually.")
