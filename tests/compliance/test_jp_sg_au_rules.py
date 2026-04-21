"""Tests for T4S.6 — JP/SG/AU compliance rulesets (~11 rules).

Contract: docs/contracts/m3/e4-compliance.md §4.
Validates that newly added rules load, are filterable by country, and
each has the expected minimum coverage per PRD.
"""
from __future__ import annotations

import pytest

from autoservice.compliance.compliance import ComplianceEngine, load_compliance_rules


@pytest.fixture(scope="module")
def all_rules():
    """Load the real rules.yaml (includes JP/SG/AU additions from T4S.6)."""
    return load_compliance_rules()


# ──────────────────────────────────────────────────────────────────────────
# Rule count per country
# ──────────────────────────────────────────────────────────────────────────


def _by_region(rules, region):
    return [r for r in rules if r["region"] == region]


def test_jp_has_at_least_4_rules(all_rules):
    jp = _by_region(all_rules, "JP")
    assert len(jp) >= 4, f"expected ≥4 JP rules, got {len(jp)}"
    ids = {r["rule_id"] for r in jp}
    # Key areas: purpose, access, cross-border, breach notification
    assert "jp-01" in ids
    assert "jp-02" in ids
    assert "jp-03" in ids
    assert "jp-04" in ids


def test_sg_has_at_least_4_rules(all_rules):
    sg = _by_region(all_rules, "SG")
    assert len(sg) >= 4
    ids = {r["rule_id"] for r in sg}
    assert "sg-01" in ids
    assert "sg-02" in ids
    assert "sg-03" in ids
    assert "sg-04" in ids


def test_au_has_at_least_3_rules(all_rules):
    au = _by_region(all_rules, "AU")
    assert len(au) >= 3
    ids = {r["rule_id"] for r in au}
    assert "au-01" in ids
    assert "au-02" in ids
    assert "au-03" in ids


def test_total_rule_count_grew_by_at_least_11(all_rules):
    """16 (EU/US/CN baseline) + 11 new = 27+ total."""
    assert len(all_rules) >= 27


# ──────────────────────────────────────────────────────────────────────────
# Schema validation — new rules use same shape as existing
# ──────────────────────────────────────────────────────────────────────────


def test_new_rules_have_required_fields(all_rules):
    required = {
        "rule_id", "name", "name_zh", "region", "regulation",
        "severity", "trigger", "blocking",
        "description", "description_zh",
    }
    for r in all_rules:
        if r["region"] in ("JP", "SG", "AU"):
            missing = required - set(r.keys())
            assert not missing, f"{r['rule_id']} missing fields: {missing}"


def test_new_rules_severity_is_valid(all_rules):
    valid_severities = {"critical", "high", "medium", "low"}
    for r in all_rules:
        if r["region"] in ("JP", "SG", "AU"):
            assert r["severity"] in valid_severities, (
                f"{r['rule_id']} has invalid severity: {r['severity']}"
            )


def test_new_rules_trigger_has_type_field(all_rules):
    for r in all_rules:
        if r["region"] in ("JP", "SG", "AU"):
            assert "type" in r["trigger"], f"{r['rule_id']} trigger missing type"


# ──────────────────────────────────────────────────────────────────────────
# Integration with T2S.7 scan(countries=)
# ──────────────────────────────────────────────────────────────────────────


def test_jp_tenant_sees_only_jp_rules():
    engine = ComplianceEngine()  # uses real rules.yaml
    report = engine.scan(
        tenant_id="jp-corp",
        config={},  # all fields empty → all rules "fail"; we only care about which rules are EVALUATED
        countries=["JP"],
    )
    regions = {r.region for r in report.results}
    # JP + GLOBAL (if any) — but not EU/US/CN/SG/AU
    assert regions.issubset({"JP", "*"})
    # Must include JP
    assert "JP" in regions


def test_multi_country_tenant_sees_union():
    engine = ComplianceEngine()
    report = engine.scan(
        tenant_id="multi", config={}, countries=["JP", "SG"]
    )
    regions = {r.region for r in report.results}
    assert "JP" in regions
    assert "SG" in regions
    assert "EU" not in regions
    assert "US" not in regions
    assert "AU" not in regions


def test_au_country_filter_excludes_others():
    engine = ComplianceEngine()
    report = engine.scan(
        tenant_id="au-corp", config={}, countries=["AU"]
    )
    regions = {r.region for r in report.results}
    assert regions.issubset({"AU", "*"})
    assert "AU" in regions


# ──────────────────────────────────────────────────────────────────────────
# Registry validation (country_registry.validate_list)
# ──────────────────────────────────────────────────────────────────────────


def test_new_country_codes_are_valid_iso_alpha_2():
    from autoservice import country_registry
    for code in ["JP", "SG", "AU"]:
        assert country_registry.is_valid(code)
