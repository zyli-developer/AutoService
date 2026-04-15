"""§7.1 invariants — end-to-end scenarios beyond per-method tests.

Most invariants have per-method coverage; this file captures
cross-cutting scenarios that stress multiple invariants together.
"""

import asyncio

from autoservice.conversation_engine import (
    ConversationMode,
    MessageVisibility,
    Outcome,
    ParticipantRole,
)


async def test_full_takeover_cycle(engine, make_participant):
    """Integrated flow covering invariants #3, #4, #5, #8.

    auto → customer msg → operator joins (copilot) → /hijack (takeover)
      → agent msg downgraded (SIDE, irreversible)
      → operator reply (public)
      → operator leaves (→auto)
      → resolve
    """
    c = await engine.create_conversation(channel="web", external_id="full_flow")
    cust = make_participant(id="c", role=ParticipantRole.CUSTOMER)
    agent = make_participant(id="a", role=ParticipantRole.AGENT)
    op = make_participant(id="o", role=ParticipantRole.OPERATOR)
    await engine.join(c.id, cust)
    await engine.join(c.id, agent)

    q = await engine.send_message(c.id, source=cust.id, content="help?")
    assert q.visibility == MessageVisibility.PUBLIC

    await engine.join(c.id, op)
    assert (await engine.get_conversation(c.id)).mode == ConversationMode.COPILOT

    await engine.handle_command(c.id, actor_id=op.id, command="/hijack")
    assert (await engine.get_conversation(c.id)).mode == ConversationMode.TAKEOVER

    agent_reply = await engine.send_message(
        c.id,
        source=agent.id,
        content="auto-suggested",
        requested_visibility=MessageVisibility.PUBLIC,
    )
    assert agent_reply.visibility == MessageVisibility.SIDE  # Gate downgrade

    op_reply = await engine.send_message(
        c.id, source=op.id, content="human answer"
    )
    assert op_reply.visibility == MessageVisibility.PUBLIC

    # /release
    await engine.handle_command(c.id, actor_id=op.id, command="/release")
    assert (await engine.get_conversation(c.id)).mode == ConversationMode.AUTO

    # Invariant #5: the downgraded agent reply stays SIDE
    all_msgs = await engine.get_messages(c.id)
    frozen = next(m for m in all_msgs if m.id == agent_reply.id)
    assert frozen.visibility == MessageVisibility.SIDE

    # Invariant #8: operator leaves (already in auto, so no mode change needed)
    await engine.leave(c.id, op.id)
    assert (await engine.get_conversation(c.id)).mode == ConversationMode.AUTO

    # Resolve
    await engine.close_conversation(c.id, outcome=Outcome.RESOLVED, resolved_by=op.id)


async def test_event_sequence_strict_monotonic_under_concurrency(
    engine, conversation, make_participant
):
    """§7.1 #4: per-conv sequence_number is strictly increasing even under
    concurrent writes."""
    cust = make_participant(id="cust_c", role=ParticipantRole.CUSTOMER)
    await engine.join(conversation.id, cust)

    async def send(n):
        await engine.send_message(
            conversation.id, source=cust.id, content=f"msg_{n}"
        )

    await asyncio.gather(*(send(i) for i in range(20)))
    msgs = await engine.get_messages(conversation.id, limit=100)
    seqs = [m.sequence_number for m in msgs]
    # All unique, strictly monotonic when sorted
    assert len(set(seqs)) == len(seqs)
    assert sorted(seqs) == seqs


async def test_create_after_close_creates_new_conversation(engine):
    """§7.1 #1: idempotency is conditional on 'not closed'. Once closed, a new
    create with same (channel, external_id) must produce a distinct conv."""
    a = await engine.create_conversation(channel="web", external_id="reopen_x")
    await engine.close_conversation(a.id, outcome=Outcome.RESOLVED, resolved_by="sys")
    b = await engine.create_conversation(channel="web", external_id="reopen_x")
    # New conversation: either new id (likely, since {channel}_{external_id}
    # collision must be resolved) or explicit reactivation; spec leaves the
    # implementation latitude but forbids returning the *closed* one.
    assert (await engine.get_conversation(b.id)).state.value != "closed"
