"""Tests for SquadPlugin."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    ConversationState,
    Outcome,
    Participant,
    ParticipantRole,
)
from autoservice.plugins.squad_plugin import SquadPlugin


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_conv(
    conv_id: str = "web_ext1",
    metadata: dict | None = None,
) -> Conversation:
    now = _now()
    return Conversation(
        id=conv_id,
        state=ConversationState.CREATED,
        mode=ConversationMode.AUTO,
        participants=(),
        created_at=now,
        updated_at=now,
        metadata=metadata or {},
    )


# ---------- Unit tests ----------


class TestDefaultSquadAssignment:
    @pytest.mark.asyncio
    async def test_default_squad_when_no_config(self) -> None:
        plugin = SquadPlugin()
        conv = _make_conv()
        await plugin.on_conversation_created(conv)
        assert plugin.get_squad(conv.id) == "general"

    @pytest.mark.asyncio
    async def test_custom_default_squad(self) -> None:
        plugin = SquadPlugin({"default_squad": "vip"})
        conv = _make_conv()
        await plugin.on_conversation_created(conv)
        assert plugin.get_squad(conv.id) == "vip"


class TestChannelBasedRouting:
    @pytest.mark.asyncio
    async def test_channel_routing_from_metadata(self) -> None:
        plugin = SquadPlugin({
            "default_squad": "general",
            "channel_routing": {"feishu": "cn-support", "web": "en-support"},
        })
        conv = _make_conv(metadata={"channel": "feishu"})
        await plugin.on_conversation_created(conv)
        assert plugin.get_squad(conv.id) == "cn-support"

    @pytest.mark.asyncio
    async def test_channel_routing_inferred_from_id(self) -> None:
        plugin = SquadPlugin({
            "channel_routing": {"web": "en-support"},
        })
        conv = _make_conv(conv_id="web_ext1")
        await plugin.on_conversation_created(conv)
        assert plugin.get_squad(conv.id) == "en-support"

    @pytest.mark.asyncio
    async def test_unknown_channel_falls_back_to_default(self) -> None:
        plugin = SquadPlugin({
            "default_squad": "fallback",
            "channel_routing": {"feishu": "cn-support"},
        })
        conv = _make_conv(conv_id="slack_ext1")
        await plugin.on_conversation_created(conv)
        assert plugin.get_squad(conv.id) == "fallback"


class TestExplicitSquadId:
    @pytest.mark.asyncio
    async def test_explicit_squad_overrides_channel_routing(self) -> None:
        plugin = SquadPlugin({
            "default_squad": "general",
            "channel_routing": {"web": "en-support"},
        })
        conv = _make_conv(metadata={"squad_id": "vip", "channel": "web"})
        await plugin.on_conversation_created(conv)
        assert plugin.get_squad(conv.id) == "vip"


class TestRemovalOnClose:
    @pytest.mark.asyncio
    async def test_close_removes_assignment(self) -> None:
        plugin = SquadPlugin()
        conv = _make_conv()
        await plugin.on_conversation_created(conv)
        assert plugin.get_squad(conv.id) is not None

        await plugin.on_conversation_closed(conv)
        assert plugin.get_squad(conv.id) is None

    @pytest.mark.asyncio
    async def test_close_unknown_conv_is_noop(self) -> None:
        plugin = SquadPlugin()
        conv = _make_conv(conv_id="unknown_1")
        await plugin.on_conversation_closed(conv)  # should not raise


class TestGetSquadAndListConversations:
    @pytest.mark.asyncio
    async def test_get_squad_unknown_returns_none(self) -> None:
        plugin = SquadPlugin()
        assert plugin.get_squad("nonexistent") is None

    @pytest.mark.asyncio
    async def test_list_conversations(self) -> None:
        plugin = SquadPlugin({"default_squad": "general"})
        for i in range(3):
            await plugin.on_conversation_created(_make_conv(conv_id=f"web_ext{i}"))
        result = plugin.list_conversations("general")
        assert sorted(result) == ["web_ext0", "web_ext1", "web_ext2"]

    @pytest.mark.asyncio
    async def test_list_conversations_empty(self) -> None:
        plugin = SquadPlugin()
        assert plugin.list_conversations("nonexistent") == []


class TestReassign:
    @pytest.mark.asyncio
    async def test_reassign(self) -> None:
        plugin = SquadPlugin({"default_squad": "general"})
        conv = _make_conv()
        await plugin.on_conversation_created(conv)
        assert plugin.get_squad(conv.id) == "general"

        plugin.reassign(conv.id, "vip")
        assert plugin.get_squad(conv.id) == "vip"
        assert conv.id in plugin.list_conversations("vip")
        assert conv.id not in plugin.list_conversations("general")

    @pytest.mark.asyncio
    async def test_reassign_unknown_conv_raises(self) -> None:
        plugin = SquadPlugin()
        with pytest.raises(KeyError):
            plugin.reassign("nonexistent", "vip")


class TestIntegrationWithLocalEngine:
    @pytest.mark.asyncio
    async def test_squad_assigned_on_create(self) -> None:
        engine = LocalEngine()
        plugin = SquadPlugin({
            "default_squad": "general",
            "channel_routing": {"feishu": "cn-support"},
        })
        engine.register_hook(plugin)

        conv = await engine.create_conversation(
            channel="feishu", external_id="ext1",
        )
        assert plugin.get_squad(conv.id) == "cn-support"

    @pytest.mark.asyncio
    async def test_squad_removed_on_close(self) -> None:
        engine = LocalEngine()
        plugin = SquadPlugin({"default_squad": "general"})
        engine.register_hook(plugin)

        conv = await engine.create_conversation(
            channel="web", external_id="ext1",
        )
        assert plugin.get_squad(conv.id) == "general"

        await engine.close_conversation(
            conv.id, outcome=Outcome.RESOLVED, resolved_by="system",
        )
        assert plugin.get_squad(conv.id) is None

    @pytest.mark.asyncio
    async def test_multiple_convs_different_squads(self) -> None:
        engine = LocalEngine()
        plugin = SquadPlugin({
            "default_squad": "general",
            "channel_routing": {"feishu": "cn-support", "web": "en-support"},
        })
        engine.register_hook(plugin)

        c1 = await engine.create_conversation(channel="feishu", external_id="e1")
        c2 = await engine.create_conversation(channel="web", external_id="e2")
        c3 = await engine.create_conversation(
            channel="web", external_id="e3",
            metadata={"squad_id": "vip"},
        )

        assert plugin.get_squad(c1.id) == "cn-support"
        assert plugin.get_squad(c2.id) == "en-support"
        assert plugin.get_squad(c3.id) == "vip"

        assert sorted(plugin.list_conversations("en-support")) == [c2.id]
        assert sorted(plugin.list_conversations("vip")) == [c3.id]
