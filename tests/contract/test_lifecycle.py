"""§3 Conversation lifecycle + §7.1 invariants #1 #2."""

import pytest

from autoservice.conversation_engine import (
    ConversationNotFound,
    ConversationState,
    Outcome,
    ValidationError,
)


async def test_create_returns_conversation(engine):
    c = await engine.create_conversation(channel="web", external_id="sess_a")
    assert c.id  # Q1: id format {channel}_{external_id} — specific format tested separately
    assert c.state in {ConversationState.CREATED, ConversationState.ACTIVE}


async def test_conversation_id_format_q1(engine):
    """Q1: conversation_id = {channel}_{external_id}."""
    c = await engine.create_conversation(channel="web", external_id="sess_abc")
    assert c.id == "web_sess_abc"


async def test_create_is_idempotent_invariant_1(engine):
    """§7.1 #1: same (channel, external_id) + not closed → same conv."""
    a = await engine.create_conversation(channel="web", external_id="sess_dup")
    b = await engine.create_conversation(channel="web", external_id="sess_dup")
    assert a.id == b.id


async def test_get_unknown_raises(engine):
    with pytest.raises(ConversationNotFound):
        await engine.get_conversation("web_missing")


async def test_close_emits_resolution(engine, conversation):
    closed = await engine.close_conversation(
        conversation.id,
        outcome=Outcome.RESOLVED,
        resolved_by="op_1",
    )
    assert closed.state == ConversationState.CLOSED
    assert closed.resolution is not None
    assert closed.resolution.outcome == Outcome.RESOLVED


async def test_close_is_idempotent_invariant_2(engine, conversation):
    """§7.1 #2: already-closed close returns existing Resolution."""
    first = await engine.close_conversation(
        conversation.id, outcome=Outcome.RESOLVED, resolved_by="op_1"
    )
    second = await engine.close_conversation(
        conversation.id, outcome=Outcome.ABANDONED, resolved_by="op_2"
    )
    # Resolution must be frozen from first close, not overwritten
    assert second.resolution.outcome == first.resolution.outcome
    assert second.resolution.resolved_by == first.resolution.resolved_by


async def test_set_csat_valid(engine, conversation):
    await engine.close_conversation(
        conversation.id, outcome=Outcome.RESOLVED, resolved_by="op_1"
    )
    await engine.set_csat(conversation.id, 5)


@pytest.mark.parametrize("score", [0, 6, -1, 100])
async def test_set_csat_out_of_range_raises(engine, conversation, score):
    await engine.close_conversation(
        conversation.id, outcome=Outcome.RESOLVED, resolved_by="op_1"
    )
    with pytest.raises(ValidationError):
        await engine.set_csat(conversation.id, score)


async def test_list_active_excludes_closed(engine):
    a = await engine.create_conversation(channel="web", external_id="sess_la1")
    b = await engine.create_conversation(channel="web", external_id="sess_la2")
    await engine.close_conversation(a.id, outcome=Outcome.RESOLVED, resolved_by="op_1")
    active = await engine.list_active_conversations()
    ids = {c.id for c in active}
    assert a.id not in ids
    assert b.id in ids


async def test_list_active_filter_by_squad(engine):
    """B1: squad_id filter returns only conversations assigned to that squad."""
    active = await engine.list_active_conversations(squad_id="squad_x")
    for c in active:
        assert c.metadata.get("squad_id") == "squad_x"
