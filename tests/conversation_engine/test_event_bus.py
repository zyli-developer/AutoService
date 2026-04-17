"""T1A.3 EventBus unit tests (test-plan-003 · TC-001, TC-012, TC-017~TC-020).

Tests the EventBus class in isolation: import/instantiation, SQLite persistence,
fan-out, subscriber cleanup, schema creation, and async write performance.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from autoservice.conversation_engine.event_bus import EventBus
from autoservice.conversation_engine.events import EventType
from autoservice.conversation_engine.types import Event


# ---- TC-001: Import and instantiate ----


def test_tc001_eventbus_import_and_instantiate():
    """TC-001: EventBus can be imported and instantiated."""
    bus = EventBus(db_path=":memory:")
    assert bus is not None


# ---- TC-019: SQLite schema auto-creation ----


async def test_tc019_sqlite_schema_auto_created():
    """TC-019: EventBus creates events table on init with correct columns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "events.db")
        bus = EventBus(db_path=db_path)
        await bus.initialize()
        try:
            # Verify table exists and has expected columns
            import aiosqlite

            async with aiosqlite.connect(db_path) as db:
                cursor = await db.execute("PRAGMA table_info(events)")
                columns = {row[1] for row in await cursor.fetchall()}
            expected = {"id", "type", "conversation_id", "data", "timestamp", "sequence_number"}
            assert expected.issubset(columns), f"Missing columns: {expected - columns}"
        finally:
            await bus.close()


# ---- TC-012: SQLite persistence across instances ----


async def test_tc012_sqlite_persistence_across_instances():
    """TC-012: Events survive EventBus restart (same DB path)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "events.db")

        # First instance: emit events
        bus1 = EventBus(db_path=db_path)
        await bus1.initialize()
        ev = await bus1.emit("conversation.created", "conv_1", {"channel": "web"}, seq=1)
        await bus1.emit("message.sent", "conv_1", {"msg": "hello"}, seq=2)
        await bus1.flush()
        await bus1.close()

        # Second instance: query same DB
        bus2 = EventBus(db_path=db_path)
        await bus2.initialize()
        try:
            events = await bus2.query_events("conv_1")
            assert len(events) == 2
            assert events[0].type == "conversation.created"
            assert events[1].type == "message.sent"
        finally:
            await bus2.close()


# ---- TC-017: Multiple subscribers fan-out ----


async def test_tc017_multi_subscriber_fanout():
    """TC-017: 3 subscribers each receive the same event independently."""
    bus = EventBus(db_path=":memory:")
    await bus.initialize()
    try:
        results: list[list[Event]] = [[], [], []]

        async def collect(idx: int):
            async for ev in bus.subscribe(conversation_id="conv_1"):
                results[idx].append(ev)
                if len(results[idx]) >= 1:
                    break

        tasks = [asyncio.create_task(collect(i)) for i in range(3)]
        await asyncio.sleep(0)  # let subscribers register

        await bus.emit("message.sent", "conv_1", {"msg": "test"}, seq=1)

        await asyncio.wait_for(
            asyncio.gather(*tasks), timeout=2.0,
        )

        for i in range(3):
            assert len(results[i]) == 1, f"Subscriber {i} got {len(results[i])} events"
            assert results[i][0].type == "message.sent"
    finally:
        await bus.close()


# ---- TC-018: Subscriber cancel cleanup ----


async def test_tc018_subscriber_cancel_cleanup():
    """TC-018: Cancelled subscriber is removed, no leak."""
    bus = EventBus(db_path=":memory:")
    await bus.initialize()
    try:
        async def listen():
            async for _ in bus.subscribe(conversation_id="conv_1"):
                pass  # pragma: no cover

        task = asyncio.create_task(listen())
        await asyncio.sleep(0)  # let subscriber register
        initial_count = bus.subscriber_count

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        await asyncio.sleep(0)  # let finally block run
        assert bus.subscriber_count < initial_count, "Subscriber not cleaned up after cancel"
    finally:
        await bus.close()


# ---- TC-020: High-frequency emit does not block ----


async def test_tc020_high_frequency_emit_not_blocking():
    """TC-020: 50 rapid emits complete in < 2s (async write-behind)."""
    bus = EventBus(db_path=":memory:")
    await bus.initialize()
    try:
        import time

        start = time.monotonic()
        for i in range(50):
            await bus.emit("message.sent", "conv_perf", {"i": i}, seq=i + 1)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"50 emits took {elapsed:.2f}s, expected < 2s"
    finally:
        await bus.close()
