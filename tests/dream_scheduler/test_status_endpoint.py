"""Tests for GET /api/dream/status (M3 T4S.3b · dream-ui-augmentation P0 backend).

Contract: exposes dream_scheduler.should_trigger() reason_code to admin-portal.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoservice import api_routes, dream_runs


@pytest.fixture()
def runs_conn():
    conn = dream_runs.open_connection(db_path=None)  # module default
    yield conn


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Test client with isolated dream_runs DB."""
    # Isolate dream_runs DB per test
    db_path = tmp_path / "dream_runs.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(dream_runs.SCHEMA)
    api_routes._reset_dream_runs_db_for_tests(conn) if hasattr(
        api_routes, "_reset_dream_runs_db_for_tests"
    ) else None
    # Alternative: set the module's cached connection directly
    api_routes._dream_runs_db_conn = conn

    monkeypatch.chdir(tmp_path)

    app = FastAPI()
    app.include_router(api_routes.api_router)
    try:
        yield TestClient(app)
    finally:
        api_routes._dream_runs_db_conn = None


# ──────────────────────────────────────────────────────────────────────────
# Parameter validation
# ──────────────────────────────────────────────────────────────────────────


def test_status_requires_tenant_id(client):
    r = client.get("/api/dream/status")
    assert r.status_code == 422


def test_status_empty_tenant_id(client):
    r = client.get("/api/dream/status", params={"tenant_id": "   "})
    assert r.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# Response shape
# ──────────────────────────────────────────────────────────────────────────


def test_status_unknown_tenant_returns_never_active(client):
    """Tenant with no config, no runs → reason_code='never_active' (default)."""
    r = client.get("/api/dream/status", params={"tenant_id": "ghost-tenant"})
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "ghost-tenant"
    assert body["running"] is False
    # No memory + no config → should_trigger returns 'never_active'
    assert body["reason_code"] in ("never_active", "manual_only", "coverage_disabled")
    assert body["last_run_summary"] is None


def test_status_response_shape_has_all_documented_fields(client):
    r = client.get("/api/dream/status", params={"tenant_id": "acme"})
    assert r.status_code == 200
    body = r.json()
    for field in (
        "tenant_id", "running", "reason_code",
        "last_run_summary", "next_eligible_at",
    ):
        assert field in body, f"missing field: {field}"


# ──────────────────────────────────────────────────────────────────────────
# Last run summary
# ──────────────────────────────────────────────────────────────────────────


def test_status_includes_last_run_summary(client):
    # Seed a completed run (tool_calls/proposals_emitted not part of end_run signature)
    conn = api_routes._dream_runs_db_conn
    run_id = dream_runs.start_run(conn, "acme")
    dream_runs.end_run(
        conn, run_id, status="completed",
        tokens_in=100, tokens_out=50,
    )

    r = client.get("/api/dream/status", params={"tenant_id": "acme"})
    assert r.status_code == 200
    summary = r.json()["last_run_summary"]
    assert summary is not None
    assert summary["run_id"] == run_id
    assert summary["status"] == "completed"
    # tool_calls / proposals_emitted may be None — end_run doesn't set them


def test_status_running_true_when_in_flight_run_exists(client):
    """In-flight (status='running') run → running=True."""
    conn = api_routes._dream_runs_db_conn
    dream_runs.start_run(conn, "live-tenant")  # unterminated = running

    r = client.get("/api/dream/status", params={"tenant_id": "live-tenant"})
    body = r.json()
    assert body["running"] is True


def test_status_running_false_when_no_in_flight(client):
    conn = api_routes._dream_runs_db_conn
    rid = dream_runs.start_run(conn, "t1")
    dream_runs.end_run(conn, rid, status="completed")

    r = client.get("/api/dream/status", params={"tenant_id": "t1"})
    assert r.json()["running"] is False


# ──────────────────────────────────────────────────────────────────────────
# reason_code vocabulary — smoke-test the mapping works
# ──────────────────────────────────────────────────────────────────────────


def test_reason_code_is_snake_case(client):
    r = client.get("/api/dream/status", params={"tenant_id": "any-tenant"})
    body = r.json()
    rc = body["reason_code"]
    assert isinstance(rc, str)
    assert rc.islower()
    # Vocabulary from dream_scheduler.should_trigger docstring
    assert rc in {
        "manual_only", "already_running", "cool_down_active",
        "coverage_disabled", "insufficient_signal", "never_active",
        "not_idle", "idle", "scheduled_hit", "scheduled_miss",
        "unknown_trigger",
    }


# ──────────────────────────────────────────────────────────────────────────
# Defensive fallback — scheduler error doesn't 500
# ──────────────────────────────────────────────────────────────────────────


def test_status_graceful_fallback_on_scheduler_error(client, monkeypatch):
    """If should_trigger raises, endpoint must still return 200 with a
    sane default instead of 500 — admin-portal UI mustn't white-screen."""
    from autoservice import dream_scheduler

    def _boom(*a, **kw):
        raise RuntimeError("scheduler exploded")

    monkeypatch.setattr(dream_scheduler, "should_trigger", _boom)

    r = client.get("/api/dream/status", params={"tenant_id": "acme"})
    assert r.status_code == 200
    # Graceful fallback returns never_active + running=False (no 500)
    assert r.json()["reason_code"] == "never_active"
    assert r.json()["running"] is False
