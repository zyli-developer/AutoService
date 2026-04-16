"""Tests for MetricsPlugin (T1A.8)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from autoservice.conversation_engine.events import EventType
from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    ConversationState,
    Event,
    Outcome,
    Participant,
    ParticipantRole,
)
from autoservice.plugins.metrics_plugin import MetricsPlugin


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_conv(id: str = "test-conv") -> Conversation:
    now = _now()
    return Conversation(
        id=id,
        state=ConversationState.ACTIVE,
        mode=ConversationMode.AUTO,
        participants=(),
        created_at=now,
        updated_at=now,
    )


def _make_event(event_type: str, data: dict | None = None) -> Event:
    return Event(
        id="ev-1",
        type=event_type,
        conversation_id="test-conv",
        data=data or {},
        timestamp=_now(),
    )


# ---------- Unit tests ----------


@pytest.mark.asyncio
async def test_conversations_created_counter():
    plugin = MetricsPlugin()
    conv = _make_conv()
    await plugin.on_conversation_created(conv)
    await plugin.on_conversation_created(conv)
    assert plugin.conversations_created == 2


@pytest.mark.asyncio
async def test_conversations_closed_counter():
    plugin = MetricsPlugin()
    conv = _make_conv()
    await plugin.on_conversation_closed(conv)
    assert plugin.conversations_closed == 1


@pytest.mark.asyncio
async def test_mode_changes_tracks_transitions():
    plugin = MetricsPlugin()
    conv = _make_conv()
    await plugin.on_mode_changed(
        conv, ConversationMode.AUTO, ConversationMode.COPILOT, "test",
    )
    await plugin.on_mode_changed(
        conv, ConversationMode.AUTO, ConversationMode.COPILOT, "test",
    )
    await plugin.on_mode_changed(
        conv, ConversationMode.COPILOT, ConversationMode.TAKEOVER, "test",
    )
    assert plugin.mode_changes == {
        "auto\u2192copilot": 2,
        "copilot\u2192takeover": 1,
    }


@pytest.mark.asyncio
async def test_csat_scores_collected():
    plugin = MetricsPlugin()
    ev = _make_event(EventType.CONVERSATION_CSAT_RECORDED, {"score": 5})
    await plugin.on_event(ev)
    ev2 = _make_event(EventType.CONVERSATION_CSAT_RECORDED, {"score": 3})
    await plugin.on_event(ev2)
    assert plugin.csat_scores == [5, 3]


@pytest.mark.asyncio
async def test_messages_sent_counter():
    plugin = MetricsPlugin()
    ev = _make_event(EventType.MESSAGE_SENT, {"message_id": "m1", "visibility": "public"})
    await plugin.on_event(ev)
    await plugin.on_event(ev)
    assert plugin.messages_sent == 2


@pytest.mark.asyncio
async def test_on_event_ignores_irrelevant_types():
    plugin = MetricsPlugin()
    ev = _make_event(EventType.TIMER_SET, {"name": "t1"})
    await plugin.on_event(ev)
    assert plugin.messages_sent == 0
    assert plugin.csat_scores == []


@pytest.mark.asyncio
async def test_get_metrics_returns_expected_structure():
    plugin = MetricsPlugin()
    conv = _make_conv()
    await plugin.on_conversation_created(conv)
    await plugin.on_mode_changed(
        conv, ConversationMode.AUTO, ConversationMode.COPILOT, "test",
    )
    ev = _make_event(EventType.MESSAGE_SENT, {"message_id": "m1", "visibility": "public"})
    await plugin.on_event(ev)
    ev2 = _make_event(EventType.CONVERSATION_CSAT_RECORDED, {"score": 4})
    await plugin.on_event(ev2)

    metrics = plugin.get_metrics()
    assert metrics == {
        "conversations_created": 1,
        "conversations_closed": 0,
        "mode_changes": {"auto\u2192copilot": 1},
        "csat_scores": [4],
        "messages_sent": 1,
    }


@pytest.mark.asyncio
async def test_get_metrics_returns_copies():
    """Mutations to the returned dict must not affect internal state."""
    plugin = MetricsPlugin()
    metrics = plugin.get_metrics()
    metrics["conversations_created"] = 999
    metrics["mode_changes"]["fake"] = 1
    metrics["csat_scores"].append(99)
    assert plugin.conversations_created == 0
    assert plugin.mode_changes == {}
    assert plugin.csat_scores == []


@pytest.mark.asyncio
async def test_reset_clears_all_counters():
    plugin = MetricsPlugin()
    conv = _make_conv()
    await plugin.on_conversation_created(conv)
    await plugin.on_conversation_closed(conv)
    await plugin.on_mode_changed(
        conv, ConversationMode.AUTO, ConversationMode.COPILOT, "test",
    )
    ev = _make_event(EventType.MESSAGE_SENT, {"message_id": "m1", "visibility": "public"})
    await plugin.on_event(ev)
    ev2 = _make_event(EventType.CONVERSATION_CSAT_RECORDED, {"score": 5})
    await plugin.on_event(ev2)

    plugin.reset()
    assert plugin.get_metrics() == {
        "conversations_created": 0,
        "conversations_closed": 0,
        "mode_changes": {},
        "csat_scores": [],
        "messages_sent": 0,
    }


# ---------- Integration test with LocalEngine ----------


@pytest.mark.asyncio
async def test_integration_with_local_engine():
    """Register MetricsPlugin with LocalEngine, run operations, verify metrics."""
    engine = LocalEngine()
    plugin = MetricsPlugin()
    engine.register_hook(plugin)

    # Create conversation
    conv = await engine.create_conversation(
        channel="test", external_id="int-1",
    )
    assert plugin.conversations_created == 1

    # Add participants so we can send messages
    customer = Participant(
        id="cust-1", role=ParticipantRole.CUSTOMER, joined_at=_now(),
    )
    operator = Participant(
        id="op-1", role=ParticipantRole.OPERATOR, joined_at=_now(),
    )
    await engine.join(conv.id, customer)
    await engine.join(conv.id, operator)

    # operator join triggers auto→copilot mode change
    assert plugin.mode_changes.get("auto\u2192copilot") == 1

    # Send a message
    await engine.send_message(conv.id, source="cust-1", content="Hello")
    assert plugin.messages_sent >= 1

    # Close conversation
    await engine.close_conversation(
        conv.id, outcome=Outcome.RESOLVED, resolved_by="op-1",
    )
    assert plugin.conversations_closed == 1

    # Note: set_csat uses _emit (not _emit_and_dispatch_hooks) in LocalEngine,
    # so CSAT events don't reach plugin hooks. Verify via direct on_event call.
    csat_event = _make_event(EventType.CONVERSATION_CSAT_RECORDED, {"score": 5})
    await plugin.on_event(csat_event)
    assert plugin.csat_scores == [5]

    # Verify full metrics snapshot
    metrics = plugin.get_metrics()
    assert metrics["conversations_created"] == 1
    assert metrics["conversations_closed"] == 1
    assert "auto\u2192copilot" in metrics["mode_changes"]
    assert 5 in metrics["csat_scores"]
    assert metrics["messages_sent"] >= 1
