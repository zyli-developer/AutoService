"""T5B.4 — POST /api/auth/logout tests.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §5.2.

Always 204 (idempotent). Cookie is cleared; session is revoked when present.
Unknown / already-revoked / missing cookie paths all succeed silently.
"""
from __future__ import annotations

import sqlite3

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
    return TestClient(app)


# ── /logout ───────────────────────────────────────────────────────────────


def test_authenticated_logout_clears_cookie_and_revokes_session(
    app_client, auth_conn
):
    sid = auth.create_session(auth_conn, "admin@example.com", tenant_id="acme")

    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, sid)
    r = app_client.post("/api/auth/logout")
    assert r.status_code == 204

    # Cookie cleared via Max-Age=0.
    set_cookie = r.headers.get("set-cookie", "")
    assert f"{api_routes.AUTH_SESSION_COOKIE}=" in set_cookie
    assert "max-age=0" in set_cookie.lower()

    # Session row has revoked_at populated.
    row = auth_conn.execute(
        "SELECT revoked_at FROM sessions WHERE session_id = ?", (sid,)
    ).fetchone()
    assert row["revoked_at"] is not None

    # lookup_session now returns None.
    assert auth.lookup_session(auth_conn, sid) is None


def test_logout_without_cookie_is_idempotent_204(app_client, auth_conn):
    r = app_client.post("/api/auth/logout")
    assert r.status_code == 204

    set_cookie = r.headers.get("set-cookie", "")
    assert "max-age=0" in set_cookie.lower()

    # No sessions table mutations.
    count = auth_conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"]
    assert count == 0


def test_logout_with_already_revoked_session_is_idempotent_204(
    app_client, auth_conn
):
    sid = auth.create_session(auth_conn, "admin@example.com", tenant_id="acme")
    auth.revoke_session(auth_conn, sid)

    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, sid)
    r = app_client.post("/api/auth/logout")
    assert r.status_code == 204

    # revoked_at should still be set (no-op on the second revoke, no error).
    row = auth_conn.execute(
        "SELECT revoked_at FROM sessions WHERE session_id = ?", (sid,)
    ).fetchone()
    assert row["revoked_at"] is not None
