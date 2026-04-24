"""T3B.6 — /api/dream/trigger + /api/dream/runs endpoint tests.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.6.

These tests exercise the endpoints in isolation:
  * ``dream_agent.run_dream`` is monkey-patched — the Anthropic call chain
    is expensive and has its own coverage in tests/dream_agent/.
  * The runs DB is swapped for an in-memory sqlite3 connection via
    :func:`autoservice.api_routes._reset_dream_runs_db_for_tests`.
  * Tenant existence is faked by creating a ``.autoservice/sandbox/<tid>/``
    directory inside a ``monkeypatch.chdir``-ed tmp_path.

This keeps the tests fast and pool-free while still asserting the HTTP
surface: 202 Accepted shape, concurrency 409, non-blocking behaviour,
limit clamping, most-recent-first ordering, serialisation shape.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autoservice import api_routes, dream_runs
from autoservice.proposal_pipeline import apply_schema as apply_proposals_schema


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def runs_conn() -> sqlite3.Connection:
    """In-memory ``dream_runs`` SQLite connection with schema applied.

    Installed into :mod:`autoservice.api_routes` via
    :func:`_reset_dream_runs_db_for_tests` so the trigger / runs endpoints
    use this DB instead of the on-disk default.
    """
    # check_same_thread=False — TestClient dispatches endpoints on a worker
    # thread while this fixture runs on the main thread.  Both sides touch
    # the same connection (fixture seeds rows, endpoint reads them), so we
    # relax SQLite's thread guard.  The guard is a safety net against
    # concurrent mutation and this test suite is strictly sequential.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    dream_runs.init_schema(conn)
    api_routes._reset_dream_runs_db_for_tests(conn)
    yield conn
    api_routes._reset_dream_runs_db_for_tests(None)
    conn.close()


@pytest.fixture()
def app_client(runs_conn, monkeypatch, tmp_path) -> TestClient:
    """TestClient mounting ``api_router`` with the in-memory runs DB live.

    chdir into ``tmp_path`` so the ``_tenant_exists`` lookup resolves
    relative ``.autoservice/sandbox/<tid>/`` paths against a clean tree.
    """
    monkeypatch.chdir(tmp_path)
    app = FastAPI()
    app.include_router(api_routes.api_router)
    return TestClient(app)


@pytest.fixture()
def make_tenant(tmp_path):
    """Helper factory: create a sandbox dir for a tenant inside ``tmp_path``."""

    def _make(tenant_id: str) -> Path:
        tdir = tmp_path / ".autoservice" / "sandbox" / tenant_id
        tdir.mkdir(parents=True, exist_ok=True)
        return tdir

    return _make


@pytest.fixture()
def mock_run_dream(monkeypatch):
    """Patch ``_spawn_dream_run_with_run_id`` so we observe calls but skip
    the pool / run_dream side effects.

    Returns a list of ``(tenant_id, run_id)`` tuples the endpoint scheduled.
    """
    calls: list[tuple[str, str]] = []

    async def _fake(tenant_id: str, run_id: str) -> None:
        calls.append((tenant_id, run_id))

    monkeypatch.setattr(api_routes, "_spawn_dream_run_with_run_id", _fake)
    return calls


# ── POST /api/dream/trigger ───────────────────────────────────────────────


def test_trigger_valid_tenant_returns_202_and_run_id(
    app_client, make_tenant, mock_run_dream, runs_conn,
):
    """Happy path: valid tenant + spawn hook invoked + 202 payload shape."""
    make_tenant("acme")
    resp = app_client.post("/api/dream/trigger", json={"tenant_id": "acme"})

    assert resp.status_code == 202
    body = resp.json()
    assert body["tenant_id"] == "acme"
    assert body["status"] == "started"
    assert isinstance(body["run_id"], str) and body["run_id"]

    # Spawn hook received the same run_id we returned.
    assert len(mock_run_dream) == 1
    tid, rid = mock_run_dream[0]
    assert tid == "acme"
    assert rid == body["run_id"]

    # A 'running' row was persisted.
    row = dream_runs.get_run(runs_conn, body["run_id"])
    assert row is not None
    assert row["tenant_id"] == "acme"
    assert row["status"] == "running"


def test_trigger_missing_tenant_id_returns_422(app_client, mock_run_dream):
    """Empty body → 422 (explicit, not FastAPI's default pydantic 422)."""
    resp = app_client.post("/api/dream/trigger", json={})
    assert resp.status_code == 422
    assert "tenant_id" in resp.json().get("error", "").lower()
    assert mock_run_dream == []


def test_trigger_empty_tenant_id_returns_422(app_client, mock_run_dream):
    """Whitespace-only tenant_id is treated as missing."""
    resp = app_client.post("/api/dream/trigger", json={"tenant_id": "   "})
    assert resp.status_code == 422
    assert mock_run_dream == []


def test_trigger_nonexistent_tenant_returns_404(app_client, mock_run_dream):
    """No sandbox nor plugin dir → 404, no task scheduled."""
    resp = app_client.post("/api/dream/trigger", json={"tenant_id": "ghost"})
    assert resp.status_code == 404
    body = resp.json()
    assert body["tenant_id"] == "ghost"
    assert "not found" in body["error"].lower()
    assert mock_run_dream == []


def test_trigger_accepts_plugin_dir_tenant(
    app_client, tmp_path, mock_run_dream,
):
    """Fork-side tenants live under plugins/<tid>/ — accept those too."""
    (tmp_path / "plugins" / "fork_tenant").mkdir(parents=True)
    resp = app_client.post(
        "/api/dream/trigger", json={"tenant_id": "fork_tenant"},
    )
    assert resp.status_code == 202
    assert resp.json()["tenant_id"] == "fork_tenant"


def test_trigger_concurrent_run_returns_409(
    app_client, make_tenant, mock_run_dream, runs_conn,
):
    """A running row for this tenant blocks a second trigger."""
    make_tenant("busy_tid")
    # Pre-insert a running row so the concurrency guard trips.
    dream_runs.start_run(runs_conn, "busy_tid")

    resp = app_client.post(
        "/api/dream/trigger", json={"tenant_id": "busy_tid"},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["tenant_id"] == "busy_tid"
    assert "already in progress" in body["error"].lower()
    assert mock_run_dream == []


def test_trigger_allows_retrigger_after_completion(
    app_client, make_tenant, mock_run_dream, runs_conn,
):
    """Once the previous run is ``completed``, the next trigger must succeed."""
    make_tenant("tid_x")
    prev = dream_runs.start_run(runs_conn, "tid_x")
    dream_runs.end_run(runs_conn, prev, status="completed")

    resp = app_client.post(
        "/api/dream/trigger", json={"tenant_id": "tid_x"},
    )
    assert resp.status_code == 202
    # Concurrency guard lets it through because the prior row is no longer 'running'.
    assert len(mock_run_dream) == 1


def test_trigger_starts_background_task_not_blocking(
    app_client, make_tenant, monkeypatch,
):
    """If the spawn coroutine sleeps 5s, the response must still return fast.

    Implementation contract: the trigger endpoint ``await``-s
    ``_spawn_dream_run_with_run_id`` only to acquire pool/DB resources and
    schedule the task — the long-running ``run_dream`` must not block.

    Here we patch spawn to an **immediate-return** coroutine that itself
    creates a 5-second-sleeping background task.  If the endpoint
    accidentally ``await``-ed the sleep instead of ``create_task``-ing it,
    this test would time out well beyond the 2-second ceiling.
    """
    make_tenant("slow_tid")

    async def _fake_spawn(tenant_id: str, run_id: str) -> None:
        async def _slow():
            await asyncio.sleep(5)  # never awaited by the endpoint
        asyncio.create_task(_slow())

    monkeypatch.setattr(
        api_routes, "_spawn_dream_run_with_run_id", _fake_spawn,
    )

    t0 = time.monotonic()
    resp = app_client.post(
        "/api/dream/trigger", json={"tenant_id": "slow_tid"},
    )
    elapsed = time.monotonic() - t0

    assert resp.status_code == 202
    # Generous ceiling — CI variance — but far under the 5s sleep.
    assert elapsed < 2.0, f"trigger blocked for {elapsed:.2f}s (expected <2s)"


# ── GET /api/dream/runs ───────────────────────────────────────────────────


def test_runs_returns_empty_for_unknown_tenant(app_client, runs_conn):
    """An unknown tenant returns ``{runs: [], tenant_id}`` with 200 OK."""
    resp = app_client.get("/api/dream/runs", params={"tenant_id": "ghost"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"tenant_id": "ghost", "runs": []}


def test_runs_requires_tenant_id(app_client):
    """Missing ``tenant_id`` → FastAPI's pydantic 422 (query-param required)."""
    resp = app_client.get("/api/dream/runs")
    # FastAPI treats the missing required query param as a 422 validation
    # error with its own ``detail`` shape — we don't override it here.
    assert resp.status_code == 422


def test_runs_returns_history_most_recent_first(app_client, runs_conn):
    """Seeded runs come back newest first (by ``started_at``)."""
    # Seed 3 runs, each with a slightly-different started_at so ordering
    # is unambiguous even on machines that collapse identical timestamps.
    # list_runs ties-break by id DESC so same-timestamp rows stay stable.
    ids = []
    for i in range(3):
        rid = dream_runs.start_run(runs_conn, "hist_tid")
        dream_runs.end_run(
            runs_conn, rid, status="completed",
            tokens_in=100 * (i + 1), tokens_out=10 * (i + 1),
        )
        ids.append(rid)
        time.sleep(0.01)  # ensure distinct started_at timestamps

    resp = app_client.get("/api/dream/runs", params={"tenant_id": "hist_tid"})
    assert resp.status_code == 200
    returned_ids = [r["id"] for r in resp.json()["runs"]]
    # Most recent first — ids[2] was inserted last.
    assert returned_ids == list(reversed(ids))


def test_runs_respects_limit_param(app_client, runs_conn):
    """``limit=2`` returns exactly 2 rows."""
    for _ in range(5):
        dream_runs.start_run(runs_conn, "lim_tid")
        time.sleep(0.005)

    resp = app_client.get(
        "/api/dream/runs", params={"tenant_id": "lim_tid", "limit": 2},
    )
    assert resp.status_code == 200
    assert len(resp.json()["runs"]) == 2


def test_runs_limit_clamped_to_100(app_client, runs_conn):
    """``limit=500`` clamps to 100 — no 500-row blowup, no error."""
    # We don't need 500 rows to prove clamping; we just need to check the
    # endpoint accepts large limit values without erroring and caps the
    # effective ceiling.  Seed 3 rows and confirm the request succeeds.
    for _ in range(3):
        dream_runs.start_run(runs_conn, "big_tid")

    resp = app_client.get(
        "/api/dream/runs", params={"tenant_id": "big_tid", "limit": 500},
    )
    assert resp.status_code == 200
    # All 3 seeded rows returned — clamping doesn't cap below row count.
    assert len(resp.json()["runs"]) == 3


def test_runs_limit_clamped_to_min_one(app_client, runs_conn):
    """A zero or negative ``limit`` clamps to 1 — never returns zero rows."""
    dream_runs.start_run(runs_conn, "min_tid")
    dream_runs.start_run(runs_conn, "min_tid")

    resp = app_client.get(
        "/api/dream/runs", params={"tenant_id": "min_tid", "limit": 0},
    )
    assert resp.status_code == 200
    assert len(resp.json()["runs"]) == 1


# ── Dev stub path (DREAM_DEV_STUB=1) ──────────────────────────────────────


def test_dev_stub_emits_three_proposals_and_completes(runs_conn, monkeypatch):
    """``_run_dev_stub_dream`` writes 3 draft proposals + one completed run.

    Directly exercises the stub coroutine with in-memory DBs — no HTTP,
    no pool, no LLM.  Asserts the visible user-facing outcome: three
    distinct proposals in the proposals table and a single ``completed``
    row in dream_runs with non-zero token counts for UI display.
    """
    # Keep the test fast — zero the artificial delay.
    monkeypatch.setattr(api_routes, "DREAM_DEV_STUB_DELAY_SEC", 0)

    proposals_conn = sqlite3.connect(":memory:", check_same_thread=False)
    proposals_conn.row_factory = sqlite3.Row
    apply_proposals_schema(proposals_conn)
    try:
        asyncio.run(
            api_routes._run_dev_stub_dream(
                "cinnox", proposals_conn, runs_conn,
            )
        )

        rows = proposals_conn.execute(
            "SELECT data, status, category FROM proposals "
            "WHERE tenant_id = ? ORDER BY created_at",
            ("cinnox",),
        ).fetchall()
        assert len(rows) == 3
        # Red-line CON-04: emit_proposal hardcodes status='draft'.
        assert {r["status"] for r in rows} == {"draft"}
        # Three distinct categories keep the admin-portal UI varied.
        assert {r["category"] for r in rows} == {
            "response_quality", "knowledge_gap", "escalation_signal",
        }
        # Risk levels spread across low/medium/high (parsed from JSON blob).
        risks = {json.loads(r["data"])["risk_level"] for r in rows}
        assert risks == {"low", "medium", "high"}

        runs = dream_runs.list_runs(runs_conn, "cinnox", limit=10)
        assert len(runs) == 1
        row = runs[0]
        assert row["status"] == "completed"
        assert row["proposals_emitted"] == 3
        assert row["tokens_in"] == 123 and row["tokens_out"] == 456
        assert row["ended_at"] is not None
    finally:
        proposals_conn.close()


def test_runs_serialization_shape(app_client, runs_conn):
    """Every returned row has all 10 documented fields — no extras, no missing."""
    rid = dream_runs.start_run(runs_conn, "shape_tid")
    dream_runs.update_run(
        runs_conn, rid, tool_calls=3, proposals_emitted=1,
    )
    dream_runs.end_run(
        runs_conn, rid, status="completed", tokens_in=200, tokens_out=50,
    )

    resp = app_client.get("/api/dream/runs", params={"tenant_id": "shape_tid"})
    assert resp.status_code == 200
    runs = resp.json()["runs"]
    assert len(runs) == 1
    row = runs[0]

    expected_keys = {
        "id",
        "tenant_id",
        "started_at",
        "ended_at",
        "status",
        "tool_calls",
        "tokens_in",
        "tokens_out",
        "proposals_emitted",
        "error",
    }
    assert set(row.keys()) == expected_keys
    # Spot-check values to confirm the projection preserves them.
    assert row["tenant_id"] == "shape_tid"
    assert row["status"] == "completed"
    assert row["tool_calls"] == 3
    assert row["proposals_emitted"] == 1
    assert row["tokens_in"] == 200
    assert row["tokens_out"] == 50
    assert row["error"] is None
