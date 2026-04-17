import pytest
from datetime import datetime, timezone

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    ConversationMode, Participant, ParticipantRole,
)


@pytest.fixture
async def engine_with_conv():
    eng = LocalEngine()
    conv = await eng.create_conversation(channel="web", external_id="x")
    now = datetime.now(timezone.utc)
    await eng.join(conv.id, Participant(id="cust1", role=ParticipantRole.CUSTOMER, joined_at=now))
    await eng.join(conv.id, Participant(id="op42", role=ParticipantRole.OPERATOR, joined_at=now))
    return eng, conv.id


@pytest.mark.asyncio
async def test_hijack_sets_takeover_operator_id(engine_with_conv):
    eng, cid = engine_with_conv
    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.TAKEOVER
    assert conv.takeover_operator_id == "op42"


@pytest.mark.asyncio
async def test_release_clears_takeover_operator_id(engine_with_conv):
    eng, cid = engine_with_conv
    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    await eng.handle_command(cid, actor_id="op42", command="/release")
    conv = await eng.get_conversation(cid)
    assert conv.mode == ConversationMode.AUTO
    assert conv.takeover_operator_id is None


@pytest.mark.asyncio
async def test_mode_changed_event_includes_takeover_operator_id(engine_with_conv):
    eng, cid = engine_with_conv
    await eng.handle_command(cid, actor_id="op42", command="/hijack")
    events = await eng.query_events(cid, types=["mode.changed"])
    ev = events[-1]
    assert ev.data["new_mode"] == "takeover"
    assert ev.data["takeover_operator_id"] == "op42"

    await eng.handle_command(cid, actor_id="op42", command="/release")
    events = await eng.query_events(cid, types=["mode.changed"])
    ev = events[-1]
    assert ev.data["new_mode"] == "auto"
    assert ev.data["takeover_operator_id"] is None
