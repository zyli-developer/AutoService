"""Tests for T3S.6 admin-to-admin invite + T4S.3 apply_proposal HTTP layer.

Contracts:
- e1-auth-rbac.md §3.3 (admin invite)
- e5-dream.md v1.1 §2.6 (apply endpoint)
"""
from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoservice import (
    api_routes,
    auth,
    operator_routes,
    operators,
    proposal_pipeline,
)


@pytest.fixture()
def db_conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    auth.apply_schema(c)
    operators.apply_operators_schema(c)
    operators.migrate_login_tokens_add_role(c)
    proposal_pipeline.apply_schema(c)
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


def _seed_proposal(db_conn, *, pid="p-1", status="accepted",
                   category="workflow", tenant_id="acme"):
    data = {
        "id": pid, "tenant_id": tenant_id, "category": category,
        "status": status, "title": "t", "description": "d", "suggestion": "s",
        "evidence": "e", "risk_level": "low", "target_role": "dream",
        "created_at": "2026-04-21T00:00:00+00:00",
    }
    db_conn.execute(
        "INSERT INTO proposals (id, created_at, data, status, category, tenant_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (pid, data["created_at"], json.dumps(data), status, category, tenant_id),
    )
    db_conn.commit()
    return pid


# ──────────────────────────────────────────────────────────────────────────
# T3S.6 admin-to-admin invite
# ──────────────────────────────────────────────────────────────────────────


def test_admin_invite_created_via_post_invites(client, db_conn, admin_cookie):
    """T1S.5 path: POST /admin/{tid}/invites with role=tenant_admin persists token."""
    r = client.post(
        "/api/admin/acme/invites",
        json={"email": "co-admin@acme.com", "role": "tenant_admin"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 201
    token_url = r.json()["invite_url"]
    assert "accept-invite?token=" in token_url or "verify?token=" in token_url


def test_accept_admin_invite_sets_auth_session(client, db_conn, admin_cookie):
    # Issue token
    r1 = client.post(
        "/api/admin/acme/invites",
        json={"email": "co-admin@acme.com", "role": "tenant_admin"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r1.status_code == 201
    # Pull token from URL
    url = r1.json()["invite_url"]
    token = url.split("token=")[1].split("&")[0]

    # Consume via T3S.6 accept endpoint
    r2 = client.get(
        f"/api/auth/admin/accept-invite?token={token}",
        follow_redirects=False,
    )
    assert r2.status_code == 302
    assert r2.headers["location"] == "/admin"
    assert r2.cookies.get(auth.AUTH_SESSION_COOKIE_NAME) is not None


def test_accept_admin_invite_rejects_operator_token(client, db_conn, admin_cookie):
    """Operator-role token MUST NOT authenticate via admin accept endpoint."""
    # Issue an operator token (role='operator')
    tok = operators.issue_operator_login_token(
        db_conn, operator_email="op@acme.com", tenant_id="acme",
        invited_by="admin@acme.com",
    )
    r = client.get(
        f"/api/auth/admin/accept-invite?token={tok}",
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_accept_admin_invite_requires_token(client):
    r = client.get("/api/auth/admin/accept-invite", follow_redirects=False)
    assert r.status_code == 422


def test_accept_admin_invite_single_use(client, db_conn, admin_cookie):
    r1 = client.post(
        "/api/admin/acme/invites",
        json={"email": "co-admin@acme.com", "role": "tenant_admin"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    token = r1.json()["invite_url"].split("token=")[1].split("&")[0]

    first = client.get(
        f"/api/auth/admin/accept-invite?token={token}", follow_redirects=False
    )
    assert first.status_code == 302

    # Second use → burned
    second = client.get(
        f"/api/auth/admin/accept-invite?token={token}", follow_redirects=False
    )
    assert second.status_code == 401


# ──────────────────────────────────────────────────────────────────────────
# T4S.3 Apply proposal endpoint
# ──────────────────────────────────────────────────────────────────────────


def test_apply_happy_path(client, db_conn, admin_cookie):
    pid = _seed_proposal(db_conn, status="accepted", category="workflow")
    r = client.post(
        f"/api/admin/proposals/{pid}/apply",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["result"]["new_status"] == "applied"
    assert data["result"]["previous_status"] == "accepted"
    assert data["result"]["admin_user_id"] == "admin@acme.com"
    assert data["result"]["idempotent"] is False


def test_apply_idempotent_returns_200_no_duplicate_audit(client, db_conn, admin_cookie):
    pid = _seed_proposal(db_conn, status="accepted")
    client.post(
        f"/api/admin/proposals/{pid}/apply",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    # Second apply — idempotent
    r2 = client.post(
        f"/api/admin/proposals/{pid}/apply",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r2.status_code == 200
    assert r2.json()["result"]["idempotent"] is True

    # Audit row count: exactly 1
    audit_count = db_conn.execute(
        "SELECT COUNT(*) AS n FROM proposal_audit WHERE proposal_id = ?", (pid,)
    ).fetchone()["n"]
    assert audit_count == 1


def test_apply_missing_proposal_returns_404(client, db_conn, admin_cookie):
    r = client.post(
        "/api/admin/proposals/ghost/apply",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 404


def test_apply_draft_proposal_returns_409(client, db_conn, admin_cookie):
    pid = _seed_proposal(db_conn, status="draft")
    r = client.post(
        f"/api/admin/proposals/{pid}/apply",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 409


def test_apply_unauthenticated_returns_401(client, db_conn):
    pid = _seed_proposal(db_conn, status="accepted")
    r = client.post(f"/api/admin/proposals/{pid}/apply")
    assert r.status_code == 401


def test_apply_platform_level_as_tenant_admin_returns_403(client, db_conn, admin_cookie):
    """🔒 Tier-0 requirement enforced: tenant_admin on acme can't apply
    a platform_level proposal."""
    pid = _seed_proposal(
        db_conn, status="accepted", category="platform_level",
        tenant_id="_master",
    )
    r = client.post(
        f"/api/admin/proposals/{pid}/apply",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    # The tenant-access middleware allows tier-1 admin to touch tier-0 tenant
    # for admin operations (per M2 rule 4), but apply_proposal inside enforces
    # is_platform_admin=False for tenant_admin → 403 permission_denied
    assert r.status_code == 403


def test_apply_platform_level_as_tier_zero_admin_succeeds(client, db_conn):
    tier0 = auth.create_session(db_conn, "platform@example.com", tenant_id=None)
    pid = _seed_proposal(
        db_conn, status="accepted", category="platform_level",
        tenant_id="_master",
    )
    r = client.post(
        f"/api/admin/proposals/{pid}/apply",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: tier0},
    )
    assert r.status_code == 200
    assert r.json()["result"]["new_status"] == "applied"


def test_apply_writes_audit_row(client, db_conn, admin_cookie):
    pid = _seed_proposal(db_conn, status="accepted")
    client.post(
        f"/api/admin/proposals/{pid}/apply",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    audit = db_conn.execute(
        "SELECT * FROM proposal_audit WHERE proposal_id = ?", (pid,)
    ).fetchone()
    assert audit is not None
    assert audit["action"] == "apply"
    assert audit["admin_user_id"] == "admin@acme.com"
    assert audit["previous_status"] == "accepted"
    assert audit["new_status"] == "applied"
