"""Tests for T2S.4 — per-tenant SLA thresholds (contract e3-triage §1.3).

OQ-E3-1 default: only pool_wait_ms + first_reply_ms accept per-tenant
overrides in M3.  Others stay global.  Resolution order: tenant → global → None.
"""
from __future__ import annotations

import pytest

from autoservice.sla_aggregator import (
    MetricType,
    PER_TENANT_METRICS_M3,
    PER_TENANT_THRESHOLDS,
    SLA_THRESHOLDS,
    _Threshold,
    clear_all_tenant_thresholds,
    clear_tenant_threshold,
    resolve_threshold,
    set_tenant_threshold,
)


@pytest.fixture(autouse=True)
def _clean_overrides():
    clear_all_tenant_thresholds()
    yield
    clear_all_tenant_thresholds()


# ──────────────────────────────────────────────────────────────────────────
# Metric registry
# ──────────────────────────────────────────────────────────────────────────


def test_pool_wait_ms_metric_type_exists():
    assert MetricType.POOL_WAIT_MS.value == "pool_wait_ms"


def test_pool_wait_ms_has_global_default():
    assert MetricType.POOL_WAIT_MS in SLA_THRESHOLDS
    t = SLA_THRESHOLDS[MetricType.POOL_WAIT_MS]
    assert t.comparator == "gt"
    assert t.limit > 0


def test_m3_per_tenant_scope_matches_oq_e3_1():
    """OQ-E3-1: only pool_wait_ms + first_reply_ms in M3."""
    assert PER_TENANT_METRICS_M3 == frozenset({
        MetricType.POOL_WAIT_MS,
        MetricType.FIRST_REPLY_MS,
    })


# ──────────────────────────────────────────────────────────────────────────
# set_tenant_threshold
# ──────────────────────────────────────────────────────────────────────────


def test_set_tenant_threshold_for_allowed_metric():
    set_tenant_threshold(
        "acme", MetricType.POOL_WAIT_MS,
        _Threshold(limit=500.0, comparator="gt", severity="critical"),
    )
    t = resolve_threshold("acme", MetricType.POOL_WAIT_MS)
    assert t is not None
    assert t.limit == 500.0
    assert t.severity == "critical"


def test_set_tenant_threshold_rejects_non_whitelisted_metric():
    with pytest.raises(ValueError, match="not enabled in M3"):
        set_tenant_threshold(
            "acme", MetricType.CSAT_SCORE,
            _Threshold(limit=4.5, comparator="lt", severity="warning"),
        )
    with pytest.raises(ValueError):
        set_tenant_threshold(
            "acme", MetricType.COMPLAINT_RATE,
            _Threshold(limit=0.1, comparator="gt", severity="warning"),
        )


# ──────────────────────────────────────────────────────────────────────────
# resolve_threshold — lookup order
# ──────────────────────────────────────────────────────────────────────────


def test_resolve_falls_back_to_global_when_no_tenant_override():
    t = resolve_threshold("acme", MetricType.FIRST_REPLY_MS)
    assert t is SLA_THRESHOLDS[MetricType.FIRST_REPLY_MS]


def test_resolve_tenant_override_wins():
    set_tenant_threshold(
        "acme", MetricType.FIRST_REPLY_MS,
        _Threshold(limit=3_000.0, comparator="gt", severity="warning"),
    )
    t = resolve_threshold("acme", MetricType.FIRST_REPLY_MS)
    assert t.limit == 3_000.0  # not the global 10_000.0


def test_resolve_other_tenant_gets_global():
    set_tenant_threshold(
        "acme", MetricType.POOL_WAIT_MS,
        _Threshold(limit=100.0, comparator="gt", severity="critical"),
    )
    # Tenant B has no override → gets global
    t_b = resolve_threshold("b-corp", MetricType.POOL_WAIT_MS)
    assert t_b.limit == SLA_THRESHOLDS[MetricType.POOL_WAIT_MS].limit


def test_resolve_global_only_metric_ignores_per_tenant_table():
    """CSAT is not in PER_TENANT_METRICS_M3 → tenant-lookup skipped even if
    a stray row somehow exists in the dict."""
    # Even if somebody bypassed set_tenant_threshold and injected directly:
    PER_TENANT_THRESHOLDS[("acme", MetricType.CSAT_SCORE)] = _Threshold(
        limit=99.0, comparator="lt", severity="warning"
    )
    t = resolve_threshold("acme", MetricType.CSAT_SCORE)
    # Resolves to global, not the injected row (safety against OQ drift)
    assert t.limit == SLA_THRESHOLDS[MetricType.CSAT_SCORE].limit


def test_resolve_returns_none_for_metric_without_global():
    # RESOLUTION_RATE is a MetricType but not in SLA_THRESHOLDS defaults
    t = resolve_threshold("acme", MetricType.RESOLUTION_RATE)
    assert t is None


def test_resolve_none_tenant_skips_per_tenant_lookup():
    """tenant_id=None → directly global (platform-scope event)."""
    set_tenant_threshold(
        "acme", MetricType.POOL_WAIT_MS,
        _Threshold(limit=500.0, comparator="gt", severity="warning"),
    )
    t = resolve_threshold(None, MetricType.POOL_WAIT_MS)
    assert t.limit == SLA_THRESHOLDS[MetricType.POOL_WAIT_MS].limit


# ──────────────────────────────────────────────────────────────────────────
# clear_tenant_threshold
# ──────────────────────────────────────────────────────────────────────────


def test_clear_tenant_threshold_restores_global():
    set_tenant_threshold(
        "acme", MetricType.POOL_WAIT_MS,
        _Threshold(limit=100.0, comparator="gt", severity="critical"),
    )
    assert resolve_threshold("acme", MetricType.POOL_WAIT_MS).limit == 100.0

    clear_tenant_threshold("acme", MetricType.POOL_WAIT_MS)
    assert resolve_threshold("acme", MetricType.POOL_WAIT_MS).limit == (
        SLA_THRESHOLDS[MetricType.POOL_WAIT_MS].limit
    )


def test_clear_tenant_threshold_missing_is_noop():
    clear_tenant_threshold("ghost", MetricType.POOL_WAIT_MS)  # no raise
