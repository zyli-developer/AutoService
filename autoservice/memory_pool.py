"""Conversation memory pool — SQLite store for per-turn data.

T4A.1 产出 | 2026-04-16
T2B.2 update | 2026-04-20 — tenant_id column + tenant-scoped read API
(spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §3.7)

Records every conversation turn with intent, sentiment, KB hits, and
resolution status.  The Dream Engine (T4A.4) replays this data for
overnight analysis.

M2 note: each row carries a ``tenant_id``. Legacy rows that existed
before this migration are back-filled to ``'_master'`` via the column
default. The Dream Scheduler/agent (T2B.1, T2B.3) consumes the new
tenant-scoped helpers ``recent(tid)`` / ``last_message_at(tid)``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_DB_PATH = PROJECT_ROOT / ".autoservice" / "database" / "memory_pool.db"

#: Bootstrap tenant id for the master deployment's internal tenant and
#: the back-fill value for legacy rows. Matches the convention in
#: the M2 design (§1.2, §3.7, §5.3 ``INTERNAL_TENANT_PREFIX``).
DEFAULT_TENANT_ID = "_master"

SCHEMA = """\
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
    metadata TEXT,
    tenant_id TEXT NOT NULL DEFAULT '_master'
);

CREATE INDEX IF NOT EXISTS idx_memory_turns_conv_turn
    ON memory_turns(conversation_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_memory_turns_timestamp
    ON memory_turns(timestamp);
"""
# NOTE: indexes that reference the ``tenant_id`` column are created
# inside ``_apply_migrations`` *after* the column is guaranteed to
# exist — otherwise opening a legacy pre-T2B.2 DB would fail at the
# ``executescript(SCHEMA)`` step (the index CREATE would reference a
# column that does not yet exist).


class MemoryPool:
    """SQLite-backed conversation memory pool."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._apply_migrations()

    # ------------------------------------------------------------------
    # Migrations (idempotent)
    # ------------------------------------------------------------------

    def _apply_migrations(self) -> None:
        """Apply any pending in-place schema migrations.

        Currently the only migration is adding ``tenant_id`` to legacy
        ``memory_turns`` rows (T2B.2). Detection uses
        ``PRAGMA table_info`` so the call is safe to re-run.
        """
        cols = {
            row["name"]
            for row in self._conn.execute(
                "PRAGMA table_info(memory_turns)"
            ).fetchall()
        }
        if "tenant_id" not in cols:
            # Legacy DB — add column with DEFAULT which back-fills
            # existing rows to '_master' in a single statement.
            self._conn.execute(
                "ALTER TABLE memory_turns "
                f"ADD COLUMN tenant_id TEXT NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'"
            )

        # Ensure the tenant indexes exist even on legacy databases that
        # were created before the index clauses in SCHEMA landed.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_turns_tenant "
            "ON memory_turns(tenant_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_turns_tenant_ts "
            "ON memory_turns(tenant_id, timestamp)"
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_turn(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        intent: str | None = None,
        sentiment: str | None = None,
        kb_hit_count: int = 0,
        kb_sources: list[str] | None = None,
        resolution_status: str = "open",
        metadata: dict | None = None,
    ) -> int:
        """Record a single turn.  Returns the auto-generated turn id.

        ``turn_index`` is auto-incremented per
        ``(tenant_id, conversation_id)``. Scoping the counter to the
        tenant keeps conversations belonging to different tenants that
        happen to share a ``conversation_id`` independent (not expected
        in practice but defensive against collisions).
        """
        # Determine next turn_index for this (tenant, conversation)
        row = self._conn.execute(
            "SELECT COALESCE(MAX(turn_index), -1) AS max_idx "
            "FROM memory_turns WHERE conversation_id = ? AND tenant_id = ?",
            (conversation_id, tenant_id),
        ).fetchone()
        next_index: int = row["max_idx"] + 1

        now = datetime.now(tz=timezone.utc).isoformat()

        cursor = self._conn.execute(
            """INSERT INTO memory_turns
               (conversation_id, turn_index, timestamp, role, content,
                intent, sentiment, kb_hit_count, kb_sources,
                resolution_status, metadata, tenant_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                conversation_id,
                next_index,
                now,
                role,
                content,
                intent,
                sentiment,
                kb_hit_count,
                json.dumps(kb_sources) if kb_sources else None,
                resolution_status,
                json.dumps(metadata) if metadata else None,
                tenant_id,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_conversation(self, conversation_id: str) -> list[dict]:
        """Return all turns for *conversation_id*, ordered by turn_index.

        Backwards-compatible: not tenant-scoped. Dream agent code
        should prefer :meth:`recent` which is tenant-scoped.
        """
        rows = self._conn.execute(
            "SELECT * FROM memory_turns WHERE conversation_id = ? "
            "ORDER BY turn_index",
            (conversation_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_conversations_in_range(
        self, start: str, end: str, *, limit: int = 100
    ) -> list[str]:
        """Return distinct conversation_ids with turns in [start, end]."""
        rows = self._conn.execute(
            "SELECT DISTINCT conversation_id FROM memory_turns "
            "WHERE timestamp >= ? AND timestamp <= ? "
            "ORDER BY timestamp LIMIT ?",
            (start, end, limit),
        ).fetchall()
        return [r["conversation_id"] for r in rows]

    def get_stats(self, conversation_id: str) -> dict:
        """Aggregate stats for a conversation.

        Returns ``{turn_count, sentiment_distribution, kb_hit_total,
        resolution_status}``.
        """
        turns = self.get_conversation(conversation_id)
        if not turns:
            return {
                "turn_count": 0,
                "sentiment_distribution": {},
                "kb_hit_total": 0,
                "resolution_status": None,
            }

        sentiment_dist: dict[str, int] = {}
        kb_total = 0
        for t in turns:
            s = t.get("sentiment")
            if s:
                sentiment_dist[s] = sentiment_dist.get(s, 0) + 1
            kb_total += t.get("kb_hit_count", 0) or 0

        return {
            "turn_count": len(turns),
            "sentiment_distribution": sentiment_dist,
            "kb_hit_total": kb_total,
            "resolution_status": turns[-1].get("resolution_status"),
        }

    # ------------------------------------------------------------------
    # Tenant-scoped API (T2B.2 / spec §3.7)
    # ------------------------------------------------------------------

    def recent(self, tenant_id: str, limit: int = 20) -> list[dict]:
        """Return the *limit* most-recent turns for *tenant_id*.

        Ordered newest-first by ``timestamp`` then ``id``. Each row is
        deserialised the same way :meth:`get_conversation` does, so
        callers see ``kb_sources`` / ``metadata`` as Python objects.

        The Dream agent feeds this directly into the LLM context
        (spec §2.2 "最近 N=20 条对话").
        """
        rows = self._conn.execute(
            "SELECT * FROM memory_turns WHERE tenant_id = ? "
            "ORDER BY timestamp DESC, id DESC LIMIT ?",
            (tenant_id, int(limit)),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def last_message_at(self, tenant_id: str) -> datetime | None:
        """Return the timestamp of the tenant's most-recent turn.

        Returns ``None`` if the tenant has no recorded turns.

        Used by :class:`DreamScheduler` (T2B.1) to evaluate
        ``config.json.dream.trigger=idle`` — a tenant is "idle" when
        ``now - last_message_at > idle_threshold_min``.
        """
        row = self._conn.execute(
            "SELECT MAX(timestamp) AS ts FROM memory_turns WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchone()
        if row is None or row["ts"] is None:
            return None
        return _parse_iso_utc(row["ts"])

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        # Deserialise JSON fields
        if d.get("kb_sources"):
            try:
                d["kb_sources"] = json.loads(d["kb_sources"])
            except (json.JSONDecodeError, TypeError):
                pass
        if d.get("metadata"):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d


def _parse_iso_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp as a timezone-aware UTC datetime.

    Tolerant of the trailing ``Z`` shorthand that some clients write.
    """
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
