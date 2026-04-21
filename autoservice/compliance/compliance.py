"""Compliance pre-check engine and policy enforcement.

T3A.7 产出 | 2026-04-16
关联: PRD δ8 / US-1.4 / rule-schema.md (T3A.4) / rules.yaml (T3A.5)

Scans tenant configuration against 16 compliance rules.
Outputs risk level and blocking decisions per environment
(sandbox / production / dream_engine).
"""

from __future__ import annotations

import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class RiskLevel(str, Enum):
    PASS = "pass"             # All rules satisfied
    LOW = "low"               # Only medium/low violations
    HIGH = "high"             # Has high severity violations
    CRITICAL = "critical"     # Has critical violations — blocks production


@dataclass
class RuleResult:
    """Result of checking a single compliance rule."""
    rule_id: str
    name_zh: str
    region: str
    severity: str
    passed: bool
    field: str
    condition: str
    actual_value: Any = None
    remediation_doc: str = ""


@dataclass
class ComplianceReport:
    """Full compliance scan report for a tenant."""
    tenant_id: str
    risk_level: RiskLevel
    total_rules: int
    passed: int
    failed: int
    results: list[RuleResult] = field(default_factory=list)
    blocking: BlockingDecision = None  # type: ignore

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total_rules if self.total_rules else 0.0


@dataclass
class BlockingDecision:
    """Per-environment blocking decision."""
    sandbox_blocked: bool = False
    production_blocked: bool = False
    dream_engine_blocked: bool = False
    blocking_rules: list[str] = field(default_factory=list)  # rule_ids that cause blocking


# ---------------------------------------------------------------------------
# Rule loader
# ---------------------------------------------------------------------------

_RULES_PATH = Path(__file__).parent / "rules.yaml"


def load_compliance_rules(path: Path | None = None) -> list[dict]:
    p = path or _RULES_PATH
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------

def _resolve_field(config: dict, field_path: str) -> Any:
    """Resolve a dot-notation field path from nested config dict."""
    parts = field_path.split(".")
    current = config
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _evaluate_condition(value: Any, condition: str) -> bool:
    """Evaluate a declarative condition against a value."""
    if condition == "must_be_true":
        return value is True
    elif condition == "must_be_false":
        return value is False
    elif condition == "must_exist":
        return value is not None
    elif condition == "must_not_empty":
        if value is None:
            return False
        if isinstance(value, str):
            return len(value.strip()) > 0
        if isinstance(value, (list, dict)):
            return len(value) > 0
        return True
    elif condition.startswith("must_match:"):
        pattern = condition[len("must_match:"):]
        if not isinstance(value, str):
            return False
        return bool(re.search(pattern, value))
    elif condition.startswith("must_contain:"):
        target = condition[len("must_contain:"):]
        if isinstance(value, (list, tuple)):
            return target in value
        return False
    else:
        return False  # Unknown condition = fail safe


# ---------------------------------------------------------------------------
# ComplianceEngine
# ---------------------------------------------------------------------------

class ComplianceEngine:
    """Scans tenant config against compliance rules and produces a report.

    Usage:
        engine = ComplianceEngine()
        report = engine.scan(tenant_id, tenant_config)
        if report.blocking.production_blocked:
            # prevent go-live
    """

    def __init__(self, rules: list[dict] | None = None):
        self._rules = rules or load_compliance_rules()

    def scan(
        self,
        tenant_id: str,
        config: dict,
        region_filter: Optional[str] = None,
        *,
        countries: Optional[list[str]] = None,
    ) -> ComplianceReport:
        """Scan tenant config against compliance rules.

        Filtering (T2S.7 — contract e4-compliance.md §3):
        - ``countries`` (preferred): list of ISO 3166-1 alpha-2 codes OR
          ``'*'`` (GLOBAL_TAG) OR ``'EU'`` alias.  Rules match when
          ``rule.region in countries`` OR ``rule.region == '*'``.
          Empty list → fail-closed (OQ-E4-1): raises ValueError so the
          caller surfaces "tenant.countries not configured" to the user.
        - ``region_filter`` (deprecated, removed M4): single-region string.
          Emits DeprecationWarning when used.
        - Both provided: ValueError — ambiguous caller intent.
        - Neither provided: fallback to unfiltered scan (all rules) —
          preserved for M2 callers until they migrate.
        """
        from autoservice import country_registry

        if region_filter is not None and countries is not None:
            raise ValueError(
                "scan() takes EITHER region_filter (deprecated) OR countries, not both"
            )

        if region_filter is not None:
            import warnings
            warnings.warn(
                "scan(region_filter=) is deprecated (M4 removal). "
                "Use scan(countries=[...]) instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        if countries is not None:
            if not countries:
                # OQ-E4-1: fail-closed on empty list
                raise ValueError(
                    "tenant.countries is empty — compliance scan blocked. "
                    "Configure tenant.countries in admin-portal before running scans."
                )
            # Validate codes early (catches typos at scan time, not rule mismatch time)
            invalid = country_registry.validate_list(countries)
            if invalid:
                raise ValueError(
                    f"Invalid country code(s) in scan(countries=): {invalid}"
                )

        results: list[RuleResult] = []

        for rule in self._rules:
            rule_region = rule["region"]

            # Filtering priority: countries (new) > region_filter (deprecated)
            if countries is not None:
                # Match iff rule is GLOBAL ('*') or its region is in the tenant's countries
                if rule_region != country_registry.GLOBAL_TAG and rule_region not in countries:
                    continue
            elif region_filter and rule_region != region_filter:
                continue

            trigger = rule["trigger"]
            field_path = trigger["field"]
            condition = trigger["condition"]

            actual = _resolve_field(config, field_path)
            passed = _evaluate_condition(actual, condition)

            results.append(RuleResult(
                rule_id=rule["rule_id"],
                name_zh=rule["name_zh"],
                region=rule["region"],
                severity=rule["severity"],
                passed=passed,
                field=field_path,
                condition=condition,
                actual_value=actual,
                remediation_doc=rule.get("remediation_doc", ""),
            ))

        passed_count = sum(1 for r in results if r.passed)
        failed_count = len(results) - passed_count

        # Determine risk level
        risk_level = self._compute_risk_level(results)

        # Determine blocking
        blocking = self._compute_blocking(results)

        report = ComplianceReport(
            tenant_id=tenant_id,
            risk_level=risk_level,
            total_rules=len(results),
            passed=passed_count,
            failed=failed_count,
            results=results,
            blocking=blocking,
        )
        return report

    def _compute_risk_level(self, results: list[RuleResult]) -> RiskLevel:
        failed = [r for r in results if not r.passed]
        if not failed:
            return RiskLevel.PASS
        severities = {r.severity for r in failed}
        if "critical" in severities:
            return RiskLevel.CRITICAL
        if "high" in severities:
            return RiskLevel.HIGH
        return RiskLevel.LOW

    def _compute_blocking(self, results: list[RuleResult]) -> BlockingDecision:
        """Compute per-environment blocking based on failed rules.

        Uses the severity-based blocking policy from rule-schema.md:
        - critical: sandbox=false, production=true, dream_engine=true
        - high: sandbox=false, production=true, dream_engine=false
        - medium: sandbox=false, production=false, dream_engine=false
        """
        decision = BlockingDecision()

        for r in results:
            if r.passed:
                continue

            rule_data = next((rd for rd in self._rules if rd["rule_id"] == r.rule_id), None)
            if not rule_data:
                continue

            blocking = rule_data.get("blocking", {})
            if blocking.get("sandbox", False):
                decision.sandbox_blocked = True
            if blocking.get("production", False):
                decision.production_blocked = True
                decision.blocking_rules.append(r.rule_id)
            if blocking.get("dream_engine", False):
                decision.dream_engine_blocked = True

        return decision
