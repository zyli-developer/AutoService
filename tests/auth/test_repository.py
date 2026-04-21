"""Unit tests for ``autoservice.auth`` repository functions (T5B.1).

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §5.1.

Covers the schema + repository layer in isolation — no FastAPI, no HTTP.
Each test opens an in-memory sqlite3 connection so the suite is fast and
independent of the on-disk ``.autoservice/database/auth.db``.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from autoservice import auth


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Fresh in-memory sqlite3 connection with auth schema applied."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    auth.apply_schema(c)
    yield c
    c.close()


# ── Schema ────────────────────────────────────────────────────────────────


def test_apply_schema_is_idempotent(conn):
    # Second call MUST NOT raise (IF NOT EXISTS clauses in SCHEMA).
    auth.apply_schema(conn)
    auth.apply_schema(conn)

    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"login_tokens", "sessions"}.issubset(tables)


# ── Login tokens ──────────────────────────────────────────────────────────


def test_issue_and_consume_login_token_roundtrip(conn):
    token = auth.issue_login_token(conn, "admin@example.com", tenant_id="acme")
    assert isinstance(token, str) and len(token) >= 20

    result = auth.consume_login_token(conn, token)
    assert result == ("admin@example.com", "acme")

    # Second consume must fail (burn-on-first-use invariant).
    assert auth.consume_login_token(conn, token) is None

    row = conn.execute(
        "SELECT consumed_at FROM login_tokens WHERE token = ?", (token,)
    ).fetchone()
    assert row["consumed_at"] is not None


def test_consume_expired_token_returns_none_and_does_not_burn(conn):
    token = auth.issue_login_token(conn, "admin@example.com", ttl_min=10)

    # Simulate "20 minutes later" via explicit ``now``.
    future = datetime.now(tz=timezone.utc) + timedelta(minutes=20)
    assert auth.consume_login_token(conn, token, now=future) is None

    row = conn.execute(
        "SELECT consumed_at FROM login_tokens WHERE token = ?", (token,)
    ).fetchone()
    # CRITICAL: expired tokens stay un-burned so operators can debug.
    assert row["consumed_at"] is None


def test_consume_unknown_token_returns_none(conn):
    assert auth.consume_login_token(conn, "not-a-real-token") is None


# ── Sessions ──────────────────────────────────────────────────────────────


def test_create_and_lookup_session_roundtrip(conn):
    sid = auth.create_session(conn, "admin@example.com", tenant_id=None)
    assert isinstance(sid, str) and len(sid) >= 30

    session = auth.lookup_session(conn, sid)
    assert session is not None
    assert session["admin_email"] == "admin@example.com"
    assert session["tenant_id"] is None  # _master tier 0 has NULL tenant
    assert "expires_at" in session


def test_revoke_session_makes_lookup_return_none(conn):
    sid = auth.create_session(conn, "admin@example.com", tenant_id="acme")
    assert auth.lookup_session(conn, sid) is not None

    auth.revoke_session(conn, sid)
    assert auth.lookup_session(conn, sid) is None

    # Idempotent — revoking twice is a no-op, not an error.
    auth.revoke_session(conn, sid)
    auth.revoke_session(conn, "nonexistent-session-id")


def test_lookup_expired_session_returns_none(conn):
    sid = auth.create_session(conn, "admin@example.com", ttl_days=30)

    future = datetime.now(tz=timezone.utc) + timedelta(days=31)
    assert auth.lookup_session(conn, sid, now=future) is None
