"""T5B.3 — GET /api/auth/verify tests.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §5.2 + §5.7.

Valid token → 302 + Set-Cookie + session row.
Invalid / expired / already-consumed token → 401, and expired tokens are
NOT burned (so operators can debug).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autoservice import api_routes, auth


@pytest.fixture()
def auth_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    auth.apply_schema(conn)
    api_routes._reset_auth_db_for_tests(conn)
    yield conn
    api_routes._reset_auth_db_for_tests(None)
    conn.close()


@pytest.fixture()
def app_client(auth_conn) -> TestClient:
    app = FastAPI()
    app.include_router(api_routes.api_router)
    # Don't follow redirects so we can assert the Location + Set-Cookie
    # headers directly.
    return TestClient(app, follow_redirects=False)


# ── /verify ───────────────────────────────────────────────────────────────


def test_valid_token_302s_with_set_cookie_and_creates_session(
    app_client, auth_conn
):
    token = auth.issue_login_token(auth_conn, "admin@example.com", tenant_id="acme")

    r = app_client.get(
        "/api/auth/verify",
        params={"token": token, "redirect": "/t/acme/admin"},
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/t/acme/admin"
    set_cookie = r.headers.get("set-cookie", "")
    assert f"{api_routes.AUTH_SESSION_COOKIE}=" in set_cookie
    lower = set_cookie.lower()
    assert "httponly" in lower
    assert "samesite=lax" in lower

    # Session row created.
    rows = auth_conn.execute("SELECT * FROM sessions").fetchall()
    assert len(rows) == 1
    assert rows[0]["admin_email"] == "admin@example.com"
    assert rows[0]["tenant_id"] == "acme"


def test_invalid_token_returns_401_and_no_session_created(
    app_client, auth_conn
):
    r = app_client.get(
        "/api/auth/verify",
        params={"token": "definitely-not-real", "redirect": "/admin"},
    )
    assert r.status_code == 401
    assert "Invalid or expired" in r.text

    count = auth_conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"]
    assert count == 0


def test_expired_token_returns_401_and_is_not_burned(
    app_client, auth_conn, monkeypatch
):
    # Issue a token that is already "ancient" by writing past expiry manually.
    past = datetime.now(tz=timezone.utc) - timedelta(minutes=30)
    token = "expired-test-token-abc"
    auth_conn.execute(
        """INSERT INTO login_tokens
             (token, admin_email, tenant_id, created_at, expires_at, consumed_at)
           VALUES (?, ?, ?, ?, ?, NULL)""",
        (
            token,
            "admin@example.com",
            None,
            past.isoformat(),
            (past + timedelta(minutes=10)).isoformat(),
        ),
    )
    auth_conn.commit()

    r = app_client.get("/api/auth/verify", params={"token": token})
    assert r.status_code == 401

    # CRITICAL: expired tokens stay un-burned for debuggability.
    row = auth_conn.execute(
        "SELECT consumed_at FROM login_tokens WHERE token = ?", (token,)
    ).fetchone()
    assert row["consumed_at"] is None


def test_already_consumed_token_returns_401(app_client, auth_conn):
    """Second verify of the same token must fail (replay defence)."""
    token = auth.issue_login_token(auth_conn, "admin@example.com")

    r1 = app_client.get("/api/auth/verify", params={"token": token})
    assert r1.status_code == 302

    r2 = app_client.get("/api/auth/verify", params={"token": token})
    assert r2.status_code == 401


def test_missing_token_returns_422(app_client):
    r = app_client.get("/api/auth/verify")
    assert r.status_code == 422
    assert "token" in r.json()["error"]
