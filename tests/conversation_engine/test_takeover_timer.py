"""Tests for Task 4 — idle takeover auto-release timer (LocalEngine side).

Timer schedule:
  idle_timeout_ms  = 100 ms
  warning_ms       =  30 ms
  → warning fires at 70 ms after /hijack
  → release fires at 70 + 30 = 100 ms after /hijack
"""
import asyncio
import pytest
from datetime import datetime, timezone

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    ConversationMode, Participant, ParticipantRole,
)
from autoservice.takeover_config import TakeoverConfig


@pytest.fixture
async def engine_with_conv():
    """LocalEngine configured with a fast takeover timer (100ms idle, 30ms warning)."""
    cfg = TakeoverConfig(idle_timeout_ms=100, warning_ms=30, offline_grace_ms=200)
    eng = LocalEngine(config={"takeover": cfg})
    conv = await eng.create_conversation(channel="web", external_id="x")
    now = datetime.now(timezone.utc)
    await eng.join(conv.id, Participant(id="cust1", role=ParticipantRole.CUSTOMER, joined_at=now))
    await eng.join(conv.id, Participant(id="op42", role=ParticipantRole.OPERATOR, joined_at=now))
    return eng, conv.id


@pytest.mark.asyncio
async def test_hijack_arms_warning_and_release_timers(engine_with_conv):
    eng, cid = engine_with_conv
    warnings: list[dict] = []
    eng.on_takeover_warning(lambda ev: warnings.append(ev))

    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    await asyncio.sleep(0.2)

    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.COPILOT
    assert conv.takeover_operator_id is None
    assert len(warnings) == 1
    assert warnings[0]["conversation_id"] == cid
    assert warnings[0]["operator_id"] == "op42"
    assert warnings[0]["remaining_ms"] == 30


@pytest.mark.asyncio
async def test_operator_message_resets_takeover_timer(engine_with_conv):
    eng, cid = engine_with_conv
    warnings: list[dict] = []
    cancels: list[str] = []
    eng.on_takeover_warning(lambda ev: warnings.append(ev))
    eng.on_takeover_warning_cancelled(lambda ev: cancels.append(ev["conversation_id"]))

    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    await asyncio.sleep(0.08)  # past 70ms warning trigger
    assert len(warnings) == 1

    await eng.send_message(cid, source="op42", content="hi")
    await asyncio.sleep(0.01)
    assert cancels == [cid]

    await asyncio.sleep(0.05)
    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.TAKEOVER


@pytest.mark.asyncio
async def test_non_takeover_operator_message_does_not_reset(engine_with_conv):
    eng, cid = engine_with_conv
    now = datetime.now(timezone.utc)
    await eng.join(cid, Participant(id="op99", role=ParticipantRole.OPERATOR, joined_at=now))
    await eng.handle_command(cid, actor_id="op42", command="/hijack")

    await asyncio.sleep(0.05)
    await eng.send_message(cid, source="op99", content="hi from another op")
    await asyncio.sleep(0.2)

    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.COPILOT


@pytest.mark.asyncio
async def test_release_command_cancels_timers(engine_with_conv):
    eng, cid = engine_with_conv
    warnings: list[dict] = []
    eng.on_takeover_warning(lambda ev: warnings.append(ev))

    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    await eng.handle_command(cid, actor_id="op42", command="/release")
    await asyncio.sleep(0.2)

    assert warnings == []
    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.AUTO


@pytest.mark.asyncio
async def test_continue_ack_resets_timer(engine_with_conv):
    eng, cid = engine_with_conv
    warnings: list[dict] = []
    cancels: list[str] = []
    eng.on_takeover_warning(lambda ev: warnings.append(ev))
    eng.on_takeover_warning_cancelled(lambda ev: cancels.append(ev["conversation_id"]))

    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    await asyncio.sleep(0.08)
    assert len(warnings) == 1

    await eng.reset_takeover_timer(cid, actor_id="op42")
    await asyncio.sleep(0.01)
    assert cancels == [cid]

    await asyncio.sleep(0.05)
    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.TAKEOVER


@pytest.mark.asyncio
async def test_armed_callback_fires_on_hijack(engine_with_conv):
    eng, cid = engine_with_conv
    armed: list[dict] = []
    eng.on_takeover_armed(lambda ev: armed.append(ev))

    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    assert len(armed) == 1
    assert armed[0]["conversation_id"] == cid
    assert armed[0]["operator_id"] == "op42"
    assert armed[0]["idle_timeout_ms"] == 100
    assert armed[0]["warning_ms"] == 30
    assert armed[0]["armed_at"]  # non-empty ISO string


@pytest.mark.asyncio
async def test_armed_callback_fires_on_reset(engine_with_conv):
    eng, cid = engine_with_conv
    armed: list[dict] = []
    eng.on_takeover_armed(lambda ev: armed.append(ev))

    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    await eng.reset_takeover_timer(cid, actor_id="op42")

    assert len(armed) == 2  # one for hijack, one for reset


@pytest.mark.asyncio
async def test_close_conversation_cancels_takeover_timer(engine_with_conv):
    """Closing a conversation directly (not via /resolve) must cancel takeover timer."""
    from autoservice.conversation_engine.types import Outcome

    eng, cid = engine_with_conv
    warnings: list[dict] = []
    eng.on_takeover_warning(lambda ev: warnings.append(ev))

    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    # Close directly without going through /resolve or /abandon command dispatch
    await eng.close_conversation(cid, outcome=Outcome.RESOLVED, resolved_by="op42")

    # Wait past where warning/release would have fired
    await asyncio.sleep(0.2)

    assert warnings == []  # timer was cancelled, warning never fired
    # Underlying state: conversation closed, mode=TAKEOVER frozen (can't change on closed conv)
    conv = await eng.get_conversation(cid)
    assert conv.state.value == "closed"
