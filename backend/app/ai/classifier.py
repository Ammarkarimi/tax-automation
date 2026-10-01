"""Income/expense classification: keyword rules first, OpenAI for the rest.

Pipeline for a batch of transactions:
  1. Deterministic rules handle the obvious cases (IRS payments, Stripe fees...)
     with high confidence and zero cost.
  2. Remaining items go to OpenAI in chunks (if enabled + user consented), with
     PII-redacted descriptions and strict JSON-schema output.
  3. Anything still uncertain is flagged `needs_review` for the user.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal

from app.ai import prompts
from app.ai.client import AIUnavailable, prepare_text, structured_completion
from app.models.enums import Category, ClassifiedBy, Direction

log = logging.getLogger(__name__)

REVIEW_THRESHOLD = 0.70
BATCH_SIZE = 40


@dataclass
class TxnIn:
    ref: int  # caller-side index
    description: str
    amount: Decimal  # positive
    direction: Direction
    date: str = ""


@dataclass
class Classification:
    ref: int
    category: Category
    direction: Direction
    business_use_pct: int
    confidence: float
    classified_by: ClassifiedBy
    rationale: str
    merchant: str | None = None

    @property
    def needs_review(self) -> bool:
        return self.confidence < REVIEW_THRESHOLD or self.category == Category.UNCATEGORIZED


# (pattern, category, forced direction or None, business_use_pct, confidence)
_RULES: list[tuple[str, Category, Direction | None, int, float]] = [
    (r"\b(irs|usataxpymt|eftps)\b", Category.ESTIMATED_TAX_PAYMENT, Direction.EXPENSE, 100, 0.95),
    (r"\b(stripe|square|paypal|shopify|etsy)\b.*\bfees?\b", Category.COMMISSIONS_FEES, Direction.EXPENSE, 100, 0.93),
    (r"\b(credit card payment|card payment|autopay|online transfer|transfer to|transfer from|xfer)\b", Category.TRANSFER, None, 0, 0.85),
    (r"\b(loan proceeds|sba loan)\b", Category.LOAN, None, 0, 0.85),
    (r"\b(monthly service fee|overdraft|wire fee|maintenance fee)\b", Category.BANK_FEES, Direction.EXPENSE, 100, 0.9),
    (r"\b(interest paid|interest earned|int earned)\b", Category.INTEREST_INCOME, Direction.INCOME, 100, 0.85),
    (r"\b(google ads|facebook ads|fb ads|meta ads|meta platforms|yelp ads|linkedin ads|vistaprint)\b", Category.ADVERTISING, Direction.EXPENSE, 100, 0.9),
    (r"\b(adobe|microsoft|github|aws|amazon web services|google workspace|gsuite|dropbox|notion|slack|zoom|canva|openai|quickbooks|xero|shopify subscription)\b", Category.SOFTWARE, Direction.EXPENSE, 100, 0.85),
    (r"\b(turbotax|h&r block|cpa|attorney|law office|legal ?zoom|bookkeep)\b", Category.LEGAL_PROFESSIONAL, Direction.EXPENSE, 100, 0.85),
    (r"\b(shell|chevron|exxon|mobil|bp|texaco|arco|valero|sunoco|citgo|speedway|parking|toll|ez-?pass|fastrak)\b", Category.CAR_TRUCK, Direction.EXPENSE, 100, 0.75),
    (r"\b(delta|united airlines|american airlines|southwest|jetblue|alaska air|marriott|hilton|hyatt|airbnb|expedia|amtrak)\b", Category.TRAVEL, Direction.EXPENSE, 100, 0.75),
    (r"\b(starbucks|restaurant|cafe|coffee|grill|pizza|bistro|doordash|grubhub|uber eats|chipotle|mcdonald)\b", Category.MEALS, Direction.EXPENSE, 100, 0.6),
    (r"\b(staples|office depot|officemax|usps|ups store|fedex|postage)\b", Category.OFFICE_EXPENSE, Direction.EXPENSE, 100, 0.8),
    (r"\b(verizon|at&t|att\b|t-mobile|tmobile|comcast|xfinity|spectrum|pg&e|con ?ed|electric|water bill|utility)\b", Category.UTILITIES, Direction.EXPENSE, 50, 0.7),
    (r"\b(rent|lease)\b", Category.RENT_PROPERTY, Direction.EXPENSE, 100, 0.65),
    (r"\b(blue cross|bcbs|aetna|kaiser|cigna|humana|united ?healthcare|healthcare\.gov|covered california)\b", Category.HEALTH_INSURANCE, Direction.EXPENSE, 100, 0.85),
    (r"\b(insurance|geico|progressive|state farm|allstate|next insurance|hiscox)\b", Category.INSURANCE, Direction.EXPENSE, 100, 0.65),
    (r"\b(sam'?s club|costco business|restaurant depot|wholesale|distributor|supplier|mckesson|sysco|faire)\b", Category.INVENTORY_PURCHASES, Direction.EXPENSE, 100, 0.7),
    (r"\b(home depot|lowe'?s|hardware|repair)\b", Category.REPAIRS, Direction.EXPENSE, 100, 0.55),
    (r"\b(udemy|coursera|skillshare|masterclass|seminar|workshop)\b", Category.EDUCATION, Direction.EXPENSE, 100, 0.75),
    (r"\b(upwork|fiverr|freelancer\.com)\b.*\b(fee|service)\b", Category.COMMISSIONS_FEES, Direction.EXPENSE, 100, 0.85),
    (r"\b(gusto|adp|paychex)\b", Category.WAGES, Direction.EXPENSE, 100, 0.7),
    (r"\b(sep ?ira|solo ?401k|retirement contribution)\b", Category.RETIREMENT_CONTRIBUTION, Direction.EXPENSE, 100, 0.85),
    (r"\b(netflix|spotify|hulu|disney\+|apple music|gym|planet fitness|grocery|safeway|kroger|whole foods|trader joe)\b", Category.PERSONAL, Direction.EXPENSE, 0, 0.75),
    (r"\b(business license|permit|sales tax|franchise tax|cdtfa|department of revenue)\b", Category.TAXES_LICENSES, Direction.EXPENSE, 100, 0.85),
    (r"\b(refund to customer|customer refund|chargeback)\b", Category.RETURNS_ALLOWANCES, Direction.EXPENSE, 100, 0.8),
]

_INCOME_RULES: list[tuple[str, Category, float]] = [
    (r"\b(stripe|square|paypal|shopify|etsy|amazon payments|venmo business|clover|toast)\b", Category.BUSINESS_INCOME, 0.9),
    (r"\b(uber|lyft|doordash|instacart|grubhub|postmates|upwork|fiverr|taskrabbit|rover)\b", Category.BUSINESS_INCOME, 0.9),
    (r"\b(invoice|client payment|payment from|zelle from|ach credit|mobile deposit|cash deposit|pos deposit)\b", Category.BUSINESS_INCOME, 0.7),
    (r"\b(interest)\b", Category.INTEREST_INCOME, 0.85),
    (r"\b(transfer from|online transfer)\b", Category.TRANSFER, 0.85),
]

_COMPILED = [(re.compile(p, re.I), c, d, b, conf) for p, c, d, b, conf in _RULES]
_COMPILED_INCOME = [(re.compile(p, re.I), c, conf) for p, c, conf in _INCOME_RULES]


def classify_by_rules(t: TxnIn) -> Classification:
    desc = t.description or ""
    if t.direction == Direction.INCOME:
        for pattern, cat, conf in _COMPILED_INCOME:
            if pattern.search(desc):
                return Classification(t.ref, cat, Direction.INCOME, 100 if cat == Category.BUSINESS_INCOME else 0,
                                      conf, ClassifiedBy.RULES, f"Matched rule: {pattern.pattern[:40]}")
        return Classification(t.ref, Category.BUSINESS_INCOME, Direction.INCOME, 100, 0.5,
                              ClassifiedBy.RULES, "Deposit assumed to be business income — please confirm")
    for pattern, cat, forced_dir, bpct, conf in _COMPILED:
        if pattern.search(desc):
            return Classification(t.ref, cat, forced_dir or t.direction, bpct, conf,
                                  ClassifiedBy.RULES, f"Matched rule: {pattern.pattern[:40]}")
    return Classification(t.ref, Category.UNCATEGORIZED, t.direction, 100, 0.0,
                          ClassifiedBy.RULES, "No rule matched")


_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ref", "category", "direction", "business_use_pct", "confidence", "merchant", "rationale"],
    "properties": {
        "ref": {"type": "integer"},
        "category": {"type": "string", "enum": [c.value for c in Category]},
        "direction": {"type": "string", "enum": [d.value for d in Direction]},
        "business_use_pct": {"type": "integer", "minimum": 0, "maximum": 100},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "merchant": {"type": ["string", "null"]},
        "rationale": {"type": "string"},
    },
}
_BATCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {"items": {"type": "array", "items": _ITEM_SCHEMA}},
}


def classify_with_ai(items: list[TxnIn], business_context: str) -> dict[int, Classification]:
    """Classify via OpenAI. Raises AIUnavailable on any failure."""
    results: dict[int, Classification] = {}
    for start in range(0, len(items), BATCH_SIZE):
        chunk = items[start : start + BATCH_SIZE]
        lines = [
            f"{t.ref} | {t.date} | {t.direction.value} | ${t.amount:.2f} | {prepare_text(t.description, 200)}"
            for t in chunk
        ]
        user = (
            f"Business: {prepare_text(business_context, 300) or 'not specified'}\n\n"
            "Transactions (ref | date | direction | amount | description):\n" + "\n".join(lines)
        )
        data = structured_completion(
            system=prompts.TRANSACTION_CLASSIFIER,
            user=user,
            schema_name="transaction_classification",
            schema=_BATCH_SCHEMA,
            max_tokens=120 * len(chunk) + 200,
        )
        valid_refs = {t.ref for t in chunk}
        for item in data.get("items", []):
            if item["ref"] not in valid_refs:
                continue  # ignore hallucinated refs
            results[item["ref"]] = Classification(
                ref=item["ref"],
                category=Category(item["category"]),
                direction=Direction(item["direction"]),
                business_use_pct=max(0, min(100, int(item["business_use_pct"]))),
                confidence=float(item["confidence"]),
                classified_by=ClassifiedBy.AI,
                rationale=item["rationale"][:480],
                merchant=(item.get("merchant") or None),
            )
    return results


def classify_transactions(
    items: list[TxnIn], business_context: str = "", use_ai: bool = False
) -> list[Classification]:
    """Classify a batch. Rules first; AI for low-confidence leftovers; never raises."""
    by_rules = {t.ref: classify_by_rules(t) for t in items}
    pending = [t for t in items if by_rules[t.ref].confidence < 0.8]
    final = dict(by_rules)
    if use_ai and pending:
        try:
            ai = classify_with_ai(pending, business_context)
            for ref, cls in ai.items():
                # Keep the rule result if AI is less sure than the rule.
                if cls.confidence >= final[ref].confidence:
                    final[ref] = cls
        except AIUnavailable as exc:
            log.info("AI classification unavailable, using rules only: %s", exc)
    return [final[t.ref] for t in items]
