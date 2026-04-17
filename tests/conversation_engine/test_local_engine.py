"""T1A.1 LocalEngine functional tests (test-plan-003 · TC-001 ~ TC-030).

Replaces the T0.4 stub tests. Structural checks (TC-001~003, TC-023~025)
are preserved; the NotImplementedError checks are retired since the methods
are now implemented.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from autoservice.conversation_engine import (
    ConversationMode,
    ConversationNotFound,
    ConversationState,
    IllegalModeTransition,
    LocalEngine,
    MessageVisibility,
    Outcome,
    Participant,
    ParticipantRole,
    ValidationError,
)


# ---- Group A: Import / instantiation / structure (preserved from T0.4) ----


def test_tc001_import_local_engine() -> None:
    from autoservice.conversation_engine import LocalEngine as LE
    assert LE is LocalEngine


def test_tc002_instantiate_local_engine() -> None:
    assert isinstance(LocalEngine(), LocalEngine)


PROTOCOL_METHOD_NAMES = [
    "create_conversation", "get_conversation", "list_active_conversations",
    "close_conversation", "set_csat", "join", "leave", "switch_mode",
    "send_message", "edit_message", "delete_message", "get_messages",
    "handle_command", "set_timer", "cancel_timer", "subscribe",
    "query_events", "register_hook",
]


def test_tc003_protocol_structural_check(engine: LocalEngine) -> None:
    for name in PROTOCOL_METHOD_NAMES:
        assert hasattr(engine, name) and callable(getattr(engine, name))


# ---- Group B: Conversation lifecycle ----


async def test_tc_create_conversation(engine: LocalEngine) -> None:
    """TC-001: basic creation."""
    conv = await engine.create_conversation(channel="web", external_id="sess_1")
    assert conv.id == "web_sess_1"
    assert conv.state == ConversationState.CREATED
    assert conv.mode == ConversationMode.AUTO
    assert conv.participants == ()


async def test_tc_create_conversation_idempotent(engine: LocalEngine) -> None:
    """TC-002: same (channel, external_id) returns existing."""
    c1 = await engine.create_conversation(channel="web", external_id="s1")
    c2 = await engine.create_conversation(channel="web", external_id="s1")
    assert c1.id == c2.id


async def test_tc_get_conversation_not_found(engine: LocalEngine) -> None:
    """TC-003: raises ConversationNotFound."""
    with pytest.raises(ConversationNotFound):
        await engine.get_conversation("web_nonexist")


async def test_tc_close_conversation(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-004: close sets CLOSED + Resolution."""
    conv = await engine.create_conversation(channel="web", external_id="c1")
    await engine.join(conv.id, participant_customer)
    closed = await engine.close_conversation(
        conv.id, outcome=Outcome.RESOLVED, resolved_by="op_1",
    )
    assert closed.state == ConversationState.CLOSED
    assert closed.resolution is not None
    assert closed.resolution.outcome == Outcome.RESOLVED


async def test_tc_close_conversation_idempotent(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-005: closing already-closed conv returns existing, no error."""
    conv = await engine.create_conversation(channel="web", external_id="c2")
    await engine.join(conv.id, participant_customer)
    await engine.close_conversation(conv.id, outcome=Outcome.RESOLVED, resolved_by="op")
    again = await engine.close_conversation(conv.id, outcome=Outcome.ABANDONED, resolved_by="op")
    assert again.state == ConversationState.CLOSED
    assert again.resolution.outcome == Outcome.RESOLVED  # first close wins


# ---- Group C: Participants ----


async def test_tc_operator_join_auto_to_copilot(
    engine: LocalEngine, participant_customer: Participant, participant_operator: Participant,
) -> None:
    """TC-006: operator join triggers auto→copilot."""
    conv = await engine.create_conversation(channel="web", external_id="p1")
    await engine.join(conv.id, participant_customer)
    await engine.join(conv.id, participant_operator)
    updated = await engine.get_conversation(conv.id)
    assert updated.mode == ConversationMode.COPILOT
    assert len(updated.participants) == 2


async def test_tc_join_idempotent(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-007: duplicate join is no-op."""
    conv = await engine.create_conversation(channel="web", external_id="p2")
    await engine.join(conv.id, participant_customer)
    await engine.join(conv.id, participant_customer)
    updated = await engine.get_conversation(conv.id)
    assert len(updated.participants) == 1


async def test_tc_last_operator_leave_copilot_to_auto(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    """TC-008: last operator leave → copilot→auto (§7.1 #8)."""
    conv = await engine.create_conversation(channel="web", external_id="p3")
    await engine.join(conv.id, participant_customer)
    await engine.join(conv.id, participant_operator)
    assert (await engine.get_conversation(conv.id)).mode == ConversationMode.COPILOT
    await engine.leave(conv.id, participant_operator.id)
    assert (await engine.get_conversation(conv.id)).mode == ConversationMode.AUTO


# ---- Group D: Mode state machine ----


async def test_tc_switch_mode_to_takeover(
    engine: LocalEngine, participant_customer: Participant, participant_operator: Participant,
) -> None:
    """TC-009: switch auto→takeover."""
    conv = await engine.create_conversation(channel="web", external_id="m1")
    await engine.join(conv.id, participant_customer)
    await engine.join(conv.id, participant_operator)
    # now copilot; switch to takeover
    await engine.switch_mode(
        conv.id, ConversationMode.TAKEOVER,
        triggered_by=participant_operator.id, trigger="/hijack",
    )
    assert (await engine.get_conversation(conv.id)).mode == ConversationMode.TAKEOVER


async def test_tc_switch_mode_noop_q4(
    engine: LocalEngine, participant_customer: Participant, participant_operator: Participant,
) -> None:
    """TC-010: target == current → mode.noop event, no exception (Q4)."""
    conv = await engine.create_conversation(channel="web", external_id="m2")
    await engine.join(conv.id, participant_customer)
    await engine.join(conv.id, participant_operator)
    # now copilot; switch to copilot again — should not raise
    await engine.switch_mode(
        conv.id, ConversationMode.COPILOT,
        triggered_by=participant_operator.id, trigger="/copilot",
    )
    events = await engine.query_events(conv.id, types=["mode.noop"])
    assert any(e.type == "mode.noop" for e in events)


async def test_tc_switch_mode_closed_raises(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-011: switch_mode on closed conv → IllegalModeTransition."""
    conv = await engine.create_conversation(channel="web", external_id="m3")
    await engine.join(conv.id, participant_customer)
    await engine.close_conversation(conv.id, outcome=Outcome.RESOLVED, resolved_by="op")
    with pytest.raises(IllegalModeTransition):
        await engine.switch_mode(
            conv.id, ConversationMode.TAKEOVER,
            triggered_by="op", trigger="/hijack",
        )


async def test_tc_switch_mode_serialized(
    engine: LocalEngine, participant_customer: Participant, participant_operator: Participant,
) -> None:
    """TC-012: concurrent switch_mode is serialized (§7.1 #3)."""
    conv = await engine.create_conversation(channel="web", external_id="m4")
    await engine.join(conv.id, participant_customer)
    await engine.join(conv.id, participant_operator)

    async def to(target: ConversationMode, i: int) -> None:
        await engine.switch_mode(
            conv.id, target, triggered_by="op", trigger=f"serial_{i}",
        )

    targets = [ConversationMode.TAKEOVER, ConversationMode.COPILOT] * 5
    await asyncio.gather(*(to(t, i) for i, t in enumerate(targets)))
    final = (await engine.get_conversation(conv.id)).mode
    assert final in {ConversationMode.TAKEOVER, ConversationMode.COPILOT}


# ---- Group E: Gate ----


async def _setup_all_roles(engine, conv_id, participant_customer, participant_operator, participant_agent):
    await engine.join(conv_id, participant_customer)
    await engine.join(conv_id, participant_operator)
    await engine.join(conv_id, participant_agent)


async def test_tc_gate_copilot_operator_downgrade(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
    participant_agent: Participant,
) -> None:
    """TC-013: copilot + operator PUBLIC → SIDE."""
    conv = await engine.create_conversation(channel="web", external_id="g1")
    await _setup_all_roles(engine, conv.id, participant_customer, participant_operator, participant_agent)
    # now copilot
    m = await engine.send_message(
        conv.id, source=participant_operator.id, content="suggestion",
        requested_visibility=MessageVisibility.PUBLIC,
    )
    assert m.visibility == MessageVisibility.SIDE


async def test_tc_gate_takeover_agent_downgrade(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
    participant_agent: Participant,
) -> None:
    """TC-014: takeover + agent PUBLIC → SIDE."""
    conv = await engine.create_conversation(channel="web", external_id="g2")
    await _setup_all_roles(engine, conv.id, participant_customer, participant_operator, participant_agent)
    await engine.switch_mode(
        conv.id, ConversationMode.TAKEOVER,
        triggered_by=participant_operator.id, trigger="/hijack",
    )
    m = await engine.send_message(
        conv.id, source=participant_agent.id, content="ai hint",
        requested_visibility=MessageVisibility.PUBLIC,
    )
    assert m.visibility == MessageVisibility.SIDE


async def test_tc_gate_auto_agent_no_downgrade(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
    participant_agent: Participant,
) -> None:
    """TC-015: auto + agent PUBLIC stays PUBLIC."""
    conv = await engine.create_conversation(channel="web", external_id="g3")
    await _setup_all_roles(engine, conv.id, participant_customer, participant_operator, participant_agent)
    # switch back to auto
    await engine.switch_mode(
        conv.id, ConversationMode.AUTO,
        triggered_by=participant_operator.id, trigger="/release",
    )
    m = await engine.send_message(
        conv.id, source=participant_agent.id, content="reply",
        requested_visibility=MessageVisibility.PUBLIC,
    )
    assert m.visibility == MessageVisibility.PUBLIC


async def test_tc_gate_side_never_upgraded_q5(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_agent: Participant,
) -> None:
    """TC-016: requested=SIDE stays SIDE (Q5)."""
    conv = await engine.create_conversation(channel="web", external_id="g4")
    await engine.join(conv.id, participant_customer)
    await engine.join(conv.id, participant_agent)
    m = await engine.send_message(
        conv.id, source=participant_agent.id, content="internal",
        requested_visibility=MessageVisibility.SIDE,
    )
    assert m.visibility == MessageVisibility.SIDE


async def test_tc_gate_downgrade_irreversible(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
    participant_agent: Participant,
) -> None:
    """TC-017: gate downgrade is irreversible (§7.1 #5)."""
    conv = await engine.create_conversation(channel="web", external_id="g5")
    await _setup_all_roles(engine, conv.id, participant_customer, participant_operator, participant_agent)
    await engine.switch_mode(
        conv.id, ConversationMode.TAKEOVER,
        triggered_by=participant_operator.id, trigger="/hijack",
    )
    m = await engine.send_message(
        conv.id, source=participant_agent.id, content="gated",
        requested_visibility=MessageVisibility.PUBLIC,
    )
    assert m.visibility == MessageVisibility.SIDE
    # switch back to auto
    await engine.switch_mode(
        conv.id, ConversationMode.AUTO,
        triggered_by=participant_operator.id, trigger="/release",
    )
    msgs = await engine.get_messages(conv.id)
    same = next(mm for mm in msgs if mm.id == m.id)
    assert same.visibility == MessageVisibility.SIDE


# ---- Group F: Messages ----


async def test_tc_send_message_sequence(
    engine: LocalEngine,
    participant_customer: Participant,
) -> None:
    """TC-018: sequence numbers increment per conversation."""
    conv = await engine.create_conversation(channel="web", external_id="msg1")
    await engine.join(conv.id, participant_customer)
    m1 = await engine.send_message(conv.id, source=participant_customer.id, content="a")
    m2 = await engine.send_message(conv.id, source=participant_customer.id, content="b")
    m3 = await engine.send_message(conv.id, source=participant_customer.id, content="c")
    assert m1.sequence_number == 1
    assert m2.sequence_number == 2
    assert m3.sequence_number == 3


async def test_tc_edit_message(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_agent: Participant,
) -> None:
    """TC-019: edit_message for placeholder→continuation."""
    conv = await engine.create_conversation(channel="web", external_id="msg2")
    await engine.join(conv.id, participant_customer)
    await engine.join(conv.id, participant_agent)
    placeholder = await engine.send_message(
        conv.id, source=participant_agent.id, content="...",
    )
    edited = await engine.edit_message(
        conv.id, placeholder.id, new_content="Full reply here", edited_by=participant_agent.id,
    )
    assert edited.content == "Full reply here"
    assert edited.edit_of == placeholder.id


async def test_tc_get_messages_viewer_role_filter(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
    participant_agent: Participant,
) -> None:
    """TC-020: CUSTOMER viewer doesn't see SIDE messages (Q9)."""
    conv = await engine.create_conversation(channel="web", external_id="msg3")
    await _setup_all_roles(engine, conv.id, participant_customer, participant_operator, participant_agent)
    # copilot: operator PUBLIC → SIDE
    await engine.send_message(
        conv.id, source=participant_operator.id, content="side msg",
        requested_visibility=MessageVisibility.PUBLIC,
    )
    await engine.send_message(
        conv.id, source=participant_customer.id, content="public msg",
    )
    customer_view = await engine.get_messages(conv.id, viewer_role=ParticipantRole.CUSTOMER)
    assert all(m.visibility != MessageVisibility.SIDE for m in customer_view)
    assert len(customer_view) == 1


async def test_tc_get_messages_since_sequence(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-021: since_sequence filters correctly."""
    conv = await engine.create_conversation(channel="web", external_id="msg4")
    await engine.join(conv.id, participant_customer)
    for i in range(5):
        await engine.send_message(conv.id, source=participant_customer.id, content=f"m{i+1}")
    msgs = await engine.get_messages(conv.id, since_sequence=3)
    assert [m.sequence_number for m in msgs] == [4, 5]


async def test_tc_get_messages_before_sequence(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-022: before_sequence for scroll-up."""
    conv = await engine.create_conversation(channel="web", external_id="msg5")
    await engine.join(conv.id, participant_customer)
    for i in range(5):
        await engine.send_message(conv.id, source=participant_customer.id, content=f"m{i+1}")
    msgs = await engine.get_messages(conv.id, before_sequence=4, limit=2)
    assert all(m.sequence_number < 4 for m in msgs)
    assert len(msgs) <= 2


async def test_tc_get_messages_since_before_mutually_exclusive(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-023: since + before together → ValidationError."""
    conv = await engine.create_conversation(channel="web", external_id="msg6")
    await engine.join(conv.id, participant_customer)
    with pytest.raises(ValidationError):
        await engine.get_messages(conv.id, since_sequence=1, before_sequence=5)


# ---- Group G: CSAT ----


async def test_tc_set_csat_valid(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-024: valid CSAT score is recorded."""
    conv = await engine.create_conversation(channel="web", external_id="csat1")
    await engine.join(conv.id, participant_customer)
    await engine.close_conversation(conv.id, outcome=Outcome.RESOLVED, resolved_by="op")
    await engine.set_csat(conv.id, score=4)
    updated = await engine.get_conversation(conv.id)
    assert updated.resolution.csat_score == 4


async def test_tc_set_csat_invalid(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-025: invalid CSAT score → ValidationError."""
    conv = await engine.create_conversation(channel="web", external_id="csat2")
    await engine.join(conv.id, participant_customer)
    await engine.close_conversation(conv.id, outcome=Outcome.RESOLVED, resolved_by="op")
    with pytest.raises(ValidationError):
        await engine.set_csat(conv.id, score=0)
    with pytest.raises(ValidationError):
        await engine.set_csat(conv.id, score=6)


# ---- Group H: list_active_conversations ----


async def test_tc_list_active_all(engine: LocalEngine, participant_customer: Participant) -> None:
    """TC-026: list returns active, not closed."""
    for i in range(3):
        c = await engine.create_conversation(channel="web", external_id=f"la{i}")
        await engine.join(c.id, participant_customer)
    c4 = await engine.create_conversation(channel="web", external_id="la_closed")
    await engine.join(c4.id, participant_customer)
    await engine.close_conversation(c4.id, outcome=Outcome.RESOLVED, resolved_by="op")
    active = await engine.list_active_conversations()
    assert len(active) == 3
    assert all(c.state != ConversationState.CLOSED for c in active)


async def test_tc_list_active_by_operator(
    engine: LocalEngine, participant_customer: Participant, participant_operator: Participant,
) -> None:
    """TC-027: filter by operator_id."""
    c1 = await engine.create_conversation(channel="web", external_id="lo1")
    c2 = await engine.create_conversation(channel="web", external_id="lo2")
    c3 = await engine.create_conversation(channel="web", external_id="lo3")
    await engine.join(c1.id, participant_customer)
    await engine.join(c2.id, participant_customer)
    await engine.join(c3.id, participant_customer)
    await engine.join(c1.id, participant_operator)
    await engine.join(c2.id, participant_operator)
    result = await engine.list_active_conversations(operator_id=participant_operator.id)
    assert len(result) == 2


# ---- Group I: Contract factory registration (TC-028) ----


async def test_tc_contract_factory_registered() -> None:
    """TC-028: LocalEngine factory is registered for contract tests via env var."""
    import os
    assert os.environ.get("AUTOSERVICE_CONTRACT_ENGINE_FACTORY") is not None


# ---- Group J: Events minimal (TC-029) ----


async def test_tc_subscribe_receives_mode_changed(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    """TC-029: subscribe receives mode.changed events."""
    conv = await engine.create_conversation(channel="web", external_id="ev1")
    await engine.join(conv.id, participant_customer)
    await engine.join(conv.id, participant_operator)

    events: list = []

    async def collect():
        async for ev in engine.subscribe(
            conversation_id=conv.id, event_types=["mode.changed"],
        ):
            events.append(ev)
            if len(events) >= 1:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)
    await engine.switch_mode(
        conv.id, ConversationMode.TAKEOVER,
        triggered_by=participant_operator.id, trigger="/hijack",
    )
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
        pytest.fail("subscribe did not receive mode.changed event")
    assert events[0].type == "mode.changed"


# ---- Group K: delete_message (TC-030) ----


async def test_tc_delete_message(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-030: delete_message removes from get_messages."""
    conv = await engine.create_conversation(channel="web", external_id="del1")
    await engine.join(conv.id, participant_customer)
    m = await engine.send_message(conv.id, source=participant_customer.id, content="to delete")
    await engine.delete_message(conv.id, m.id, deleted_by="op")
    msgs = await engine.get_messages(conv.id)
    assert not any(mm.id == m.id for mm in msgs)


# ---- Group L: EventBus subscribe scopes (T1A.3 · TC-002~TC-008) ----


async def test_tc_subscribe_conv_scope(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-002: subscribe(conversation_id) receives events for that conv."""
    conv = await engine.create_conversation(channel="web", external_id="eb1")
    await engine.join(conv.id, participant_customer)

    events: list = []

    async def collect():
        async for ev in engine.subscribe(conversation_id=conv.id):
            events.append(ev)
            if len(events) >= 1:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)
    await engine.send_message(conv.id, source=participant_customer.id, content="hi")
    await asyncio.wait_for(task, timeout=2.0)
    assert any(e.type == "message.sent" for e in events)


async def test_tc_subscribe_event_types_filter(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    """TC-003: subscribe with event_types only yields matching types."""
    conv = await engine.create_conversation(channel="web", external_id="eb2")
    await engine.join(conv.id, participant_customer)
    await engine.join(conv.id, participant_operator)

    events: list = []

    async def collect():
        async for ev in engine.subscribe(
            conversation_id=conv.id, event_types=["mode.changed"],
        ):
            events.append(ev)
            if len(events) >= 1:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)
    # send_message → message.sent (should be filtered out)
    await engine.send_message(conv.id, source=participant_customer.id, content="msg")
    # switch mode → mode.changed (should pass filter)
    await engine.switch_mode(
        conv.id, ConversationMode.TAKEOVER,
        triggered_by=participant_operator.id, trigger="/hijack",
    )
    await asyncio.wait_for(task, timeout=2.0)
    assert all(e.type == "mode.changed" for e in events)


async def test_tc_subscribe_squad_scope(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-004: subscribe(squad_id) only receives events from that squad."""
    conv_a = await engine.create_conversation(
        channel="web", external_id="sq1", metadata={"squad_id": "s1"},
    )
    conv_b = await engine.create_conversation(
        channel="web", external_id="sq2", metadata={"squad_id": "s2"},
    )
    await engine.join(conv_a.id, participant_customer)
    cust2 = Participant(
        id="u-customer-2", role=ParticipantRole.CUSTOMER,
        joined_at=participant_customer.joined_at,
    )
    await engine.join(conv_b.id, cust2)

    events: list = []

    async def collect():
        async for ev in engine.subscribe(squad_id="s1"):
            events.append(ev)
            if len(events) >= 1:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)
    # Event on conv_b (squad s2) — should NOT reach subscriber
    await engine.send_message(conv_b.id, source=cust2.id, content="s2 msg")
    # Event on conv_a (squad s1) — should reach subscriber
    await engine.send_message(conv_a.id, source=participant_customer.id, content="s1 msg")
    await asyncio.wait_for(task, timeout=2.0)
    assert all(e.conversation_id == conv_a.id for e in events)


async def test_tc_subscribe_global_scope(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-005: subscribe() with no scope receives all events."""
    conv1 = await engine.create_conversation(channel="web", external_id="gl1")
    conv2 = await engine.create_conversation(channel="web", external_id="gl2")
    await engine.join(conv1.id, participant_customer)
    cust2 = Participant(
        id="u-customer-2", role=ParticipantRole.CUSTOMER,
        joined_at=participant_customer.joined_at,
    )
    await engine.join(conv2.id, cust2)

    events: list = []

    async def collect():
        # Filter to message.sent only to avoid noise from conversation.activated
        async for ev in engine.subscribe(event_types=["message.sent"]):
            events.append(ev)
            if len(events) >= 2:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)
    await engine.send_message(conv1.id, source=participant_customer.id, content="a")
    await engine.send_message(conv2.id, source=cust2.id, content="b")
    await asyncio.wait_for(task, timeout=2.0)
    conv_ids = {e.conversation_id for e in events}
    assert conv1.id in conv_ids and conv2.id in conv_ids


async def test_tc_subscribe_since_sequence_conv(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-006: since_sequence replays missed events then continues live."""
    conv = await engine.create_conversation(channel="web", external_id="ss1")
    await engine.join(conv.id, participant_customer)
    # Generate 5 events (message.sent) with seq 1-5 (plus earlier events from create/join)
    for i in range(5):
        await engine.send_message(conv.id, source=participant_customer.id, content=f"m{i+1}")

    # Get all events to find the sequence to resume from
    all_events = await engine.query_events(conv.id)
    mid_seq = all_events[len(all_events) // 2].sequence_number

    events: list = []

    async def collect():
        async for ev in engine.subscribe(
            conversation_id=conv.id, since_sequence=mid_seq,
        ):
            events.append(ev)
            if len(events) >= 3:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.05)  # allow replay
    # Also send a new live event
    await engine.send_message(conv.id, source=participant_customer.id, content="live")
    await asyncio.wait_for(task, timeout=3.0)

    # All replayed events should have seq > mid_seq
    replayed = [e for e in events if e.sequence_number <= all_events[-1].sequence_number]
    assert all(e.sequence_number > mid_seq for e in replayed)


async def test_tc_subscribe_viewer_role_filters_side(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
    participant_agent: Participant,
) -> None:
    """TC-008: CUSTOMER viewer does not receive SIDE message events."""
    conv = await engine.create_conversation(channel="web", external_id="vr1")
    await _setup_all_roles(engine, conv.id, participant_customer, participant_operator, participant_agent)
    # Now in copilot mode

    events: list = []

    async def collect():
        async for ev in engine.subscribe(
            conversation_id=conv.id,
            event_types=["message.sent"],
            viewer_role=ParticipantRole.CUSTOMER,
        ):
            events.append(ev)
            if len(events) >= 1:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)
    # Operator PUBLIC in copilot → SIDE (should be filtered for CUSTOMER viewer)
    await engine.send_message(
        conv.id, source=participant_operator.id, content="side",
        requested_visibility=MessageVisibility.PUBLIC,
    )
    # Customer PUBLIC stays PUBLIC (should pass through)
    await engine.send_message(
        conv.id, source=participant_customer.id, content="public",
    )
    await asyncio.wait_for(task, timeout=2.0)
    # The customer viewer should only see the PUBLIC message event
    assert all(e.data.get("visibility") != "side" for e in events)


# ---- Group M: query_events (T1A.3 · TC-009~TC-011) ----


async def test_tc_query_events_limit(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-009: query_events with limit returns at most N events."""
    conv = await engine.create_conversation(channel="web", external_id="qe1")
    await engine.join(conv.id, participant_customer)
    for i in range(10):
        await engine.send_message(conv.id, source=participant_customer.id, content=f"q{i}")
    events = await engine.query_events(conv.id, limit=5)
    assert len(events) == 5
    # Should be ordered by sequence_number
    seqs = [e.sequence_number for e in events]
    assert seqs == sorted(seqs)


async def test_tc_query_events_type_filter(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    """TC-010: query_events with types filter."""
    conv = await engine.create_conversation(channel="web", external_id="qe2")
    await engine.join(conv.id, participant_customer)
    await engine.join(conv.id, participant_operator)
    await engine.send_message(conv.id, source=participant_customer.id, content="msg")
    await engine.switch_mode(
        conv.id, ConversationMode.TAKEOVER,
        triggered_by=participant_operator.id, trigger="/hijack",
    )
    events = await engine.query_events(conv.id, types=["mode.changed"])
    assert all(e.type == "mode.changed" for e in events)
    assert len(events) >= 1


async def test_tc_query_events_since_and_until(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-011: query_events with since_sequence + until combo."""
    conv = await engine.create_conversation(channel="web", external_id="qe3")
    await engine.join(conv.id, participant_customer)
    for i in range(5):
        await engine.send_message(conv.id, source=participant_customer.id, content=f"t{i}")
    all_events = await engine.query_events(conv.id)
    if len(all_events) >= 4:
        cutoff_time = all_events[-1].timestamp
        events = await engine.query_events(
            conv.id, since_sequence=2, until=cutoff_time,
        )
        assert all(e.sequence_number > 2 for e in events)
        assert all(e.timestamp <= cutoff_time for e in events)


# ---- Group N: Plugin Hook dispatch (T1A.3 · TC-013~TC-016, TC-021~TC-023) ----


class _RecordingHook:
    """Test helper: records all hook calls."""

    def __init__(self):
        self.events: list = []
        self.conversations_created: list = []
        self.conversations_closed: list = []
        self.mode_changes: list = []
        self.participants_joined: list = []

    async def on_event(self, event):
        self.events.append(event)

    async def on_conversation_created(self, conv):
        self.conversations_created.append(conv)

    async def on_conversation_closed(self, conv):
        self.conversations_closed.append(conv)

    async def on_mode_changed(self, conv, old_mode, new_mode, trigger):
        self.mode_changes.append((conv, old_mode, new_mode, trigger))

    async def on_participant_joined(self, conv, p):
        self.participants_joined.append((conv, p))

    async def on_timer_expired(self, conv, timer):
        pass  # not tested here


class _FailingHook:
    """Test helper: on_event always raises."""

    async def on_event(self, event):
        raise RuntimeError("hook deliberately fails")

    async def on_conversation_created(self, conv):
        pass

    async def on_conversation_closed(self, conv):
        pass

    async def on_mode_changed(self, conv, old_mode, new_mode, trigger):
        pass

    async def on_participant_joined(self, conv, p):
        pass

    async def on_timer_expired(self, conv, timer):
        pass


async def test_tc_hook_on_event(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-013: on_event is called for every emitted event."""
    hook = _RecordingHook()
    engine.register_hook(hook)
    conv = await engine.create_conversation(channel="web", external_id="hk1")
    await engine.join(conv.id, participant_customer)
    await engine.send_message(conv.id, source=participant_customer.id, content="hi")
    assert len(hook.events) > 0
    assert any(e.type == "message.sent" for e in hook.events)


async def test_tc_hook_on_conversation_created(engine: LocalEngine) -> None:
    """TC-014: on_conversation_created fires on create_conversation."""
    hook = _RecordingHook()
    engine.register_hook(hook)
    await engine.create_conversation(channel="web", external_id="hk2")
    assert len(hook.conversations_created) == 1
    assert hook.conversations_created[0].id == "web_hk2"


async def test_tc_hook_on_mode_changed(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    """TC-015: on_mode_changed fires with correct old/new mode."""
    hook = _RecordingHook()
    engine.register_hook(hook)
    conv = await engine.create_conversation(channel="web", external_id="hk3")
    await engine.join(conv.id, participant_customer)
    await engine.join(conv.id, participant_operator)  # auto → copilot
    assert len(hook.mode_changes) >= 1
    _, old, new, trigger = hook.mode_changes[0]
    assert old == ConversationMode.AUTO
    assert new == ConversationMode.COPILOT


async def test_tc_hook_exception_isolation(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-016: Hook exception is swallowed + hook.failed event emitted."""
    failing = _FailingHook()
    engine.register_hook(failing)
    conv = await engine.create_conversation(channel="web", external_id="hk4")
    await engine.join(conv.id, participant_customer)
    # This should NOT raise despite the failing hook
    msg = await engine.send_message(conv.id, source=participant_customer.id, content="safe")
    assert msg.content == "safe"
    # Check hook.failed event was emitted
    events = await engine.query_events(conv.id, types=["hook.failed"])
    assert len(events) > 0


async def test_tc_hook_on_conversation_closed(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-021: on_conversation_closed fires on close_conversation."""
    hook = _RecordingHook()
    engine.register_hook(hook)
    conv = await engine.create_conversation(channel="web", external_id="hk5")
    await engine.join(conv.id, participant_customer)
    await engine.close_conversation(conv.id, outcome=Outcome.RESOLVED, resolved_by="op")
    assert len(hook.conversations_closed) == 1


async def test_tc_hook_on_participant_joined(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-022: on_participant_joined fires on join."""
    hook = _RecordingHook()
    engine.register_hook(hook)
    conv = await engine.create_conversation(channel="web", external_id="hk6")
    await engine.join(conv.id, participant_customer)
    assert len(hook.participants_joined) == 1
    _, p = hook.participants_joined[0]
    assert p.id == participant_customer.id


async def test_tc_hook_multi_hook_isolation(
    engine: LocalEngine, participant_customer: Participant,
) -> None:
    """TC-023: Multiple hooks — one failure doesn't block the other."""
    good_hook = _RecordingHook()
    bad_hook = _FailingHook()
    engine.register_hook(good_hook)
    engine.register_hook(bad_hook)
    conv = await engine.create_conversation(channel="web", external_id="hk7")
    await engine.join(conv.id, participant_customer)
    await engine.send_message(conv.id, source=participant_customer.id, content="test")
    # good_hook should have received events despite bad_hook failing
    assert len(good_hook.events) > 0
    assert any(e.type == "message.sent" for e in good_hook.events)


# ---- Preserved structural checks from T0.4 ----


def test_tc023_no_autoservice_engine_dir() -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    assert not (repo_root / "autoservice" / "engine").exists()


def test_tc024_no_enum_redefinition_in_local_engine() -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    source = (repo_root / "autoservice" / "conversation_engine" / "local_engine.py").read_text(encoding="utf-8")
    forbidden = ["class Mode", "class Visibility", "class ConversationMode",
                 "class MessageVisibility", "class EventType", "class ParticipantRole",
                 "class Outcome", "class ConversationState"]
    assert not [tok for tok in forbidden if tok in source]


def test_tc025_init_exports() -> None:
    from autoservice import conversation_engine as ce
    assert "LocalEngine" in ce.__all__
    assert ce.LocalEngine is LocalEngine
