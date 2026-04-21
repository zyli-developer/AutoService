"""Integration tests for ``autoservice.operator_routes`` — login + CRUD (M3 T1S.2 + T1S.4).

Uses FastAPI TestClient with an in-memory sqlite3 connection injected via
``_reset_op_db_for_tests`` + ``api_routes._reset_auth_db_for_tests`` to keep
the suite hermetic (never touches the on-disk ``auth.db``).
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoservice import api_routes, auth, operator_routes, operators


# ──────────────────────────────────────────────────────────────────────────
# App fixture + DB injection
# ──────────────────────────────────────────────────────────────────────────


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
def app(db_conn) -> FastAPI:
    """Minimal FastAPI app with api_router mounted (includes operator_router).

    Both operator_routes and api_routes point at the same injected in-memory
    conn so admin auth_session + operator magic-links live in one DB.
    """
    operator_routes._reset_op_db_for_tests(db_conn)
    api_routes._reset_auth_db_for_tests(db_conn)

    app = FastAPI()
    app.include_router(api_routes.api_router)

    yield app

    operator_routes._reset_op_db_for_tests(None)
    api_routes._reset_auth_db_for_tests(None)


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def seed_operator(db_conn):
    """Seed an active operator and return the :class:`Operator`."""
    return operators.create_operator(
        db_conn,
        tenant_id="acme",
        email="alice@acme.com",
        role="responder",
    )


@pytest.fixture()
def admin_session_cookie(db_conn):
    """Create an admin session row and return the cookie value."""
    session_id = auth.create_session(
        db_conn, "admin@acme.com", tenant_id="acme"
    )
    return session_id


# ──────────────────────────────────────────────────────────────────────────
# Login flow (T1S.2)
# ──────────────────────────────────────────────────────────────────────────


def test_request_login_returns_anti_enumeration_shape(client, db_conn, seed_operator):
    # Known operator
    r1 = client.post(
        "/api/auth/operator/request-login",
        json={"email": "alice@acme.com", "tenant_id": "acme"},
    )
    assert r1.status_code == 200
    assert r1.json() == {"status": "sent", "delivered": "log"}

    # Unknown operator — SAME response shape
    r2 = client.post(
        "/api/auth/operator/request-login",
        json={"email": "ghost@acme.com", "tenant_id": "acme"},
    )
    assert r2.status_code == 200
    assert r2.json() == r1.json()


def test_request_login_persists_token_only_for_known_operator(
    client, db_conn, seed_operator
):
    client.post(
        "/api/auth/operator/request-login",
        json={"email": "alice@acme.com", "tenant_id": "acme"},
    )
    rows = db_conn.execute(
        "SELECT admin_email, role FROM login_tokens WHERE admin_email = ?",
        ("alice@acme.com",),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["role"] == "operator"

    # Unknown email — no row persisted
    client.post(
        "/api/auth/operator/request-login",
        json={"email": "ghost@acme.com", "tenant_id": "acme"},
    )
    rows2 = db_conn.execute(
        "SELECT admin_email FROM login_tokens WHERE admin_email = ?",
        ("ghost@acme.com",),
    ).fetchall()
    assert len(rows2) == 0


def test_request_login_requires_email_and_tenant_id(client):
    r = client.post("/api/auth/operator/request-login", json={})
    assert r.status_code == 422
    r = client.post("/api/auth/operator/request-login", json={"email": "x@y"})
    assert r.status_code == 422
    r = client.post(
        "/api/auth/operator/request-login", json={"tenant_id": "acme"}
    )
    assert r.status_code == 422


def test_verify_consumes_token_and_sets_cookie(client, db_conn, seed_operator, caplog):
    # Issue token directly (bypass request-login's dev log grep)
    token = operators.issue_operator_login_token(
        db_conn, operator_email="alice@acme.com", tenant_id="acme"
    )

    r = client.get(
        f"/api/auth/operator/verify?token={token}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/operator"

    cookie = r.cookies.get(operators.OPERATOR_SESSION_COOKIE_NAME)
    assert cookie is not None and len(cookie) > 20

    # Token is burned — second consume fails (returns 401)
    r2 = client.get(
        f"/api/auth/operator/verify?token={token}",
        follow_redirects=False,
    )
    assert r2.status_code == 401


def test_verify_rejects_admin_token(client, db_conn, seed_operator):
    """Admin magic-link MUST NOT authenticate as operator (role gate)."""
    admin_token = auth.issue_login_token(
        db_conn, "admin@acme.com", tenant_id="acme"
    )
    r = client.get(
        f"/api/auth/operator/verify?token={admin_token}",
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_verify_rejects_missing_token(client):
    r = client.get("/api/auth/operator/verify", follow_redirects=False)
    assert r.status_code == 422


def test_verify_rejects_disabled_operator(client, db_conn, seed_operator):
    token = operators.issue_operator_login_token(
        db_conn, operator_email="alice@acme.com", tenant_id="acme"
    )
    operators.update_operator(db_conn, seed_operator.id, status="disabled")

    r = client.get(
        f"/api/auth/operator/verify?token={token}",
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_me_returns_session_context(client, db_conn, seed_operator):
    token = operators.issue_operator_login_token(
        db_conn, operator_email="alice@acme.com", tenant_id="acme"
    )
    r_verify = client.get(
        f"/api/auth/operator/verify?token={token}",
        follow_redirects=False,
    )
    cookie = r_verify.cookies[operators.OPERATOR_SESSION_COOKIE_NAME]

    r_me = client.get(
        "/api/auth/operator/me",
        cookies={operators.OPERATOR_SESSION_COOKIE_NAME: cookie},
    )
    assert r_me.status_code == 200
    data = r_me.json()
    assert data["email"] == "alice@acme.com"
    assert data["tenant_id"] == "acme"
    assert data["role"] == "responder"
    assert data["operator_id"] == seed_operator.id


def test_me_without_cookie_returns_401(client):
    r = client.get("/api/auth/operator/me")
    assert r.status_code == 401


def test_logout_revokes_session_and_clears_cookie(client, db_conn, seed_operator):
    token = operators.issue_operator_login_token(
        db_conn, operator_email="alice@acme.com", tenant_id="acme"
    )
    r_verify = client.get(
        f"/api/auth/operator/verify?token={token}",
        follow_redirects=False,
    )
    session_cookie = r_verify.cookies[operators.OPERATOR_SESSION_COOKIE_NAME]

    # Session works
    r = client.get(
        "/api/auth/operator/me",
        cookies={operators.OPERATOR_SESSION_COOKIE_NAME: session_cookie},
    )
    assert r.status_code == 200

    # Logout
    r_out = client.post(
        "/api/auth/operator/logout",
        cookies={operators.OPERATOR_SESSION_COOKIE_NAME: session_cookie},
    )
    assert r_out.status_code == 204

    # Session dead
    r_dead = client.get(
        "/api/auth/operator/me",
        cookies={operators.OPERATOR_SESSION_COOKIE_NAME: session_cookie},
    )
    assert r_dead.status_code == 401


def test_logout_is_idempotent_without_cookie(client):
    r = client.post("/api/auth/operator/logout")
    assert r.status_code == 204


# ──────────────────────────────────────────────────────────────────────────
# CRUD (T1S.4) — admin-authenticated + tenant-scoped
# ──────────────────────────────────────────────────────────────────────────


def test_crud_requires_admin_session(client):
    r = client.get("/api/admin/acme/operators")
    assert r.status_code == 401


def test_list_operators(client, db_conn, admin_session_cookie, seed_operator):
    # Add a second operator
    operators.create_operator(
        db_conn, tenant_id="acme", email="bob@acme.com", role="viewer"
    )
    r = client.get(
        "/api/admin/acme/operators",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["operators"]) == 2
    emails = {o["email"] for o in data["operators"]}
    assert emails == {"alice@acme.com", "bob@acme.com"}


def test_list_operators_cross_tenant_denied(client, db_conn):
    # Admin scoped to acme
    sid = auth.create_session(db_conn, "admin@acme.com", tenant_id="acme")
    r = client.get(
        "/api/admin/other/operators",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: sid},
    )
    assert r.status_code == 403


def test_create_operator(client, db_conn, admin_session_cookie):
    r = client.post(
        "/api/admin/acme/operators",
        json={"email": "new@acme.com", "role": "viewer", "display_name": "New"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert r.status_code == 201
    op = r.json()["operator"]
    assert op["email"] == "new@acme.com"
    assert op["role"] == "viewer"
    assert op["status"] == "active"
    assert op["created_by"] == "admin@acme.com"


def test_create_operator_rejects_invalid_role(client, db_conn, admin_session_cookie):
    r = client.post(
        "/api/admin/acme/operators",
        json={"email": "x@acme.com", "role": "god"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert r.status_code == 422


def test_create_operator_returns_409_on_duplicate(
    client, db_conn, admin_session_cookie, seed_operator
):
    r = client.post(
        "/api/admin/acme/operators",
        json={"email": "alice@acme.com", "role": "admin"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert r.status_code == 409


def test_get_operator(client, db_conn, admin_session_cookie, seed_operator):
    r = client.get(
        f"/api/admin/acme/operators/{seed_operator.id}",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert r.status_code == 200
    assert r.json()["operator"]["email"] == "alice@acme.com"


def test_get_operator_cross_tenant_returns_404(
    client, db_conn, admin_session_cookie, seed_operator
):
    # Create an operator in different tenant; admin's session is acme.
    other_op = operators.create_operator(
        db_conn, tenant_id="other", email="z@other.com", role="viewer"
    )
    r = client.get(
        f"/api/admin/acme/operators/{other_op.id}",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_session_cookie},
    )
    # Admin scope is acme, so "other" tenant operator not visible under acme → 404
    assert r.status_code == 404


def test_update_operator(client, db_conn, admin_session_cookie, seed_operator):
    r = client.patch(
        f"/api/admin/acme/operators/{seed_operator.id}",
        json={"role": "admin", "display_name": "Alice Admin"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert r.status_code == 200
    op = r.json()["operator"]
    assert op["role"] == "admin"
    assert op["display_name"] == "Alice Admin"


def test_update_operator_disable_revokes_sessions(
    client, db_conn, admin_session_cookie, seed_operator
):
    # Issue a session for the operator
    tok = operators.issue_operator_session(
        db_conn, operator_id=seed_operator.id, tenant_id="acme"
    )
    assert operators.lookup_operator_session(db_conn, tok) is not None

    client.patch(
        f"/api/admin/acme/operators/{seed_operator.id}",
        json={"status": "disabled"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_session_cookie},
    )
    # Session revoked
    assert operators.lookup_operator_session(db_conn, tok) is None


def test_delete_operator(client, db_conn, admin_session_cookie, seed_operator):
    r = client.delete(
        f"/api/admin/acme/operators/{seed_operator.id}",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert r.status_code == 204
    assert operators.get_operator(db_conn, seed_operator.id) is None

    # Second delete — 404
    r2 = client.delete(
        f"/api/admin/acme/operators/{seed_operator.id}",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert r2.status_code == 404
