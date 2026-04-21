"""Tests for T2S.7 — multi-region compliance scan API (contract e4-compliance §3).

Covers:
- ``scan(countries=[...])`` preferred API
- ``scan(region_filter=)`` still works but emits DeprecationWarning
- Mutual exclusion: can't pass both
- Empty countries list → fail-closed (OQ-E4-1)
- Invalid country codes rejected at scan time
- GLOBAL rules (region='*') always apply
"""
from __future__ import annotations

import warnings

import pytest

from autoservice.compliance.compliance import ComplianceEngine


# Minimal rule fixtures — use existing rules.yaml structure
_RULES = [
    {
        "rule_id": "us-01",
        "region": "US",
        "name_zh": "美国规则",
        "severity": "medium",
        "trigger": {"field": "a.b", "condition": "must_exist"},
        "remediation_doc": "",
    },
    {
        "rule_id": "eu-01",
        "region": "EU",
        "name_zh": "欧盟规则",
        "severity": "high",
        "trigger": {"field": "x.y", "condition": "must_exist"},
        "remediation_doc": "",
    },
    {
        "rule_id": "jp-01",
        "region": "JP",
        "name_zh": "日本规则",
        "severity": "medium",
        "trigger": {"field": "p.q", "condition": "must_exist"},
        "remediation_doc": "",
    },
    {
        "rule_id": "global-01",
        "region": "*",
        "name_zh": "全球规则",
        "severity": "low",
        "trigger": {"field": "g.h", "condition": "must_exist"},
        "remediation_doc": "",
    },
]


@pytest.fixture()
def engine():
    return ComplianceEngine(rules=_RULES)


def _rule_ids(report) -> set[str]:
    return {r.rule_id for r in report.results}


# ──────────────────────────────────────────────────────────────────────────
# countries=[...] API (preferred)
# ──────────────────────────────────────────────────────────────────────────


def test_countries_single_region_filters_to_that_region_plus_global(engine):
    report = engine.scan(
        tenant_id="acme", config={}, countries=["US"]
    )
    ids = _rule_ids(report)
    # US rules + GLOBAL rules only
    assert "us-01" in ids
    assert "global-01" in ids
    assert "eu-01" not in ids
    assert "jp-01" not in ids


def test_countries_multiple_regions(engine):
    report = engine.scan(
        tenant_id="acme", config={}, countries=["US", "EU"]
    )
    ids = _rule_ids(report)
    assert ids == {"us-01", "eu-01", "global-01"}


def test_countries_global_rules_always_apply(engine):
    report = engine.scan(
        tenant_id="acme", config={}, countries=["JP"]
    )
    ids = _rule_ids(report)
    assert "global-01" in ids  # universal
    assert "jp-01" in ids


# ──────────────────────────────────────────────────────────────────────────
# Fail-closed + validation
# ──────────────────────────────────────────────────────────────────────────


def test_countries_empty_list_fails_closed(engine):
    """OQ-E4-1: empty list raises, forcing tenant to configure."""
    with pytest.raises(ValueError, match="empty"):
        engine.scan(tenant_id="acme", config={}, countries=[])


def test_countries_invalid_code_rejected_early(engine):
    with pytest.raises(ValueError, match="Invalid country code"):
        engine.scan(tenant_id="acme", config={}, countries=["US", "XX"])


def test_countries_and_region_filter_mutually_exclusive(engine):
    with pytest.raises(ValueError, match="EITHER region_filter"):
        engine.scan(
            tenant_id="acme", config={},
            region_filter="US", countries=["US"],
        )


# ──────────────────────────────────────────────────────────────────────────
# Deprecated region_filter
# ──────────────────────────────────────────────────────────────────────────


def test_region_filter_still_works(engine):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        report = engine.scan(tenant_id="acme", config={}, region_filter="US")
    ids = _rule_ids(report)
    assert "us-01" in ids
    assert "eu-01" not in ids


def test_region_filter_emits_deprecation_warning(engine):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        engine.scan(tenant_id="acme", config={}, region_filter="US")
    dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(dep_warnings) >= 1
    assert "region_filter" in str(dep_warnings[0].message)
    assert "M4" in str(dep_warnings[0].message)


# ──────────────────────────────────────────────────────────────────────────
# Backward-compat: no filter
# ──────────────────────────────────────────────────────────────────────────


def test_no_filter_runs_all_rules(engine):
    """Pre-M3 callers without any filter get all rules — preserved for migration."""
    report = engine.scan(tenant_id="acme", config={})
    ids = _rule_ids(report)
    assert ids == {"us-01", "eu-01", "jp-01", "global-01"}
