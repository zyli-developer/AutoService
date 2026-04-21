"""T5B.5 — require_tenant_access middleware tests.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §5.3 + §5.4.

The middleware is a FastAPI ``Depends``-style helper (plus a factory for
routes with a static target).  It reads the ``auth_session`` cookie, looks
up the session via :func:`autoservice.auth.lookup_session`, and enforces:

    - 401 when no session (missing / unknown / expired / revoked).
    - Allowed when session.tenant_id matches target, or session is tier-0
      (NULL tenant_id), or target is a deployment-internal tenant (``_`` prefix).
    - 403 otherwise.

Returns an :class:`AuthContext` dataclass to the route handler.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.testclient import TestClient

from autoservice import api_routes, auth


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def auth_conn() -> sqlite3.Connection:
    """In-memory auth DB, injected into api_routes for the middleware."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    auth.apply_schema(conn)
    api_routes._reset_auth_db_for_tests(conn)
    yield conn
    api_routes._reset_auth_db_for_tests(None)
    conn.close()


@pytest.fixture()
def app_client(auth_conn) -> TestClient:
    """FastAPI app with a protected route exercising require_tenant_access."""
    app = FastAPI()

    # Route 1: target tenant comes from the path -> dependency picks it up.
    @app.get("/protected/{tenant_id}")
    async def protected_path(
        tenant_id: str,
        request: Request,
        ctx: auth.AuthContext = Depends(auth.require_tenant_access),
    ):
        return {
            "admin_email": ctx.admin_email,
            "tenant_id": ctx.tenant_id,
            "tier": ctx.tier,
            "target": tenant_id,
        }

    # Route 2: target tenant known statically at route-definition.
    @app.get("/protected-static")
    async def protected_static(
        ctx: auth.AuthContext = Depends(auth.require_tenant_access_for("acme")),
    ):
        return {"admin_email": ctx.admin_email, "tier": ctx.tier}

    # Route 3: no target tenant (pure auth check).
    @app.get("/protected-any")
    async def protected_any(
        ctx: auth.AuthContext = Depends(auth.require_tenant_access),
    ):
        return {"admin_email": ctx.admin_email, "tier": ctx.tier}

    return TestClient(app)


# ── Tests ─────────────────────────────────────────────────────────────────


def test_anon_no_cookie_returns_401(app_client):
    """No cookie → 401 with the documented error shape."""
    r = app_client.get("/protected/acme")
    assert r.status_code == 401
    assert r.json()["detail"] == {"error": "unauthenticated"}


def test_invalid_session_cookie_returns_401(app_client):
    """Cookie value not in sessions table → 401."""
    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, "bogus-session-id")
    r = app_client.get("/protected/acme")
    assert r.status_code == 401


def test_valid_session_matching_tenant_is_allowed(app_client, auth_conn):
    """Session.tenant_id == target → allowed, AuthContext.tier==1."""
    sid = auth.create_session(auth_conn, "admin@acme.com", tenant_id="acme")
    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, sid)

    r = app_client.get("/protected/acme")
    assert r.status_code == 200
    body = r.json()
    assert body["admin_email"] == "admin@acme.com"
    assert body["tenant_id"] == "acme"
    assert body["tier"] == 1
    assert body["target"] == "acme"


def test_valid_session_cross_tenant_denied_403(app_client, auth_conn):
    """Session.tenant_id='acme', target='other' → 403."""
    sid = auth.create_session(auth_conn, "admin@acme.com", tenant_id="acme")
    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, sid)

    r = app_client.get("/protected/other")
    assert r.status_code == 403
    assert r.json()["detail"] == {"error": "cross-tenant access denied"}


def test_tier0_session_bypass_any_target(app_client, auth_conn):
    """NULL session.tenant_id → tier 0, can access any target."""
    sid = auth.create_session(auth_conn, "platform@ops.com", tenant_id=None)
    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, sid)

    # Targets an unrelated tenant — tier-0 bypass should grant access.
    r = app_client.get("/protected/some-random-tenant")
    assert r.status_code == 200
    body = r.json()
    assert body["admin_email"] == "platform@ops.com"
    assert body["tier"] == 0
    assert body["tenant_id"] is None


def test_revoked_session_returns_401(app_client, auth_conn):
    """Revoked session → lookup_session returns None → 401."""
    sid = auth.create_session(auth_conn, "admin@acme.com", tenant_id="acme")
    auth.revoke_session(auth_conn, sid)

    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, sid)
    r = app_client.get("/protected/acme")
    assert r.status_code == 401


def test_expired_session_returns_401(app_client, auth_conn):
    """Session row with expires_at in the past → 401."""
    # Insert a manually-aged session row.
    past = datetime.now(tz=timezone.utc) - timedelta(days=31)
    sid = "expired-session-xyz"
    auth_conn.execute(
        """INSERT INTO sessions
             (session_id, admin_email, tenant_id, created_at, expires_at, revoked_at)
           VALUES (?, ?, ?, ?, ?, NULL)""",
        (sid, "admin@acme.com", "acme", past.isoformat(), past.isoformat()),
    )
    auth_conn.commit()

    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, sid)
    r = app_client.get("/protected/acme")
    assert r.status_code == 401


def test_internal_tenant_prefix_bypass(app_client, auth_conn):
    """Session.tenant_id='acme' → target='_local_admin' (internal) → allowed.

    Spec §5.3 Rule 3: a deployment-internal tenant (underscore prefix) is
    in-scope for any authenticated admin.  This is how a tier-1 fork admin
    reaches ``_local_admin`` via ChatTab.
    """
    sid = auth.create_session(auth_conn, "admin@acme.com", tenant_id="acme")
    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, sid)

    r = app_client.get("/protected/_local_admin")
    assert r.status_code == 200
    body = r.json()
    assert body["target"] == "_local_admin"


def test_static_factory_matches_session_tenant(app_client, auth_conn):
    """require_tenant_access_for('acme') lets the matching tenant in."""
    sid = auth.create_session(auth_conn, "admin@acme.com", tenant_id="acme")
    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, sid)

    r = app_client.get("/protected-static")
    assert r.status_code == 200
    assert r.json()["admin_email"] == "admin@acme.com"


def test_static_factory_denies_mismatch(app_client, auth_conn):
    """require_tenant_access_for('acme') rejects sessions for a different tenant."""
    sid = auth.create_session(auth_conn, "admin@other.com", tenant_id="other")
    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, sid)

    r = app_client.get("/protected-static")
    assert r.status_code == 403


def test_no_target_dependency_only_validates_auth(app_client, auth_conn):
    """When a route has no tenant_id in path and uses the base helper, it acts as auth-only."""
    sid = auth.create_session(auth_conn, "admin@acme.com", tenant_id="acme")
    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, sid)

    r = app_client.get("/protected-any")
    assert r.status_code == 200
    assert r.json()["admin_email"] == "admin@acme.com"
