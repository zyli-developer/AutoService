from __future__ import annotations

import pytest

from autoservice.canary import CanaryRouter, CanaryStage
from autoservice.canary_monitor import CanaryMonitor


class TestCanaryMonitor:
    """Tests for CanaryMonitor -- canary metric monitoring + auto-rollback."""

    # ------------------------------------------------------------------ #
    # 1. Import and instantiate
    # ------------------------------------------------------------------ #
    def test_import_and_instantiate(self):
        router = CanaryRouter()
        monitor = CanaryMonitor(router)
        assert monitor is not None

    # ------------------------------------------------------------------ #
    # 2. set_baseline stores values
    # ------------------------------------------------------------------ #
    def test_set_baseline_stores_values(self):
        router = CanaryRouter()
        monitor = CanaryMonitor(router)
        baseline = {"csat": 4.2, "complaint_rate": 0.01}
        monitor.set_baseline(baseline)
        # Verify via check -- baseline values appear in metrics detail
        result = monitor.check()
        assert result["metrics"]["csat"]["baseline"] == 4.2
        assert result["metrics"]["complaint_rate"]["baseline"] == 0.01

    # ------------------------------------------------------------------ #
    # 3. record_canary_metrics stores values
    # ------------------------------------------------------------------ #
    def test_record_canary_metrics_stores_values(self):
        router = CanaryRouter()
        monitor = CanaryMonitor(router)
        monitor.set_baseline({"csat": 4.0})
        monitor.record_canary_metrics({"csat": 3.9})
        result = monitor.check()
        assert result["metrics"]["csat"]["current"] == 3.9

    # ------------------------------------------------------------------ #
    # 4. check healthy -- all metrics within threshold
    # ------------------------------------------------------------------ #
    def test_check_healthy_all_within_threshold(self):
        router = CanaryRouter()
        monitor = CanaryMonitor(router)
        baseline = {
            "csat": 4.0,
            "resolution_rate": 0.8,
            "digest_rate": 0.9,
            "accept_wait_ms": 5000.0,
            "complaint_rate": 0.02,
        }
        canary = {
            "csat": 3.8,
            "resolution_rate": 0.75,
            "digest_rate": 0.85,
            "accept_wait_ms": 5500.0,
            "complaint_rate": 0.025,
        }
        monitor.set_baseline(baseline)
        monitor.record_canary_metrics(canary)
        result = monitor.check()
        assert result["status"] == "healthy"
        assert result["breaches"] == []
        assert result["action_taken"] == "none"

    # ------------------------------------------------------------------ #
    # 5. check degraded -- one metric breached
    # ------------------------------------------------------------------ #
    def test_check_degraded_one_breach(self):
        router = CanaryRouter()
        monitor = CanaryMonitor(router)
        monitor.set_baseline({
            "csat": 4.0,
            "complaint_rate": 0.01,
        })
        # complaint_rate 3x baseline exceeds default 2x threshold
        monitor.record_canary_metrics({
            "csat": 3.5,
            "complaint_rate": 0.03,
        })
        result = monitor.check()
        assert result["status"] == "degraded"
        assert "complaint_rate" in result["breaches"]
        assert "csat" not in result["breaches"]

    # ------------------------------------------------------------------ #
    # 6. check multiple breaches
    # ------------------------------------------------------------------ #
    def test_check_multiple_breaches(self):
        router = CanaryRouter()
        monitor = CanaryMonitor(router)
        monitor.set_baseline({
            "csat": 4.0,
            "complaint_rate": 0.01,
            "accept_wait_ms": 5000.0,
        })
        # csat drops to 1.5 (< 4.0/2 = 2.0), complaint_rate goes 5x,
        # accept_wait_ms goes 3x
        monitor.record_canary_metrics({
            "csat": 1.5,
            "complaint_rate": 0.05,
            "accept_wait_ms": 15000.0,
        })
        result = monitor.check()
        assert result["status"] == "degraded"
        assert len(result["breaches"]) == 3
        assert "csat" in result["breaches"]
        assert "complaint_rate" in result["breaches"]
        assert "accept_wait_ms" in result["breaches"]

    # ------------------------------------------------------------------ #
    # 7. auto_rollback triggers on breach
    # ------------------------------------------------------------------ #
    @pytest.mark.asyncio
    async def test_auto_rollback_triggers_on_breach(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()  # STAGE_5
        monitor = CanaryMonitor(router, auto_rollback=True)
        monitor.set_baseline({"complaint_rate": 0.01})
        monitor.record_canary_metrics({"complaint_rate": 0.05})  # 5x

        result = await monitor.monitor_and_act()

        assert result["status"] == "rolled_back"
        assert result["action_taken"] == "rollback"
        assert router.current_stage == CanaryStage.DISABLED
        # Verify rollback reason recorded
        last_hist = router.history[-1]
        assert last_hist["action"] == "rollback"
        assert "complaint_rate" in last_hist["reason"]

    # ------------------------------------------------------------------ #
    # 8. auto_rollback=False does not rollback
    # ------------------------------------------------------------------ #
    @pytest.mark.asyncio
    async def test_auto_rollback_false_no_rollback(self):
        router = CanaryRouter(observation_hours=0)
        router.advance()  # STAGE_5
        monitor = CanaryMonitor(router, auto_rollback=False)
        monitor.set_baseline({"complaint_rate": 0.01})
        monitor.record_canary_metrics({"complaint_rate": 0.05})  # 5x

        result = await monitor.monitor_and_act()

        assert result["status"] == "degraded"
        assert result["action_taken"] == "none"
        # Router is NOT rolled back
        assert router.current_stage == CanaryStage.STAGE_5

    # ------------------------------------------------------------------ #
    # 9. CSAT degradation detection (lower is worse)
    # ------------------------------------------------------------------ #
    def test_csat_degradation_detected(self):
        router = CanaryRouter()
        monitor = CanaryMonitor(router)
        monitor.set_baseline({"csat": 4.0})
        # csat drops below baseline/2 = 2.0
        monitor.record_canary_metrics({"csat": 1.8})
        result = monitor.check()
        assert result["status"] == "degraded"
        assert "csat" in result["breaches"]
        assert result["metrics"]["csat"]["ok"] is False

    # ------------------------------------------------------------------ #
    # 10. Complaint rate degradation (higher is worse)
    # ------------------------------------------------------------------ #
    def test_complaint_rate_degradation_detected(self):
        router = CanaryRouter()
        monitor = CanaryMonitor(router)
        monitor.set_baseline({"complaint_rate": 0.02})
        # complaint_rate doubles exactly -- at boundary, not breached
        monitor.record_canary_metrics({"complaint_rate": 0.04})
        result_boundary = monitor.check()
        assert "complaint_rate" not in result_boundary["breaches"]

        # Just above 2x -- breached
        monitor.record_canary_metrics({"complaint_rate": 0.041})
        result_breach = monitor.check()
        assert "complaint_rate" in result_breach["breaches"]
        assert result_breach["metrics"]["complaint_rate"]["ok"] is False

    # ------------------------------------------------------------------ #
    # 11. No baseline set -- check returns healthy
    # ------------------------------------------------------------------ #
    def test_no_baseline_returns_healthy(self):
        router = CanaryRouter()
        monitor = CanaryMonitor(router)
        # No baseline, no canary data
        result = monitor.check()
        assert result["status"] == "healthy"
        assert result["breaches"] == []

    # ------------------------------------------------------------------ #
    # 12. Custom thresholds
    # ------------------------------------------------------------------ #
    def test_custom_thresholds(self):
        router = CanaryRouter()
        # Strict threshold: 1.5x instead of 2x for complaint_rate
        monitor = CanaryMonitor(
            router, thresholds={"complaint_rate": 1.5}
        )
        monitor.set_baseline({"complaint_rate": 0.02})
        # 1.6x -- within default 2x but exceeds custom 1.5x
        monitor.record_canary_metrics({"complaint_rate": 0.032})
        result = monitor.check()
        assert "complaint_rate" in result["breaches"]

        # Under 1.5x -- not breached
        monitor.record_canary_metrics({"complaint_rate": 0.029})
        result2 = monitor.check()
        assert "complaint_rate" not in result2["breaches"]
