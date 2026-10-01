"""Upload validation and the document-processing pipeline.

upload -> validate (size, type, magic bytes) -> encrypt & store -> process:
  * bank CSV   -> parse rows -> classify (rules + AI) -> transactions
  * PDF        -> text layer -> AI/regex extraction -> income form or transactions
  * image      -> AI vision extraction (if consented) -> income form or transactions
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.ai.classifier import Classification, TxnIn, classify_transactions
from app.ai.document_extractor import Extraction, extract_from_image, extract_from_text
from app.core.config import get_settings
from app.models import Document, IncomeForm, TaxProfile, Transaction, User
from app.models.enums import TAX_FORM_TYPES, Direction, DocumentStatus, DocumentType
from app.services import parsing, storage

log = logging.getLogger(__name__)

ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "text/csv": "csv",
    "application/vnd.ms-excel": "csv",  # browsers often label CSVs this way
    "text/plain": "csv",
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
}

_MAGIC = {
    "pdf": [b"%PDF"],
    "image": [b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF"],
}


class UploadRejected(ValueError):
    pass


def validate_upload(filename: str, content_type: str, data: bytes) -> str:
    """Return the file kind ('pdf' | 'csv' | 'image') or raise UploadRejected."""
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if not data:
        raise UploadRejected("File is empty")
    if len(data) > max_bytes:
        raise UploadRejected(f"File exceeds {get_settings().max_upload_mb} MB")
    kind = ALLOWED_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if kind is None and filename.lower().endswith(".csv"):
        kind = "csv"
    if kind is None:
        raise UploadRejected("Unsupported file type. Upload PDF, CSV, JPG, PNG or WEBP.")
    # Don't trust the client-declared type: verify file signatures.
    if kind in _MAGIC and not any(data.startswith(sig) for sig in _MAGIC[kind]):
        raise UploadRejected("File content doesn't match its type")
    if kind == "csv":
        if b"\x00" in data[:4096]:
            raise UploadRejected("CSV appears to be binary")
    return kind


def _use_ai(user: User) -> bool:
    return get_settings().ai_enabled and user.ai_consent


def _business_context(db: Session, user: User, year: int) -> str:
    profile = db.query(TaxProfile).filter_by(user_id=user.id, tax_year=year).first()
    if not profile:
        return ""
    return " — ".join(x for x in (profile.business_description, profile.business_code and f"NAICS {profile.business_code}") if x)


def _apply_classification(t: Transaction, c: Classification) -> None:
    t.category = c.category.value
    t.direction = c.direction.value
    t.business_use_pct = c.business_use_pct
    t.confidence = round(c.confidence, 3)
    t.classified_by = c.classified_by.value
    t.ai_rationale = c.rationale[:500] if c.rationale else None
    t.merchant = (c.merchant or None) and c.merchant[:200]
    t.needs_review = c.needs_review


def create_transactions(
    db: Session, user: User, doc: Document | None, year: int,
    rows: list[tuple[date, str, Decimal, Direction]],
) -> list[Transaction]:
    """Insert rows (skipping other-year dates) and classify them in one batch."""
    rows = [r for r in rows if r[0].year == year]
    txns = [
        Transaction(
            user_id=user.id, document_id=doc.id if doc else None, tax_year=year,
            txn_date=d, description=desc, amount=amt, direction=direction.value,
        )
        for d, desc, amt, direction in rows
    ]
    items = [
        TxnIn(ref=i, description=t.description, amount=Decimal(t.amount),
              direction=Direction(t.direction), date=t.txn_date.isoformat())
        for i, t in enumerate(txns)
    ]
    for t, c in zip(txns, classify_transactions(items, _business_context(db, user, year), _use_ai(user)), strict=True):
        _apply_classification(t, c)
    db.add_all(txns)
    return txns


def reclassify(db: Session, user: User, txns: list[Transaction], year: int) -> int:
    items = [
        TxnIn(ref=i, description=t.description, amount=Decimal(t.amount),
              direction=Direction(t.direction), date=t.txn_date.isoformat())
        for i, t in enumerate(txns)
    ]
    results = classify_transactions(items, _business_context(db, user, year), _use_ai(user))
    for t, c in zip(txns, results, strict=True):
        _apply_classification(t, c)
    db.commit()
    return len(txns)


def _rows_from_extraction(ex: Extraction, year: int) -> list[tuple[date, str, Decimal, Direction]]:
    rows = []
    for li in ex.line_items:
        d = parsing.parse_date(li.get("date") or "") or date(year, 12, 31)
        label = (ex.counterparty or "").strip()
        desc = f"{label}: {li['description']}" if label else li["description"]
        rows.append((d, desc[:500], Decimal(str(li["amount"])).quantize(Decimal("0.01")), Direction(li["direction"])))
    return rows


def process_document(db: Session, user: User, doc: Document, kind: str, hint: DocumentType | None) -> Document:
    doc.status = DocumentStatus.PROCESSING.value
    db.commit()
    try:
        raw = storage.load(doc.storage_key)
        created_txns = 0
        created_form = None
        if kind == "csv":
            parsed = parsing.parse_bank_csv(raw)
            txns = create_transactions(
                db, user, doc, doc.tax_year,
                [(p.txn_date, p.description, p.amount, p.direction) for p in parsed],
            )
            created_txns = len(txns)
            doc.doc_type = DocumentType.BANK_CSV.value
            doc.extracted_data = {
                "method": "csv",
                "rows_in_file": len(parsed),
                "rows_imported": created_txns,
                "skipped_other_years": len(parsed) - created_txns,
            }
        else:
            if kind == "pdf":
                text = parsing.extract_pdf_text(raw)
                ex = extract_from_text(text, "document.pdf", _use_ai(user), hint)
                if not text.strip() and ex.method != "ai":
                    ex.notes = "This PDF has no text layer (scanned). Enable AI processing to read it, or enter amounts manually."
            else:
                ex = extract_from_image(raw, doc.content_type, _use_ai(user), hint)
            doc.doc_type = ex.doc_type.value
            if ex.doc_type in TAX_FORM_TYPES:
                created_form = IncomeForm(
                    user_id=user.id, document_id=doc.id, tax_year=doc.tax_year,
                    form_type=ex.doc_type.value, payer_name=(ex.payer_name or None),
                    amounts={k: v for k, v in ex.amounts.items() if v is not None},
                    confirmed=False,
                )
                db.add(created_form)
            elif ex.line_items:
                created_txns = len(create_transactions(db, user, doc, doc.tax_year, _rows_from_extraction(ex, doc.tax_year)))
            data = ex.to_dict()
            data["transactions_created"] = created_txns
            if ex.tax_year and ex.tax_year != doc.tax_year:
                data["warning"] = f"Document appears to be for {ex.tax_year}, but was uploaded to {doc.tax_year}."
            doc.extracted_data = data
        doc.status = DocumentStatus.PROCESSED.value
        doc.error = None
        doc.processed_at = datetime.now(timezone.utc)
        db.commit()
        if created_form is not None:
            db.refresh(created_form)
    except parsing.ParseError as exc:
        db.rollback()
        doc.status = DocumentStatus.FAILED.value
        doc.error = str(exc)[:500]
        db.commit()
    except Exception:
        db.rollback()
        log.exception("document processing failed")
        doc.status = DocumentStatus.FAILED.value
        doc.error = "Processing failed. Check the file and try again."
        db.commit()
    db.refresh(doc)
    return doc
