"""Alert engine — evaluates SLA alert rules and pushes notifications.

T2A.4 产出 | 2026-04-16
关联: alerts.yaml (config) / SLAAggregator (T2A.3) / web_gateway (T0.5)

Periodically checks SLAAggregator metrics against alert rules.
Fires alerts to admin-portal via web_gateway push (or stdout fallback).
"""

from __future__ import annotations

import time
import logging
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

from autoservice.sla_aggregator import (
    SLAAggregator, MetricType, WindowSize, PercentileResult,
)

logger = logging.getLogger("autoservice.alert_engine")

_ALERTS_PATH = Path(__file__).parent / "alerts.yaml"


@dataclass
class AlertRule:
    id: str
    name: str
    name_zh: str
    metric: MetricType
    window: WindowSize
    percentile: str         # "p50" or "p95"
    threshold: float
    severity: str           # "critical" | "high" | "medium"
    cooldown_seconds: int
    message_zh: str
    message_en: str
    direction: str = "above"  # "above" (default) or "below"
    # T2S.5 (reviewer C1): optional tenant_id so rules can be platform-wide
    # (None) or tenant-scoped.  Propagated to FiredAlert.tenant_id for the
    # operator-WS push filter (web_gateway._push_alert_to_operators).
    # NOTE: AlertEngine currently evaluates against a single global aggregator
    # snapshot; full per-tenant evaluation (one buffer per tenant) is a T4S.4
    # follow-up.  For M3: tenant_id here is metadata-only — operators receive
    # alerts whose rule is tagged with their tenant, admins receive all.
    tenant_id: str | None = None


@dataclass
class FiredAlert:
    rule_id: str
    rule_name_zh: str
    severity: str
    metric: str
    window: str
    value: float
    threshold: float
    message: str
    timestamp: float = field(default_factory=time.time)
    # T2S.5: tenant_id for operator-WS scope filtering.  None = platform-wide
    # (admin-only visibility; operators do not see platform alerts).
    tenant_id: str | None = None


# Notification callback type
NotifyFn = Callable[[FiredAlert], Awaitable[None]]


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_alert_rules(path: Path | None = None) -> list[AlertRule]:
    """Load alert rules from YAML config."""
    p = path or _ALERTS_PATH
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    rules = []
    for r in data.get("rules", []):
        rules.append(AlertRule(
            id=r["id"],
            name=r["name"],
            name_zh=r["name_zh"],
            metric=MetricType(r["metric"]),
            window=WindowSize(r["window"]),
            percentile=r["percentile"],
            threshold=r["threshold"],
            severity=r["severity"],
            cooldown_seconds=r["cooldown_seconds"],
            message_zh=r["message_zh"],
            message_en=r["message_en"],
            direction=r.get("direction", "above"),
        ))
    return rules


# ---------------------------------------------------------------------------
# AlertEngine
# ---------------------------------------------------------------------------

class AlertEngine:
    """Evaluates alert rules against SLAAggregator and fires notifications.

    Usage:
        engine = AlertEngine(sla_aggregator)
        alerts = engine.evaluate()  # returns list of FiredAlert
        # or with async notification:
        engine.set_notify(my_notify_fn)
        await engine.evaluate_and_notify()
    """

    def __init__(self, aggregator: SLAAggregator, rules: list[AlertRule] | None = None):
        self._aggregator = aggregator
        self._rules = rules or load_alert_rules()
        self._last_fired: dict[str, float] = {}  # rule_id → timestamp
        self._notify_fn: Optional[NotifyFn] = None

    def set_notify(self, fn: NotifyFn) -> None:
        """Set async notification callback (e.g., web_gateway push)."""
        self._notify_fn = fn

    def evaluate(self) -> list[FiredAlert]:
        """Evaluate all rules and return fired alerts (respecting cooldown)."""
        now = time.time()
        fired = []

        for rule in self._rules:
            # Check cooldown
            last = self._last_fired.get(rule.id, 0)
            if now - last < rule.cooldown_seconds:
                continue

            # Get metric
            result = self._aggregator.get_percentiles(rule.metric, rule.window)
            if result.count == 0:
                continue

            value = result.p95 if rule.percentile == "p95" else result.p50
            if value is None:
                continue

            # Check threshold
            triggered = False
            if rule.direction == "below":
                triggered = value < rule.threshold
            else:
                triggered = value > rule.threshold

            if triggered:
                msg = rule.message_zh.format(value=value, threshold=rule.threshold)
                alert = FiredAlert(
                    rule_id=rule.id,
                    rule_name_zh=rule.name_zh,
                    severity=rule.severity,
                    metric=rule.metric.value,
                    window=rule.window.value,
                    value=value,
                    threshold=rule.threshold,
                    message=msg,
                    timestamp=now,
                    tenant_id=rule.tenant_id,  # T2S.5: propagate rule's scope to alert
                )
                fired.append(alert)
                self._last_fired[rule.id] = now
                logger.warning("Alert fired: %s — %s", rule.id, msg)

        return fired

    async def evaluate_and_notify(self) -> list[FiredAlert]:
        """Evaluate rules and push alerts via notification callback."""
        alerts = self.evaluate()
        if self._notify_fn and alerts:
            for alert in alerts:
                try:
                    await self._notify_fn(alert)
                except Exception:
                    logger.exception("Failed to notify alert %s", alert.rule_id)
        return alerts
