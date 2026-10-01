"""Natural-language explanations (tax summary, audit risk, Q&A, extra deductions).

Only computed, non-identifying numbers are sent to OpenAI — never names, SSNs,
addresses or raw transaction descriptions. Every function has a deterministic
template fallback so the UI always has something useful to show.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai import prompts
from app.ai.client import AIUnavailable, prepare_text, structured_completion, text_completion
from app.models.enums import Category

log = logging.getLogger(__name__)


def _usd(x: float) -> str:
    return f"${x:,.0f}"


def _safe_summary(result: dict[str, Any]) -> dict[str, Any]:
    """The subset of a tax result we're willing to send to the model."""
    return {
        "tax_year": result["tax_year"],
        "filing_status": result["filing_status"],
        "summary": result["summary"],
        "schedule_c": {k: v for k, v in result["schedule_c"].items() if k != "cogs"},
        "schedule_se": result["schedule_se"],
        "adjustments": result["schedule_1"],
        "deductions": {
            "standard": result["form_1040"]["line12_standard_deduction"],
            "qbi": result["form_1040"]["line13a_qbi_deduction"],
            "schedule_1a": result["schedule_1a"],
        },
        "credits": result["credits"],
        "warnings": result["warnings"],
    }


def template_tax_explanation(result: dict[str, Any]) -> str:
    s, sc = result["summary"], result["schedule_c"]
    owe = s["balance_due"]
    lines = [
        f"### Your {result['tax_year']} federal tax estimate",
        "",
        f"- **Business profit (Schedule C):** {_usd(sc['line31_net_profit'])} — "
        f"income of {_usd(sc['line7_gross_income'])} minus {_usd(sc['line28_total_expenses'] + sc['line4_cogs'])} "
        "in expenses and cost of goods.",
        f"- **Self-employment tax:** {_usd(s['self_employment_tax'])}. This is Social Security + "
        "Medicare, which an employer would normally split with you (15.3% of 92.35% of profit).",
        f"- **Adjusted gross income:** {_usd(s['agi'])}; after the standard deduction and "
        f"QBI deduction your **taxable income** is {_usd(s['taxable_income'])}.",
        f"- **Income tax:** {_usd(s['income_tax'])} (top bracket {s['marginal_income_rate']:.0%}).",
        f"- **Total tax:** {_usd(s['total_tax'])}, effective rate {s['effective_rate']:.1%} of total income.",
        "",
        f"**{'You owe ' + _usd(owe) if owe > 0 else 'Expected refund: ' + _usd(s['refund'])}** "
        f"after {_usd(s['total_payments'])} of withholding, estimated payments and refundable credits.",
        "",
        "**Biggest levers:** record every business expense, track mileage, consider a "
        "SEP-IRA contribution, and pay quarterly estimates to avoid penalties.",
    ]
    return "\n".join(lines)


def explain_tax(result: dict[str, Any], use_ai: bool) -> dict[str, Any]:
    if use_ai:
        try:
            text = text_completion(
                system=prompts.TAX_EXPLAINER,
                user="Explain this estimate:\n" + json.dumps(_safe_summary(result)),
            )
            if text:
                return {"source": "ai", "markdown": text}
        except AIUnavailable:
            pass
    return {"source": "template", "markdown": template_tax_explanation(result)}


def template_audit_explanation(risk: dict[str, Any]) -> str:
    if not risk["factors"]:
        return "No notable audit-risk indicators were found. Keep your receipts and records for at least 3 years."
    out = [f"### Audit-risk check: **{risk['level'].upper()}** ({risk['score']}/100)", ""]
    for f in risk["factors"]:
        out.append(f"- **{f['title']}** ({f['severity']}): {f['detail']} _What to do:_ {f['recommendation']}")
    out += ["", f"_{risk['disclaimer']}_"]
    return "\n".join(out)


def explain_audit_risk(risk: dict[str, Any], use_ai: bool) -> dict[str, Any]:
    if use_ai and risk["factors"]:
        try:
            text = text_completion(system=prompts.AUDIT_EXPLAINER, user=json.dumps(risk))
            if text:
                return {"source": "ai", "markdown": text}
        except AIUnavailable:
            pass
    return {"source": "template", "markdown": template_audit_explanation(risk)}


def answer_question(question: str, result: dict[str, Any], use_ai: bool) -> dict[str, Any]:
    question = prepare_text(question.strip(), 1000)
    if use_ai:
        try:
            text = text_completion(
                system=prompts.ASSISTANT,
                user=f"My tax summary JSON:\n{json.dumps(_safe_summary(result))}\n\nQuestion: {question}",
            )
            if text:
                return {"source": "ai", "markdown": text}
        except AIUnavailable:
            pass
    return {
        "source": "template",
        "markdown": (
            "The AI assistant is not available right now (no OpenAI key configured or AI "
            "processing is turned off in your settings). Here's your current summary:\n\n"
            + template_tax_explanation(result)
        ),
    }


_SUGGESTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["suggestions"],
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "description", "category"],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "category": {"type": "string", "enum": [c.value for c in Category]},
                },
            },
        }
    },
}


def ai_deduction_ideas(
    business_description: str, category_totals: dict[str, float], existing_titles: list[str], use_ai: bool
) -> list[dict[str, Any]]:
    if not use_ai:
        return []
    try:
        data = structured_completion(
            system=prompts.DEDUCTION_FINDER,
            user=json.dumps(
                {
                    "business_description": prepare_text(business_description or "small business", 300),
                    "expense_totals_by_category": category_totals,
                    "existing_suggestions": existing_titles,
                }
            ),
            schema_name="deduction_ideas",
            schema=_SUGGESTION_SCHEMA,
            max_tokens=800,
        )
    except AIUnavailable:
        return []
    return [
        {**s, "id": f"ai-{i}", "status": "opportunity", "confidence": "low",
         "estimated_deduction": 0, "estimated_savings": 0, "action": "Review with your records", "source": "ai"}
        for i, s in enumerate(data.get("suggestions", [])[:5])
    ]
