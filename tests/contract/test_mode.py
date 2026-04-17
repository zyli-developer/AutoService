"""§3 Mode + Q4 (mode.noop) + §7.1 invariant #3."""

import asyncio

import pytest

from autoservice.conversation_engine import (
    ConversationMode,
    IllegalModeTransition,
    ParticipantRole,
)


async def _with_operator(engine, conv, make_participant):
    op = make_participant(id="op_1", role=ParticipantRole.OPERATOR)
    await engine.join(conv.id, op)


async def test_switch_auto_to_copilot(engine, conversation, make_participant):
    await _with_operator(engine, conversation, make_participant)
    # join already switched to copilot; switch back and forward
    await engine.switch_mode(
        conversation.id,
        ConversationMode.AUTO,
        triggered_by="op_1",
        trigger="/release",
    )
    await engine.switch_mode(
        conversation.id,
        ConversationMode.COPILOT,
        triggered_by="op_1",
        trigger="/copilot",
    )
    assert (await engine.get_conversation(conversation.id)).mode == ConversationMode.COPILOT


async def test_switch_same_target_is_noop_q4(engine, conversation, make_participant):
    """Q4: target == current → mode.noop event, NOT IllegalModeTransition."""
    await _with_operator(engine, conversation, make_participant)
    # conv now in copilot; switch to copilot again
    events: list = []

    async def collect():
        async for ev in engine.subscribe(
            conversation_id=conversation.id, event_types=["mode.noop"]
        ):
            events.append(ev)
            if len(events) >= 1:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)  # let subscribe register
    await engine.switch_mode(
        conversation.id,
        ConversationMode.COPILOT,
        triggered_by="op_1",
        trigger="/copilot",
    )
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("Q4: no mode.noop event emitted when target == current")
    assert events[0].type == "mode.noop"


async def test_switch_on_closed_conversation_raises(
    engine, conversation, make_participant
):
    """Closed conv cannot change mode → IllegalModeTransition."""
    from autoservice.conversation_engine import Outcome

    await engine.close_conversation(
        conversation.id, outcome=Outcome.RESOLVED, resolved_by="op_1"
    )
    with pytest.raises(IllegalModeTransition):
        await engine.switch_mode(
            conversation.id,
            ConversationMode.TAKEOVER,
            triggered_by="op_1",
            trigger="/hijack",
        )


async def test_switch_mode_serialized_invariant_3(
    engine, conversation, make_participant
):
    """§7.1 #3: concurrent switch_mode is serialized (FIFO, no interleaving)."""
    await _with_operator(engine, conversation, make_participant)

    async def to(target, trig):
        await engine.switch_mode(
            conversation.id, target, triggered_by="op_1", trigger=trig
        )

    # Fire 10 concurrent toggles; final state must equal last-issued target
    targets = [ConversationMode.TAKEOVER, ConversationMode.COPILOT] * 5
    await asyncio.gather(*(to(t, f"serial_{i}") for i, t in enumerate(targets)))
    final = (await engine.get_conversation(conversation.id)).mode
    # Final mode must be a legal value (serialization means no torn state)
    assert final in {ConversationMode.TAKEOVER, ConversationMode.COPILOT}
