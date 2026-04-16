"""CanaryMonitor -- monitors 5 key metrics during canary rollout.

T4A.7 | 2026-04-16
Tracks baseline vs canary-period metrics and auto-rolls back via
CanaryRouter when any metric degrades beyond a configurable threshold.

The 5 metrics (from PRD):
  1. csat            -- CSAT score (avg), higher is better
  2. resolution_rate -- Escalation-to-resolution rate, higher is better
  3. digest_rate     -- Conversation digest rate, higher is better
  4. accept_wait_ms  -- P95 accept wait time, lower is better
  5. complaint_rate  -- Complaints / total conversations, lower is better
"""

from __future__ import annotations

from autoservice.canary import CanaryRouter

# Metrics where a higher value is better (breach when current drops)
_HIGHER_IS_BETTER = {"csat", "resolution_rate", "digest_rate"}

# Metrics where a lower value is better (breach when current rises)
_LOWER_IS_BETTER = {"accept_wait_ms", "complaint_rate"}

_ALL_METRICS = _HIGHER_IS_BETTER | _LOWER_IS_BETTER

_DEFAULT_THRESHOLD = 2.0


class CanaryMonitor:
    """Monitors canary rollout metrics and triggers auto-rollback on breach.

    Parameters
    ----------
    canary_router : CanaryRouter
        The router controlling canary stage progression / rollback.
    thresholds : dict[str, float] | None
        Per-metric max degradation ratio.  Default ``2.0`` for every metric.
    auto_rollback : bool
        If True, ``monitor_and_act`` will call ``canary_router.rollback``
        when any metric breaches its threshold.
    """

    def __init__(
        self,
        canary_router: CanaryRouter,
        *,
        thresholds: dict[str, float] | None = None,
        auto_rollback: bool = True,
    ) -> None:
        self._router = canary_router
        self._thresholds: dict[str, float] = {
            m: _DEFAULT_THRESHOLD for m in _ALL_METRICS
        }
        if thresholds:
            self._thresholds.update(thresholds)
        self._auto_rollback = auto_rollback
        self._baseline: dict[str, float] = {}
        self._canary: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Data recording
    # ------------------------------------------------------------------

    def set_baseline(self, metrics: dict[str, float]) -> None:
        """Record baseline metrics captured before canary starts."""
        self._baseline = dict(metrics)

    def record_canary_metrics(self, metrics: dict[str, float]) -> None:
        """Record current canary-period metrics."""
        self._canary = dict(metrics)

    # ------------------------------------------------------------------
    # Check logic
    # ------------------------------------------------------------------

    def check(self) -> dict:
        """Compare canary vs baseline for each metric.

        Returns a dict with keys:
            status       -- ``"healthy"`` | ``"degraded"`` | ``"rolled_back"``
            metrics      -- per-metric detail (baseline, current, ratio, ok)
            breaches     -- list of metric names exceeding threshold
            action_taken -- ``"none"`` | ``"rollback"``
        """
        breaches: list[str] = []
        metric_details: dict[str, dict] = {}

        for name in _ALL_METRICS:
            baseline_val = self._baseline.get(name)
            current_val = self._canary.get(name)

            # If either value is missing, we cannot compare -- assume OK
            if baseline_val is None or current_val is None:
                metric_details[name] = {
                    "baseline": baseline_val,
                    "current": current_val,
                    "ratio": None,
                    "ok": True,
                }
                continue

            # Compute directional ratio and check breach
            ok = True
            if name in _HIGHER_IS_BETTER:
                # breach if current < baseline / threshold
                if baseline_val == 0:
                    ratio = 1.0 if current_val == 0 else current_val
                else:
                    ratio = current_val / baseline_val
                threshold = self._thresholds.get(name, _DEFAULT_THRESHOLD)
                if current_val < baseline_val / threshold:
                    ok = False
            else:
                # lower-is-better: breach if current > baseline * threshold
                if baseline_val == 0:
                    ratio = 1.0 if current_val == 0 else float("inf")
                else:
                    ratio = current_val / baseline_val
                threshold = self._thresholds.get(name, _DEFAULT_THRESHOLD)
                if current_val > baseline_val * threshold:
                    ok = False

            if not ok:
                breaches.append(name)

            metric_details[name] = {
                "baseline": baseline_val,
                "current": current_val,
                "ratio": ratio,
                "ok": ok,
            }

        status = "degraded" if breaches else "healthy"

        return {
            "status": status,
            "metrics": metric_details,
            "breaches": sorted(breaches),
            "action_taken": "none",
        }

    # ------------------------------------------------------------------
    # Monitor + act
    # ------------------------------------------------------------------

    async def monitor_and_act(self) -> dict:
        """Run ``check`` and, if breached and ``auto_rollback`` is enabled,
        call ``canary_router.rollback``.

        Returns the check result dict with ``status`` and ``action_taken``
        updated if a rollback occurred.
        """
        result = self.check()

        if result["breaches"] and self._auto_rollback:
            reason = (
                f"Canary metric breach: {', '.join(result['breaches'])}"
            )
            self._router.rollback(reason=reason)
            result["status"] = "rolled_back"
            result["action_taken"] = "rollback"

        return result
