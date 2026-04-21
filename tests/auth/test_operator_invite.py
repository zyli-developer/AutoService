"""Tests for T1S.5 — operator invite flow.

Contract: docs/contracts/m3/e1-auth-rbac.md §3.3.

Scenarios:
- Admin creates operator invite → URL issued
- Invitee clicks link → operator created (default role='viewer') + session
- Admin creates tenant_admin invite → token persisted with role='tenant_admin'
- Invite token with admin role does NOT work via operator accept-invite
- Invalid / expired / already-consumed invite → 401
- Role validation on invite creation
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoservice import api_routes, auth, operator_routes, operators


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
def app(db_conn):
    operator_routes._reset_op_db_for_tests(db_conn)
    api_routes._reset_auth_db_for_tests(db_conn)
    a = FastAPI()
    a.include_router(api_routes.api_router)
    yield a
    operator_routes._reset_op_db_for_tests(None)
    api_routes._reset_auth_db_for_tests(None)


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def admin_cookie(db_conn):
    return auth.create_session(db_conn, "admin@acme.com", tenant_id="acme")


# ──────────────────────────────────────────────────────────────────────────
# Create invite (admin side)
# ──────────────────────────────────────────────────────────────────────────


def test_admin_creates_operator_invite(client, admin_cookie):
    r = client.post(
        "/api/admin/acme/invites",
        json={"email": "new-op@acme.com", "role": "operator"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["role"] == "operator"
    assert data["expires_in_min"] == 10
    assert "accept-invite?token=" in data["invite_url"]


def test_invite_requires_admin_session(client):
    r = client.post(
        "/api/admin/acme/invites",
        json={"email": "new-op@acme.com", "role": "operator"},
    )
    assert r.status_code == 401


def test_invite_cross_tenant_denied(client, db_conn):
    sid = auth.create_session(db_conn, "admin@acme.com", tenant_id="acme")
    r = client.post(
        "/api/admin/other/invites",
        json={"email": "x@other.com", "role": "operator"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: sid},
    )
    assert r.status_code == 403


def test_invite_rejects_invalid_role(client, admin_cookie):
    r = client.post(
        "/api/admin/acme/invites",
        json={"email": "x@acme.com", "role": "superuser"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 422


def test_invite_rejects_missing_email(client, admin_cookie):
    r = client.post(
        "/api/admin/acme/invites",
        json={"role": "operator"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 422


def test_invite_persists_token_with_role_operator(client, db_conn, admin_cookie):
    r = client.post(
        "/api/admin/acme/invites",
        json={"email": "fresh@acme.com", "role": "operator"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 201
    row = db_conn.execute(
        "SELECT role, invited_by FROM login_tokens WHERE admin_email = ?",
        ("fresh@acme.com",),
    ).fetchone()
    assert row["role"] == "operator"
    assert row["invited_by"] == "admin@acme.com"


def test_invite_tenant_admin_persists_with_role(client, db_conn, admin_cookie):
    r = client.post(
        "/api/admin/acme/invites",
        json={"email": "co-admin@acme.com", "role": "tenant_admin"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 201
    assert r.json()["role"] == "tenant_admin"
    row = db_conn.execute(
        "SELECT role, invited_by FROM login_tokens WHERE admin_email = ?",
        ("co-admin@acme.com",),
    ).fetchone()
    assert row["role"] == "tenant_admin"
    assert row["invited_by"] == "admin@acme.com"


# ──────────────────────────────────────────────────────────────────────────
# Accept invite (invitee side)
# ──────────────────────────────────────────────────────────────────────────


def test_accept_invite_creates_operator_and_sets_cookie(client, db_conn):
    # Admin issues invite token directly (bypass HTTP, focus on accept path)
    token = operators.issue_operator_login_token(
        db_conn,
        operator_email="newbie@acme.com",
        tenant_id="acme",
        invited_by="admin@acme.com",
    )

    r = client.get(
        f"/api/auth/operator/accept-invite?token={token}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/operator"

    # Cookie set
    cookie = r.cookies.get(operators.OPERATOR_SESSION_COOKIE_NAME)
    assert cookie is not None

    # Operator row created with default role='viewer' + invited_by captured
    op = operators.get_operator_by_email(db_conn, "acme", "newbie@acme.com")
    assert op is not None
    assert op.role == "viewer"
    assert op.status == "active"
    assert op.created_by == "admin@acme.com"


def test_accept_invite_works_for_existing_operator(client, db_conn):
    """Accept-invite is idempotent on already-existing operator (no duplicate row)."""
    # Pre-existing operator
    existing = operators.create_operator(
        db_conn, tenant_id="acme", email="existing@acme.com", role="responder"
    )

    token = operators.issue_operator_login_token(
        db_conn,
        operator_email="existing@acme.com",
        tenant_id="acme",
        invited_by="admin@acme.com",
    )

    r = client.get(
        f"/api/auth/operator/accept-invite?token={token}",
        follow_redirects=False,
    )
    assert r.status_code == 302

    # Still just one operator with existing role preserved (didn't get downgraded to viewer)
    op = operators.get_operator_by_email(db_conn, "acme", "existing@acme.com")
    assert op is not None
    assert op.id == existing.id
    assert op.role == "responder"  # preserved


def test_accept_invite_rejects_missing_token(client):
    r = client.get("/api/auth/operator/accept-invite", follow_redirects=False)
    assert r.status_code == 422


def test_accept_invite_rejects_admin_token(client, db_conn):
    """Admin magic-link MUST NOT be accepted as operator invite (role gate)."""
    admin_token = auth.issue_login_token(db_conn, "admin2@acme.com", tenant_id="acme")
    r = client.get(
        f"/api/auth/operator/accept-invite?token={admin_token}",
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_accept_invite_rejects_expired(client, db_conn):
    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    tok = operators.issue_operator_login_token(
        db_conn,
        operator_email="x@acme.com",
        tenant_id="acme",
        invited_by="admin@acme.com",
        ttl_min=5,
        now=t0,
    )
    r = client.get(
        f"/api/auth/operator/accept-invite?token={tok}",
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_accept_invite_is_single_use(client, db_conn):
    token = operators.issue_operator_login_token(
        db_conn,
        operator_email="onceuser@acme.com",
        tenant_id="acme",
        invited_by="admin@acme.com",
    )

    r1 = client.get(
        f"/api/auth/operator/accept-invite?token={token}",
        follow_redirects=False,
    )
    assert r1.status_code == 302

    # Second use → token burned
    r2 = client.get(
        f"/api/auth/operator/accept-invite?token={token}",
        follow_redirects=False,
    )
    assert r2.status_code == 401


def test_accept_invite_rejects_disabled_operator(client, db_conn):
    op = operators.create_operator(
        db_conn, tenant_id="acme", email="dead@acme.com", role="viewer"
    )
    operators.update_operator(db_conn, op.id, status="disabled")

    token = operators.issue_operator_login_token(
        db_conn,
        operator_email="dead@acme.com",
        tenant_id="acme",
        invited_by="admin@acme.com",
    )
    r = client.get(
        f"/api/auth/operator/accept-invite?token={token}",
        follow_redirects=False,
    )
    assert r.status_code == 401
