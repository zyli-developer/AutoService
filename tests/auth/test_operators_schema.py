"""Unit tests for ``autoservice.operators`` schema + migration (M3 T1S.1).

Contract: docs/contracts/m3/e1-auth-rbac.md §2 (Session Storage).

Covers:
* `operators` + `operator_sessions` table creation + idempotency
* CHECK constraints on `role` and `status`
* UNIQUE(tenant_id, email) on operators
* FK operator_sessions.operator_id → operators.id with ON DELETE CASCADE
* `login_tokens` migration: ADD COLUMN role + invited_by (idempotent)
* Migration preserves existing login_token rows (M2 regression guard)

All tests use in-memory sqlite3 for isolation — M2 pattern (tests/auth/test_repository.py).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from autoservice import auth, operators


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """In-memory sqlite3 connection with M2 auth schema + M3 operators schema applied."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")  # required for FK enforcement in tests
    auth.apply_schema(c)
    operators.apply_operators_schema(c)
    operators.migrate_login_tokens_add_role(c)
    yield c
    c.close()


@pytest.fixture()
def m2_conn() -> sqlite3.Connection:
    """Connection with ONLY M2 schema — used to test M3 migrations on pre-existing data."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    auth.apply_schema(c)
    yield c
    c.close()


# ──────────────────────────────────────────────────────────────────────────
# Schema creation
# ──────────────────────────────────────────────────────────────────────────


def test_apply_operators_schema_creates_tables(conn):
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"operators", "operator_sessions"}.issubset(tables)


def test_apply_operators_schema_idempotent(conn):
    # Calling twice must not raise (uses CREATE TABLE IF NOT EXISTS).
    operators.apply_operators_schema(conn)
    operators.apply_operators_schema(conn)


def test_cookie_name_constant():
    # CON-08: separate from auth_session (admin)
    assert operators.OPERATOR_SESSION_COOKIE_NAME == "operator_session"
    assert operators.OPERATOR_SESSION_COOKIE_NAME != auth.AUTH_SESSION_COOKIE_NAME


# ──────────────────────────────────────────────────────────────────────────
# operators table constraints
# ──────────────────────────────────────────────────────────────────────────


def test_operator_role_check_constraint(conn):
    now = datetime.now(tz=timezone.utc).isoformat()
    # Valid role — inserts cleanly
    conn.execute(
        "INSERT INTO operators (id, tenant_id, email, role, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("op-1", "acme", "op1@example.com", "viewer", "active", now),
    )

    # Invalid role — CHECK constraint raises
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO operators (id, tenant_id, email, role, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("op-2", "acme", "op2@example.com", "superadmin", "active", now),
        )


def test_operator_status_check_constraint(conn):
    now = datetime.now(tz=timezone.utc).isoformat()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO operators (id, tenant_id, email, role, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("op-x", "acme", "ox@example.com", "responder", "maybe", now),
        )


def test_operator_unique_per_tenant_email(conn):
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO operators (id, tenant_id, email, role, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("op-a", "acme", "dup@example.com", "viewer", "active", now),
    )
    # Same tenant + email → UNIQUE violation
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO operators (id, tenant_id, email, role, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("op-b", "acme", "dup@example.com", "admin", "active", now),
        )

    # Same email across tenants is OK (operators are per-tenant)
    conn.execute(
        "INSERT INTO operators (id, tenant_id, email, role, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("op-c", "other-tenant", "dup@example.com", "viewer", "active", now),
    )


def test_operator_role_accepts_all_three_tiers(conn):
    now = datetime.now(tz=timezone.utc).isoformat()
    for idx, role in enumerate(["viewer", "responder", "admin"]):
        conn.execute(
            "INSERT INTO operators (id, tenant_id, email, role, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (f"op-{idx}", "acme", f"r{idx}@example.com", role, "active", now),
        )


# ──────────────────────────────────────────────────────────────────────────
# operator_sessions foreign key
# ──────────────────────────────────────────────────────────────────────────


def test_operator_session_fk_to_operators(conn):
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO operators (id, tenant_id, email, role, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("op-valid", "acme", "v@example.com", "viewer", "active", now),
    )
    # Valid: operator_id references existing operator
    conn.execute(
        "INSERT INTO operator_sessions "
        "(token, operator_id, tenant_id, issued_at, expires_at, idle_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("tok-1", "op-valid", "acme", now, now, now),
    )

    # Invalid: operator_id does not exist → FK error (foreign_keys = ON fixture)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO operator_sessions "
            "(token, operator_id, tenant_id, issued_at, expires_at, idle_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("tok-bad", "op-missing", "acme", now, now, now),
        )


def test_operator_session_cascade_on_operator_delete(conn):
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO operators (id, tenant_id, email, role, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("op-del", "acme", "del@example.com", "viewer", "active", now),
    )
    conn.execute(
        "INSERT INTO operator_sessions "
        "(token, operator_id, tenant_id, issued_at, expires_at, idle_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("tok-del", "op-del", "acme", now, now, now),
    )
    conn.execute("DELETE FROM operators WHERE id = ?", ("op-del",))
    # Cascade deletes the session
    row = conn.execute(
        "SELECT token FROM operator_sessions WHERE token = ?", ("tok-del",)
    ).fetchone()
    assert row is None


# ──────────────────────────────────────────────────────────────────────────
# login_tokens migration (add role + invited_by)
# ──────────────────────────────────────────────────────────────────────────


def test_migrate_login_tokens_adds_role_column(m2_conn):
    # Before migration: M2 schema has no `role` column
    cols_before = {r[1] for r in m2_conn.execute("PRAGMA table_info(login_tokens)")}
    assert "role" not in cols_before
    assert "invited_by" not in cols_before

    operators.migrate_login_tokens_add_role(m2_conn)

    cols_after = {r[1] for r in m2_conn.execute("PRAGMA table_info(login_tokens)")}
    assert "role" in cols_after
    assert "invited_by" in cols_after


def test_migration_idempotent(m2_conn):
    operators.migrate_login_tokens_add_role(m2_conn)
    # Second call must not raise (already-added columns skipped)
    operators.migrate_login_tokens_add_role(m2_conn)
    operators.migrate_login_tokens_add_role(m2_conn)


def test_migration_preserves_existing_rows(m2_conn):
    # Seed pre-migration login_token row (M2 shape)
    existing_token = auth.issue_login_token(
        m2_conn, "existing@example.com", tenant_id="legacy-tenant"
    )

    # Run migration
    operators.migrate_login_tokens_add_role(m2_conn)

    # Existing row preserved; role defaulted to 'tenant_admin'
    row = m2_conn.execute(
        "SELECT admin_email, tenant_id, role, invited_by "
        "FROM login_tokens WHERE token = ?",
        (existing_token,),
    ).fetchone()
    assert row is not None
    assert row["admin_email"] == "existing@example.com"
    assert row["tenant_id"] == "legacy-tenant"
    assert row["role"] == "tenant_admin"
    assert row["invited_by"] is None


def test_migration_default_role_is_tenant_admin(m2_conn):
    operators.migrate_login_tokens_add_role(m2_conn)
    now = datetime.now(tz=timezone.utc).isoformat()
    m2_conn.execute(
        "INSERT INTO login_tokens "
        "(token, admin_email, tenant_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("tok-new", "a@example.com", "acme", now, now),
    )
    row = m2_conn.execute(
        "SELECT role FROM login_tokens WHERE token = ?", ("tok-new",)
    ).fetchone()
    assert row["role"] == "tenant_admin"  # default per contract §3


def test_migration_allows_operator_role_insert(m2_conn):
    operators.migrate_login_tokens_add_role(m2_conn)
    now = datetime.now(tz=timezone.utc).isoformat()
    # Role='operator' now insertable post-migration (used by T1S.5 invite flow)
    m2_conn.execute(
        "INSERT INTO login_tokens "
        "(token, admin_email, tenant_id, created_at, expires_at, role, invited_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "inv-tok",
            "new-op@example.com",
            "acme",
            now,
            now,
            "operator",
            "admin@acme.com",
        ),
    )
    row = m2_conn.execute(
        "SELECT role, invited_by FROM login_tokens WHERE token = ?", ("inv-tok",)
    ).fetchone()
    assert row["role"] == "operator"
    assert row["invited_by"] == "admin@acme.com"
