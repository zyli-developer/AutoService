"""POST /api/auth/operator/dev-login tests.

Mirrors tests/auth/test_dev_login.py (admin side) but for the operator dev
bypass: AUTH_DEV_MODE=1 gated, upserts an ``operators`` row if missing, mints
an ``operator_session`` cookie, and appends to the shared audit JSONL.

Fills the M3 gap surfaced when T1S.3 (strict WS cookie validation) landed
without an operator-side dev-login counterpart to admin's AUTH_DEV_MODE
bypass.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autoservice import api_routes, auth, operator_routes, operators


# ── Fixtures (mirror tests/auth/test_operator_routes.py + test_dev_login.py) ─


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    auth.apply_schema(c)
    operators.apply_operators_schema(c)
    operators.migrate_login_tokens_add_role(c)
    yield c
    c.close()


@pytest.fixture()
def app_client(db_conn, monkeypatch, tmp_path) -> TestClient:
    """FastAPI app + both DBs wired to the same in-memory conn, chdir to tmp."""
    monkeypatch.chdir(tmp_path)
    operator_routes._reset_op_db_for_tests(db_conn)
    api_routes._reset_auth_db_for_tests(db_conn)
    app = FastAPI()
    app.include_router(api_routes.api_router)
    yield TestClient(app)
    operator_routes._reset_op_db_for_tests(None)
    api_routes._reset_auth_db_for_tests(None)


@pytest.fixture()
def dev_mode_off(monkeypatch):
    monkeypatch.setattr(operator_routes, "DEV_MODE_ENABLED", False)


@pytest.fixture()
def dev_mode_on(monkeypatch):
    monkeypatch.setattr(operator_routes, "DEV_MODE_ENABLED", True)


# ── Disabled path ─────────────────────────────────────────────────────────


def test_operator_dev_login_returns_404_when_env_unset(
    dev_mode_off, app_client, db_conn
):
    r = app_client.post(
        "/api/auth/operator/dev-login",
        json={"email": "op@dev.local", "tenant_id": "acme"},
    )
    assert r.status_code == 404
    # No operator row auto-created.
    rows = db_conn.execute("SELECT COUNT(*) AS c FROM operators").fetchone()
    assert rows["c"] == 0
    # No session row.
    rows = db_conn.execute(
        "SELECT COUNT(*) AS c FROM operator_sessions"
    ).fetchone()
    assert rows["c"] == 0
    # No cookie.
    assert operators.OPERATOR_SESSION_COOKIE_NAME not in r.cookies


# ── Enabled — payload validation ──────────────────────────────────────────


def test_operator_dev_login_requires_email(dev_mode_on, app_client):
    r = app_client.post(
        "/api/auth/operator/dev-login", json={"tenant_id": "acme"}
    )
    assert r.status_code == 400
    assert "email" in r.json()["error"]


def test_operator_dev_login_requires_tenant_id(dev_mode_on, app_client):
    r = app_client.post(
        "/api/auth/operator/dev-login", json={"email": "op@dev.local"}
    )
    assert r.status_code == 400
    assert "tenant_id" in r.json()["error"]


def test_operator_dev_login_empty_strings_return_400(dev_mode_on, app_client):
    r = app_client.post(
        "/api/auth/operator/dev-login",
        json={"email": "  ", "tenant_id": "acme"},
    )
    assert r.status_code == 400
    r = app_client.post(
        "/api/auth/operator/dev-login",
        json={"email": "op@dev.local", "tenant_id": "  "},
    )
    assert r.status_code == 400


# ── Enabled — happy paths ─────────────────────────────────────────────────


def test_operator_dev_login_autocreates_unknown_operator(
    dev_mode_on, app_client, db_conn
):
    """Unknown (tenant_id, email) → auto-upsert operators row with role=responder."""
    r = app_client.post(
        "/api/auth/operator/dev-login",
        json={"email": "newbie@dev.local", "tenant_id": "acme"},
    )
    assert r.status_code == 200

    body = r.json()
    assert body["ok"] is True
    assert body["redirect"] == "/operator"
    assert body["tenant_id"] == "acme"
    assert body["email"] == "newbie@dev.local"
    assert isinstance(body["operator_id"], str) and body["operator_id"]

    row = db_conn.execute(
        "SELECT id, tenant_id, email, role, status FROM operators"
    ).fetchone()
    assert row["id"] == body["operator_id"]
    assert row["tenant_id"] == "acme"
    assert row["email"] == "newbie@dev.local"
    assert row["role"] == "responder"
    assert row["status"] == "active"


def test_operator_dev_login_reuses_existing_operator(
    dev_mode_on, app_client, db_conn
):
    """Existing (tenant_id, email) → same operator_id returned; no duplicate row."""
    existing = operators.create_operator(
        db_conn,
        tenant_id="acme",
        email="alice@acme.com",
        role="admin",
    )

    r = app_client.post(
        "/api/auth/operator/dev-login",
        json={"email": "alice@acme.com", "tenant_id": "acme"},
    )
    assert r.status_code == 200
    assert r.json()["operator_id"] == existing.id

    count = db_conn.execute(
        "SELECT COUNT(*) AS c FROM operators WHERE tenant_id = 'acme'"
    ).fetchone()["c"]
    assert count == 1


def test_operator_dev_login_email_is_case_insensitive(
    dev_mode_on, app_client, db_conn
):
    operators.create_operator(
        db_conn, tenant_id="acme", email="alice@acme.com", role="responder"
    )
    r = app_client.post(
        "/api/auth/operator/dev-login",
        json={"email": "ALICE@ACME.COM", "tenant_id": "acme"},
    )
    assert r.status_code == 200
    # Still one row — the create_operator already lowercased, and dev-login
    # must normalise before lookup / upsert.
    count = db_conn.execute("SELECT COUNT(*) AS c FROM operators").fetchone()[
        "c"
    ]
    assert count == 1


def test_operator_dev_login_rejects_disabled_operator(
    dev_mode_on, app_client, db_conn
):
    existing = operators.create_operator(
        db_conn, tenant_id="acme", email="ghost@acme.com", role="responder"
    )
    operators.update_operator(db_conn, existing.id, status="disabled")

    r = app_client.post(
        "/api/auth/operator/dev-login",
        json={"email": "ghost@acme.com", "tenant_id": "acme"},
    )
    assert r.status_code == 401
    assert "disabled" in r.json()["error"].lower()


# ── Cookie + session row ──────────────────────────────────────────────────


def test_operator_dev_login_issues_session_row(
    dev_mode_on, app_client, db_conn
):
    r = app_client.post(
        "/api/auth/operator/dev-login",
        json={"email": "op@dev.local", "tenant_id": "acme"},
    )
    assert r.status_code == 200

    rows = db_conn.execute(
        "SELECT operator_id, tenant_id, expires_at, idle_at FROM operator_sessions"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["operator_id"] == r.json()["operator_id"]
    assert rows[0]["tenant_id"] == "acme"


def test_operator_dev_login_sets_cookie_with_expected_attrs(
    dev_mode_on, app_client
):
    r = app_client.post(
        "/api/auth/operator/dev-login",
        json={"email": "op@dev.local", "tenant_id": "acme"},
    )
    assert r.status_code == 200

    header = r.headers.get("set-cookie", "")
    assert f"{operators.OPERATOR_SESSION_COOKIE_NAME}=" in header
    assert "HttpOnly" in header
    assert "samesite=lax" in header.lower()
    assert "path=/" in header.lower()


# ── Audit trail ───────────────────────────────────────────────────────────


def test_operator_dev_login_writes_audit_jsonl_entry(
    dev_mode_on, app_client, tmp_path
):
    r = app_client.post(
        "/api/auth/operator/dev-login",
        json={"email": "op@dev.local", "tenant_id": "acme"},
    )
    assert r.status_code == 200

    log_path = tmp_path / ".autoservice" / "logs" / "auth-devmail.jsonl"
    assert log_path.exists()
    records = [
        json.loads(line) for line in log_path.read_text("utf-8").splitlines()
    ]
    # Only the operator dev-login entry (no admin calls in this test).
    ours = [r for r in records if r["kind"] == "operator_dev_login"]
    assert len(ours) == 1
    rec = ours[0]
    assert rec["email"] == "op@dev.local"
    assert rec["tenant_id"] == "acme"
    assert "operator_id" in rec
    assert "session_token_prefix" in rec
    assert len(rec["session_token_prefix"]) == 8
    # Full token must NOT be logged.
    assert "session_token" not in rec


# ── End-to-end: cookie from dev-login unlocks /api/auth/operator/me ───────


def test_operator_dev_login_cookie_satisfies_me_endpoint(
    dev_mode_on, app_client
):
    r = app_client.post(
        "/api/auth/operator/dev-login",
        json={"email": "e2e@dev.local", "tenant_id": "acme"},
    )
    assert r.status_code == 200

    # TestClient auto-carries the cookie jar into the next request.
    r2 = app_client.get("/api/auth/operator/me")
    assert r2.status_code == 200
    me = r2.json()
    assert me["email"] == "e2e@dev.local"
    assert me["tenant_id"] == "acme"
    assert me["operator_id"] == r.json()["operator_id"]
