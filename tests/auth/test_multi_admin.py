"""Tests for T2S.2 — multi-admin per tenant (E1.5).

Contract: docs/contracts/m3/e1-auth-rbac.md §6 (Multi-Admin).
PRD §2 E1.5: ≥2 admins per tenant with identical permissions.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoservice import api_routes, auth, operator_routes, operators


@pytest.fixture()
def db_conn():
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
    return auth.create_session(db_conn, "primary@acme.com", tenant_id="acme")


# ──────────────────────────────────────────────────────────────────────────
# List admins
# ──────────────────────────────────────────────────────────────────────────


def test_list_admins_shows_single_admin(client, db_conn, admin_cookie):
    r = client.get(
        "/api/admin/acme/admins",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["admins"]) == 1
    assert data["admins"][0]["email"] == "primary@acme.com"


def test_list_admins_shows_two_distinct_admins(client, db_conn, admin_cookie):
    # Add a second admin for the same tenant
    auth.create_session(db_conn, "co-admin@acme.com", tenant_id="acme")
    r = client.get(
        "/api/admin/acme/admins",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    data = r.json()
    emails = {a["email"] for a in data["admins"]}
    assert emails == {"primary@acme.com", "co-admin@acme.com"}


def test_list_admins_dedupes_multiple_sessions_same_admin(client, db_conn, admin_cookie):
    # Same admin with 3 active sessions — should still count as ONE admin
    auth.create_session(db_conn, "primary@acme.com", tenant_id="acme")
    auth.create_session(db_conn, "primary@acme.com", tenant_id="acme")
    r = client.get(
        "/api/admin/acme/admins",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    data = r.json()
    assert len(data["admins"]) == 1


def test_list_admins_excludes_expired_sessions(client, db_conn, admin_cookie):
    # Create an "expired" session by inserting directly with past expiry
    from datetime import datetime, timedelta, timezone
    past = (datetime.now(tz=timezone.utc) - timedelta(days=60)).isoformat()
    db_conn.execute(
        "INSERT INTO sessions (session_id, admin_email, tenant_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("expired-sid", "ghost@acme.com", "acme", past, past),
    )
    db_conn.commit()

    r = client.get(
        "/api/admin/acme/admins",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    emails = {a["email"] for a in r.json()["admins"]}
    assert "ghost@acme.com" not in emails


def test_list_admins_excludes_revoked_sessions(client, db_conn, admin_cookie):
    revoked_sid = auth.create_session(db_conn, "revoked@acme.com", tenant_id="acme")
    auth.revoke_session(db_conn, revoked_sid)

    r = client.get(
        "/api/admin/acme/admins",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    emails = {a["email"] for a in r.json()["admins"]}
    assert "revoked@acme.com" not in emails


def test_list_admins_cross_tenant_denied(client, db_conn, admin_cookie):
    r = client.get(
        "/api/admin/other-tenant/admins",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 403


def test_list_admins_unauthenticated_rejected(client):
    r = client.get("/api/admin/acme/admins")
    assert r.status_code == 401


# ──────────────────────────────────────────────────────────────────────────
# Revoke admin (with last-admin guard)
# ──────────────────────────────────────────────────────────────────────────


def test_revoke_admin_removes_co_admin_sessions(client, db_conn, admin_cookie):
    auth.create_session(db_conn, "co-admin@acme.com", tenant_id="acme")

    r = client.delete(
        "/api/admin/acme/admins/co-admin@acme.com",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 200

    # List now shows only primary
    r2 = client.get(
        "/api/admin/acme/admins",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    emails = {a["email"] for a in r2.json()["admins"]}
    assert emails == {"primary@acme.com"}


def test_revoke_admin_last_admin_blocked(client, db_conn, admin_cookie):
    """Cannot remove the last admin on a tenant."""
    r = client.delete(
        "/api/admin/acme/admins/primary@acme.com",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["error"] == "cannot_revoke_last_admin"


def test_revoke_admin_not_found(client, db_conn, admin_cookie):
    auth.create_session(db_conn, "co-admin@acme.com", tenant_id="acme")  # prevent last-admin case
    r = client.delete(
        "/api/admin/acme/admins/ghost@acme.com",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 404


def test_revoke_admin_case_insensitive_email(client, db_conn, admin_cookie):
    auth.create_session(db_conn, "co-admin@acme.com", tenant_id="acme")
    r = client.delete(
        "/api/admin/acme/admins/CO-ADMIN@acme.com",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 200


def test_revoke_admin_cross_tenant_denied(client, db_conn, admin_cookie):
    r = client.delete(
        "/api/admin/other/admins/x@other.com",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: admin_cookie},
    )
    assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# E1.5 functional requirement: 2+ admins, identical permissions
# ──────────────────────────────────────────────────────────────────────────


def test_two_admins_both_can_crud_operators(client, db_conn):
    """PRD §2 E1.5: 2 admins on same tenant, identical permissions."""
    sid_1 = auth.create_session(db_conn, "admin1@acme.com", tenant_id="acme")
    sid_2 = auth.create_session(db_conn, "admin2@acme.com", tenant_id="acme")

    # Both can create operators
    r1 = client.post(
        "/api/admin/acme/operators",
        json={"email": "op1@acme.com", "role": "viewer"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: sid_1},
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/api/admin/acme/operators",
        json={"email": "op2@acme.com", "role": "responder"},
        cookies={auth.AUTH_SESSION_COOKIE_NAME: sid_2},
    )
    assert r2.status_code == 201

    # Both see the same operator list
    list_1 = client.get(
        "/api/admin/acme/operators",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: sid_1},
    )
    list_2 = client.get(
        "/api/admin/acme/operators",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: sid_2},
    )
    assert list_1.json() == list_2.json()
