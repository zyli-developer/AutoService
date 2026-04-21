"""Tests for T2S.8 — master dream skeleton + scheduler routing.

Covers:
- ``master_dream_agent.run_platform_dream`` emits platform_level proposal
  with CON-04 enforced (status='draft' hardcoded)
- Routing guard: calling with non-master tenant_id raises
- DreamScheduler._build_run_dream_coro routes _master → master_dream_agent
- Per-tenant dream path still works for regular tenants
"""
from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock

import pytest

from autoservice import (
    bootstrap,
    dream_runs,
    dream_scheduler,
    master_dream_agent,
    proposal_pipeline,
)


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
    ids = await master_dream_agent.run_platform_dream(
        tenant_id=bootstrap.MASTER_TENANT_ID,
        cc_pool=None,
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
    uniformly.
    """
    ids = await master_dream_agent.run_platform_dream(
        tenant_id=bootstrap.MASTER_TENANT_ID,
        cc_pool=None,
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
    import json as _json

    # Seed a tenant
    proposals_conn.execute(
        "INSERT INTO proposals (id, created_at, data, status, category, tenant_id) "
        "VALUES (?, ?, ?, 'draft', 'workflow', 'acme')",
        ("p-1", "2026-04-21T00:00:00", _json.dumps({"id": "p-1"})),
    )
    proposals_conn.commit()

    ids = await master_dream_agent.run_platform_dream(
        tenant_id=bootstrap.MASTER_TENANT_ID,
        cc_pool=None, mempool=None,
        proposals_conn=proposals_conn, runs_conn=runs_conn,
    )
    # Fetch emitted proposal and check evidence carries signal snapshot
    row = proposals_conn.execute(
        "SELECT data FROM proposals WHERE id = ?", (ids[0],)
    ).fetchone()
    data = _json.loads(row["data"])
    assert "tenant_count" in data["evidence"]
    assert "total_proposals" in data["evidence"]


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
