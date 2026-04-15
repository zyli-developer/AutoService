"""§5 events + Q6 subscribe semantics + §7.1 #4 ordering."""

import asyncio

import pytest

from autoservice.conversation_engine import (
    ConversationMode,
    EventType,
    ParticipantRole,
)


async def _collect(engine, *, timeout=2.0, max_events=10, **subscribe_kwargs):
    out = []

    async def run():
        async for ev in engine.subscribe(**subscribe_kwargs):
            out.append(ev)
            if len(out) >= max_events:
                break

    task = asyncio.create_task(run())
    await asyncio.sleep(0)
    return task, out


async def test_subscribe_receives_conversation_created(engine):
    task, events = await _collect(engine, max_events=1)
    await engine.create_conversation(channel="web", external_id="sess_ev1")
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("no event received on conversation.created")
    assert events[0].type == EventType.CONVERSATION_CREATED.value


async def test_subscribe_filters_by_event_types(engine, conversation, make_participant):
    task, events = await _collect(
        engine,
        conversation_id=conversation.id,
        event_types=["mode.changed"],
        max_events=1,
    )
    op = make_participant(id="op_1", role=ParticipantRole.OPERATOR)
    await engine.join(conversation.id, op)  # emits mode.changed (auto→copilot) + participant.joined
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("mode.changed event not delivered to filtered subscriber")
    assert all(e.type == "mode.changed" for e in events)


async def test_subscribe_since_sequence_per_conv_ordering_invariant_4(
    engine, conversation, make_participant
):
    """§7.1 #4: per-conv events have monotonic sequence_number."""
    cust = make_participant(id="cust_1", role=ParticipantRole.CUSTOMER)
    await engine.join(conversation.id, cust)
    for i in range(3):
        await engine.send_message(conversation.id, source=cust.id, content=f"m{i}")

    evs = await engine.query_events(conversation.id)
    seqs = [e.sequence_number for e in evs]
    assert seqs == sorted(seqs)
    # strictly monotonic
    assert all(b > a for a, b in zip(seqs, seqs[1:]))


async def test_subscribe_squad_scope_returns_cross_conv_events(
    engine, make_participant
):
    """B8: squad_id subscription sees events from multiple conversations."""
    # Create 2 convs with squad metadata
    a = await engine.create_conversation(
        channel="web", external_id="sq_a", metadata={"squad_id": "sq1"}
    )
    b = await engine.create_conversation(
        channel="web", external_id="sq_b", metadata={"squad_id": "sq1"}
    )
    task, events = await _collect(engine, squad_id="sq1", max_events=2)
    cust = make_participant(id="cust_sq", role=ParticipantRole.CUSTOMER)
    await engine.join(a.id, cust)
    await engine.join(b.id, cust)
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("squad-scope subscription missed events")
    conv_ids = {e.conversation_id for e in events}
    assert conv_ids >= {a.id, b.id}


async def test_hook_exception_emits_hook_failed_invariant_7(
    engine, conversation, make_participant
):
    """§7.1 #7: PluginHook exception → swallowed + hook.failed event."""

    class BoomHook:
        async def on_conversation_created(self, conv):
            raise RuntimeError("boom")

        async def on_conversation_closed(self, conv): ...
        async def on_mode_changed(self, conv, old, new, trigger): ...
        async def on_participant_joined(self, conv, p): ...
        async def on_timer_expired(self, conv, timer): ...
        async def on_event(self, event): ...

    engine.register_hook(BoomHook())

    task, events = await _collect(
        engine, event_types=["hook.failed"], max_events=1
    )
    # Trigger the failing hook
    await engine.create_conversation(channel="web", external_id="hook_boom")
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("hook.failed event not emitted after PluginHook exception")
    assert events[0].type == "hook.failed"


async def test_query_events_respects_types_filter(
    engine, conversation, make_participant
):
    cust = make_participant(id="cust_1", role=ParticipantRole.CUSTOMER)
    await engine.join(conversation.id, cust)
    await engine.send_message(conversation.id, source=cust.id, content="hi")
    evs = await engine.query_events(conversation.id, types=["message.sent"])
    assert all(e.type == "message.sent" for e in evs)
    assert len(evs) >= 1
