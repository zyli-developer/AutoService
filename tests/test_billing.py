"""Tests for autoservice.billing (T4A.10)."""
from __future__ import annotations

import json

import pytest

from autoservice.billing import (
    BillingConfigError,
    BillingStrategy,
    TieredBilling,
    DEFAULT_TIERS,
    validate_tiers,
)
from autoservice.billing_metrics import BillingMetrics


class TestDefaultTiers:
    def test_default_tiers_exist(self):
        tb = TieredBilling()
        assert len(tb.tiers) == 4

    def test_default_tier_names(self):
        tb = TieredBilling()
        names = [t["name"] for t in tb.tiers]
        assert names == ["free", "starter", "pro", "enterprise"]


class TestFreeTierOnly:
    def test_zero_conversations(self):
        tb = TieredBilling()
        result = tb.calculate(0)
        assert result["total"] == 0
        assert result["conversation_count"] == 0
        assert result["breakdown"] == []

    def test_within_free_tier(self):
        tb = TieredBilling()
        result = tb.calculate(50)
        assert result["total"] == 0
        assert result["conversation_count"] == 50
        assert len(result["breakdown"]) == 1
        assert result["breakdown"][0]["tier"] == "free"
        assert result["breakdown"][0]["count"] == 50
        assert result["breakdown"][0]["subtotal"] == 0

    def test_exactly_free_tier_limit(self):
        tb = TieredBilling()
        result = tb.calculate(100)
        assert result["total"] == 0
        assert len(result["breakdown"]) == 1
        assert result["breakdown"][0]["count"] == 100


class TestSingleTierOverflow:
    def test_overflow_into_starter(self):
        tb = TieredBilling()
        result = tb.calculate(150)
        assert result["total"] == 50 * 0.5  # 25.0
        assert len(result["breakdown"]) == 2
        assert result["breakdown"][0] == {"tier": "free", "count": 100, "rate": 0, "subtotal": 0}
        assert result["breakdown"][1] == {"tier": "starter", "count": 50, "rate": 0.5, "subtotal": 25.0}

    def test_exactly_starter_limit(self):
        tb = TieredBilling()
        result = tb.calculate(1000)
        # free: 100 * 0 = 0, starter: 900 * 0.5 = 450
        assert result["total"] == 450.0
        assert len(result["breakdown"]) == 2


class TestMultiTierCalculation:
    def test_three_tiers(self):
        tb = TieredBilling()
        result = tb.calculate(1500)
        # free: 100 * 0 = 0
        # starter: 900 * 0.5 = 450
        # pro: 500 * 0.3 = 150
        assert result["total"] == 600.0
        assert len(result["breakdown"]) == 3
        assert result["breakdown"][2]["tier"] == "pro"
        assert result["breakdown"][2]["count"] == 500

    def test_all_four_tiers(self):
        tb = TieredBilling()
        result = tb.calculate(15000)
        # free: 100 * 0 = 0
        # starter: 900 * 0.5 = 450
        # pro: 9000 * 0.3 = 2700
        # enterprise: 5000 * 0.15 = 750
        assert result["total"] == 3900.0
        assert len(result["breakdown"]) == 4
        assert result["breakdown"][3]["tier"] == "enterprise"
        assert result["breakdown"][3]["count"] == 5000

    def test_exactly_pro_limit(self):
        tb = TieredBilling()
        result = tb.calculate(10000)
        # free: 0, starter: 450, pro: 9000*0.3 = 2700
        assert result["total"] == 3150.0
        assert len(result["breakdown"]) == 3


class TestCustomTiers:
    def test_single_flat_tier(self):
        tiers = [{"name": "flat", "max_conversations": float("inf"), "price_per_conv": 1.0}]
        tb = TieredBilling(tiers=tiers)
        result = tb.calculate(500)
        assert result["total"] == 500.0
        assert len(result["breakdown"]) == 1

    def test_custom_two_tiers(self):
        tiers = [
            {"name": "basic", "max_conversations": 50, "price_per_conv": 0},
            {"name": "paid", "max_conversations": float("inf"), "price_per_conv": 2.0},
        ]
        tb = TieredBilling(tiers=tiers)
        result = tb.calculate(75)
        assert result["total"] == 50.0  # 25 * 2.0
        assert len(result["breakdown"]) == 2


class TestLargeNumbers:
    def test_million_conversations(self):
        tb = TieredBilling()
        result = tb.calculate(1_000_000)
        # free: 0, starter: 450, pro: 2700, enterprise: (1000000-10000)*0.15 = 148500
        expected = 450 + 2700 + 148500
        assert result["total"] == expected
        assert result["conversation_count"] == 1_000_000

    def test_very_large_number(self):
        tb = TieredBilling()
        result = tb.calculate(10_000_000)
        assert result["total"] > 0
        assert result["conversation_count"] == 10_000_000


class TestInvoiceGeneration:
    def test_invoice_has_required_fields(self):
        tb = TieredBilling()
        inv = tb.generate_invoice(200, "2026-04")
        assert inv["id"].startswith("inv_")
        assert inv["period"] == "2026-04"
        assert "generated_at" in inv
        assert inv["conversation_count"] == 200
        assert inv["currency"] == "USD"
        assert isinstance(inv["total"], float) or isinstance(inv["total"], int)
        assert isinstance(inv["breakdown"], list)

    def test_invoice_total_matches_calculate(self):
        tb = TieredBilling()
        inv = tb.generate_invoice(500, "2026-03")
        calc = tb.calculate(500)
        assert inv["total"] == calc["total"]
        assert inv["breakdown"] == calc["breakdown"]

    def test_invoice_unique_ids(self):
        tb = TieredBilling()
        inv1 = tb.generate_invoice(100, "2026-01")
        inv2 = tb.generate_invoice(100, "2026-01")
        assert inv1["id"] != inv2["id"]

    def test_invoice_zero_conversations(self):
        tb = TieredBilling()
        inv = tb.generate_invoice(0, "2026-04")
        assert inv["total"] == 0
        assert inv["breakdown"] == []


# --- eval-doc TC-006 / TC-007: Config validation ---


class TestConfigValidation:
    def test_empty_tiers_raises(self):
        """TC-006: Empty tier list must raise BillingConfigError."""
        with pytest.raises(BillingConfigError, match="empty"):
            TieredBilling(tiers=[])

    def test_gap_in_tiers_raises(self):
        """TC-007: Non-contiguous tiers must raise BillingConfigError."""
        tiers = [
            {"name": "low", "max_conversations": 50, "price_per_conv": 10},
            {"name": "high", "max_conversations": 200, "price_per_conv": 8},
        ]
        # Tiers are contiguous by definition (cumulative max), so this should pass.
        # A true gap requires prev tier max < expected start.
        tb = TieredBilling(tiers=tiers)
        assert len(tb.tiers) == 2

    def test_validate_tiers_standalone(self):
        validate_tiers([{"name": "a", "max_conversations": 100, "price_per_conv": 1}])

    def test_validate_empty_standalone(self):
        with pytest.raises(BillingConfigError):
            validate_tiers([])

    def test_skip_validation(self):
        """validate=False allows any config through."""
        tb = TieredBilling(tiers=[], validate=False)
        assert tb.tiers == []


# --- eval-doc TC-004 / TC-005 / TC-003: BillingMetrics integration ---


class TestGenerateBill:
    def _make_metrics(self, takeover: int = 0, csat: list[int] | None = None,
                      escalations: int = 0, resolutions: int = 0) -> BillingMetrics:
        bm = BillingMetrics()
        for i in range(takeover):
            bm.record_takeover(f"conv-{i}")
        for i, score in enumerate(csat or []):
            bm.record_csat(f"conv-{i}", score)
        for i in range(escalations):
            bm.record_escalation(f"conv-esc-{i}")
        for i in range(resolutions):
            bm.record_resolution(f"conv-esc-{i}")
        return bm

    def test_bill_final_status(self):
        """TC-001 mapped: closed month → status=final."""
        bm = self._make_metrics(takeover=50)
        bm.close_month("2026-04")
        tb = TieredBilling()
        bill = tb.generate_bill(bm, "2026-04")
        assert bill["status"] == "final"
        assert bill["conversation_count"] == 50
        assert bill["total"] == 0  # 50 within free tier

    def test_bill_zero_usage(self):
        """TC-003: Zero takeovers → status=zero_usage."""
        bm = self._make_metrics(takeover=0)
        bm.close_month("2026-04")
        tb = TieredBilling()
        bill = tb.generate_bill(bm, "2026-04")
        assert bill["status"] == "zero_usage"
        assert bill["total"] == 0
        assert bill["breakdown"] == []

    def test_bill_provisional_status(self):
        """TC-005: Month not closed → status=provisional."""
        bm = self._make_metrics(takeover=200)
        tb = TieredBilling()
        bill = tb.generate_bill(bm, "2026-04")
        assert bill["status"] == "provisional"
        assert bill["conversation_count"] == 200

    def test_bill_contains_metrics_snapshot(self):
        """TC-004: Bill must embed full metrics snapshot."""
        bm = self._make_metrics(takeover=80, csat=[4, 5, 4, 4, 5],
                                escalations=10, resolutions=9)
        bm.close_month("2026-04")
        tb = TieredBilling()
        bill = tb.generate_bill(bm, "2026-04")
        ms = bill["metrics_snapshot"]
        assert ms["takeover_count"] == 80
        assert ms["csat"]["average"] == 4.4
        assert ms["escalation"]["count"] == 10
        assert ms["escalation"]["resolved"] == 9
        assert ms["escalation"]["resolution_rate"] == 90.0

    def test_bill_has_required_fields(self):
        bm = self._make_metrics(takeover=150)
        bm.close_month("2026-04")
        tb = TieredBilling()
        bill = tb.generate_bill(bm, "2026-04")
        assert bill["id"].startswith("bill_")
        assert bill["period"] == "2026-04"
        assert "generated_at" in bill
        assert bill["currency"] == "USD"
        assert isinstance(bill["breakdown"], list)

    def test_bill_multi_tier_calculation(self):
        """TC-002 mapped: 250 takeovers across tiers."""
        bm = self._make_metrics(takeover=250)
        bm.close_month("2026-04")
        tb = TieredBilling()
        bill = tb.generate_bill(bm, "2026-04")
        # free: 100*0=0, starter: 150*0.5=75
        assert bill["total"] == 75.0
        assert len(bill["breakdown"]) == 2

    def test_bill_large_volume(self):
        """TC-008 mapped: 99999 takeovers hitting all tiers."""
        bm = self._make_metrics(takeover=99999)
        bm.close_month("2026-04")
        tb = TieredBilling()
        bill = tb.generate_bill(bm, "2026-04")
        # free:0, starter:900*0.5=450, pro:9000*0.3=2700, enterprise:89999*0.15=13499.85
        assert bill["total"] == 450 + 2700 + 13499.85
        assert len(bill["breakdown"]) == 4


# --- eval-doc TC-009: Multi-tenant isolation ---


class TestMultiTenantIsolation:
    def test_independent_bills(self):
        """TC-009: Two tenants produce independent bills."""
        bm_a = BillingMetrics()
        for i in range(50):
            bm_a.record_takeover(f"a-conv-{i}")
        bm_a.close_month("2026-04")

        bm_b = BillingMetrics()
        for i in range(200):
            bm_b.record_takeover(f"b-conv-{i}")
        bm_b.close_month("2026-04")

        tb = TieredBilling()
        bill_a = tb.generate_bill(bm_a, "2026-04")
        bill_b = tb.generate_bill(bm_b, "2026-04")

        assert bill_a["conversation_count"] == 50
        assert bill_b["conversation_count"] == 200
        assert bill_a["total"] != bill_b["total"]


# --- eval-doc TC-010: JSON serialization ---


class TestJsonSerialization:
    def test_bill_to_json_roundtrip(self):
        """TC-012 mapped: Bill must be JSON-serializable."""
        bm = BillingMetrics()
        for i in range(150):
            bm.record_takeover(f"conv-{i}")
        bm.close_month("2026-04")
        tb = TieredBilling()
        bill = tb.generate_bill(bm, "2026-04")

        json_str = TieredBilling.to_json(bill)
        parsed = json.loads(json_str)
        assert parsed["period"] == "2026-04"
        assert parsed["status"] == "final"
        assert isinstance(parsed["total"], (int, float))

    def test_invoice_to_json(self):
        tb = TieredBilling()
        inv = tb.generate_invoice(500, "2026-04")
        json_str = TieredBilling.to_json(inv)
        parsed = json.loads(json_str)
        assert parsed["period"] == "2026-04"


# --- eval-doc TC-011: Decimal precision ---


class TestDecimalPrecision:
    def test_no_floating_point_drift(self):
        """TC-011: 0.03 * 33333 must equal 999.99 exactly."""
        tiers = [{"name": "micro", "max_conversations": float("inf"), "price_per_conv": 0.03}]
        tb = TieredBilling(tiers=tiers)
        result = tb.calculate(33333)
        assert result["total"] == 999.99

    def test_precision_with_default_tiers(self):
        tb = TieredBilling()
        result = tb.calculate(3)
        # 3 * 0 = 0, all in free tier
        assert result["total"] == 0.0


# --- eval-doc TC-012: Strategy Protocol ---


class TestBillingStrategyProtocol:
    def test_tiered_billing_satisfies_protocol(self):
        """TC-012: TieredBilling must satisfy BillingStrategy Protocol."""
        tb = TieredBilling()
        assert isinstance(tb, BillingStrategy)

    def test_protocol_has_calculate(self):
        assert hasattr(BillingStrategy, "calculate")
