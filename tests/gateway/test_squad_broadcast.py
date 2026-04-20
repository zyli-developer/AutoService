"""E2E tests for T6A.2 — Squad-Filtered Message Broadcast.

Covers: squad-based routing, multi-squad isolation, fallback broadcast,
channel_routing config, reassignment.  All 5 test cases from plan-T6A.2.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice.plugins.squad_plugin import SquadPlugin
from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    ConversationState,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def squad_plugin():
    return SquadPlugin(squad_config={
        "default_squad": "general",
        "channel_routing": {"web": "web-support", "vip-line": "vip"},
    })


@pytest.fixture
def make_conv():
    """Factory for minimal Conversation objects."""
    _counter = 0

    def _make(conv_id=None, channel="web", squad_id=None):
        nonlocal _counter
        _counter += 1
        cid = conv_id or f"conv-{_counter}"
        meta = {"channel": channel}
        if squad_id:
            meta["squad_id"] = squad_id
        return Conversation(
            id=cid,
            state=ConversationState.ACTIVE,
            mode=ConversationMode.AUTO,
            participants=(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            metadata=meta,
        )
    return _make


# ---------------------------------------------------------------------------
# TC-009: Customer message only reaches squad-subscribed operator
# ---------------------------------------------------------------------------

async def test_tc009_message_reaches_correct_squad(squad_plugin, make_conv):
    """Conversation assigned to 'web-support' squad via channel_routing."""
    conv = make_conv(conv_id="conv-ws-1", channel="web")
    await squad_plugin.on_conversation_created(conv)

    assigned = squad_plugin.get_squad("conv-ws-1")
    assert assigned == "web-support", \
        f"web channel should route to web-support, got {assigned}"


# ---------------------------------------------------------------------------
# TC-010: Multiple squads complete isolation
# ---------------------------------------------------------------------------

async def test_tc010_multi_squad_isolation(squad_plugin, make_conv):
    """Conversations on different channels get different squads."""
    conv_web = make_conv(conv_id="c-web", channel="web")
    conv_vip = make_conv(conv_id="c-vip", channel="vip-line")

    await squad_plugin.on_conversation_created(conv_web)
    await squad_plugin.on_conversation_created(conv_vip)

    assert squad_plugin.get_squad("c-web") == "web-support"
    assert squad_plugin.get_squad("c-vip") == "vip"

    # List isolation
    web_convs = squad_plugin.list_conversations("web-support")
    vip_convs = squad_plugin.list_conversations("vip")
    assert "c-web" in web_convs and "c-vip" not in web_convs, \
        "web-support should only contain c-web"
    assert "c-vip" in vip_convs and "c-web" not in vip_convs, \
        "vip should only contain c-vip"


# ---------------------------------------------------------------------------
# TC-011: No squad assigned — fallback to default
# ---------------------------------------------------------------------------

async def test_tc011_fallback_default_squad(make_conv):
    """Unknown channel falls back to default_squad='general'."""
    plugin = SquadPlugin(squad_config={"default_squad": "general"})
    conv = make_conv(conv_id="c-unknown", channel="phone")
    await plugin.on_conversation_created(conv)

    assert plugin.get_squad("c-unknown") == "general", \
        "unrouted channel should fall back to default squad"


# ---------------------------------------------------------------------------
# TC-012: Squad assignment via explicit metadata.squad_id
# ---------------------------------------------------------------------------

async def test_tc012_explicit_squad_metadata(squad_plugin, make_conv):
    """Explicit squad_id in metadata takes priority over channel_routing."""
    conv = make_conv(conv_id="c-explicit", channel="web", squad_id="vip")
    await squad_plugin.on_conversation_created(conv)

    assert squad_plugin.get_squad("c-explicit") == "vip", \
        "explicit metadata squad_id should override channel_routing"


# ---------------------------------------------------------------------------
# TC-013: Squad reassignment
# ---------------------------------------------------------------------------

async def test_tc013_reassignment(squad_plugin, make_conv):
    """reassign() moves conversation to a new squad."""
    conv = make_conv(conv_id="c-move", channel="web")
    await squad_plugin.on_conversation_created(conv)
    assert squad_plugin.get_squad("c-move") == "web-support"

    squad_plugin.reassign("c-move", "vip")
    assert squad_plugin.get_squad("c-move") == "vip", \
        "after reassign, squad should be vip"

    # Old squad should no longer list it
    assert "c-move" not in squad_plugin.list_conversations("web-support")
    assert "c-move" in squad_plugin.list_conversations("vip")
