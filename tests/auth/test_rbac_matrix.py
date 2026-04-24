"""Unit tests for ``autoservice.rbac`` — permission matrix + FastAPI dep.

Contract: docs/contracts/m3/e1-auth-rbac.md §5.
Covers T2S.1 matrix correctness, dependency extraction, and the NFR-02
P95 <5ms benchmark.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from autoservice import auth, operator_routes, operators, rbac


# ──────────────────────────────────────────────────────────────────────────
# Matrix correctness
# ──────────────────────────────────────────────────────────────────────────


def test_admin_can_do_admin_only_actions():
    for action in ("crud_operators", "send_invites", "approve_proposal",
                   "apply_proposal", "edit_classify_intent",
                   "edit_tenant_config", "reject_proposal"):
        assert rbac.check("admin", action), f"admin should allow {action}"


def test_admin_can_do_everything_responder_can():
    for action in ("hijack", "release", "send_copilot_suggestion",
                   "view_compliance_scan"):
        assert rbac.check("admin", action)
        assert rbac.check("responder", action)


def test_viewer_cannot_do_operator_actions():
    for action in ("hijack", "release", "send_copilot_suggestion",
                   "crud_operators", "approve_proposal", "apply_proposal"):
        assert not rbac.check("viewer", action), (
            f"viewer must NOT allow {action}"
        )


def test_responder_cannot_do_admin_only_actions():
    for action in ("crud_operators", "send_invites", "approve_proposal",
                   "apply_proposal", "edit_classify_intent",
                   "edit_tenant_config"):
        assert not rbac.check("responder", action)


def test_all_roles_can_view_conversations():
    for role in ("viewer", "responder", "admin"):
        assert rbac.check(role, "view_conversations")


def test_viewer_cannot_view_compliance():
    """Compliance is ops-level: viewer (read-only monitor) doesn't see it."""
    assert not rbac.check("viewer", "view_compliance_scan")


def test_check_unknown_role_returns_false():
    assert not rbac.check("superuser", "crud_operators")
    assert not rbac.check("", "view_conversations")
    assert not rbac.check("ADMIN", "crud_operators")  # case-sensitive


def test_check_unknown_action_returns_false():
    assert not rbac.check("admin", "launch_nukes")


def test_action_registry_matches_matrix():
    # Every (role, action) in PERMISSIONS has its action in ACTIONS set
    for _role, action in rbac.PERMISSIONS:
        assert action in rbac.ACTIONS


def test_require_raises_on_unknown_action():
    with pytest.raises(ValueError, match="unknown action"):
        rbac.require("lol_no_such_action")


# ──────────────────────────────────────────────────────────────────────────
# NFR-02 P95 < 5ms benchmark
# ──────────────────────────────────────────────────────────────────────────


def test_nfr02_check_p95_under_5ms():
    """NFR-02: RBAC decision P95 < 5ms.  frozenset lookup is O(1); 10k
    iterations P95 should be WELL under 5ms per call."""
    n = 10_000
    samples: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        rbac.check("admin", "crud_operators")
        samples.append((time.perf_counter() - t0) * 1000)  # ms

    samples.sort()
    p95 = samples[int(n * 0.95)]
    assert p95 < 5.0, f"NFR-02 violated: P95 = {p95:.4f} ms (target <5 ms)"


# ──────────────────────────────────────────────────────────────────────────
# FastAPI dependency integration
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    auth.apply_schema(c)
    operators.apply_operators_schema(c)
    operators.migrate_login_tokens_add_role(c)
    operator_routes._reset_op_db_for_tests(c)
    yield c
    operator_routes._reset_op_db_for_tests(None)
    c.close()


@pytest.fixture()
def app(db_conn):
    a = FastAPI()

    @a.get("/need-admin")
    async def admin_only(ctx: dict = Depends(rbac.require("crud_operators"))):
        return {"ok": True, "role": ctx["role"]}

    @a.get("/need-responder")
    async def responder_plus(ctx: dict = Depends(rbac.require("hijack"))):
        return {"ok": True, "role": ctx["role"]}

    @a.get("/need-view")
    async def anyone(ctx: dict = Depends(rbac.require("view_conversations"))):
        return {"ok": True, "role": ctx["role"]}

    @a.get("/any-authenticated")
    async def any_auth(ctx: dict = Depends(rbac.resolve_ctx)):
        return {"role": ctx["role"], "actor_id": ctx["actor_id"]}

    return a


@pytest.fixture()
def client(app):
    return TestClient(app)


def test_no_cookie_returns_401(client):
    r = client.get("/need-view")
    assert r.status_code == 401


def test_operator_admin_role_can_access_admin_action(client, db_conn):
    op = operators.create_operator(
        db_conn, tenant_id="acme", email="admin-op@acme.com", role="admin"
    )
    tok = operators.issue_operator_session(
        db_conn, operator_id=op.id, tenant_id="acme"
    )
    r = client.get(
        "/need-admin",
        cookies={operators.OPERATOR_SESSION_COOKIE_NAME: tok},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "role": "admin"}


def test_operator_responder_role_blocked_from_admin_action(client, db_conn):
    op = operators.create_operator(
        db_conn, tenant_id="acme", email="responder@acme.com", role="responder"
    )
    tok = operators.issue_operator_session(
        db_conn, operator_id=op.id, tenant_id="acme"
    )
    r = client.get(
        "/need-admin",
        cookies={operators.OPERATOR_SESSION_COOKIE_NAME: tok},
    )
    assert r.status_code == 403
    body = r.json()["detail"]
    assert body["error"] == "permission_denied"
    assert body["action"] == "crud_operators"
    assert body["role"] == "responder"


def test_operator_viewer_role_can_view_but_not_hijack(client, db_conn):
    op = operators.create_operator(
        db_conn, tenant_id="acme", email="viewer@acme.com", role="viewer"
    )
    tok = operators.issue_operator_session(
        db_conn, operator_id=op.id, tenant_id="acme"
    )
    # view allowed
    assert client.get(
        "/need-view", cookies={operators.OPERATOR_SESSION_COOKIE_NAME: tok}
    ).status_code == 200
    # hijack denied
    assert client.get(
        "/need-responder", cookies={operators.OPERATOR_SESSION_COOKIE_NAME: tok}
    ).status_code == 403


def test_admin_session_cookie_gets_admin_role(client, db_conn):
    """A plain admin auth_session cookie maps to role='admin'."""
    sid = auth.create_session(db_conn, "admin@acme.com", tenant_id="acme")
    r = client.get(
        "/need-admin",
        cookies={auth.AUTH_SESSION_COOKIE_NAME: sid},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_tier0_platform_admin_also_maps_to_admin(client, db_conn):
    """Tier-0 sessions (tenant_id=NULL) are platform admins — still role='admin'."""
    sid = auth.create_session(db_conn, "platform@example.com", tenant_id=None)
    r = client.get(
        "/any-authenticated", cookies={auth.AUTH_SESSION_COOKIE_NAME: sid}
    )
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_per_request_cache_avoids_duplicate_db_lookup(client, db_conn, monkeypatch):
    """Multiple Depends(require(...)) in same request → single DB lookup (NFR-02)."""
    op = operators.create_operator(
        db_conn, tenant_id="acme", email="cached@acme.com", role="admin"
    )
    tok = operators.issue_operator_session(
        db_conn, operator_id=op.id, tenant_id="acme"
    )
    call_count = {"n": 0}
    original = operators.lookup_operator_session

    def counting_lookup(*args, **kwargs):
        call_count["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(operators, "lookup_operator_session", counting_lookup)

    # Build an app that has 3 RBAC deps on one route
    a = FastAPI()

    @a.get("/multi-check")
    async def multi(
        c1: dict = Depends(rbac.require("crud_operators")),
        c2: dict = Depends(rbac.require("send_invites")),
        c3: dict = Depends(rbac.require("edit_classify_intent")),
    ):
        return {"ok": True}

    with TestClient(a) as c:
        r = c.get("/multi-check", cookies={operators.OPERATOR_SESSION_COOKIE_NAME: tok})
        assert r.status_code == 200

    # One DB hit, not three
    assert call_count["n"] == 1, (
        f"expected 1 DB lookup across 3 Depends(require), got {call_count['n']}"
    )


def test_ensure_helper_raises_403_on_deny(db_conn):
    """rbac.ensure(ctx, action) — programmatic check, raises 403 on fail."""
    from fastapi import HTTPException

    ctx = {"role": "viewer", "tenant_id": "acme", "actor_id": "x", "actor_kind": "operator"}
    with pytest.raises(HTTPException) as exc:
        rbac.ensure(ctx, "crud_operators")
    assert exc.value.status_code == 403


def test_ensure_helper_passes_when_allowed(db_conn):
    ctx = {"role": "admin", "tenant_id": "acme", "actor_id": "x", "actor_kind": "admin"}
    rbac.ensure(ctx, "crud_operators")  # no raise


# ──────────────────────────────────────────────────────────────────────────
# Reviewer C2 follow-up: cookie collision
# ──────────────────────────────────────────────────────────────────────────


def test_both_cookies_operator_wins(client, db_conn, caplog):
    """If both operator + auth cookies set, operator (least-privilege) wins."""
    # Admin session (would otherwise grant admin role)
    admin_sid = auth.create_session(db_conn, "admin@acme.com", tenant_id="acme")
    # Operator session with LOWER role
    op = operators.create_operator(
        db_conn, tenant_id="acme", email="both@acme.com", role="viewer"
    )
    op_tok = operators.issue_operator_session(
        db_conn, operator_id=op.id, tenant_id="acme"
    )

    import logging

    with caplog.at_level(logging.WARNING, logger="autoservice.rbac"):
        r = client.get(
            "/any-authenticated",
            cookies={
                auth.AUTH_SESSION_COOKIE_NAME: admin_sid,
                operators.OPERATOR_SESSION_COOKIE_NAME: op_tok,
            },
        )

    assert r.status_code == 200
    data = r.json()
    # Operator (viewer) wins — not admin
    assert data["role"] == "viewer"
    # Audit trail
    assert any("BOTH operator_session + auth_session" in rec.message for rec in caplog.records)


def test_expired_operator_cookie_falls_through_to_auth(client, db_conn):
    """Stale operator cookie must NOT 401; falls through to auth cookie."""
    from datetime import datetime, timezone
    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)

    op = operators.create_operator(
        db_conn, tenant_id="acme", email="stale@acme.com", role="viewer"
    )
    stale_op_tok = operators.issue_operator_session(
        db_conn, operator_id=op.id, tenant_id="acme", now=t0
    )
    admin_sid = auth.create_session(db_conn, "admin@acme.com", tenant_id="acme")

    r = client.get(
        "/need-admin",
        cookies={
            operators.OPERATOR_SESSION_COOKIE_NAME: stale_op_tok,  # expired
            auth.AUTH_SESSION_COOKIE_NAME: admin_sid,  # live
        },
    )
    # Stale op cookie → lookup returns None → fall through → admin cookie grants
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_disabled_operator_falls_through_to_auth(client, db_conn):
    """Disabled operator → lookup returns None → fall through to auth cookie."""
    op = operators.create_operator(
        db_conn, tenant_id="acme", email="disabled@acme.com", role="admin"
    )
    op_tok = operators.issue_operator_session(
        db_conn, operator_id=op.id, tenant_id="acme"
    )
    operators.update_operator(db_conn, op.id, status="disabled")

    admin_sid = auth.create_session(db_conn, "admin@acme.com", tenant_id="acme")

    r = client.get(
        "/need-admin",
        cookies={
            operators.OPERATOR_SESSION_COOKIE_NAME: op_tok,
            auth.AUTH_SESSION_COOKIE_NAME: admin_sid,
        },
    )
    # Disabled op → None → fall through → admin cookie OK
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
