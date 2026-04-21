"""T2B.2 — memory_pool tenant_id column migration + tenant-scoped API.

Covers:
- Fresh DB has ``tenant_id`` column on ``memory_turns``
- Legacy DB (created without the column) is upgraded in-place and
  existing rows are back-filled with ``'_master'``
- The migration is idempotent (opening an already-migrated DB a
  second time is a no-op)
- ``recent(tenant_id, limit)`` filters rows by tenant
- ``last_message_at(tenant_id)`` returns the tenant's most-recent
  timestamp only

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §3.7
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from autoservice.memory_pool import DEFAULT_TENANT_ID, MemoryPool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Schema that the memory_pool shipped *before* T2B.2 — used to simulate
# a "legacy" database file on disk that the migration must upgrade.
_LEGACY_SCHEMA = """\
CREATE TABLE IF NOT EXISTS memory_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    intent TEXT,
    sentiment TEXT,
    kb_hit_count INTEGER DEFAULT 0,
    kb_sources TEXT,
    resolution_status TEXT DEFAULT 'open',
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_turns_conv_turn
    ON memory_turns(conversation_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_memory_turns_timestamp
    ON memory_turns(timestamp);
"""


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _make_legacy_db(path) -> None:
    """Create a memory_pool.db in the pre-T2B.2 shape with one row.

    The row is inserted *before* the migration so we can assert that
    back-fill assigns ``'_master'`` to pre-existing data.
    """
    conn = sqlite3.connect(str(path))
    conn.executescript(_LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO memory_turns "
        "(conversation_id, turn_index, timestamp, role, content) "
        "VALUES (?, ?, ?, ?, ?)",
        ("legacy-conv", 0, "2026-04-10T00:00:00+00:00", "customer", "hello"),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Schema / migration
# ---------------------------------------------------------------------------


def test_fresh_db_has_tenant_id_column(tmp_path):
    """A brand-new DB ships with the tenant_id column + NOT NULL + default."""
    mp = MemoryPool(db_path=tmp_path / "fresh.db")
    try:
        cols = _table_columns(mp._conn, "memory_turns")
        assert "tenant_id" in cols

        # Verify NOT NULL + DEFAULT via the column metadata.
        meta = {
            row[1]: row
            for row in mp._conn.execute("PRAGMA table_info(memory_turns)").fetchall()
        }
        tenant_col = meta["tenant_id"]
        # table_info columns: cid, name, type, notnull, dflt_value, pk
        assert tenant_col[2].upper() == "TEXT"
        assert tenant_col[3] == 1, "tenant_id must be NOT NULL"
        assert tenant_col[4] is not None, "tenant_id must carry a DEFAULT"
        # Default literal is quoted in sqlite's reflection.
        assert DEFAULT_TENANT_ID in str(tenant_col[4])
    finally:
        mp.close()


def test_migration_upgrades_legacy_db(tmp_path):
    """Opening a pre-T2B.2 DB adds the column and back-fills '_master'."""
    db_path = tmp_path / "legacy.db"
    _make_legacy_db(db_path)

    # Sanity check — column truly absent before migration
    pre = sqlite3.connect(str(db_path))
    assert "tenant_id" not in _table_columns(pre, "memory_turns")
    pre.close()

    mp = MemoryPool(db_path=db_path)
    try:
        cols = _table_columns(mp._conn, "memory_turns")
        assert "tenant_id" in cols

        # Existing legacy row is back-filled to '_master'.
        rows = mp._conn.execute(
            "SELECT conversation_id, tenant_id FROM memory_turns"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["conversation_id"] == "legacy-conv"
        assert rows[0]["tenant_id"] == DEFAULT_TENANT_ID
    finally:
        mp.close()


def test_migration_idempotent(tmp_path):
    """Re-opening an already-migrated DB must not fail or duplicate work."""
    db_path = tmp_path / "idem.db"
    _make_legacy_db(db_path)

    # First open: performs the ALTER TABLE.
    mp1 = MemoryPool(db_path=db_path)
    mp1.close()

    # Second open: column already present — must be a no-op.
    mp2 = MemoryPool(db_path=db_path)
    try:
        cols = _table_columns(mp2._conn, "memory_turns")
        assert "tenant_id" in cols
        # Row count unchanged.
        count = mp2._conn.execute(
            "SELECT COUNT(*) AS n FROM memory_turns"
        ).fetchone()["n"]
        assert count == 1
    finally:
        mp2.close()

    # Third open to really hammer the idempotency guarantee.
    mp3 = MemoryPool(db_path=db_path)
    try:
        count = mp3._conn.execute(
            "SELECT COUNT(*) AS n FROM memory_turns"
        ).fetchone()["n"]
        assert count == 1
    finally:
        mp3.close()


# ---------------------------------------------------------------------------
# Tenant-scoped read API
# ---------------------------------------------------------------------------


@pytest.fixture()
def pool(tmp_path):
    mp = MemoryPool(db_path=tmp_path / "scoped.db")
    yield mp
    mp.close()


def test_recent_filters_by_tenant_id(pool: MemoryPool):
    """``recent(tid)`` must only return rows for the requested tenant."""
    pool.record_turn("convA", "customer", "A-1", tenant_id="tenant_A")
    pool.record_turn("convA", "agent", "A-2", tenant_id="tenant_A")
    pool.record_turn("convB", "customer", "B-1", tenant_id="tenant_B")
    pool.record_turn("convB", "agent", "B-2", tenant_id="tenant_B")
    pool.record_turn("convB", "customer", "B-3", tenant_id="tenant_B")

    a_rows = pool.recent("tenant_A", limit=20)
    b_rows = pool.recent("tenant_B", limit=20)

    assert len(a_rows) == 2
    assert {r["content"] for r in a_rows} == {"A-1", "A-2"}
    assert all(r["tenant_id"] == "tenant_A" for r in a_rows)

    assert len(b_rows) == 3
    assert {r["content"] for r in b_rows} == {"B-1", "B-2", "B-3"}
    assert all(r["tenant_id"] == "tenant_B" for r in b_rows)


def test_recent_respects_limit_and_order(pool: MemoryPool):
    """``recent`` returns newest-first and honours the limit."""
    for i in range(5):
        pool.record_turn("c", "customer", f"msg-{i}", tenant_id="tenant_A")

    rows = pool.recent("tenant_A", limit=3)
    assert len(rows) == 3
    # Newest first: msg-4, msg-3, msg-2
    assert [r["content"] for r in rows] == ["msg-4", "msg-3", "msg-2"]


def test_recent_unknown_tenant_returns_empty(pool: MemoryPool):
    pool.record_turn("c", "customer", "hi", tenant_id="tenant_A")
    assert pool.recent("ghost") == []


def test_last_message_at_is_tenant_scoped(pool: MemoryPool):
    """``last_message_at(tid)`` reads only that tenant's timestamps."""
    # Insert with deterministic timestamps via direct SQL so we can
    # compare the returned datetime exactly.
    pool._conn.execute(
        "INSERT INTO memory_turns "
        "(conversation_id, turn_index, timestamp, role, content, tenant_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cA", 0, "2026-04-10T12:00:00+00:00", "customer", "hi-A", "tenant_A"),
    )
    pool._conn.execute(
        "INSERT INTO memory_turns "
        "(conversation_id, turn_index, timestamp, role, content, tenant_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cA", 1, "2026-04-11T12:00:00+00:00", "agent", "hi-A2", "tenant_A"),
    )
    pool._conn.execute(
        "INSERT INTO memory_turns "
        "(conversation_id, turn_index, timestamp, role, content, tenant_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cB", 0, "2026-04-15T00:00:00+00:00", "customer", "hi-B", "tenant_B"),
    )
    pool._conn.commit()

    ts_a = pool.last_message_at("tenant_A")
    ts_b = pool.last_message_at("tenant_B")

    assert ts_a == datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc)
    assert ts_b == datetime(2026, 4, 15, 0, 0, 0, tzinfo=timezone.utc)
    # Tenant A's later timestamp must NOT leak into B's max and vice versa.
    assert ts_a < ts_b


def test_last_message_at_returns_none_for_empty_tenant(pool: MemoryPool):
    pool.record_turn("c", "customer", "hi", tenant_id="tenant_A")
    assert pool.last_message_at("tenant_B") is None
    assert pool.last_message_at("nonexistent") is None


def test_record_turn_defaults_to_master_tenant(pool: MemoryPool):
    """Callers that pre-date T2B.2 land on the '_master' tenant."""
    pool.record_turn("c1", "customer", "hello")  # no tenant_id kwarg
    rows = pool.recent(DEFAULT_TENANT_ID, limit=10)
    assert len(rows) == 1
    assert rows[0]["content"] == "hello"
    assert rows[0]["tenant_id"] == DEFAULT_TENANT_ID
