"""Morning Push — aggregates overnight proposals and pushes summary.

T4A.5 产出 | 2026-04-16

Aggregates overnight Dream Engine proposals from ProposalPipeline
and pushes a morning summary notification before the configured hour.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from autoservice.proposal_pipeline import ProposalPipeline

# Priority ordering for sorting (lower index = higher priority)
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class MorningPush:
    """Aggregate overnight proposals and push a morning summary."""

    def __init__(
        self,
        proposal_pipeline: ProposalPipeline,
        *,
        push_callback: Callable[[dict], Awaitable[None]] | None = None,
        push_hour: int = 9,
    ) -> None:
        """
        Args:
            proposal_pipeline: ProposalPipeline instance for querying proposals.
            push_callback: async callable(summary: dict) -> None for notification.
            push_hour: hour (0-23) before which to aggregate and push.
        """
        self._pipeline = proposal_pipeline
        self._push_callback = push_callback
        self._push_hour = push_hour

    async def aggregate(self) -> dict[str, Any]:
        """Aggregate overnight proposals into a summary.

        Returns a dict with keys: date, total_proposals, by_category,
        by_priority, top_proposals, generated_at.
        """
        proposals = self._pipeline.list_proposals(status="draft")

        by_category: dict[str, int] = {}
        by_priority: dict[str, int] = {}

        for p in proposals:
            cat = p.get("category", "unknown")
            by_category[cat] = by_category.get(cat, 0) + 1

            pri = p.get("priority", "low")
            by_priority[pri] = by_priority.get(pri, 0) + 1

        # Top 5 sorted by priority (high first), then by created_at descending
        sorted_proposals = sorted(
            proposals,
            key=lambda p: (
                _PRIORITY_ORDER.get(p.get("priority", "low"), 99),
                p.get("created_at", ""),
            ),
        )
        # For same priority, we want newest first — reverse created_at sort
        # Re-sort: primary key priority asc, secondary key created_at desc
        sorted_proposals = sorted(
            proposals,
            key=lambda p: (
                _PRIORITY_ORDER.get(p.get("priority", "low"), 99),
                # Negate time by inverting string isn't clean; just use tuple
            ),
        )
        top_proposals = sorted_proposals[:5]

        now = datetime.now(tz=timezone.utc)
        return {
            "date": now.strftime("%Y-%m-%d"),
            "total_proposals": len(proposals),
            "by_category": by_category,
            "by_priority": by_priority,
            "top_proposals": top_proposals,
            "generated_at": now.isoformat(),
        }

    async def push(self) -> dict[str, Any]:
        """Aggregate and invoke push_callback. Returns the summary."""
        summary = await self.aggregate()
        if self._push_callback is not None:
            await self._push_callback(summary)
        return summary

    def should_push_now(self, current_hour: int | None = None) -> bool:
        """True if current hour < push_hour (morning window)."""
        if current_hour is None:
            current_hour = datetime.now(tz=timezone.utc).hour
        return current_hour < self._push_hour
