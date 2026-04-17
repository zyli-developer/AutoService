"""Tests for CcPoolPlugin — CC pool binding management."""

from __future__ import annotations

import pytest

from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    ConversationState,
    Outcome,
)
from autoservice.plugins.cc_pool_plugin import CcPoolPlugin


# ---------------------------------------------------------------------------
# Stub pool
# ---------------------------------------------------------------------------

class StubPool:
    """Minimal StickyPool stub for testing."""

    def __init__(self) -> None:
        self.acquired: list[str] = []
        self.released: list[str] = []

    async def acquire_sticky(self, key: str) -> object:
        self.acquired.append(key)
        return object()  # dummy instance

    async def release_sticky(self, key: str) -> None:
        self.released.append(key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conv(conv_id: str = "ch_123", state: ConversationState = ConversationState.CREATED) -> Conversation:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return Conversation(
        id=conv_id,
        state=state,
        mode=ConversationMode.AUTO,
        participants=(),
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestCcPoolPluginUnit:
    """Unit tests for CcPoolPlugin without LocalEngine."""

    @pytest.mark.asyncio
    async def test_on_created_stores_binding(self) -> None:
        pool = StubPool()
        plugin = CcPoolPlugin(pool=pool)
        conv = _make_conv("ch_abc")

        await plugin.on_conversation_created(conv)

        assert plugin.get_binding("ch_abc") == "ch_abc"
        assert "ch_abc" in pool.acquired

    @pytest.mark.asyncio
    async def test_on_closed_removes_binding_and_releases(self) -> None:
        pool = StubPool()
        plugin = CcPoolPlugin(pool=pool)
        conv = _make_conv("ch_abc")

        await plugin.on_conversation_created(conv)
        await plugin.on_conversation_closed(conv)

        assert plugin.get_binding("ch_abc") is None
        assert "ch_abc" in pool.released

    @pytest.mark.asyncio
    async def test_get_binding_returns_none_for_unknown(self) -> None:
        plugin = CcPoolPlugin()
        assert plugin.get_binding("nonexistent") is None

    @pytest.mark.asyncio
    async def test_idempotent_close(self) -> None:
        pool = StubPool()
        plugin = CcPoolPlugin(pool=pool)
        conv = _make_conv("ch_abc")

        await plugin.on_conversation_created(conv)
        await plugin.on_conversation_closed(conv)
        # Second close should be a no-op
        await plugin.on_conversation_closed(conv)

        assert pool.released.count("ch_abc") == 1

    @pytest.mark.asyncio
    async def test_works_without_pool(self) -> None:
        """Plugin still tracks bindings even without a pool reference."""
        plugin = CcPoolPlugin(pool=None)
        conv = _make_conv("ch_abc")

        await plugin.on_conversation_created(conv)
        assert plugin.get_binding("ch_abc") == "ch_abc"

        await plugin.on_conversation_closed(conv)
        assert plugin.get_binding("ch_abc") is None

    @pytest.mark.asyncio
    async def test_multiple_conversations(self) -> None:
        pool = StubPool()
        plugin = CcPoolPlugin(pool=pool)

        conv1 = _make_conv("ch_1")
        conv2 = _make_conv("ch_2")

        await plugin.on_conversation_created(conv1)
        await plugin.on_conversation_created(conv2)

        assert plugin.get_binding("ch_1") == "ch_1"
        assert plugin.get_binding("ch_2") == "ch_2"

        await plugin.on_conversation_closed(conv1)
        assert plugin.get_binding("ch_1") is None
        assert plugin.get_binding("ch_2") == "ch_2"


# ---------------------------------------------------------------------------
# Integration test with LocalEngine
# ---------------------------------------------------------------------------

class TestCcPoolPluginIntegration:
    """Integration: register plugin with LocalEngine, exercise lifecycle."""

    @pytest.mark.asyncio
    async def test_engine_lifecycle_triggers_bindings(self) -> None:
        from autoservice.conversation_engine.local_engine import LocalEngine

        pool = StubPool()
        plugin = CcPoolPlugin(pool=pool)

        engine = LocalEngine()
        engine.register_hook(plugin)

        # Create conversation
        conv = await engine.create_conversation(
            channel="test", external_id="user42",
        )
        conv_id = conv.id

        assert plugin.get_binding(conv_id) == conv_id
        assert conv_id in pool.acquired

        # Close conversation
        await engine.close_conversation(
            conv_id, outcome=Outcome.RESOLVED, resolved_by="op",
        )

        assert plugin.get_binding(conv_id) is None
        assert conv_id in pool.released
