"""EventBus — in-process pub/sub + SQLite async persistence (T1A.3).

Provides:
- Queue-based fan-out to multiple subscribers (Q6: O(1) per sub)
- Scope filtering: conversation_id / squad_id / global
- since_sequence replay from SQLite for reconnection
- viewer_role filtering for SIDE event suppression (Q9)
- Async write-behind to SQLite (aiosqlite)

See docs/contracts/conversation-engine.md §5 for event types.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

import aiosqlite

from autoservice.conversation_engine.types import Event


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _gen_id() -> str:
    return uuid.uuid4().hex


class EventBus:
    """In-process event bus with SQLite persistence."""

    def __init__(
        self,
        db_path: str = ":memory:",
        *,
        conv_metadata_fn: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._subscribers: list[_Subscriber] = []
        self._write_queue: asyncio.Queue[Event] = asyncio.Queue()
        self._write_task: asyncio.Task | None = None
        self._conv_metadata_fn = conv_metadata_fn
        self._initialized = False

    async def initialize(self) -> None:
        """Create DB connection and schema. Must be called before use."""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                data TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                sequence_number INTEGER NOT NULL
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_conv_seq
            ON events (conversation_id, sequence_number)
        """)
        await self._db.commit()
        self._write_task = asyncio.create_task(self._write_loop())
        self._initialized = True

    async def close(self) -> None:
        """Flush pending writes and close DB."""
        if self._write_task:
            await self.flush()
            self._write_task.cancel()
            try:
                await self._write_task
            except asyncio.CancelledError:
                pass
            self._write_task = None
        if self._db:
            await self._db.close()
            self._db = None
        self._initialized = False

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def emit(
        self,
        event_type: str,
        conversation_id: str,
        data: dict[str, Any],
        *,
        seq: int,
        event_id: str | None = None,
    ) -> Event:
        """Create event, fan-out to subscribers, queue for SQLite write."""
        ev = Event(
            id=event_id or _gen_id(),
            type=event_type,
            conversation_id=conversation_id,
            data=data,
            timestamp=_now(),
            sequence_number=seq,
        )
        # Fan-out to live subscribers
        for sub in list(self._subscribers):
            if sub.matches(ev, self._conv_metadata_fn):
                sub.queue.put_nowait(ev)
        # Queue for async persistence
        self._write_queue.put_nowait(ev)
        return ev

    async def subscribe(
        self,
        *,
        conversation_id: str | None = None,
        squad_id: str | None = None,
        event_types: list[str] | None = None,
        since_sequence: int | str | None = None,
        viewer_role: str | None = None,
    ) -> AsyncIterator[Event]:
        """Async iterator yielding events matching the given scope.

        If since_sequence is provided, replays historical events from SQLite
        before switching to live stream.
        """
        sub = _Subscriber(
            conversation_id=conversation_id,
            squad_id=squad_id,
            event_types=set(event_types) if event_types else None,
            viewer_role=viewer_role,
        )
        # Replay historical events if since_sequence given
        if since_sequence is not None and self._db:
            await self.flush()  # ensure all pending writes are persisted
            if conversation_id:
                # Conv scope: since_sequence is int
                rows = await self._query_db(
                    "SELECT * FROM events WHERE conversation_id = ? AND sequence_number > ? ORDER BY sequence_number",
                    (conversation_id, int(since_sequence)),
                )
            else:
                # Squad/global scope: since_sequence is ULID string
                rows = await self._query_db(
                    "SELECT * FROM events WHERE id > ? ORDER BY id",
                    (str(since_sequence),),
                )
            for row in rows:
                ev = self._row_to_event(row)
                if sub.matches(ev, self._conv_metadata_fn):
                    yield ev

        # Switch to live stream
        self._subscribers.append(sub)
        try:
            while True:
                ev = await sub.queue.get()
                yield ev
        finally:
            if sub in self._subscribers:
                self._subscribers.remove(sub)

    async def query_events(
        self,
        conversation_id: str,
        *,
        since_sequence: int | None = None,
        until: datetime | None = None,
        types: list[str] | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """One-shot query from SQLite."""
        await self.flush()
        conditions = ["conversation_id = ?"]
        params: list[Any] = [conversation_id]
        if since_sequence is not None:
            conditions.append("sequence_number > ?")
            params.append(since_sequence)
        if until is not None:
            conditions.append("timestamp <= ?")
            params.append(until.isoformat())
        if types is not None:
            placeholders = ",".join("?" for _ in types)
            conditions.append(f"type IN ({placeholders})")
            params.extend(types)
        where = " AND ".join(conditions)
        params.append(limit)
        rows = await self._query_db(
            f"SELECT * FROM events WHERE {where} ORDER BY sequence_number LIMIT ?",
            tuple(params),
        )
        return [self._row_to_event(row) for row in rows]

    async def flush(self) -> None:
        """Force all queued writes to DB."""
        if not self._db:
            return
        # Drain the write queue
        events: list[Event] = []
        while not self._write_queue.empty():
            try:
                events.append(self._write_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if events:
            await self._write_batch(events)

    # ---- internal ----

    async def _write_loop(self) -> None:
        """Background task: batch-write events to SQLite."""
        while True:
            try:
                ev = await self._write_queue.get()
                batch = [ev]
                # Drain any additional queued events
                while not self._write_queue.empty():
                    try:
                        batch.append(self._write_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                await self._write_batch(batch)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # write errors are non-fatal

    async def _write_batch(self, events: list[Event]) -> None:
        if not self._db:
            return
        await self._db.executemany(
            "INSERT OR IGNORE INTO events (id, type, conversation_id, data, timestamp, sequence_number) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    ev.id,
                    ev.type,
                    ev.conversation_id,
                    json.dumps(dict(ev.data)),
                    ev.timestamp.isoformat(),
                    ev.sequence_number,
                )
                for ev in events
            ],
        )
        await self._db.commit()

    async def _query_db(self, sql: str, params: tuple = ()) -> list[tuple]:
        if not self._db:
            return []
        cursor = await self._db.execute(sql, params)
        return await cursor.fetchall()

    @staticmethod
    def _row_to_event(row: tuple) -> Event:
        return Event(
            id=row[0],
            type=row[1],
            conversation_id=row[2],
            data=json.loads(row[3]),
            timestamp=datetime.fromisoformat(row[4]),
            sequence_number=row[5],
        )


class _Subscriber:
    """Internal subscriber with scope filter."""

    def __init__(
        self,
        *,
        conversation_id: str | None = None,
        squad_id: str | None = None,
        event_types: set[str] | None = None,
        viewer_role: str | None = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.squad_id = squad_id
        self.event_types = event_types
        self.viewer_role = viewer_role
        self.queue: asyncio.Queue[Event] = asyncio.Queue()

    def matches(
        self,
        event: Event,
        conv_metadata_fn: Callable[[str], dict[str, Any]] | None = None,
    ) -> bool:
        # Conversation scope filter
        if self.conversation_id and event.conversation_id != self.conversation_id:
            return False
        # Squad scope filter
        if self.squad_id and conv_metadata_fn:
            meta = conv_metadata_fn(event.conversation_id)
            if meta.get("squad_id") != self.squad_id:
                return False
        elif self.squad_id:
            return False
        # Event type filter
        if self.event_types and event.type not in self.event_types:
            return False
        # Viewer role filter (Q9): hide SIDE message events from CUSTOMER
        if self.viewer_role == "customer" and event.type == "message.sent":
            if event.data.get("visibility") == "side":
                return False
        return True
