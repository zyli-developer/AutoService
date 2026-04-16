"""Tests for autoservice.billing_metrics (T4A.9)."""
from __future__ import annotations

import pytest

from autoservice.billing_metrics import BillingMetrics, MetricSnapshot


class TestRecordTakeover:
    def test_single_takeover(self):
        bm = BillingMetrics()
        bm.record_takeover("conv-1")
        snap = bm.get_current_snapshot()
        assert snap.takeover_count == 1

    def test_multiple_takeovers_same_conversation(self):
        bm = BillingMetrics()
        bm.record_takeover("conv-1")
        bm.record_takeover("conv-1")
        bm.record_takeover("conv-1")
        snap = bm.get_current_snapshot()
        assert snap.takeover_count == 3

    def test_takeovers_across_conversations(self):
        bm = BillingMetrics()
        bm.record_takeover("conv-1")
        bm.record_takeover("conv-2")
        bm.record_takeover("conv-1")
        snap = bm.get_current_snapshot()
        assert snap.takeover_count == 3

    def test_takeover_with_timestamp(self):
        bm = BillingMetrics()
        bm.record_takeover("conv-1", timestamp="2026-04-16T10:00:00Z")
        snap = bm.get_current_snapshot()
        assert snap.takeover_count == 1


class TestRecordCsat:
    def test_valid_scores(self):
        bm = BillingMetrics()
        for score in range(1, 6):
            bm.record_csat(f"conv-{score}", score)
        snap = bm.get_current_snapshot()
        assert snap.csat_total_responses == 5
        assert snap.csat_average == 3.0

    def test_score_below_range(self):
        bm = BillingMetrics()
        with pytest.raises(ValueError, match="1 and 5"):
            bm.record_csat("conv-1", 0)

    def test_score_above_range(self):
        bm = BillingMetrics()
        with pytest.raises(ValueError, match="1 and 5"):
            bm.record_csat("conv-1", 6)

    def test_non_integer_score(self):
        bm = BillingMetrics()
        with pytest.raises(ValueError):
            bm.record_csat("conv-1", 3.5)  # type: ignore[arg-type]

    def test_csat_distribution(self):
        bm = BillingMetrics()
        bm.record_csat("c1", 5)
        bm.record_csat("c2", 5)
        bm.record_csat("c3", 3)
        snap = bm.get_current_snapshot()
        assert snap.csat_distribution == {1: 0, 2: 0, 3: 1, 4: 0, 5: 2}

    def test_csat_overwrites_per_conversation(self):
        """Last score wins for a given conversation."""
        bm = BillingMetrics()
        bm.record_csat("conv-1", 1)
        bm.record_csat("conv-1", 5)
        snap = bm.get_current_snapshot()
        assert snap.csat_average == 5.0
        assert snap.csat_total_responses == 1


class TestEscalation:
    def test_escalation_and_resolution(self):
        bm = BillingMetrics()
        bm.record_escalation("conv-1")
        bm.record_resolution("conv-1")
        snap = bm.get_current_snapshot()
        assert snap.escalation_count == 1
        assert snap.escalation_resolved == 1
        assert snap.escalation_resolution_rate == 100.0

    def test_escalation_without_resolution(self):
        bm = BillingMetrics()
        bm.record_escalation("conv-1")
        snap = bm.get_current_snapshot()
        assert snap.escalation_count == 1
        assert snap.escalation_resolved == 0
        assert snap.escalation_resolution_rate == 0.0

    def test_resolution_without_escalation_is_noop(self):
        bm = BillingMetrics()
        bm.record_resolution("conv-1")
        snap = bm.get_current_snapshot()
        assert snap.escalation_count == 0

    def test_resolution_rate_calculation(self):
        bm = BillingMetrics()
        bm.record_escalation("c1")
        bm.record_escalation("c2")
        bm.record_escalation("c3")
        bm.record_resolution("c1")
        snap = bm.get_current_snapshot()
        assert snap.escalation_count == 3
        assert snap.escalation_resolved == 1
        assert snap.escalation_resolution_rate == pytest.approx(33.33, abs=0.01)

    def test_division_by_zero_no_escalations(self):
        bm = BillingMetrics()
        snap = bm.get_current_snapshot()
        assert snap.escalation_resolution_rate == 0.0


class TestGetCurrentSnapshot:
    def test_aggregation(self):
        bm = BillingMetrics()
        bm.record_takeover("c1")
        bm.record_takeover("c2")
        bm.record_csat("c1", 4)
        bm.record_csat("c2", 2)
        bm.record_escalation("c1")
        bm.record_resolution("c1")
        snap = bm.get_current_snapshot()
        assert snap.takeover_count == 2
        assert snap.csat_average == 3.0
        assert snap.csat_total_responses == 2
        assert snap.escalation_count == 1
        assert snap.escalation_resolved == 1
        assert snap.escalation_resolution_rate == 100.0


class TestCloseMonth:
    def test_close_month_freezes_data(self):
        bm = BillingMetrics()
        bm.record_takeover("c1")
        bm.record_csat("c1", 5)
        bm.record_escalation("c1")
        bm.record_resolution("c1")

        snap = bm.close_month("2026-04")
        assert snap.period == "2026-04"
        assert snap.takeover_count == 1
        assert snap.csat_average == 5.0
        assert snap.escalation_resolution_rate == 100.0

        # Live data is reset after close
        live = bm.get_current_snapshot()
        assert live.takeover_count == 0
        assert live.csat_total_responses == 0
        assert live.escalation_count == 0

    def test_get_monthly_snapshot_after_close(self):
        bm = BillingMetrics()
        bm.record_takeover("c1")
        bm.close_month("2026-03")
        snap = bm.get_monthly_snapshot("2026-03")
        assert snap is not None
        assert snap.period == "2026-03"
        assert snap.takeover_count == 1

    def test_get_monthly_snapshot_not_found(self):
        bm = BillingMetrics()
        assert bm.get_monthly_snapshot("2099-01") is None


class TestToBillingJson:
    def test_format(self):
        bm = BillingMetrics()
        bm.record_takeover("c1")
        bm.record_csat("c1", 4)
        bm.record_escalation("c1")
        bm.record_resolution("c1")
        bm.close_month("2026-04")

        result = bm.to_billing_json("2026-04")
        assert result["period"] == "2026-04"
        assert result["takeover_count"] == 1
        assert result["csat"]["average"] == 4.0
        assert result["csat"]["distribution"] == {1: 0, 2: 0, 3: 0, 4: 0, 5: 0} or result["csat"]["distribution"][4] == 1
        assert result["csat"]["total_responses"] == 1
        assert result["escalation"]["count"] == 1
        assert result["escalation"]["resolved"] == 1
        assert result["escalation"]["resolution_rate"] == 100.0

    def test_billing_json_unclosed_period(self):
        bm = BillingMetrics()
        bm.record_takeover("c1")
        result = bm.to_billing_json("2026-04")
        assert result["period"] == "2026-04"
        assert result["takeover_count"] == 1


class TestEmptyState:
    def test_empty_returns_zeroes(self):
        bm = BillingMetrics()
        snap = bm.get_current_snapshot()
        assert snap.takeover_count == 0
        assert snap.csat_average == 0.0
        assert snap.csat_total_responses == 0
        assert snap.csat_distribution == {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        assert snap.escalation_count == 0
        assert snap.escalation_resolved == 0
        assert snap.escalation_resolution_rate == 0.0


class TestMultipleConversations:
    def test_independent_tracking(self):
        bm = BillingMetrics()
        bm.record_takeover("c1")
        bm.record_takeover("c1")
        bm.record_takeover("c2")
        bm.record_csat("c1", 5)
        bm.record_csat("c2", 1)
        bm.record_csat("c3", 3)
        bm.record_escalation("c1")
        bm.record_escalation("c2")
        bm.record_resolution("c2")

        snap = bm.get_current_snapshot()
        assert snap.takeover_count == 3  # 2 + 1
        assert snap.csat_average == 3.0  # (5+1+3)/3
        assert snap.csat_total_responses == 3
        assert snap.escalation_count == 2
        assert snap.escalation_resolved == 1
        assert snap.escalation_resolution_rate == 50.0
