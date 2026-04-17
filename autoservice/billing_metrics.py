"""Three-star billing metrics.

T4A.9 产出 | 2026-04-16
Related: T1A.8 (metrics plugin), T4A.10 (billing)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class MetricSnapshot:
    """Immutable snapshot of the three billing metrics for a given period."""

    period: str  # "2026-04" format
    takeover_count: int = 0
    csat_average: float = 0.0
    csat_distribution: dict[int, int] = field(default_factory=lambda: {1: 0, 2: 0, 3: 0, 4: 0, 5: 0})
    csat_total_responses: int = 0
    escalation_count: int = 0
    escalation_resolved: int = 0
    escalation_resolution_rate: float = 0.0


class BillingMetrics:
    """Tracks the three starred billing metrics.

    Metrics:
      1. 接管次数 (Takeover Count)
      2. CSAT (Customer Satisfaction Score)
      3. 升级转结案率 (Escalation-to-Resolution Rate)
    """

    def __init__(self) -> None:
        # Per-conversation tracking
        self._takeovers: dict[str, int] = {}          # conv_id → count
        self._csat: dict[str, int] = {}               # conv_id → score (1-5)
        self._escalations: dict[str, str] = {}        # conv_id → status
        self._monthly: dict[str, MetricSnapshot] = {} # "2026-04" → snapshot

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_takeover(self, conversation_id: str, timestamp: str | None = None) -> None:
        """Record a takeover event (auto/copilot → takeover mode switch)."""
        self._takeovers[conversation_id] = self._takeovers.get(conversation_id, 0) + 1

    def record_csat(self, conversation_id: str, score: int) -> None:
        """Record a CSAT score for a conversation.

        Args:
            conversation_id: The conversation identifier.
            score: Customer satisfaction rating, must be 1-5.

        Raises:
            ValueError: If *score* is outside the 1-5 range.
        """
        if not isinstance(score, int) or score < 1 or score > 5:
            raise ValueError(f"CSAT score must be an integer between 1 and 5, got {score!r}")
        self._csat[conversation_id] = score

    def record_escalation(self, conversation_id: str) -> None:
        """Mark a conversation as escalated."""
        self._escalations[conversation_id] = "escalated"

    def record_resolution(self, conversation_id: str) -> None:
        """Mark an escalated conversation as resolved.

        If the conversation was not previously escalated this is a no-op –
        resolution without prior escalation is silently ignored.
        """
        if conversation_id in self._escalations:
            self._escalations[conversation_id] = "resolved"

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def _current_period(self) -> str:
        """Return the current year-month string."""
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m")

    def get_current_snapshot(self) -> MetricSnapshot:
        """Calculate a live snapshot from in-memory data."""
        period = self._current_period()

        # Takeover count
        takeover_count = sum(self._takeovers.values())

        # CSAT
        scores = list(self._csat.values())
        csat_total = len(scores)
        csat_avg = sum(scores) / csat_total if csat_total else 0.0
        csat_dist: dict[int, int] = {i: 0 for i in range(1, 6)}
        for s in scores:
            csat_dist[s] += 1

        # Escalation
        escalation_count = len(self._escalations)
        escalation_resolved = sum(1 for st in self._escalations.values() if st == "resolved")
        resolution_rate = (
            (escalation_resolved / escalation_count * 100) if escalation_count else 0.0
        )

        return MetricSnapshot(
            period=period,
            takeover_count=takeover_count,
            csat_average=round(csat_avg, 2),
            csat_distribution=csat_dist,
            csat_total_responses=csat_total,
            escalation_count=escalation_count,
            escalation_resolved=escalation_resolved,
            escalation_resolution_rate=round(resolution_rate, 2),
        )

    def get_monthly_snapshot(self, period: str) -> MetricSnapshot | None:
        """Return a previously frozen monthly snapshot, or ``None``."""
        return self._monthly.get(period)

    def close_month(self, period: str) -> MetricSnapshot:
        """Freeze current in-memory data into a monthly snapshot.

        The snapshot is stored internally and the live counters are reset.
        """
        snapshot = self.get_current_snapshot()
        # Override the period to the requested one (may differ from UTC now)
        snapshot = MetricSnapshot(
            period=period,
            takeover_count=snapshot.takeover_count,
            csat_average=snapshot.csat_average,
            csat_distribution=snapshot.csat_distribution,
            csat_total_responses=snapshot.csat_total_responses,
            escalation_count=snapshot.escalation_count,
            escalation_resolved=snapshot.escalation_resolved,
            escalation_resolution_rate=snapshot.escalation_resolution_rate,
        )
        self._monthly[period] = snapshot

        # Reset live counters
        self._takeovers.clear()
        self._csat.clear()
        self._escalations.clear()

        return snapshot

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_billing_json(self, period: str) -> dict:
        """Export a monthly snapshot as a plain dict for billing integration.

        If the requested *period* has not been closed yet the current live
        snapshot is used instead.
        """
        snapshot = self._monthly.get(period)
        if snapshot is None:
            snapshot = self.get_current_snapshot()
            snapshot = MetricSnapshot(
                period=period,
                takeover_count=snapshot.takeover_count,
                csat_average=snapshot.csat_average,
                csat_distribution=snapshot.csat_distribution,
                csat_total_responses=snapshot.csat_total_responses,
                escalation_count=snapshot.escalation_count,
                escalation_resolved=snapshot.escalation_resolved,
                escalation_resolution_rate=snapshot.escalation_resolution_rate,
            )

        return {
            "period": snapshot.period,
            "takeover_count": snapshot.takeover_count,
            "csat": {
                "average": snapshot.csat_average,
                "distribution": snapshot.csat_distribution,
                "total_responses": snapshot.csat_total_responses,
            },
            "escalation": {
                "count": snapshot.escalation_count,
                "resolved": snapshot.escalation_resolved,
                "resolution_rate": snapshot.escalation_resolution_rate,
            },
        }
