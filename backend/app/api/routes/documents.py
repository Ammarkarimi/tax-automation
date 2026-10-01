"""Secure document upload, processing, download and deletion."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, tax_year_param
from app.core.config import get_settings
from app.core.crypto import sha256_hex
from app.db.session import get_db
from app.models import Document, User
from app.models.enums import DocumentType
from app.schemas import DocumentOut
from app.services import audit, storage
from app.services.document_service import UploadRejected, process_document, validate_upload

router = APIRouter(prefix="/documents", tags=["documents"])


def _owned(db: Session, user: User, doc_id: uuid.UUID) -> Document:
    doc = db.get(Document, doc_id)
    # Same 404 for "missing" and "not yours" — don't leak existence of other users' ids.
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _kind(doc: Document) -> str:
    if doc.content_type == "application/pdf":
        return "pdf"
    if doc.content_type.startswith("image/"):
        return "image"
    return "csv"


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    doc_type: DocumentType | None = Form(default=None),
    process: bool = Form(default=True),
    year: int = Depends(tax_year_param),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    filename = (file.filename or "upload").replace("/", "_").replace("\\", "_")[:200]
    try:
        kind = validate_upload(filename, file.content_type or "", data)
    except UploadRejected as exc:
        audit.record(db, "document.upload_rejected", request=request, actor_id=user.id, success=False,
                     details={"reason": str(exc)})
        raise HTTPException(status_code=422, detail=str(exc)) from None

    digest = sha256_hex(data)
    dup = db.scalar(select(Document).where(Document.user_id == user.id, Document.sha256 == digest,
                                           Document.tax_year == year))
    if dup:
        raise HTTPException(status_code=409, detail="This file was already uploaded for this tax year")

    content_type = {"csv": "text/csv"}.get(kind, (file.content_type or "").split(";")[0].lower())
    key = storage.save(data)
    doc = Document(
        user_id=user.id, tax_year=year, original_filename=filename, content_type=content_type,
        size_bytes=len(data), sha256=digest, storage_key=key,
        doc_type=(doc_type or (DocumentType.BANK_CSV if kind == "csv" else DocumentType.OTHER)).value,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    audit.record(db, "document.uploaded", request=request, actor_id=user.id, actor_role=user.role,
                 resource_type="document", resource_id=doc.id, details={"kind": kind, "size": len(data), "year": year})
    if process:
        # Processing is synchronous for local use; see ROADMAP for a background queue.
        doc = process_document(db, user, doc, kind, doc_type)
        audit.record(db, "document.processed", request=request, actor_id=user.id, resource_type="document",
                     resource_id=doc.id, success=doc.status == "processed")
    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(year: int = Depends(tax_year_param), user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> list[Document]:
    return list(db.scalars(select(Document).where(Document.user_id == user.id, Document.tax_year == year)
                           .order_by(Document.created_at.desc())))


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Document:
    return _owned(db, user, doc_id)


@router.post("/{doc_id}/process", response_model=DocumentOut)
def reprocess_document(doc_id: uuid.UUID, request: Request, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> Document:
    doc = _owned(db, user, doc_id)
    if doc.status == "processed" and doc.doc_type == DocumentType.BANK_CSV.value:
        raise HTTPException(status_code=409, detail="CSV already imported; delete it first to re-import")
    hint = DocumentType(doc.doc_type) if doc.doc_type != DocumentType.OTHER.value else None
    doc = process_document(db, user, doc, _kind(doc), hint)
    audit.record(db, "document.processed", request=request, actor_id=user.id, resource_type="document",
                 resource_id=doc.id, success=doc.status == "processed")
    return doc


@router.get("/{doc_id}/download")
def download_document(doc_id: uuid.UUID, request: Request, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)) -> Response:
    doc = _owned(db, user, doc_id)
    data = storage.load(doc.storage_key)
    audit.record(db, "document.downloaded", request=request, actor_id=user.id, resource_type="document",
                 resource_id=doc.id)
    safe_name = "".join(c for c in doc.original_filename if c.isalnum() or c in "._- ")[:100] or "document"
    return Response(content=data, media_type=doc.content_type, headers={
        "Content-Disposition": f'attachment; filename="{safe_name}"',
        "Cache-Control": "no-store",
    })


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: uuid.UUID, request: Request, delete_transactions: bool = True,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    from app.models import IncomeForm, Transaction

    doc = _owned(db, user, doc_id)
    if delete_transactions:
        for t in db.scalars(select(Transaction).where(Transaction.document_id == doc.id)):
            db.delete(t)
        for f in db.scalars(select(IncomeForm).where(IncomeForm.document_id == doc.id)):
            db.delete(f)
    key = doc.storage_key
    db.delete(doc)
    db.commit()
    storage.delete(key)
    audit.record(db, "document.deleted", request=request, actor_id=user.id, resource_type="document",
                 resource_id=doc_id, details={"with_transactions": delete_transactions})
    return Response(status_code=204)
