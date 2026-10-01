"""Inputs shared by the deduction finder and the audit-risk scorer."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.tax.engine import TaxInput


@dataclass
class AnalysisContext:
    inp: TaxInput
    result: dict[str, Any]  # output of compute_tax(inp)
    category_totals: dict[str, Decimal] = field(default_factory=dict)
    category_counts: dict[str, int] = field(default_factory=dict)
    total_transactions: int = 0
    needs_review_count: int = 0
    round_number_expense_ratio: float = 0.0  # share of expenses that are whole $100s
    car_expense_full_business_use: bool = False
    reported_1099_income: Decimal = Decimal("0")  # NEC + MISC + K totals from forms
    form_1099k_gross: Decimal = Decimal("0")
    is_cash_intensive: bool = False
    has_documents: bool = False

    @property
    def summary(self) -> dict[str, Any]:
        return self.result["summary"]

    def cat(self, name: str) -> Decimal:
        return self.category_totals.get(name, Decimal("0"))
