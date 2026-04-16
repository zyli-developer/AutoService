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
