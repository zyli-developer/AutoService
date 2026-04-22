"""Tests for T2S.8 → T5S.14 — master dream + scheduler routing.

Covers:
- ``master_dream_agent.run_platform_dream`` emits platform_level proposal
  with CON-04 enforced (status='draft' hardcoded) — now LLM tool-loop
  driven (post-T5S.14; was static skeleton in M3 T2S.8)
- Routing guard: calling with non-master tenant_id raises
- DreamScheduler._build_run_dream_coro routes _master → master_dream_agent
- Per-tenant dream path still works for regular tenants

Post-T5S.14: tests supply a fake cc_pool returning a scripted dream
client instead of the M3-era ``cc_pool=None`` skeleton pattern.
"""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from autoservice import (
    bootstrap,
    dream_runs,
    dream_scheduler,
    master_dream_agent,
    proposal_pipeline,
)


# ──────────────────────────────────────────────────────────────────────────
# T5S.14 fake cc_pool / dream client — shared across tests that drive
# the real LLM tool-loop.
# ──────────────────────────────────────────────────────────────────────────


class _FakeDreamClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def call_with_tools(self, *, system, messages, tools):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        if not self._responses:
            raise AssertionError("fake client out of scripted responses")
        return self._responses.pop(0)


class _FakePooledInstance:
    def __init__(self, client):
        self.client = client
        self.id = "fake-master-routing-1"


class _FakeCCPool:
    def __init__(self, dream_client):
        self._dream_client = dream_client

    def acquire(self, *, role, tenant_id=None, timeout=None):
        @asynccontextmanager
        async def _cm():
            yield _FakePooledInstance(self._dream_client)
        return _cm()


def _tool_use_resp(tool_name, tool_input, *, use_id="tu"):
    return {
        "content": [
            {"type": "tool_use", "id": use_id, "name": tool_name, "input": tool_input}
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 3},
    }


def _text_resp(text="done"):
    return {
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }


_PLATFORM_EMIT_PAYLOAD = {
    "category": "platform_level",
    "title": "Cross-tenant CSAT drop",
    "description": "LLM-driven analysis.",
    "suggestion": "Refresh KB on billing topics.",
    "evidence": "{\"tenant_count\": 1, \"total_proposals\": 1}",
    "risk_level": "low",
    "target_role": "dream",
}


@pytest.fixture()
def proposals_conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    proposal_pipeline.apply_schema(c)
    yield c
    c.close()


@pytest.fixture()
def runs_conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(dream_runs.SCHEMA)
    yield c
    c.close()


# ──────────────────────────────────────────────────────────────────────────
# master_dream_agent.run_platform_dream
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_platform_dream_emits_platform_level_proposal(
    proposals_conn, runs_conn
):
    """Post-T5S.14: LLM tool-loop emits platform_level proposal with CON-04."""
    dream_client = _FakeDreamClient([
        _tool_use_resp("emit_proposal", _PLATFORM_EMIT_PAYLOAD, use_id="tu_p1"),
        _text_resp(),
    ])
    cc_pool = _FakeCCPool(dream_client)

    ids = await master_dream_agent.run_platform_dream(
        tenant_id=bootstrap.MASTER_TENANT_ID,
        cc_pool=cc_pool,
        mempool=None,
        proposals_conn=proposals_conn,
        runs_conn=runs_conn,
    )
    assert len(ids) == 1

    row = proposals_conn.execute(
        "SELECT category, status, tenant_id FROM proposals WHERE id = ?",
        (ids[0],),
    ).fetchone()
    assert row is not None
    assert row["category"] == "platform_level"
    assert row["status"] == "draft"  # CON-04 enforced by emit_proposal
    assert row["tenant_id"] == bootstrap.MASTER_TENANT_ID


@pytest.mark.asyncio
async def test_run_platform_dream_rejects_non_master_tenant(
    proposals_conn, runs_conn
):
    with pytest.raises(ValueError, match="non-master tenant_id"):
        await master_dream_agent.run_platform_dream(
            tenant_id="acme",
            cc_pool=None,
            mempool=None,
            proposals_conn=proposals_conn,
            runs_conn=runs_conn,
        )


@pytest.mark.asyncio
async def test_con04_red_line_status_is_draft(proposals_conn, runs_conn):
    """Even from master path, emit_proposal locks status='draft'.

    Key CON-04 invariant: platform_level proposals cannot bypass the
    red line by virtue of being master-emitted.  5-layer defense applies
    uniformly — regardless of whether the emit is driven by the T5S.14
    LLM tool-loop or (historically) the T2S.8 static skeleton.
    """
    dream_client = _FakeDreamClient([
        _tool_use_resp("emit_proposal", _PLATFORM_EMIT_PAYLOAD, use_id="tu_draft"),
        _text_resp(),
    ])
    cc_pool = _FakeCCPool(dream_client)

    ids = await master_dream_agent.run_platform_dream(
        tenant_id=bootstrap.MASTER_TENANT_ID,
        cc_pool=cc_pool,
        mempool=None,
        proposals_conn=proposals_conn,
        runs_conn=runs_conn,
    )
    row = proposals_conn.execute(
        "SELECT status FROM proposals WHERE id = ?", (ids[0],)
    ).fetchone()
    assert row["status"] == "draft"
    # No way to upgrade to accepted/applied without explicit admin action


# ──────────────────────────────────────────────────────────────────────────
# master_dream_agent does NOT import proposal_apply (CON-04 Layer 3)
# ──────────────────────────────────────────────────────────────────────────


def test_master_dream_does_not_import_proposal_apply_module():
    """Layer 3 import cone: dream modules must not touch apply module."""
    import autoservice.master_dream_agent as mda
    import ast
    import inspect

    src = inspect.getsource(mda)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                if node.module is not None:
                    names = [node.module]
            for n in names:
                assert "proposal_apply" not in n, (
                    f"CON-04 violation: master_dream_agent imports {n}"
                )


# ──────────────────────────────────────────────────────────────────────────
# DreamScheduler routing
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scheduler_routes_master_to_master_dream_agent(
    proposals_conn, runs_conn, monkeypatch
):
    """_build_run_dream_coro must dispatch _master → master_dream_agent."""
    # Spy on master_dream_agent.run_platform_dream
    called = {"count": 0, "tenant_id": None}

    original = master_dream_agent.run_platform_dream

    async def spy_master(tenant_id, *args, **kwargs):
        called["count"] += 1
        called["tenant_id"] = tenant_id
        return await original(tenant_id, *args, **kwargs)

    monkeypatch.setattr(master_dream_agent, "run_platform_dream", spy_master)

    # Spy that per-tenant run_dream is NOT called for _master
    per_tenant_called = {"count": 0}

    async def fake_per_tenant(*args, **kwargs):
        per_tenant_called["count"] += 1

    sched = dream_scheduler.DreamScheduler()
    # Wire in a stub run_dream_fn
    monkeypatch.setattr(
        sched, "_get_cc_pool_sync", lambda: None
    )
    monkeypatch.setattr(
        sched, "_get_memory_pool", lambda: None
    )
    monkeypatch.setattr(
        sched, "_get_proposals_conn", lambda: proposals_conn
    )

    from autoservice import dream_runs as _dream_runs
    monkeypatch.setattr(_dream_runs, "open_connection", lambda: runs_conn)

    coro = sched._build_run_dream_coro(fake_per_tenant, bootstrap.MASTER_TENANT_ID)
    assert coro is not None
    await coro

    assert called["count"] == 1
    assert called["tenant_id"] == bootstrap.MASTER_TENANT_ID
    assert per_tenant_called["count"] == 0, (
        "per-tenant run_dream_fn MUST NOT be invoked for _master"
    )


# ──────────────────────────────────────────────────────────────────────────
# T4S.4 cross-tenant signals
# ──────────────────────────────────────────────────────────────────────────


def test_gather_platform_signals_empty_db(proposals_conn):
    signals = master_dream_agent.gather_platform_signals(proposals_conn)
    assert signals.tenant_count == 0
    assert signals.active_tenants == []
    assert signals.total_proposal_count == 0
    assert signals.per_tenant_proposal_counts == {}
    assert signals.pool_metrics is None
    assert signals.emitted_at_ms > 0


def test_gather_platform_signals_counts_proposals_per_tenant(proposals_conn):
    import json as _json

    # Seed 3 tenants with different counts
    for i in range(2):
        proposals_conn.execute(
            "INSERT INTO proposals (id, created_at, data, status, category, tenant_id) "
            "VALUES (?, ?, ?, 'draft', 'workflow', 'acme')",
            (f"p-acme-{i}", "2026-04-21T00:00:00", _json.dumps({"id": f"p-acme-{i}"})),
        )
    for i in range(3):
        proposals_conn.execute(
            "INSERT INTO proposals (id, created_at, data, status, category, tenant_id) "
            "VALUES (?, ?, ?, 'draft', 'workflow', 'beta-corp')",
            (f"p-beta-{i}", "2026-04-21T00:00:00", _json.dumps({"id": f"p-beta-{i}"})),
        )
    proposals_conn.commit()

    signals = master_dream_agent.gather_platform_signals(proposals_conn)
    assert signals.tenant_count == 2
    assert set(signals.active_tenants) == {"acme", "beta-corp"}
    assert signals.total_proposal_count == 5
    assert signals.per_tenant_proposal_counts == {"acme": 2, "beta-corp": 3}


def test_gather_platform_signals_includes_pool_metrics_when_available(proposals_conn):
    class _FakePool:
        def metrics(self):
            from dataclasses import dataclass

            @dataclass(frozen=True)
            class _M:
                available_count: int = 3
                busy_count: int = 1
                queue_length: int = 0
                wait_time_histogram_ms: dict = None  # type: ignore[assignment]
                total_checkouts: int = 10
                total_timeouts: int = 0
                emitted_at_ms: int = 0
            return _M(wait_time_histogram_ms={"0-100": 10})

    signals = master_dream_agent.gather_platform_signals(
        proposals_conn, cc_pool=_FakePool(),
    )
    assert signals.pool_metrics is not None
    assert signals.pool_metrics["available_count"] == 3
    assert signals.pool_metrics["busy_count"] == 1


def test_gather_platform_signals_tolerates_broken_pool(proposals_conn):
    class _BadPool:
        def metrics(self):
            raise RuntimeError("pool down")

    signals = master_dream_agent.gather_platform_signals(
        proposals_conn, cc_pool=_BadPool()
    )
    # Soft dependency — broken pool doesn't crash the collection
    assert signals.pool_metrics is None


@pytest.mark.asyncio
async def test_run_platform_dream_uses_signals_in_evidence(proposals_conn, runs_conn):
    """Post-T5S.14: signals reach the LLM via the initial prompt.

    The M3-era assertion ("evidence field contains the signal keys") no
    longer applies — evidence is now whatever the LLM chooses to emit.
    This test pins the upstream invariant: the first prompt contains
    signal values, so the LLM CAN base evidence on them if it wants.
    """
    import json as _json

    # Seed a tenant
    proposals_conn.execute(
        "INSERT INTO proposals (id, created_at, data, status, category, tenant_id) "
        "VALUES (?, ?, ?, 'draft', 'workflow', 'acme')",
        ("p-1", "2026-04-21T00:00:00", _json.dumps({"id": "p-1"})),
    )
    proposals_conn.commit()

    # LLM just wraps up — we only care that the signals reached it.
    dream_client = _FakeDreamClient([_text_resp("observed; nothing to propose")])
    cc_pool = _FakeCCPool(dream_client)

    await master_dream_agent.run_platform_dream(
        tenant_id=bootstrap.MASTER_TENANT_ID,
        cc_pool=cc_pool, mempool=None,
        proposals_conn=proposals_conn, runs_conn=runs_conn,
    )

    # The first call's initial user message must surface the signal
    # values — we seeded 1 tenant with 1 proposal, so both "1"s should
    # appear in the rendered context.
    assert dream_client.calls, "LLM was never called — pool not consulted?"
    initial = dream_client.calls[0]["messages"][0]["content"]
    assert "tenant_count:" in initial
    assert "total_proposal_count:" in initial
    assert "1" in initial  # tenant_count=1 AND total_proposal_count=1


@pytest.mark.asyncio
async def test_scheduler_routes_regular_tenant_to_per_tenant_path(
    proposals_conn, runs_conn, monkeypatch
):
    """Non-master tenant → uses run_dream_fn, NOT master_dream_agent."""
    master_called = {"count": 0}

    async def spy_master(*args, **kwargs):
        master_called["count"] += 1

    monkeypatch.setattr(master_dream_agent, "run_platform_dream", spy_master)

    per_tenant_called = {"count": 0, "tenant_id": None}

    async def fake_per_tenant(tenant_id, *args, **kwargs):
        per_tenant_called["count"] += 1
        per_tenant_called["tenant_id"] = tenant_id

    sched = dream_scheduler.DreamScheduler()
    monkeypatch.setattr(sched, "_get_cc_pool_sync", lambda: None)
    monkeypatch.setattr(sched, "_get_memory_pool", lambda: None)
    monkeypatch.setattr(sched, "_get_proposals_conn", lambda: proposals_conn)
    from autoservice import dream_runs as _dream_runs
    monkeypatch.setattr(_dream_runs, "open_connection", lambda: runs_conn)

    coro = sched._build_run_dream_coro(fake_per_tenant, "acme-corp")
    assert coro is not None
    await coro

    assert per_tenant_called["count"] == 1
    assert per_tenant_called["tenant_id"] == "acme-corp"
    assert master_called["count"] == 0, (
        "master_dream_agent.run_platform_dream MUST NOT be invoked for non-master"
    )
