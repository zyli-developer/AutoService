"""§3 Participants + §7.1 invariant #8 (operator leave auto-fallback)."""

from autoservice.conversation_engine import (
    ConversationMode,
    ParticipantRole,
)


async def test_join_is_idempotent(engine, conversation, make_participant):
    op = make_participant(id="op_1", role=ParticipantRole.OPERATOR)
    await engine.join(conversation.id, op)
    await engine.join(conversation.id, op)  # no raise
    c = await engine.get_conversation(conversation.id)
    op_ids = [p.id for p in c.participants if p.role == ParticipantRole.OPERATOR]
    assert op_ids.count("op_1") == 1


async def test_first_operator_join_switches_auto_to_copilot(
    engine, conversation, make_participant
):
    """§3 join docstring + §7.1 #8."""
    assert conversation.mode == ConversationMode.AUTO
    op = make_participant(id="op_1", role=ParticipantRole.OPERATOR)
    await engine.join(conversation.id, op)
    c = await engine.get_conversation(conversation.id)
    assert c.mode == ConversationMode.COPILOT


async def test_second_operator_join_does_not_change_mode(
    engine, conversation, make_participant
):
    op1 = make_participant(id="op_1", role=ParticipantRole.OPERATOR)
    op2 = make_participant(id="op_2", role=ParticipantRole.OPERATOR)
    await engine.join(conversation.id, op1)
    mode_after_first = (await engine.get_conversation(conversation.id)).mode
    await engine.join(conversation.id, op2)
    mode_after_second = (await engine.get_conversation(conversation.id)).mode
    assert mode_after_first == mode_after_second == ConversationMode.COPILOT


async def test_last_operator_leave_falls_back_to_auto_invariant_8(
    engine, conversation, make_participant
):
    """§7.1 #8: last operator leaves + mode=copilot → auto."""
    op = make_participant(id="op_1", role=ParticipantRole.OPERATOR)
    await engine.join(conversation.id, op)
    assert (await engine.get_conversation(conversation.id)).mode == ConversationMode.COPILOT
    await engine.leave(conversation.id, "op_1")
    c = await engine.get_conversation(conversation.id)
    assert c.mode == ConversationMode.AUTO


async def test_non_last_operator_leave_keeps_copilot(
    engine, conversation, make_participant
):
    op1 = make_participant(id="op_1", role=ParticipantRole.OPERATOR)
    op2 = make_participant(id="op_2", role=ParticipantRole.OPERATOR)
    await engine.join(conversation.id, op1)
    await engine.join(conversation.id, op2)
    await engine.leave(conversation.id, "op_1")
    c = await engine.get_conversation(conversation.id)
    assert c.mode == ConversationMode.COPILOT


async def test_leave_unknown_participant_is_idempotent(engine, conversation):
    """§3 leave docstring: idempotent."""
    await engine.leave(conversation.id, "never_joined")  # no raise
