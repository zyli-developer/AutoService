"""§4 Gate + Q5 (only downgrades) + Q7/§7.1 #5 (irreversibility)."""

import asyncio

import pytest

from autoservice.conversation_engine import (
    ConversationMode,
    MessageVisibility,
    ParticipantRole,
)


async def _join_cust_and_op(engine, conv, make_participant):
    cust = make_participant(id="cust_1", role=ParticipantRole.CUSTOMER)
    op = make_participant(id="op_1", role=ParticipantRole.OPERATOR)
    await engine.join(conv.id, cust)
    await engine.join(conv.id, op)  # auto → copilot
    agent = make_participant(id="agent_1", role=ParticipantRole.AGENT)
    await engine.join(conv.id, agent)
    return cust, op, agent


@pytest.mark.parametrize(
    "mode,role,requested,expected",
    [
        # §4 table
        (ConversationMode.AUTO, ParticipantRole.AGENT, MessageVisibility.PUBLIC, MessageVisibility.PUBLIC),
        (ConversationMode.AUTO, ParticipantRole.CUSTOMER, MessageVisibility.PUBLIC, MessageVisibility.PUBLIC),
        (ConversationMode.AUTO, ParticipantRole.OPERATOR, MessageVisibility.PUBLIC, MessageVisibility.SIDE),
        (ConversationMode.COPILOT, ParticipantRole.AGENT, MessageVisibility.PUBLIC, MessageVisibility.PUBLIC),
        (ConversationMode.COPILOT, ParticipantRole.OPERATOR, MessageVisibility.PUBLIC, MessageVisibility.SIDE),
        (ConversationMode.TAKEOVER, ParticipantRole.AGENT, MessageVisibility.PUBLIC, MessageVisibility.SIDE),
        (ConversationMode.TAKEOVER, ParticipantRole.OPERATOR, MessageVisibility.PUBLIC, MessageVisibility.PUBLIC),
    ],
)
async def test_gate_matrix(
    engine, conversation, make_participant, mode, role, requested, expected
):
    cust, op, agent = await _join_cust_and_op(engine, conversation, make_participant)
    sender = {
        ParticipantRole.AGENT: agent,
        ParticipantRole.CUSTOMER: cust,
        ParticipantRole.OPERATOR: op,
    }[role]

    # Drive to target mode
    if mode == ConversationMode.AUTO:
        await engine.switch_mode(
            conversation.id,
            ConversationMode.AUTO,
            triggered_by=op.id,
            trigger="/release",
        )
    elif mode == ConversationMode.TAKEOVER:
        await engine.switch_mode(
            conversation.id,
            ConversationMode.TAKEOVER,
            triggered_by=op.id,
            trigger="/hijack",
        )
    # else: stay in copilot (default after op join)

    m = await engine.send_message(
        conversation.id,
        source=sender.id,
        content="payload",
        requested_visibility=requested,
    )
    assert m.visibility == expected


async def test_gate_only_downgrades_q5(engine, conversation, make_participant):
    """Q5: requested=SIDE always stays SIDE (never upgraded to PUBLIC)."""
    cust, op, agent = await _join_cust_and_op(engine, conversation, make_participant)
    m = await engine.send_message(
        conversation.id,
        source=agent.id,
        content="side by request",
        requested_visibility=MessageVisibility.SIDE,
    )
    assert m.visibility == MessageVisibility.SIDE


async def test_gate_downgrade_emits_message_gated(
    engine, conversation, make_participant
):
    """§4: Gate downgrade → message.gated event (for operator UI)."""
    cust, op, agent = await _join_cust_and_op(engine, conversation, make_participant)
    events: list = []

    async def collect():
        async for ev in engine.subscribe(
            conversation_id=conversation.id, event_types=["message.gated"]
        ):
            events.append(ev)
            if len(events) >= 1:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)
    await engine.send_message(
        conversation.id,
        source=op.id,
        content="suggestion for customer",
        requested_visibility=MessageVisibility.PUBLIC,
    )
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("message.gated event not emitted on operator downgrade")
    assert events[0].type == "message.gated"


async def test_gate_downgrade_irreversible_invariant_5(
    engine, conversation, make_participant
):
    """§7.1 #5 ⚓: once PUBLIC→SIDE, mode changes never upgrade it back."""
    cust, op, agent = await _join_cust_and_op(engine, conversation, make_participant)
    # Switch to takeover; agent message PUBLIC → SIDE
    await engine.switch_mode(
        conversation.id,
        ConversationMode.TAKEOVER,
        triggered_by=op.id,
        trigger="/hijack",
    )
    m = await engine.send_message(
        conversation.id,
        source=agent.id,
        content="pre-release reply",
        requested_visibility=MessageVisibility.PUBLIC,
    )
    assert m.visibility == MessageVisibility.SIDE

    # /release → back to auto
    await engine.switch_mode(
        conversation.id,
        ConversationMode.AUTO,
        triggered_by=op.id,
        trigger="/release",
    )
    # Re-fetch the message; visibility must still be SIDE
    all_msgs = await engine.get_messages(conversation.id)
    same = next(mm for mm in all_msgs if mm.id == m.id)
    assert same.visibility == MessageVisibility.SIDE
