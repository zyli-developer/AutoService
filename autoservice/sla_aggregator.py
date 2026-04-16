"""SLAAggregator — ring-buffer SLA metrics with P50/P95 percentiles.

T2A.3 产出 | 2026-04-16
关联: PRD δ5 / US-3.3 / EventBus (T1A.3) / alerts.yaml (T2A.4)

Tracks SLA metrics across 3 time windows (5m / 1h / 24h) using ring buffers.
Subscribes to EventBus events and computes:
- first_reply_ms — time from conversation.created to first agent message
- accept_ms — time from conversation.created to operator accept (copilot/takeover)
- csat_score — customer satisfaction score (1-5)
- resolution_rate — conversations resolved vs total closed

Provides P50/P95 percentiles per window for dashboard and alerting.
"""

from __future__ import annotations

import time
import bisect
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence


class MetricType(str, Enum):
    FIRST_REPLY_MS = "first_reply_ms"
    ACCEPT_MS = "accept_ms"
    CSAT_SCORE = "csat_score"
    RESOLUTION_RATE = "resolution_rate"


class WindowSize(str, Enum):
    FIVE_MIN = "5m"
    ONE_HOUR = "1h"
    TWENTY_FOUR_HOUR = "24h"


WINDOW_SECONDS = {
    WindowSize.FIVE_MIN: 300,
    WindowSize.ONE_HOUR: 3600,
    WindowSize.TWENTY_FOUR_HOUR: 86400,
}


@dataclass
class MetricPoint:
    """A single metric data point."""
    timestamp: float       # time.time()
    value: float


@dataclass
class PercentileResult:
    """P50/P95 result for a metric in a time window."""
    metric: MetricType
    window: WindowSize
    p50: Optional[float] = None
    p95: Optional[float] = None
    count: int = 0
    min_val: Optional[float] = None
    max_val: Optional[float] = None


# ---------------------------------------------------------------------------
# RingBuffer — time-windowed metric storage
# ---------------------------------------------------------------------------

class RingBuffer:
    """Time-windowed ring buffer for metric points.

    Automatically evicts points older than the window size.
    Max capacity prevents unbounded memory growth.
    """

    def __init__(self, window_seconds: int, max_capacity: int = 10000):
        self._window_seconds = window_seconds
        self._max_capacity = max_capacity
        self._points: deque[MetricPoint] = deque(maxlen=max_capacity)

    def add(self, value: float, timestamp: Optional[float] = None) -> None:
        ts = timestamp or time.time()
        self._points.append(MetricPoint(timestamp=ts, value=value))

    def _evict_old(self, now: Optional[float] = None) -> None:
        cutoff = (now or time.time()) - self._window_seconds
        while self._points and self._points[0].timestamp < cutoff:
            self._points.popleft()

    def values(self, now: Optional[float] = None) -> list[float]:
        self._evict_old(now)
        return [p.value for p in self._points]

    @property
    def count(self) -> int:
        self._evict_old()
        return len(self._points)


# ---------------------------------------------------------------------------
# Percentile calculation
# ---------------------------------------------------------------------------

def percentile(sorted_values: Sequence[float], pct: float) -> Optional[float]:
    """Calculate percentile from sorted values. pct in [0, 100]."""
    if not sorted_values:
        return None
    n = len(sorted_values)
    k = (pct / 100.0) * (n - 1)
    f = int(k)
    c = f + 1 if f + 1 < n else f
    d = k - f
    return sorted_values[f] + d * (sorted_values[c] - sorted_values[f])


# ---------------------------------------------------------------------------
# SLAAggregator
# ---------------------------------------------------------------------------

class SLAAggregator:
    """Aggregates SLA metrics across 3 time windows with P50/P95.

    Usage:
        agg = SLAAggregator()
        agg.record(MetricType.FIRST_REPLY_MS, 1200.0)
        result = agg.get_percentiles(MetricType.FIRST_REPLY_MS, WindowSize.FIVE_MIN)
        # result.p50, result.p95
    """

    def __init__(self):
        self._buffers: dict[tuple[MetricType, WindowSize], RingBuffer] = {}
        for metric in MetricType:
            for window in WindowSize:
                self._buffers[(metric, window)] = RingBuffer(
                    window_seconds=WINDOW_SECONDS[window],
                )

    def record(self, metric: MetricType, value: float, timestamp: Optional[float] = None) -> None:
        """Record a metric value into all 3 time windows."""
        ts = timestamp or time.time()
        for window in WindowSize:
            self._buffers[(metric, window)].add(value, ts)

    def get_percentiles(self, metric: MetricType, window: WindowSize) -> PercentileResult:
        """Get P50/P95 for a metric in a specific window."""
        buf = self._buffers[(metric, window)]
        vals = sorted(buf.values())
        return PercentileResult(
            metric=metric,
            window=window,
            p50=percentile(vals, 50),
            p95=percentile(vals, 95),
            count=len(vals),
            min_val=vals[0] if vals else None,
            max_val=vals[-1] if vals else None,
        )

    def get_all_percentiles(self, window: WindowSize) -> dict[MetricType, PercentileResult]:
        """Get P50/P95 for all metrics in a specific window."""
        return {metric: self.get_percentiles(metric, window) for metric in MetricType}

    def get_snapshot(self) -> dict[str, dict[str, PercentileResult]]:
        """Full snapshot: all metrics × all windows."""
        return {
            window.value: self.get_all_percentiles(window)
            for window in WindowSize
        }

    # ------------------------------------------------------------------
    # EventBus integration helpers
    # ------------------------------------------------------------------

    def on_first_reply(self, conversation_id: str, latency_ms: float) -> None:
        """Called when agent sends first reply to a conversation."""
        self.record(MetricType.FIRST_REPLY_MS, latency_ms)

    def on_operator_accept(self, conversation_id: str, latency_ms: float) -> None:
        """Called when operator accepts (joins copilot/takeover)."""
        self.record(MetricType.ACCEPT_MS, latency_ms)

    def on_csat_response(self, conversation_id: str, score: float) -> None:
        """Called when customer submits CSAT score (1-5)."""
        self.record(MetricType.CSAT_SCORE, score)

    def on_conversation_resolved(self, conversation_id: str, was_escalated: bool) -> None:
        """Called when conversation closes. Records resolution rate (1.0 or 0.0)."""
        self.record(MetricType.RESOLUTION_RATE, 0.0 if was_escalated else 1.0)
