"""Dream run tracking — SQLite store for Dream agent run metadata.

T2B.3 产出 | 2026-04-20

Per the tenant-sandbox M2 design spec §2.4 (runs table) and §2.2 last step
("run 结束写 runs.db 一条记录（tokens / duration / tool_calls）"), this
module persists one row per Dream agent run so the platform can observe
tool usage, token cost, proposal throughput, and failure modes.

The repository is intentionally a collection of module-level functions that
accept an explicit :class:`sqlite3.Connection`.  This keeps the module
easy to test (tests open an in-memory connection) and avoids a hidden
global singleton that complicates multi-tenant / multi-process callers.

Typical usage::

    from autoservice import dream_runs

    conn = dream_runs.open_connection()
    run_id = dream_runs.start_run(conn, tenant_id="acme")
    try:
        ...                                         # run the dream agent
        dream_runs.update_run(conn, run_id, tool_calls=7, proposals_emitted=2)
    finally:
        dream_runs.end_run(
            conn,
            run_id,
            status="completed",
            tokens_in=12_345,
            tokens_out=678,
        )
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_DB_PATH = PROJECT_ROOT / ".autoservice" / "database" / "dream_runs.db"

# Valid terminal statuses.  'running' is the initial state written by
# ``start_run``; ``end_run`` must transition to one of the terminals.
VALID_TERMINAL_STATUSES = frozenset({"completed", "failed", "overrun"})
VALID_STATUSES = frozenset({"running"}) | VALID_TERMINAL_STATUSES

SCHEMA = """\
CREATE TABLE IF NOT EXISTS dream_runs (
    id           TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    status       TEXT NOT NULL DEFAULT 'running',
    tool_calls   INTEGER NOT NULL DEFAULT 0,
    tokens_in    INTEGER,
    tokens_out   INTEGER,
    proposals_emitted INTEGER NOT NULL DEFAULT 0,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_dream_runs_tenant
    ON dream_runs(tenant_id, started_at DESC);
"""


# ──────────────────────────────────────────────────────────────────────────
# Schema / connection helpers
# ──────────────────────────────────────────────────────────────────────────


def init_schema(conn: sqlite3.Connection) -> None:
    """Create the ``dream_runs`` table and index if they do not already exist.

    Idempotent — safe to call repeatedly on the same connection.
    """
    conn.executescript(SCHEMA)
    conn.commit()


def open_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a :class:`sqlite3.Connection` and ensure the schema exists.

    If *db_path* is ``None`` the default location
    ``.autoservice/database/dream_runs.db`` is used, matching the peer
    ``memory_pool.db``.  The parent directory is created automatically.
    """
    path = db_path or _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


# ──────────────────────────────────────────────────────────────────────────
# Write API
# ──────────────────────────────────────────────────────────────────────────


def start_run(conn: sqlite3.Connection, tenant_id: str) -> str:
    """Insert a fresh ``running`` row for *tenant_id* and return its id.

    The id is a uuid4 hex string so callers can correlate logs / metrics.
    """
    run_id = uuid.uuid4().hex
    started_at = _utcnow_iso()
    conn.execute(
        """INSERT INTO dream_runs
             (id, tenant_id, started_at, status, tool_calls, proposals_emitted)
           VALUES (?, ?, ?, 'running', 0, 0)""",
        (run_id, tenant_id, started_at),
    )
    conn.commit()
    return run_id


def update_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    tool_calls: int | None = None,
    proposals_emitted: int | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> None:
    """Apply a partial update to an in-progress run.

    Any argument left as ``None`` is skipped — callers may freely update
    one field at a time (e.g. increment ``tool_calls`` as the agent works).
    Calling with no fields set is a no-op.
    """
    assignments: list[str] = []
    params: list[Any] = []

    if tool_calls is not None:
        assignments.append("tool_calls = ?")
        params.append(tool_calls)
    if proposals_emitted is not None:
        assignments.append("proposals_emitted = ?")
        params.append(proposals_emitted)
    if tokens_in is not None:
        assignments.append("tokens_in = ?")
        params.append(tokens_in)
    if tokens_out is not None:
        assignments.append("tokens_out = ?")
        params.append(tokens_out)

    if not assignments:
        return  # nothing to update

    params.append(run_id)
    conn.execute(
        f"UPDATE dream_runs SET {', '.join(assignments)} WHERE id = ?",
        params,
    )
    conn.commit()


def end_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    error: str | None = None,
) -> None:
    """Mark *run_id* as finished with *status* and stamp ``ended_at``.

    *status* must be one of ``completed``, ``failed`` or ``overrun``.  The
    optional ``tokens_in`` / ``tokens_out`` are the final accounting values
    (callers typically supply these at the end even if they have not been
    updated during the run).  ``error`` is typically populated only when
    ``status='failed'`` but the store does not enforce that — it is
    recorded verbatim so operators can attach context to e.g. ``overrun``.
    """
    if status not in VALID_TERMINAL_STATUSES:
        raise ValueError(
            f"Invalid terminal status {status!r}; "
            f"must be one of {sorted(VALID_TERMINAL_STATUSES)}"
        )

    ended_at = _utcnow_iso()
    assignments = ["ended_at = ?", "status = ?"]
    params: list[Any] = [ended_at, status]

    if tokens_in is not None:
        assignments.append("tokens_in = ?")
        params.append(tokens_in)
    if tokens_out is not None:
        assignments.append("tokens_out = ?")
        params.append(tokens_out)
    if error is not None:
        assignments.append("error = ?")
        params.append(error)

    params.append(run_id)
    conn.execute(
        f"UPDATE dream_runs SET {', '.join(assignments)} WHERE id = ?",
        params,
    )
    conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# Read API
# ──────────────────────────────────────────────────────────────────────────


def get_run(conn: sqlite3.Connection, run_id: str) -> dict | None:
    """Return the run row as a dict, or ``None`` if not found."""
    row = conn.execute(
        "SELECT * FROM dream_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def list_runs(
    conn: sqlite3.Connection,
    tenant_id: str,
    limit: int = 20,
) -> list[dict]:
    """Return the most recent runs for *tenant_id*, newest first.

    Results are capped at *limit* rows.  Ordered by ``started_at DESC``
    and broken ties by ``id`` so the ordering is deterministic even when
    two runs share a timestamp (common in tests).
    """
    rows = conn.execute(
        "SELECT * FROM dream_runs "
        "WHERE tenant_id = ? "
        "ORDER BY started_at DESC, id DESC "
        "LIMIT ?",
        (tenant_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────


def _utcnow_iso() -> str:
    """Current UTC timestamp in ISO-8601 format (seconds-precise)."""
    return datetime.now(tz=timezone.utc).isoformat()
