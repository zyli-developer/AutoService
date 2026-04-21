"""Unit tests for ``autoservice.operators`` helpers — CRUD, sessions, magic-link.

Covers T1S.2 (operator sessions + magic-link consume) + T1S.4 (CRUD).

Contract: docs/contracts/m3/e1-auth-rbac.md §2-3.

Pattern: in-memory sqlite3 + explicit ``now`` injection for deterministic TTL.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from autoservice import auth, operators


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    auth.apply_schema(c)
    operators.apply_operators_schema(c)
    operators.migrate_login_tokens_add_role(c)
    yield c
    c.close()


@pytest.fixture()
def seed_operator(conn):
    """Seed a baseline active operator; return the :class:`Operator`."""
    op = operators.create_operator(
        conn,
        tenant_id="acme",
        email="alice@acme.com",
        role="responder",
        display_name="Alice",
        created_by="admin@acme.com",
    )
    return op


# ──────────────────────────────────────────────────────────────────────────
# CRUD (T1S.4)
# ──────────────────────────────────────────────────────────────────────────


def test_create_operator_normalizes_email_and_sets_defaults(conn):
    op = operators.create_operator(
        conn,
        tenant_id="acme",
        email="  BoB@Acme.com  ",
        role="viewer",
    )
    assert op.email == "bob@acme.com"  # normalized
    assert op.status == "active"  # default
    assert op.tenant_id == "acme"
    assert op.role == "viewer"
    assert len(op.id) > 0


def test_create_operator_rejects_invalid_role(conn):
    with pytest.raises(ValueError, match="role must be"):
        operators.create_operator(
            conn, tenant_id="acme", email="x@a.com", role="superadmin"  # type: ignore[arg-type]
        )


def test_create_operator_rejects_duplicate_email_per_tenant(conn, seed_operator):
    with pytest.raises(sqlite3.IntegrityError):
        operators.create_operator(
            conn, tenant_id="acme", email="alice@acme.com", role="admin"
        )


def test_get_operator_by_id_and_email(conn, seed_operator):
    by_id = operators.get_operator(conn, seed_operator.id)
    assert by_id is not None and by_id.email == "alice@acme.com"

    by_email = operators.get_operator_by_email(conn, "acme", "ALICE@acme.com")
    assert by_email is not None and by_email.id == seed_operator.id

    # Missing returns None
    assert operators.get_operator(conn, "nonexistent-id") is None
    assert operators.get_operator_by_email(conn, "acme", "ghost@x.com") is None


def test_list_operators_by_tenant_ordering_and_filter(conn):
    for email in ["a@acme.com", "b@acme.com", "c@acme.com"]:
        operators.create_operator(
            conn, tenant_id="acme", email=email, role="viewer"
        )
    # Disabled one
    disabled = operators.create_operator(
        conn, tenant_id="acme", email="x@acme.com", role="viewer"
    )
    operators.update_operator(conn, disabled.id, status="disabled")

    # Cross-tenant
    operators.create_operator(
        conn, tenant_id="other", email="a@other.com", role="viewer"
    )

    active = operators.list_operators_by_tenant(conn, "acme")
    assert len(active) == 3
    assert {o.email for o in active} == {"a@acme.com", "b@acme.com", "c@acme.com"}

    all_ = operators.list_operators_by_tenant(conn, "acme", include_disabled=True)
    assert len(all_) == 4


def test_update_operator_patches_only_provided_fields(conn, seed_operator):
    updated = operators.update_operator(
        conn, seed_operator.id, role="admin"
    )
    assert updated is not None
    assert updated.role == "admin"
    assert updated.email == "alice@acme.com"  # unchanged
    assert updated.status == "active"  # unchanged


def test_update_operator_rejects_invalid_values(conn, seed_operator):
    with pytest.raises(ValueError):
        operators.update_operator(conn, seed_operator.id, role="god")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        operators.update_operator(conn, seed_operator.id, status="unknown")  # type: ignore[arg-type]


def test_update_operator_missing_returns_none(conn):
    assert operators.update_operator(conn, "nope", role="admin") is None


def test_delete_operator_returns_bool_and_cascades_sessions(conn, seed_operator):
    # Put a session on the operator
    tok = operators.issue_operator_session(
        conn, operator_id=seed_operator.id, tenant_id="acme"
    )
    assert operators.lookup_operator_session(conn, tok) is not None

    assert operators.delete_operator(conn, seed_operator.id) is True
    # Session cascaded away
    assert operators.lookup_operator_session(conn, tok) is None
    # Gone for good
    assert operators.delete_operator(conn, seed_operator.id) is False


# ──────────────────────────────────────────────────────────────────────────
# Operator sessions (T1S.2)
# ──────────────────────────────────────────────────────────────────────────


def test_issue_and_lookup_session_roundtrip(conn, seed_operator):
    tok = operators.issue_operator_session(
        conn, operator_id=seed_operator.id, tenant_id="acme"
    )
    assert isinstance(tok, str) and len(tok) > 20

    ctx = operators.lookup_operator_session(conn, tok)
    assert ctx is not None
    assert ctx["operator_id"] == seed_operator.id
    assert ctx["tenant_id"] == "acme"
    assert ctx["email"] == "alice@acme.com"
    assert ctx["role"] == "responder"


def test_lookup_session_unknown_returns_none(conn):
    assert operators.lookup_operator_session(conn, "ghost-token") is None


def test_session_expires_after_ttl(conn, seed_operator):
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    tok = operators.issue_operator_session(
        conn, operator_id=seed_operator.id, tenant_id="acme", ttl_hours=1, now=t0
    )

    # Within TTL — live
    assert operators.lookup_operator_session(
        conn, tok, now=t0 + timedelta(minutes=30)
    ) is not None

    # After TTL — dead
    assert operators.lookup_operator_session(
        conn, tok, now=t0 + timedelta(hours=2)
    ) is None


def test_session_idle_timeout_kicks_in(conn, seed_operator):
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    tok = operators.issue_operator_session(
        conn, operator_id=seed_operator.id, tenant_id="acme", now=t0
    )

    # 30-min default idle
    assert operators.lookup_operator_session(
        conn, tok, now=t0 + timedelta(minutes=29)
    ) is not None
    # Past idle window — dead even though TTL unreached
    assert operators.lookup_operator_session(
        conn, tok, now=t0 + timedelta(minutes=31)
    ) is None


def test_touch_session_bumps_idle_at(conn, seed_operator):
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    tok = operators.issue_operator_session(
        conn, operator_id=seed_operator.id, tenant_id="acme", now=t0
    )

    # Touch at t+20min resets idle clock
    operators.touch_operator_session(conn, tok, now=t0 + timedelta(minutes=20))

    # At t+40min, would have timed out from t0 (40>30) but since we touched
    # at t+20, effective idle is 20min — still live
    assert operators.lookup_operator_session(
        conn, tok, now=t0 + timedelta(minutes=40)
    ) is not None


def test_lookup_session_dead_when_operator_disabled(conn, seed_operator):
    tok = operators.issue_operator_session(
        conn, operator_id=seed_operator.id, tenant_id="acme"
    )
    assert operators.lookup_operator_session(conn, tok) is not None

    operators.update_operator(conn, seed_operator.id, status="disabled")
    # Session row exists but operator disabled → lookup returns None
    assert operators.lookup_operator_session(conn, tok) is None


def test_revoke_operator_session(conn, seed_operator):
    tok = operators.issue_operator_session(
        conn, operator_id=seed_operator.id, tenant_id="acme"
    )
    assert operators.lookup_operator_session(conn, tok) is not None

    operators.revoke_operator_session(conn, tok)
    assert operators.lookup_operator_session(conn, tok) is None

    # Idempotent on already-revoked
    operators.revoke_operator_session(conn, tok)


def test_revoke_all_operator_sessions(conn, seed_operator):
    toks = [
        operators.issue_operator_session(
            conn, operator_id=seed_operator.id, tenant_id="acme"
        )
        for _ in range(3)
    ]
    n = operators.revoke_all_operator_sessions(conn, seed_operator.id)
    assert n == 3
    for t in toks:
        assert operators.lookup_operator_session(conn, t) is None


# ──────────────────────────────────────────────────────────────────────────
# Operator magic-link (T1S.2 + T1S.5)
# ──────────────────────────────────────────────────────────────────────────


def test_issue_and_consume_operator_login_token(conn):
    tok = operators.issue_operator_login_token(
        conn, operator_email="new@acme.com", tenant_id="acme", invited_by="admin@acme.com"
    )
    result = operators.consume_operator_login_token(conn, tok)
    assert result == ("new@acme.com", "acme", "admin@acme.com")

    # Burned — second consume fails
    assert operators.consume_operator_login_token(conn, tok) is None


def test_consume_rejects_expired_operator_token(conn):
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    tok = operators.issue_operator_login_token(
        conn, operator_email="x@acme.com", tenant_id="acme", ttl_min=5, now=t0
    )
    # 10 min later — expired
    assert operators.consume_operator_login_token(
        conn, tok, now=t0 + timedelta(minutes=10)
    ) is None


def test_consume_rejects_admin_token_via_operator_path(conn):
    """Admin magic-link token MUST NOT authenticate as operator (role gate)."""
    admin_tok = auth.issue_login_token(conn, "admin@acme.com", tenant_id="acme")
    # Operator-path consume rejects this token (role='tenant_admin', default)
    assert operators.consume_operator_login_token(conn, admin_tok) is None

    # But the admin-path consume still works (M2 regression)
    assert auth.consume_login_token(conn, admin_tok) == ("admin@acme.com", "acme")


def test_consume_rejects_unknown_token(conn):
    assert operators.consume_operator_login_token(conn, "ghost-token") is None
