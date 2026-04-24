"""ConversationStore — SQLite persistence for LocalEngine state.

LocalEngine holds conversations / participants / messages / events / sequence
counters in Python dicts.  Prior to this module those were lost on every
process restart, so operator-console history disappeared between deploys.

This store adds write-through persistence against
``.autoservice/database/conversations.db``.  The engine keeps its in-memory
dicts as a hot cache; every mutation is mirrored to SQLite via the methods
below, and ``load_all()`` re-populates the dicts on startup.

Scope & non-goals
-----------------
* We persist **domain state** (conversations, participants, messages,
  events, sequences).
* We do **not** persist transient asyncio state: takeover timers, user-set
  timers, mode locks, subscriber queues.  On restart, timers are re-armed
  lazily by whoever drives the conversation again; subscribers re-connect
  via normal WS handshake.
* The store is intentionally synchronous — SQLite writes are fast enough
  in-process that blocking the event loop briefly is fine, and it keeps
  the call sites simple.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    ConversationState,
    Event,
    Message,
    MessageVisibility,
    Outcome,
    Participant,
    ParticipantRole,
    Resolution,
)

log = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / ".autoservice" / "database" / "conversations.db"


SCHEMA = """\
CREATE TABLE IF NOT EXISTS conversations (
    id                   TEXT PRIMARY KEY,
    state                TEXT NOT NULL,
    mode                 TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    metadata             TEXT NOT NULL,
    resolution           TEXT,
    takeover_operator_id TEXT
);

CREATE TABLE IF NOT EXISTS participants (
    conv_id         TEXT NOT NULL,
    participant_id  TEXT NOT NULL,
    role            TEXT NOT NULL,
    joined_at       TEXT NOT NULL,
    position        INTEGER NOT NULL,
    metadata        TEXT NOT NULL,
    PRIMARY KEY (conv_id, participant_id),
    FOREIGN KEY (conv_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_participants_conv
    ON participants(conv_id, position);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conv_id         TEXT NOT NULL,
    source          TEXT NOT NULL,
    content         TEXT NOT NULL,
    visibility      TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    edit_of         TEXT,
    metadata        TEXT NOT NULL,
    FOREIGN KEY (conv_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_conv_seq
    ON messages(conv_id, sequence_number);

CREATE TABLE IF NOT EXISTS events (
    id              TEXT PRIMARY KEY,
    conv_id         TEXT NOT NULL,
    type            TEXT NOT NULL,
    data            TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    FOREIGN KEY (conv_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_events_conv_seq
    ON events(conv_id, sequence_number);

CREATE TABLE IF NOT EXISTS sequences (
    conv_id         TEXT PRIMARY KEY,
    next_msg_seq    INTEGER NOT NULL DEFAULT 0,
    next_event_seq  INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (conv_id) REFERENCES conversations(id) ON DELETE CASCADE
);
"""


# ── helpers ───────────────────────────────────────────────────────────────

def _iso(ts: datetime) -> str:
    return ts.isoformat()


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _loads(raw: str | None) -> Any:
    if not raw:
        return {}
    return json.loads(raw)


# ── loaded-state container ────────────────────────────────────────────────

@dataclass
class LoadedState:
    """Snapshot returned by ``ConversationStore.load_all()``.

    LocalEngine pours these directly into its in-memory dicts at startup.
    """
    conversations: dict[str, Conversation] = field(default_factory=dict)
    participants: dict[str, list[Participant]] = field(default_factory=dict)
    messages: dict[str, list[Message]] = field(default_factory=dict)
    events: dict[str, list[Event]] = field(default_factory=dict)
    next_msg_seq: dict[str, int] = field(default_factory=dict)
    next_event_seq: dict[str, int] = field(default_factory=dict)


# ── store ─────────────────────────────────────────────────────────────────

class ConversationStore:
    """Synchronous SQLite-backed persistence for LocalEngine.

    Open once at LocalEngine construction; the engine calls the ``save_*``
    and ``delete_*`` methods write-through at each mutation site.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._apply_schema()

    def _apply_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ── serialization helpers ──────────────────────────────────────────────

    @staticmethod
    def _conv_to_row(conv: Conversation) -> tuple[Any, ...]:
        resolution = (
            _dumps({
                "outcome": conv.resolution.outcome.value,
                "resolved_by": conv.resolution.resolved_by,
                "csat_score": conv.resolution.csat_score,
                "timestamp": _iso(conv.resolution.timestamp),
            })
            if conv.resolution is not None
            else None
        )
        return (
            conv.id,
            conv.state.value,
            conv.mode.value,
            _iso(conv.created_at),
            _iso(conv.updated_at),
            _dumps(dict(conv.metadata)),
            resolution,
            conv.takeover_operator_id,
        )

    @staticmethod
    def _row_to_resolution(raw: str | None) -> Resolution | None:
        if raw is None:
            return None
        d = json.loads(raw)
        return Resolution(
            outcome=Outcome(d["outcome"]),
            resolved_by=d["resolved_by"],
            csat_score=d.get("csat_score"),
            timestamp=_parse_ts(d["timestamp"]),
        )

    @classmethod
    def _row_to_conv(
        cls, row: sqlite3.Row, participants: tuple[Participant, ...],
    ) -> Conversation:
        return Conversation(
            id=row["id"],
            state=ConversationState(row["state"]),
            mode=ConversationMode(row["mode"]),
            participants=participants,
            created_at=_parse_ts(row["created_at"]),
            updated_at=_parse_ts(row["updated_at"]),
            metadata=_loads(row["metadata"]),
            resolution=cls._row_to_resolution(row["resolution"]),
            takeover_operator_id=row["takeover_operator_id"],
        )

    @staticmethod
    def _row_to_participant(row: sqlite3.Row) -> Participant:
        return Participant(
            id=row["participant_id"],
            role=ParticipantRole(row["role"]),
            joined_at=_parse_ts(row["joined_at"]),
            metadata=_loads(row["metadata"]),
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> Message:
        return Message(
            id=row["id"],
            conversation_id=row["conv_id"],
            source=row["source"],
            content=row["content"],
            visibility=MessageVisibility(row["visibility"]),
            timestamp=_parse_ts(row["timestamp"]),
            sequence_number=row["sequence_number"],
            edit_of=row["edit_of"],
            metadata=_loads(row["metadata"]),
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> Event:
        return Event(
            id=row["id"],
            type=row["type"],
            conversation_id=row["conv_id"],
            data=_loads(row["data"]),
            timestamp=_parse_ts(row["timestamp"]),
            sequence_number=row["sequence_number"],
        )

    # ── write-through API ──────────────────────────────────────────────────

    def upsert_conversation(self, conv: Conversation) -> None:
        row = self._conv_to_row(conv)
        self._conn.execute(
            """
            INSERT INTO conversations (
                id, state, mode, created_at, updated_at,
                metadata, resolution, takeover_operator_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                state                = excluded.state,
                mode                 = excluded.mode,
                updated_at           = excluded.updated_at,
                metadata             = excluded.metadata,
                resolution           = excluded.resolution,
                takeover_operator_id = excluded.takeover_operator_id
            """,
            row,
        )
        self._conn.commit()

    def delete_conversation(self, conv_id: str) -> None:
        self._conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        self._conn.commit()

    def replace_participants(
        self, conv_id: str, participants: Iterable[Participant],
    ) -> None:
        """Rewrite participants list — simpler than tracking per-participant diff.

        Used at every join/leave since the participant list is small and this
        guarantees the stored order matches in-memory order.
        """
        cur = self._conn.cursor()
        cur.execute("DELETE FROM participants WHERE conv_id = ?", (conv_id,))
        cur.executemany(
            """
            INSERT INTO participants
                (conv_id, participant_id, role, joined_at, position, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    conv_id,
                    p.id,
                    p.role.value,
                    _iso(p.joined_at),
                    idx,
                    _dumps(dict(p.metadata)),
                )
                for idx, p in enumerate(participants)
            ],
        )
        self._conn.commit()

    def insert_message(self, msg: Message) -> None:
        self._conn.execute(
            """
            INSERT INTO messages (
                id, conv_id, source, content, visibility,
                timestamp, sequence_number, edit_of, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg.id,
                msg.conversation_id,
                msg.source,
                msg.content,
                msg.visibility.value,
                _iso(msg.timestamp),
                msg.sequence_number,
                msg.edit_of,
                _dumps(dict(msg.metadata)),
            ),
        )
        self._conn.commit()

    def update_message(self, msg: Message) -> None:
        self._conn.execute(
            """
            UPDATE messages
               SET content    = ?,
                   edit_of    = ?,
                   metadata   = ?
             WHERE id = ?
            """,
            (
                msg.content,
                msg.edit_of,
                _dumps(dict(msg.metadata)),
                msg.id,
            ),
        )
        self._conn.commit()

    def delete_message(self, conv_id: str, message_id: str) -> None:
        self._conn.execute(
            "DELETE FROM messages WHERE conv_id = ? AND id = ?",
            (conv_id, message_id),
        )
        self._conn.commit()

    def insert_event(self, ev: Event) -> None:
        self._conn.execute(
            """
            INSERT INTO events (
                id, conv_id, type, data, timestamp, sequence_number
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ev.id,
                ev.conversation_id,
                ev.type,
                _dumps(dict(ev.data)),
                _iso(ev.timestamp),
                ev.sequence_number,
            ),
        )
        self._conn.commit()

    def save_sequences(
        self, conv_id: str, next_msg_seq: int, next_event_seq: int,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO sequences (conv_id, next_msg_seq, next_event_seq)
            VALUES (?, ?, ?)
            ON CONFLICT(conv_id) DO UPDATE SET
                next_msg_seq   = excluded.next_msg_seq,
                next_event_seq = excluded.next_event_seq
            """,
            (conv_id, next_msg_seq, next_event_seq),
        )
        self._conn.commit()

    # ── read / load ────────────────────────────────────────────────────────

    def load_all(self) -> LoadedState:
        """Load every row back into dataclasses for LocalEngine's dicts."""
        state = LoadedState()

        # Participants first so we can attach them to Conversation objects.
        part_rows = self._conn.execute(
            """
            SELECT * FROM participants ORDER BY conv_id, position
            """
        ).fetchall()
        for row in part_rows:
            state.participants.setdefault(row["conv_id"], []).append(
                self._row_to_participant(row)
            )

        conv_rows = self._conn.execute(
            "SELECT * FROM conversations"
        ).fetchall()
        for row in conv_rows:
            parts = tuple(state.participants.get(row["id"], []))
            state.conversations[row["id"]] = self._row_to_conv(row, parts)

        msg_rows = self._conn.execute(
            """
            SELECT * FROM messages ORDER BY conv_id, sequence_number
            """
        ).fetchall()
        for row in msg_rows:
            state.messages.setdefault(row["conv_id"], []).append(
                self._row_to_message(row)
            )

        evt_rows = self._conn.execute(
            """
            SELECT * FROM events ORDER BY conv_id, sequence_number
            """
        ).fetchall()
        for row in evt_rows:
            state.events.setdefault(row["conv_id"], []).append(
                self._row_to_event(row)
            )

        seq_rows = self._conn.execute(
            "SELECT conv_id, next_msg_seq, next_event_seq FROM sequences"
        ).fetchall()
        for row in seq_rows:
            state.next_msg_seq[row["conv_id"]] = row["next_msg_seq"]
            state.next_event_seq[row["conv_id"]] = row["next_event_seq"]

        # Defensive: if a conv has messages/events but no sequences row
        # (e.g. written by an older build), derive from max(sequence_number).
        for conv_id, msgs in state.messages.items():
            if conv_id not in state.next_msg_seq and msgs:
                state.next_msg_seq[conv_id] = max(m.sequence_number for m in msgs)
        for conv_id, evs in state.events.items():
            if conv_id not in state.next_event_seq and evs:
                state.next_event_seq[conv_id] = max(e.sequence_number for e in evs)

        log.info(
            "[conv-store] loaded from %s: %d conversations, %d messages, %d events",
            self.db_path,
            len(state.conversations),
            sum(len(v) for v in state.messages.values()),
            sum(len(v) for v in state.events.values()),
        )
        return state
