from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping

from pydantic import BaseModel, Field, field_validator

from verideploy.llm.contracts import AIUsage

_MICRO = Decimal("0.000001")
_MILLION = Decimal("1000000")


class ModelPrice(BaseModel):
    input_per_million_usd: Decimal = Field(ge=0)
    cached_input_per_million_usd: Decimal | None = Field(default=None, ge=0)
    output_per_million_usd: Decimal = Field(ge=0)


class PricingCatalog(BaseModel):
    catalog_version: str = Field(min_length=1, max_length=64)
    effective_at: datetime
    source: str = Field(min_length=1, max_length=512)
    models: dict[str, ModelPrice]

    @field_validator("effective_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("effective_at must include timezone")
        return value.astimezone(UTC)


@dataclass(frozen=True)
class CostEstimate:
    model: str
    estimated_input_tokens: int
    max_output_tokens: int
    estimated_cost_usd: Decimal
    priced: bool


@dataclass(frozen=True)
class CostActual:
    model: str
    input_tokens: int | None
    output_tokens: int | None
    actual_cost_usd: Decimal | None
    priced: bool


class CostCalculator:
    def __init__(self, catalog: PricingCatalog | None) -> None:
        self._catalog = catalog

    @property
    def catalog(self) -> PricingCatalog | None:
        return self._catalog

    def estimate(self, *, model: str, input_text: str, max_output_tokens: int) -> CostEstimate:
        # Conservative deterministic approximation used only for admission reservation.
        # Actual settlement uses provider-reported token usage.
        estimated_input_tokens = max(1, (len(input_text) + 3) // 4)
        price = self._price(model)
        if price is None:
            return CostEstimate(model, estimated_input_tokens, max_output_tokens, Decimal("0"), False)
        amount = (
            Decimal(estimated_input_tokens) * price.input_per_million_usd
            + Decimal(max_output_tokens) * price.output_per_million_usd
        ) / _MILLION
        return CostEstimate(model, estimated_input_tokens, max_output_tokens, self._money(amount), True)

    def actual(self, *, model: str, usage: AIUsage) -> CostActual:
        price = self._price(model)
        if price is None or usage.input_tokens is None or usage.output_tokens is None:
            return CostActual(model, usage.input_tokens, usage.output_tokens, None, False)
        amount = (
            Decimal(usage.input_tokens) * price.input_per_million_usd
            + Decimal(usage.output_tokens) * price.output_per_million_usd
        ) / _MILLION
        return CostActual(model, usage.input_tokens, usage.output_tokens, self._money(amount), True)

    def _price(self, model: str) -> ModelPrice | None:
        if self._catalog is None:
            return None
        return self._catalog.models.get(model)

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return value.quantize(_MICRO, rounding=ROUND_HALF_UP)
