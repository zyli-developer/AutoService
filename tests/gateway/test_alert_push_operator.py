"""Tests for T2S.5 — operator-WS alert push with tenant-scope filtering.

Contract: docs/contracts/m3/e3-triage.md §1.4.

Scenarios:
- Tenant-matching operator receives the alert
- Cross-tenant operator DOES NOT receive (no leak)
- Platform-wide alert (tenant_id=None) does NOT reach operators
- Admin path still receives (backward compat)
- Stale operator connections cleaned up
"""
from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice import auth, operator_routes, operators, web_gateway
from autoservice.alert_engine import FiredAlert


def _make_alert(tenant_id: str | None = "acme") -> FiredAlert:
    return FiredAlert(
        rule_id="pool-wait",
        rule_name_zh="池等待",
        severity="warning",
        metric="pool_wait_ms",
        window="5m",
        value=3000.0,
        threshold=2000.0,
        message="pool wait exceeds",
        tenant_id=tenant_id,
    )


class _FakeWS:
    """Minimal mock WebSocket with state_operator_tenant_id + send_json."""

    def __init__(self, tenant_id: str | None):
        self.state_operator_tenant_id = tenant_id
        self.sent: list[dict] = []

    async def send_json(self, frame):
        self.sent.append(frame)


@pytest.fixture(autouse=True)
def _clean_ws_state():
    """Each test gets fresh empty _operator_sessions + _ws_connections."""
    web_gateway._operator_sessions.clear()
    web_gateway._ws_connections.clear()
    web_gateway._admin_connections.clear()
    yield
    web_gateway._operator_sessions.clear()
    web_gateway._ws_connections.clear()
    web_gateway._admin_connections.clear()


# ──────────────────────────────────────────────────────────────────────────
# FiredAlert.tenant_id field
# ──────────────────────────────────────────────────────────────────────────


def test_fired_alert_tenant_id_defaults_none():
    a = FiredAlert(
        rule_id="x", rule_name_zh="x", severity="warning",
        metric="csat_score", window="5m", value=1.0, threshold=2.0,
        message="x",
    )
    assert a.tenant_id is None


# ──────────────────────────────────────────────────────────────────────────
# Tenant-scope push
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_operator_matching_tenant_receives_alert():
    op_ws = _FakeWS(tenant_id="acme")
    web_gateway._ws_connections["s1"] = op_ws  # type: ignore[assignment]
    web_gateway._operator_sessions["op-1"] = {"s1"}

    await web_gateway._push_alert_to_operators(_make_alert("acme"))

    assert len(op_ws.sent) == 1
    payload = op_ws.sent[0]["payload"]
    assert payload["tenant_id"] == "acme"
    assert payload["metric"] == "pool_wait_ms"


@pytest.mark.asyncio
async def test_operator_different_tenant_does_not_receive_alert():
    """Cross-tenant leak test — operator on tenant B must NOT see tenant A's alert."""
    op_a = _FakeWS(tenant_id="acme")
    op_b = _FakeWS(tenant_id="b-corp")
    web_gateway._ws_connections["s-a"] = op_a  # type: ignore[assignment]
    web_gateway._ws_connections["s-b"] = op_b  # type: ignore[assignment]
    web_gateway._operator_sessions["op-a"] = {"s-a"}
    web_gateway._operator_sessions["op-b"] = {"s-b"}

    await web_gateway._push_alert_to_operators(_make_alert("acme"))

    assert len(op_a.sent) == 1, "acme operator should receive"
    assert len(op_b.sent) == 0, "b-corp operator MUST NOT receive acme's alert"


@pytest.mark.asyncio
async def test_platform_wide_alert_not_pushed_to_operators():
    """alert.tenant_id=None → platform-wide → operators skipped."""
    op_ws = _FakeWS(tenant_id="acme")
    web_gateway._ws_connections["s1"] = op_ws  # type: ignore[assignment]
    web_gateway._operator_sessions["op-1"] = {"s1"}

    await web_gateway._push_alert_to_operators(_make_alert(tenant_id=None))

    assert len(op_ws.sent) == 0


@pytest.mark.asyncio
async def test_operator_without_tenant_state_does_not_receive():
    """Operator conn missing state_operator_tenant_id (defensive) → no push."""
    op_ws = _FakeWS(tenant_id=None)  # no tenant bound
    web_gateway._ws_connections["s1"] = op_ws  # type: ignore[assignment]
    web_gateway._operator_sessions["op-1"] = {"s1"}

    await web_gateway._push_alert_to_operators(_make_alert("acme"))
    assert op_ws.sent == []


# ──────────────────────────────────────────────────────────────────────────
# Multi-session + cleanup
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_operator_with_multiple_sessions_receives_on_all():
    """One operator with 2 concurrent WS conns: both get the alert."""
    ws1 = _FakeWS(tenant_id="acme")
    ws2 = _FakeWS(tenant_id="acme")
    web_gateway._ws_connections["s1"] = ws1  # type: ignore[assignment]
    web_gateway._ws_connections["s2"] = ws2  # type: ignore[assignment]
    web_gateway._operator_sessions["op-1"] = {"s1", "s2"}

    await web_gateway._push_alert_to_operators(_make_alert("acme"))

    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1


@pytest.mark.asyncio
async def test_stale_session_pruned_on_push_failure():
    failing_ws = _FakeWS(tenant_id="acme")

    async def _raise_send(*args, **kwargs):
        raise RuntimeError("connection closed")

    failing_ws.send_json = _raise_send  # type: ignore[assignment]
    web_gateway._ws_connections["s-bad"] = failing_ws  # type: ignore[assignment]
    web_gateway._operator_sessions["op-bad"] = {"s-bad"}

    await web_gateway._push_alert_to_operators(_make_alert("acme"))

    # Pruned from operator_sessions after failure
    assert "op-bad" not in web_gateway._operator_sessions


@pytest.mark.asyncio
async def test_missing_ws_cleaned_up():
    """Session ID in _operator_sessions but absent from _ws_connections → prune."""
    web_gateway._operator_sessions["op-ghost"] = {"s-ghost"}
    # _ws_connections intentionally empty

    await web_gateway._push_alert_to_operators(_make_alert("acme"))

    assert "op-ghost" not in web_gateway._operator_sessions


# ──────────────────────────────────────────────────────────────────────────
# Combined dispatch (admin + operator)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_combined_dispatch_hits_both_paths():
    admin_ws = _FakeWS(tenant_id=None)  # admins don't have tenant scope here
    op_ws = _FakeWS(tenant_id="acme")
    web_gateway._admin_connections["a1"] = admin_ws  # type: ignore[assignment]
    web_gateway._ws_connections["s1"] = op_ws  # type: ignore[assignment]
    web_gateway._operator_sessions["op-1"] = {"s1"}

    await web_gateway._push_alert_to_all_subscribers(_make_alert("acme"))

    assert len(admin_ws.sent) == 1, "admin must receive (platform visibility)"
    assert len(op_ws.sent) == 1, "matching-tenant operator must receive"


@pytest.mark.asyncio
async def test_combined_dispatch_admin_only_for_platform_alert():
    admin_ws = _FakeWS(tenant_id=None)
    op_ws = _FakeWS(tenant_id="acme")
    web_gateway._admin_connections["a1"] = admin_ws  # type: ignore[assignment]
    web_gateway._ws_connections["s1"] = op_ws  # type: ignore[assignment]
    web_gateway._operator_sessions["op-1"] = {"s1"}

    await web_gateway._push_alert_to_all_subscribers(_make_alert(tenant_id=None))

    assert len(admin_ws.sent) == 1
    assert len(op_ws.sent) == 0, "platform-wide must not reach operator"


# ──────────────────────────────────────────────────────────────────────────
# Reviewer C1 + C2 follow-ups
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alert_rule_tenant_id_propagates_to_fired_alert():
    """T2S.5 reviewer C1: AlertRule.tenant_id → FiredAlert.tenant_id.

    Without this, AlertEngine produces alerts with tenant_id=None and
    operators never see anything (push filter short-circuits).
    """
    from autoservice.alert_engine import AlertEngine, AlertRule, FiredAlert
    from autoservice.sla_aggregator import MetricType, SLAAggregator, WindowSize

    agg = SLAAggregator()
    # Force a breach
    for _ in range(20):
        agg.record(MetricType.FIRST_REPLY_MS, 99_999.0)

    rule = AlertRule(
        id="first-reply-acme",
        name="First Reply Breach (Acme)",
        name_zh="首次回复超时 (Acme)",
        metric=MetricType.FIRST_REPLY_MS,
        window=WindowSize.FIVE_MIN,
        percentile="p95",
        threshold=10_000.0,
        severity="warning",
        cooldown_seconds=0,
        message_zh="超时 {value} 超过 {threshold}",
        message_en="exceeded",
        tenant_id="acme",  # T2S.5: tenant-scope the rule
    )

    engine = AlertEngine(agg, rules=[rule])
    fired = engine.evaluate()
    assert len(fired) == 1
    assert fired[0].tenant_id == "acme"


@pytest.mark.asyncio
async def test_admin_push_failure_does_not_block_operator_push():
    """Reviewer C2: parallel dispatch via asyncio.gather — one slow/broken
    admin path must not delay operator delivery (head-of-line prevention)."""
    admin_ws = _FakeWS(tenant_id=None)

    async def _raise(*a, **kw):
        raise ConnectionError("admin unreachable")

    admin_ws.send_json = _raise  # type: ignore[assignment]
    op_ws = _FakeWS(tenant_id="acme")
    web_gateway._admin_connections["a1"] = admin_ws  # type: ignore[assignment]
    web_gateway._ws_connections["s1"] = op_ws  # type: ignore[assignment]
    web_gateway._operator_sessions["op-1"] = {"s1"}

    # Must not raise even though admin arm fails
    await web_gateway._push_alert_to_all_subscribers(_make_alert("acme"))

    # Operator still got the alert
    assert len(op_ws.sent) == 1
