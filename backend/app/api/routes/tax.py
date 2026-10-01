"""Tax computation, planning, AI explanations and PDF reports."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import explainer
from app.api.deps import get_current_user, tax_year_param
from app.core.config import get_settings
from app.core.crypto import sha256_hex
from app.db.session import get_db
from app.models import GeneratedReport, User
from app.schemas import AskRequest, Explanation
from app.services import audit, storage, tax_service
from app.services.pdf import render_return_pdf
from app.services.rate_limit import ai_limiter, client_key

router = APIRouter(prefix="/tax", tags=["tax"])


def _use_ai(user: User) -> bool:
    return get_settings().ai_enabled and user.ai_consent


@router.get("/annual")
def annual(request: Request, year: int = Depends(tax_year_param), user: User = Depends(get_current_user),
           db: Session = Depends(get_db)) -> dict:
    result = tax_service.annual(db, user, year)
    audit.record(db, "tax.annual_calculated", request=request, actor_id=user.id, details={"year": year})
    return result


@router.get("/quarterly")
def quarterly(request: Request, year: int = Depends(tax_year_param),
              as_of: date | None = Query(default=None, description="Defaults to today"),
              user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    result = tax_service.quarterly(db, user, year, as_of)
    audit.record(db, "tax.quarterly_calculated", request=request, actor_id=user.id, details={"year": year})
    return result


@router.get("/deductions")
def deductions(request: Request, year: int = Depends(tax_year_param), include_ai: bool = False,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    suggestions, ctx, agg = tax_service.deductions(db, user, year)
    ai_ideas = []
    if include_ai and _use_ai(user):
        ai_limiter.check(client_key(request, f"ai:{user.id}"))
        expense_totals = {k: float(v) for k, v in ctx.category_totals.items() if v > 0}
        ai_ideas = explainer.ai_deduction_ideas(
            agg.profile.business_description or "", expense_totals, [s["title"] for s in suggestions], True
        )
    total_savings = sum(s["estimated_savings"] for s in suggestions if s["status"] == "opportunity")
    return {"tax_year": year, "suggestions": suggestions + ai_ideas,
            "potential_savings": round(total_savings, 2), "ai_used": bool(ai_ideas)}


@router.get("/audit-risk")
def audit_risk(request: Request, year: int = Depends(tax_year_param), explain: bool = False,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    risk = tax_service.audit_risk(db, user, year)
    if explain:
        if _use_ai(user):
            ai_limiter.check(client_key(request, f"ai:{user.id}"))
        risk["explanation"] = explainer.explain_audit_risk(risk, _use_ai(user))
    return risk


@router.get("/explain", response_model=Explanation)
def explain(request: Request, year: int = Depends(tax_year_param), user: User = Depends(get_current_user),
            db: Session = Depends(get_db)) -> dict:
    if _use_ai(user):
        ai_limiter.check(client_key(request, f"ai:{user.id}"))
    result = tax_service.annual(db, user, year, save=False)
    return explainer.explain_tax(result, _use_ai(user))


@router.post("/ask", response_model=Explanation)
def ask(body: AskRequest, request: Request, year: int = Depends(tax_year_param),
        user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    ai_limiter.check(client_key(request, f"ai:{user.id}"))
    result = tax_service.annual(db, user, year, save=False)
    answer = explainer.answer_question(body.question, result, _use_ai(user))
    audit.record(db, "ai.question", request=request, actor_id=user.id, details={"source": answer["source"]})
    return answer


# ----------------------------- Reports -----------------------------


def _profile_dict(profile) -> dict:
    return {
        "taxpayer_name": profile.taxpayer_name, "ssn": profile.ssn, "address": profile.address,
        "business_name": profile.business_name, "business_description": profile.business_description,
        "business_code": profile.business_code,
    }


@router.post("/reports/return-pdf")
def generate_return_pdf(request: Request, year: int = Depends(tax_year_param),
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    result = tax_service.annual(db, user, year)
    profile = tax_service.get_or_create_profile(db, user, year)
    pdf = render_return_pdf(result, _profile_dict(profile))
    key = storage.save(pdf)
    report = GeneratedReport(user_id=user.id, tax_year=year, kind="form_1040_schedule_c",
                             storage_key=key, sha256=sha256_hex(pdf))
    db.add(report)
    db.commit()
    db.refresh(report)
    audit.record(db, "report.generated", request=request, actor_id=user.id, resource_type="report",
                 resource_id=report.id, details={"year": year})
    return {"id": str(report.id), "tax_year": year, "created_at": report.created_at.isoformat(),
            "sha256": report.sha256}


@router.get("/reports")
def list_reports(year: int = Depends(tax_year_param), user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(GeneratedReport).where(GeneratedReport.user_id == user.id,
                                                    GeneratedReport.tax_year == year)
                      .order_by(GeneratedReport.created_at.desc()))
    return [{"id": str(r.id), "tax_year": r.tax_year, "kind": r.kind, "created_at": r.created_at.isoformat(),
             "sha256": r.sha256} for r in rows]


@router.get("/reports/{report_id}/download")
def download_report(report_id: uuid.UUID, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> Response:
    report = db.get(GeneratedReport, report_id)
    if report is None or report.user_id != user.id:
        raise HTTPException(status_code=404, detail="Report not found")
    data = storage.load(report.storage_key)
    audit.record(db, "report.downloaded", request=request, actor_id=user.id, resource_type="report",
                 resource_id=report.id)
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="tax-return-{report.tax_year}.pdf"',
        "Cache-Control": "no-store",
    })
