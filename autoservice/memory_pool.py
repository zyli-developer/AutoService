"""Conversation memory pool — SQLite store for per-turn data.

T4A.1 产出 | 2026-04-16

Records every conversation turn with intent, sentiment, KB hits, and
resolution status.  The Dream Engine (T4A.4) replays this data for
overnight analysis.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_DB_PATH = PROJECT_ROOT / ".autoservice" / "database" / "memory_pool.db"

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
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_turns_conv_turn
    ON memory_turns(conversation_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_memory_turns_timestamp
    ON memory_turns(timestamp);
"""


class MemoryPool:
    """SQLite-backed conversation memory pool."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_turn(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        intent: str | None = None,
        sentiment: str | None = None,
        kb_hit_count: int = 0,
        kb_sources: list[str] | None = None,
        resolution_status: str = "open",
        metadata: dict | None = None,
    ) -> int:
        """Record a single turn.  Returns the auto-generated turn id.

        ``turn_index`` is auto-incremented per *conversation_id*.
        """
        # Determine next turn_index for this conversation
        row = self._conn.execute(
            "SELECT COALESCE(MAX(turn_index), -1) AS max_idx "
            "FROM memory_turns WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        next_index: int = row["max_idx"] + 1

        now = datetime.now(tz=timezone.utc).isoformat()

        cursor = self._conn.execute(
            """INSERT INTO memory_turns
               (conversation_id, turn_index, timestamp, role, content,
                intent, sentiment, kb_hit_count, kb_sources,
                resolution_status, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            ),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_conversation(self, conversation_id: str) -> list[dict]:
        """Return all turns for *conversation_id*, ordered by turn_index."""
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
