"""Tiered billing calculator.

T4A.10 产出 | 2026-04-16
Related: T4A.9 (billing_metrics)
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol, runtime_checkable

from autoservice.billing_metrics import BillingMetrics

DEFAULT_TIERS: list[dict] = [
    {"name": "free", "max_conversations": 100, "price_per_conv": 0},
    {"name": "starter", "max_conversations": 1000, "price_per_conv": 0.5},
    {"name": "pro", "max_conversations": 10000, "price_per_conv": 0.3},
    {"name": "enterprise", "max_conversations": float("inf"), "price_per_conv": 0.15},
]


class BillingConfigError(Exception):
    """Raised when tier configuration is invalid."""


def validate_tiers(tiers: list[dict]) -> None:
    """Validate tier configuration for completeness and consistency.

    Raises :class:`BillingConfigError` on empty list, gaps, or overlaps.
    """
    if not tiers:
        raise BillingConfigError("Tier configuration is empty")

    prev_max = 0
    for i, tier in enumerate(tiers):
        cap = tier.get("max_conversations", 0)
        if i > 0 and cap != float("inf"):
            prev = tiers[i - 1]["max_conversations"]
            if prev < prev_max:
                raise BillingConfigError(
                    f"Gap detected between tier {i - 1} (max={prev}) "
                    f"and tier {i}: expected contiguous ranges"
                )
        prev_max = cap


@runtime_checkable
class BillingStrategy(Protocol):
    """Protocol for pluggable billing strategies.

    Default implementation: :class:`TieredBilling`.
    Future: SubscriptionStrategy (base + overage).
    """

    def calculate(self, conversation_count: int) -> dict:
        """Calculate bill for a given count, returning total + breakdown."""
        ...


class TieredBilling:
    """Calculate bills using a tiered pricing model.

    Each tier defines:
      - ``name``: human-readable tier label
      - ``max_conversations``: upper bound (cumulative) for this tier
      - ``price_per_conv``: per-conversation rate within the tier

    Conversations are filled into tiers in order.  The first *N₁*
    conversations use tier-1 pricing, the next *N₂ − N₁* use tier-2,
    and so on.
    """

    def __init__(self, tiers: list[dict] | None = None, *, validate: bool = True) -> None:
        self.tiers = tiers if tiers is not None else list(DEFAULT_TIERS)
        if validate:
            validate_tiers(self.tiers)

    def calculate(self, conversation_count: int) -> dict:
        """Calculate the bill for a given conversation count.

        Returns::

            {
                "total": float,
                "breakdown": [
                    {"tier": "free", "count": 100, "rate": 0, "subtotal": 0},
                    ...
                ],
                "conversation_count": int,
            }
        """
        remaining = conversation_count
        breakdown: list[dict] = []
        total = Decimal("0")
        prev_max = 0

        for tier in self.tiers:
            if remaining <= 0:
                break
            cap = tier["max_conversations"]
            tier_capacity = (cap - prev_max) if not math.isinf(cap) else remaining
            count_in_tier = min(remaining, int(tier_capacity))
            unit = Decimal(str(tier["price_per_conv"]))
            subtotal = unit * count_in_tier
            breakdown.append(
                {
                    "tier": tier["name"],
                    "count": count_in_tier,
                    "rate": tier["price_per_conv"],
                    "subtotal": float(subtotal.quantize(Decimal("0.01"), ROUND_HALF_UP)),
                }
            )
            total += subtotal
            remaining -= count_in_tier
            prev_max = int(cap) if not math.isinf(cap) else prev_max

        return {
            "total": float(total.quantize(Decimal("0.01"), ROUND_HALF_UP)),
            "breakdown": breakdown,
            "conversation_count": conversation_count,
        }

    def generate_invoice(self, conversation_count: int, period: str) -> dict:
        """Generate a monthly invoice dict.

        Returns::

            {
                "id": "inv_<uuid>",
                "period": "2026-04",
                "generated_at": "<iso>",
                "conversation_count": N,
                "total": float,
                "breakdown": [...],
                "currency": "USD",
            }
        """
        calc = self.calculate(conversation_count)
        return {
            "id": f"inv_{uuid.uuid4().hex[:12]}",
            "period": period,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "conversation_count": conversation_count,
            "total": calc["total"],
            "breakdown": calc["breakdown"],
            "currency": "USD",
        }

    def generate_bill(self, metrics: BillingMetrics, period: str) -> dict:
        """Generate a full bill from BillingMetrics for a given period.

        Integrates with :class:`BillingMetrics` to pull takeover_count
        and embed the full metrics snapshot in the bill.

        Returns a dict with ``status`` field:
          - ``"final"`` — month has been closed
          - ``"provisional"`` — live data, month not yet closed
          - ``"zero_usage"`` — no takeovers recorded
        """
        snapshot = metrics.get_monthly_snapshot(period)
        if snapshot is not None:
            status_base = "final"
            takeover_count = snapshot.takeover_count
            metrics_snapshot = metrics.to_billing_json(period)
        else:
            status_base = "provisional"
            live = metrics.get_current_snapshot()
            takeover_count = live.takeover_count
            metrics_snapshot = metrics.to_billing_json(period)

        calc = self.calculate(takeover_count)

        status = "zero_usage" if takeover_count == 0 else status_base

        return {
            "id": f"bill_{uuid.uuid4().hex[:12]}",
            "period": period,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "conversation_count": takeover_count,
            "total": calc["total"],
            "breakdown": calc["breakdown"],
            "metrics_snapshot": metrics_snapshot,
            "currency": "USD",
        }

    @staticmethod
    def to_json(bill: dict) -> str:
        """Serialize a bill dict to a JSON string.

        Handles Decimal and float values for safe serialization.
        """
        return json.dumps(bill, ensure_ascii=False, default=str)
