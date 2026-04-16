"""Unit tests for MemoryPool (T4A.1).

Covers schema creation, turn recording, ordering, time-range queries,
stats aggregation, and empty-conversation edge cases.
"""

from __future__ import annotations

import pytest

from autoservice.memory_pool import MemoryPool


@pytest.fixture()
def pool(tmp_path):
    """Yield a MemoryPool backed by a temporary SQLite file."""
    mp = MemoryPool(db_path=tmp_path / "test_memory.db")
    yield mp
    mp.close()


# ------------------------------------------------------------------
# Schema
# ------------------------------------------------------------------

class TestSchemaCreation:
    def test_table_exists(self, pool: MemoryPool):
        """Auto-creates the memory_turns table on init."""
        rows = pool._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_turns'"
        ).fetchall()
        assert len(rows) == 1

    def test_indexes_exist(self, pool: MemoryPool):
        rows = pool._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_memory_turns%'"
        ).fetchall()
        names = {r["name"] for r in rows}
        assert "idx_memory_turns_conv_turn" in names
        assert "idx_memory_turns_timestamp" in names


# ------------------------------------------------------------------
# record_turn & turn_index auto-increment
# ------------------------------------------------------------------

class TestRecordTurn:
    def test_returns_id(self, pool: MemoryPool):
        tid = pool.record_turn("c1", "customer", "Hello")
        assert isinstance(tid, int)
        assert tid >= 1

    def test_auto_increment_turn_index(self, pool: MemoryPool):
        pool.record_turn("c1", "customer", "Hi")
        pool.record_turn("c1", "agent", "Hello!")
        pool.record_turn("c1", "customer", "Help me")

        turns = pool.get_conversation("c1")
        assert [t["turn_index"] for t in turns] == [0, 1, 2]

    def test_separate_conversations_independent_index(self, pool: MemoryPool):
        pool.record_turn("c1", "customer", "Hi")
        pool.record_turn("c2", "customer", "Hey")
        pool.record_turn("c1", "agent", "Hello!")

        c1 = pool.get_conversation("c1")
        c2 = pool.get_conversation("c2")
        assert [t["turn_index"] for t in c1] == [0, 1]
        assert [t["turn_index"] for t in c2] == [0]

    def test_optional_fields_stored(self, pool: MemoryPool):
        pool.record_turn(
            "c1", "customer", "I'm angry",
            intent="complaint",
            sentiment="angry",
            kb_hit_count=2,
            kb_sources=["faq", "manual"],
            resolution_status="open",
            metadata={"lang": "zh"},
        )
        turn = pool.get_conversation("c1")[0]
        assert turn["intent"] == "complaint"
        assert turn["sentiment"] == "angry"
        assert turn["kb_hit_count"] == 2
        assert turn["kb_sources"] == ["faq", "manual"]
        assert turn["resolution_status"] == "open"
        assert turn["metadata"] == {"lang": "zh"}

    def test_defaults_for_optional_fields(self, pool: MemoryPool):
        pool.record_turn("c1", "agent", "Welcome")
        turn = pool.get_conversation("c1")[0]
        assert turn["intent"] is None
        assert turn["sentiment"] is None
        assert turn["kb_hit_count"] == 0
        assert turn["kb_sources"] is None
        assert turn["resolution_status"] == "open"
        assert turn["metadata"] is None


# ------------------------------------------------------------------
# get_conversation ordering
# ------------------------------------------------------------------

class TestGetConversation:
    def test_ordered_by_turn_index(self, pool: MemoryPool):
        pool.record_turn("c1", "customer", "one")
        pool.record_turn("c1", "agent", "two")
        pool.record_turn("c1", "customer", "three")
        turns = pool.get_conversation("c1")
        assert [t["content"] for t in turns] == ["one", "two", "three"]

    def test_empty_conversation(self, pool: MemoryPool):
        assert pool.get_conversation("nonexistent") == []


# ------------------------------------------------------------------
# get_conversations_in_range
# ------------------------------------------------------------------

class TestGetConversationsInRange:
    def test_filters_by_time(self, pool: MemoryPool):
        # Insert turns with known timestamps via direct SQL
        pool._conn.execute(
            "INSERT INTO memory_turns "
            "(conversation_id, turn_index, timestamp, role, content) "
            "VALUES (?, ?, ?, ?, ?)",
            ("early", 0, "2026-04-10T00:00:00+00:00", "customer", "hi"),
        )
        pool._conn.execute(
            "INSERT INTO memory_turns "
            "(conversation_id, turn_index, timestamp, role, content) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mid", 0, "2026-04-12T00:00:00+00:00", "customer", "hi"),
        )
        pool._conn.execute(
            "INSERT INTO memory_turns "
            "(conversation_id, turn_index, timestamp, role, content) "
            "VALUES (?, ?, ?, ?, ?)",
            ("late", 0, "2026-04-15T00:00:00+00:00", "customer", "hi"),
        )
        pool._conn.commit()

        result = pool.get_conversations_in_range(
            "2026-04-11T00:00:00+00:00", "2026-04-14T00:00:00+00:00"
        )
        assert result == ["mid"]

    def test_respects_limit(self, pool: MemoryPool):
        for i in range(5):
            pool._conn.execute(
                "INSERT INTO memory_turns "
                "(conversation_id, turn_index, timestamp, role, content) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"c{i}", 0, f"2026-04-12T0{i}:00:00+00:00", "customer", "hi"),
            )
        pool._conn.commit()

        result = pool.get_conversations_in_range(
            "2026-04-12T00:00:00+00:00", "2026-04-12T23:59:59+00:00",
            limit=3,
        )
        assert len(result) == 3

    def test_empty_range(self, pool: MemoryPool):
        result = pool.get_conversations_in_range(
            "2099-01-01T00:00:00+00:00", "2099-12-31T00:00:00+00:00"
        )
        assert result == []


# ------------------------------------------------------------------
# get_stats
# ------------------------------------------------------------------

class TestGetStats:
    def test_basic_stats(self, pool: MemoryPool):
        pool.record_turn("c1", "customer", "Hi", sentiment="neutral", kb_hit_count=1)
        pool.record_turn("c1", "agent", "Hello!", sentiment="positive", kb_hit_count=0)
        pool.record_turn(
            "c1", "customer", "Thanks",
            sentiment="positive", kb_hit_count=2,
            resolution_status="resolved",
        )

        stats = pool.get_stats("c1")
        assert stats["turn_count"] == 3
        assert stats["sentiment_distribution"] == {"neutral": 1, "positive": 2}
        assert stats["kb_hit_total"] == 3
        assert stats["resolution_status"] == "resolved"

    def test_empty_conversation_stats(self, pool: MemoryPool):
        stats = pool.get_stats("nonexistent")
        assert stats["turn_count"] == 0
        assert stats["sentiment_distribution"] == {}
        assert stats["kb_hit_total"] == 0
        assert stats["resolution_status"] is None

    def test_no_sentiment(self, pool: MemoryPool):
        pool.record_turn("c1", "customer", "Hi")
        pool.record_turn("c1", "agent", "Hello")
        stats = pool.get_stats("c1")
        assert stats["sentiment_distribution"] == {}
        assert stats["turn_count"] == 2
