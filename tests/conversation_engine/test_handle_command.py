"""T2A.1 handle_command tests (test-plan-T2A.1 · TC-001 ~ TC-014).

Tests for command dispatch, permission checks, and edge cases.
"""

from __future__ import annotations

import pytest

from autoservice.conversation_engine import (
    ConversationMode,
    ConversationState,
    EventType,
    IllegalModeTransition,
    LocalEngine,
    Outcome,
    Participant,
    ParticipantRole,
    PermissionDenied,
    UnknownParticipant,
    ValidationError,
)


# ---- Helpers ----


async def _setup_conv_with_roles(
    engine: LocalEngine,
    ext_id: str,
    *participants: Participant,
) -> str:
    conv = await engine.create_conversation(channel="web", external_id=ext_id)
    for p in participants:
        await engine.join(conv.id, p)
    return conv.id


# ---- TC-001: /hijack normal ----


async def test_tc001_hijack(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_001", participant_customer, participant_operator)
    # now copilot (operator join auto → copilot)

    await engine.handle_command(conv_id, actor_id=participant_operator.id, command="/hijack")

    conv = await engine.get_conversation(conv_id)
    assert conv.mode == ConversationMode.TAKEOVER


# ---- TC-002: /release normal ----


async def test_tc002_release(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_002", participant_customer, participant_operator)
    await engine.switch_mode(conv_id, ConversationMode.TAKEOVER, triggered_by=participant_operator.id, trigger="/hijack")

    await engine.handle_command(conv_id, actor_id=participant_operator.id, command="/release")

    conv = await engine.get_conversation(conv_id)
    assert conv.mode == ConversationMode.AUTO


# ---- TC-003: /copilot normal ----


async def test_tc003_copilot(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_003", participant_customer, participant_operator)
    # switch to auto first, then /copilot back
    await engine.switch_mode(conv_id, ConversationMode.AUTO, triggered_by=participant_operator.id, trigger="test")

    await engine.handle_command(conv_id, actor_id=participant_operator.id, command="/copilot")

    conv = await engine.get_conversation(conv_id)
    assert conv.mode == ConversationMode.COPILOT


# ---- TC-004: /resolve normal ----


async def test_tc004_resolve(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_004", participant_customer, participant_operator)

    await engine.handle_command(conv_id, actor_id=participant_operator.id, command="/resolve")

    conv = await engine.get_conversation(conv_id)
    assert conv.state == ConversationState.CLOSED
    assert conv.resolution is not None
    assert conv.resolution.outcome == Outcome.RESOLVED


# ---- TC-005: /abandon normal ----


async def test_tc005_abandon(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_005", participant_customer, participant_operator)

    await engine.handle_command(conv_id, actor_id=participant_operator.id, command="/abandon")

    conv = await engine.get_conversation(conv_id)
    assert conv.state == ConversationState.CLOSED
    assert conv.resolution.outcome == Outcome.ABANDONED


# ---- TC-006: /status read-only ----


async def test_tc006_status(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_006", participant_customer, participant_operator)
    conv_before = await engine.get_conversation(conv_id)

    await engine.handle_command(conv_id, actor_id=participant_operator.id, command="/status")

    conv_after = await engine.get_conversation(conv_id)
    assert conv_after.state == conv_before.state
    assert conv_after.mode == conv_before.mode


# ---- TC-007: customer → PermissionDenied ----


async def test_tc007_customer_permission_denied(
    engine: LocalEngine,
    participant_customer: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_007", participant_customer)

    with pytest.raises(PermissionDenied):
        await engine.handle_command(conv_id, actor_id=participant_customer.id, command="/hijack")


# ---- TC-008: agent → PermissionDenied ----


async def test_tc008_agent_permission_denied(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_agent: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_008", participant_customer, participant_agent)

    with pytest.raises(PermissionDenied):
        await engine.handle_command(conv_id, actor_id=participant_agent.id, command="/resolve")


# ---- TC-009: mode no-op (Q4) ----


async def test_tc009_mode_noop(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_009", participant_customer, participant_operator)
    # now copilot; /copilot again → noop

    await engine.handle_command(conv_id, actor_id=participant_operator.id, command="/copilot")

    events = await engine.query_events(conv_id, types=[EventType.MODE_NOOP])
    assert any(e.type == EventType.MODE_NOOP for e in events)


# ---- TC-010: unknown command → ValidationError ----


async def test_tc010_unknown_command(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_010", participant_customer, participant_operator)

    with pytest.raises(ValidationError):
        await engine.handle_command(conv_id, actor_id=participant_operator.id, command="/unknown")


# ---- TC-011: /resolve on already closed (idempotent) ----


async def test_tc011_resolve_closed_idempotent(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_011", participant_customer, participant_operator)
    await engine.close_conversation(conv_id, outcome=Outcome.RESOLVED, resolved_by="op")

    # Should not raise
    await engine.handle_command(conv_id, actor_id=participant_operator.id, command="/resolve")


# ---- TC-012: /hijack on closed conv ----


async def test_tc012_hijack_closed(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_012", participant_customer, participant_operator)
    await engine.close_conversation(conv_id, outcome=Outcome.RESOLVED, resolved_by="op")

    with pytest.raises(IllegalModeTransition):
        await engine.handle_command(conv_id, actor_id=participant_operator.id, command="/hijack")


# ---- TC-013: unknown participant ----


async def test_tc013_unknown_participant(
    engine: LocalEngine,
    participant_customer: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_013", participant_customer)

    with pytest.raises(UnknownParticipant):
        await engine.handle_command(conv_id, actor_id="nobody", command="/status")


# ---- TC-014: /resolve with reason arg ----


async def test_tc014_resolve_with_reason(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    conv_id = await _setup_conv_with_roles(engine, "cmd_014", participant_customer, participant_operator)

    await engine.handle_command(
        conv_id, actor_id=participant_operator.id, command="/resolve",
        args={"reason": "customer satisfied"},
    )

    conv = await engine.get_conversation(conv_id)
    assert conv.state == ConversationState.CLOSED
    assert conv.resolution.outcome == Outcome.RESOLVED
