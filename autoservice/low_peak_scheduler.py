from __future__ import annotations

import time
from collections import deque
from typing import Callable, Any


class LowPeakScheduler:
    """Detects low-traffic periods and triggers Dream Engine replay callbacks.

    Core logic: 30-minute sliding window QPS average < 20% of 24h peak -> trigger callback.
    """

    _SECONDS_IN_24H = 86400

    def __init__(
        self,
        threshold: float = 0.2,
        window_minutes: int = 30,
        min_samples: int = 3,
    ):
        self.threshold = threshold
        self.window_minutes = window_minutes
        self.min_samples = min_samples

        # (timestamp, qps) samples within the sliding window
        self._samples: deque[tuple[float, float]] = deque()
        # (timestamp, window_avg) for peak tracking over 24h
        self._peak_history: deque[tuple[float, float]] = deque()
        self._callbacks: list[Callable[[], Any]] = []
        self._triggered: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_sample(self, qps: float, timestamp: float | None = None) -> None:
        """Record a QPS measurement. Auto-prunes old samples."""
        ts = timestamp if timestamp is not None else time.time()
        self._samples.append((ts, qps))
        self._prune_samples(ts)

        # Record current window average for peak tracking
        avg = self.current_avg()
        self._peak_history.append((ts, avg))
        self._prune_peak_history(ts)

    def current_avg(self) -> float:
        """Average QPS over the sliding window. Returns 0.0 if no samples."""
        if not self._samples:
            return 0.0
        total = sum(qps for _, qps in self._samples)
        return total / len(self._samples)

    @property
    def peak_qps(self) -> float:
        """Highest window-average seen in last 24h."""
        if not self._peak_history:
            return 0.0
        return max(avg for _, avg in self._peak_history)

    def is_low_peak(self) -> bool:
        """True if current avg < threshold * peak AND enough samples (not cold start)."""
        if len(self._samples) < self.min_samples:
            return False
        peak = self.peak_qps
        if peak == 0.0:
            return True
        return self.current_avg() < self.threshold * peak

    def on_low_peak(self, callback: Callable[[], Any]) -> None:
        """Register an async callback to invoke when low peak detected."""
        self._callbacks.append(callback)

    async def check_and_trigger(self) -> None:
        """Check if low peak, trigger callbacks if yes (with dedup).

        Resets _triggered when traffic recovers above threshold.
        """
        if self.is_low_peak():
            if not self._triggered:
                self._triggered = True
                for cb in self._callbacks:
                    await cb()
        else:
            # Traffic recovered — reset so next low-peak period fires again
            self._triggered = False

    def record_from_metrics(self, metrics_plugin: Any) -> None:
        """Convenience: read messages_sent from MetricsPlugin and record as QPS sample."""
        qps = float(getattr(metrics_plugin, "messages_sent", 0))
        self.record_sample(qps)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prune_samples(self, now: float) -> None:
        """Remove samples older than window_minutes."""
        cutoff = now - self.window_minutes * 60
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def _prune_peak_history(self, now: float) -> None:
        """Remove peak history entries older than 24h."""
        cutoff = now - self._SECONDS_IN_24H
        while self._peak_history and self._peak_history[0][0] < cutoff:
            self._peak_history.popleft()
