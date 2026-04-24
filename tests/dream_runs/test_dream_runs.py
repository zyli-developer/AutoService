"""Unit tests for ``autoservice.dream_runs`` (T2B.3).

Covers idempotent schema init, run lifecycle (start → update → end),
terminal status variants (``completed`` / ``failed`` / ``overrun``),
tenant-scoped listing, ordering, and partial updates.

Each test uses an in-memory SQLite connection so the suite is hermetic
and does not touch ``.autoservice/database/``.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from autoservice import dream_runs


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """In-memory SQLite connection with schema pre-applied."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dream_runs.init_schema(c)
    yield c
    c.close()


# ──────────────────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────────────────


def test_init_schema_idempotent(conn: sqlite3.Connection) -> None:
    """Calling init_schema twice must not raise or duplicate the table."""
    dream_runs.init_schema(conn)  # first call in fixture, now a second
    dream_runs.init_schema(conn)

    tables = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='dream_runs'"
    ).fetchall()
    assert len(tables) == 1

    indexes = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND name='idx_dream_runs_tenant'"
    ).fetchall()
    assert len(indexes) == 1


# ──────────────────────────────────────────────────────────────────────────
# start_run
# ──────────────────────────────────────────────────────────────────────────


def test_start_run_creates_running_row(conn: sqlite3.Connection) -> None:
    run_id = dream_runs.start_run(conn, tenant_id="tenant_A")

    assert isinstance(run_id, str)
    assert len(run_id) == 32  # uuid4 hex

    row = dream_runs.get_run(conn, run_id)
    assert row is not None
    assert row["tenant_id"] == "tenant_A"
    assert row["status"] == "running"
    assert row["ended_at"] is None
    assert row["tool_calls"] == 0
    assert row["proposals_emitted"] == 0
    assert row["tokens_in"] is None
    assert row["tokens_out"] is None
    assert row["error"] is None
    assert row["started_at"]  # non-empty ISO timestamp


# ──────────────────────────────────────────────────────────────────────────
# end_run
# ──────────────────────────────────────────────────────────────────────────


def test_end_run_completed(conn: sqlite3.Connection) -> None:
    """start → end(completed) stamps ended_at and final status."""
    run_id = dream_runs.start_run(conn, tenant_id="tenant_A")

    dream_runs.end_run(
        conn,
        run_id,
        status="completed",
        tokens_in=12_345,
        tokens_out=678,
    )

    row = dream_runs.get_run(conn, run_id)
    assert row is not None
    assert row["status"] == "completed"
    assert row["ended_at"] is not None
    assert row["tokens_in"] == 12_345
    assert row["tokens_out"] == 678
    assert row["error"] is None


def test_end_run_failed_records_error(conn: sqlite3.Connection) -> None:
    run_id = dream_runs.start_run(conn, tenant_id="tenant_A")

    dream_runs.end_run(
        conn,
        run_id,
        status="failed",
        error="MCP tool timeout after 30s",
    )

    row = dream_runs.get_run(conn, run_id)
    assert row is not None
    assert row["status"] == "failed"
    assert row["error"] == "MCP tool timeout after 30s"
    assert row["ended_at"] is not None


def test_end_run_overrun(conn: sqlite3.Connection) -> None:
    """status='overrun' must be accepted as a valid terminal state."""
    run_id = dream_runs.start_run(conn, tenant_id="tenant_A")

    dream_runs.end_run(
        conn,
        run_id,
        status="overrun",
        tokens_in=9_999,
        tokens_out=10,
        error="tool_calls cap reached",
    )

    row = dream_runs.get_run(conn, run_id)
    assert row is not None
    assert row["status"] == "overrun"
    assert row["ended_at"] is not None
    assert row["error"] == "tool_calls cap reached"


def test_end_run_rejects_invalid_status(conn: sqlite3.Connection) -> None:
    """end_run must reject non-terminal / unknown status values."""
    run_id = dream_runs.start_run(conn, tenant_id="tenant_A")

    with pytest.raises(ValueError):
        dream_runs.end_run(conn, run_id, status="running")
    with pytest.raises(ValueError):
        dream_runs.end_run(conn, run_id, status="bogus")


# ──────────────────────────────────────────────────────────────────────────
# update_run
# ──────────────────────────────────────────────────────────────────────────


def test_update_run_partial(conn: sqlite3.Connection) -> None:
    """Unspecified fields are preserved; specified fields overwrite."""
    run_id = dream_runs.start_run(conn, tenant_id="tenant_A")

    # Set tool_calls only
    dream_runs.update_run(conn, run_id, tool_calls=3)
    row = dream_runs.get_run(conn, run_id)
    assert row["tool_calls"] == 3
    assert row["proposals_emitted"] == 0
    assert row["tokens_in"] is None

    # Update proposals_emitted; tool_calls must stay 3
    dream_runs.update_run(conn, run_id, proposals_emitted=2)
    row = dream_runs.get_run(conn, run_id)
    assert row["tool_calls"] == 3
    assert row["proposals_emitted"] == 2

    # Update tokens_in/out without touching the rest
    dream_runs.update_run(conn, run_id, tokens_in=500, tokens_out=100)
    row = dream_runs.get_run(conn, run_id)
    assert row["tool_calls"] == 3
    assert row["proposals_emitted"] == 2
    assert row["tokens_in"] == 500
    assert row["tokens_out"] == 100
    assert row["status"] == "running"  # not ended

    # No-op call must not raise and must not change anything
    dream_runs.update_run(conn, run_id)
    row2 = dream_runs.get_run(conn, run_id)
    assert row2["tool_calls"] == 3
    assert row2["proposals_emitted"] == 2


# ──────────────────────────────────────────────────────────────────────────
# list_runs
# ──────────────────────────────────────────────────────────────────────────


def test_list_runs_tenant_scoped(conn: sqlite3.Connection) -> None:
    """Runs from other tenants must not appear."""
    a1 = dream_runs.start_run(conn, tenant_id="tenant_A")
    a2 = dream_runs.start_run(conn, tenant_id="tenant_A")
    b1 = dream_runs.start_run(conn, tenant_id="tenant_B")

    a_list = dream_runs.list_runs(conn, "tenant_A")
    b_list = dream_runs.list_runs(conn, "tenant_B")

    a_ids = {r["id"] for r in a_list}
    b_ids = {r["id"] for r in b_list}

    assert a_ids == {a1, a2}
    assert b_ids == {b1}
    assert a_ids.isdisjoint(b_ids)


def test_list_runs_ordered_desc(conn: sqlite3.Connection) -> None:
    """list_runs returns newest started_at first."""
    first = dream_runs.start_run(conn, tenant_id="tenant_A")
    # Sleep ~2 ms so ISO timestamps differ at microsecond resolution.
    # SQLite TEXT comparison on ISO-8601 is lexicographic, which matches
    # chronological order for same-offset timestamps.
    time.sleep(0.002)
    second = dream_runs.start_run(conn, tenant_id="tenant_A")
    time.sleep(0.002)
    third = dream_runs.start_run(conn, tenant_id="tenant_A")

    rows = dream_runs.list_runs(conn, "tenant_A")
    assert [r["id"] for r in rows] == [third, second, first]


def test_list_runs_respects_limit(conn: sqlite3.Connection) -> None:
    for _ in range(5):
        dream_runs.start_run(conn, tenant_id="tenant_A")
        time.sleep(0.001)

    rows = dream_runs.list_runs(conn, "tenant_A", limit=3)
    assert len(rows) == 3


# ──────────────────────────────────────────────────────────────────────────
# get_run
# ──────────────────────────────────────────────────────────────────────────


def test_get_run_missing_returns_none(conn: sqlite3.Connection) -> None:
    assert dream_runs.get_run(conn, "nonexistent") is None


# ──────────────────────────────────────────────────────────────────────────
# open_connection
# ──────────────────────────────────────────────────────────────────────────


def test_open_connection_initializes_schema(tmp_path) -> None:
    """open_connection must create the parent dir and apply the schema."""
    db_path = tmp_path / "nested" / "dream_runs.db"
    conn = dream_runs.open_connection(db_path=db_path)
    try:
        assert db_path.exists()
        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='dream_runs'"
        ).fetchall()
        assert len(tables) == 1

        # Sanity: round-trip a run through a real file-backed connection
        run_id = dream_runs.start_run(conn, tenant_id="tenant_A")
        dream_runs.end_run(conn, run_id, status="completed")
        row = dream_runs.get_run(conn, run_id)
        assert row["status"] == "completed"
    finally:
        conn.close()
