"""T1A.2 LocalEngine Timer tests (test-plan-T1A.2 · TC-001 ~ TC-012).

Tests for set_timer / cancel_timer / timer expiration / on_expire actions.
Written TDD-style: tests first, implementation follows.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice.conversation_engine import (
    ConversationAlreadyClosed,
    ConversationMode,
    EventType,
    LocalEngine,
    MessageVisibility,
    Outcome,
    Participant,
    ParticipantRole,
    Timer,
    ValidationError,
)


# ---- Helpers ----


async def _make_active_conv(engine: LocalEngine, ext_id: str, participant: Participant) -> str:
    """Create a conversation and join participant to make it usable."""
    conv = await engine.create_conversation(channel="web", external_id=ext_id)
    await engine.join(conv.id, participant)
    return conv.id


# ---- TC-001: set_timer basic creation + timer.set event ----


async def test_tc001_set_timer_basic(engine: LocalEngine, participant_customer: Participant) -> None:
    conv_id = await _make_active_conv(engine, "timer_001", participant_customer)

    timer = await engine.set_timer(
        conv_id, "sla_onboard", 3000,
        on_expire={"type": "callback", "params": {}},
    )

    assert isinstance(timer, Timer)
    assert timer.name == "sla_onboard"
    assert timer.duration_ms == 3000
    assert timer.conversation_id == conv_id
    assert timer.cancelled is False

    events = await engine.query_events(conv_id, types=[EventType.TIMER_SET])
    assert len(events) >= 1
    assert events[-1].data["name"] == "sla_onboard"
    assert events[-1].data["duration_ms"] == 3000


# ---- TC-002: set_timer expiration fires timer.expired ----


async def test_tc002_timer_expired(engine: LocalEngine, participant_customer: Participant) -> None:
    conv_id = await _make_active_conv(engine, "timer_002", participant_customer)

    await engine.set_timer(
        conv_id, "test_short", 50,
        on_expire={"type": "callback", "params": {}},
    )
    await asyncio.sleep(0.15)

    events = await engine.query_events(conv_id, types=[EventType.TIMER_EXPIRED])
    assert len(events) == 1
    assert events[0].data["name"] == "test_short"


# ---- TC-003: cancel_timer normal cancellation ----


async def test_tc003_cancel_timer(engine: LocalEngine, participant_customer: Participant) -> None:
    conv_id = await _make_active_conv(engine, "timer_003", participant_customer)

    await engine.set_timer(
        conv_id, "idle_timeout", 5000,
        on_expire={"type": "callback", "params": {}},
    )
    await engine.cancel_timer(conv_id, "idle_timeout")
    await asyncio.sleep(0.1)

    cancelled = await engine.query_events(conv_id, types=[EventType.TIMER_CANCELLED])
    assert len(cancelled) == 1
    assert cancelled[0].data["name"] == "idle_timeout"

    expired = await engine.query_events(conv_id, types=[EventType.TIMER_EXPIRED])
    assert len(expired) == 0


# ---- TC-004: cancel_timer idempotent (nonexistent) ----


async def test_tc004_cancel_timer_idempotent(engine: LocalEngine, participant_customer: Participant) -> None:
    conv_id = await _make_active_conv(engine, "timer_004", participant_customer)

    # Should not raise
    await engine.cancel_timer(conv_id, "nonexistent")

    cancelled = await engine.query_events(conv_id, types=[EventType.TIMER_CANCELLED])
    assert len(cancelled) == 0


# ---- TC-005: set_timer override (same name replaces) ----


async def test_tc005_set_timer_override(engine: LocalEngine, participant_customer: Participant) -> None:
    conv_id = await _make_active_conv(engine, "timer_005", participant_customer)

    await engine.set_timer(
        conv_id, "idle_timeout", 5000,
        on_expire={"type": "callback", "params": {}},
    )
    await engine.set_timer(
        conv_id, "idle_timeout", 80,
        on_expire={"type": "callback", "params": {}},
    )
    await asyncio.sleep(0.2)

    set_events = await engine.query_events(conv_id, types=[EventType.TIMER_SET])
    assert len(set_events) == 2  # old + new

    expired = await engine.query_events(conv_id, types=[EventType.TIMER_EXPIRED])
    assert len(expired) == 1  # only new timer expired

    # D2: no timer.cancelled event on override
    cancelled = await engine.query_events(conv_id, types=[EventType.TIMER_CANCELLED])
    assert len(cancelled) == 0


# ---- TC-006: on_expire mode_change action ----


async def test_tc006_on_expire_mode_change(
    engine: LocalEngine,
    participant_customer: Participant,
    participant_operator: Participant,
) -> None:
    conv_id = await _make_active_conv(engine, "timer_006", participant_customer)
    await engine.join(conv_id, participant_operator)
    # now in copilot mode

    await engine.set_timer(
        conv_id, "takeover_wait", 50,
        on_expire={
            "type": "mode_change",
            "params": {
                "target": "takeover",
                "triggered_by": "__system__",
                "trigger": "auto:takeover_wait_expired",
            },
        },
    )
    await asyncio.sleep(0.15)

    conv = await engine.get_conversation(conv_id)
    assert conv.mode == ConversationMode.TAKEOVER

    expired = await engine.query_events(conv_id, types=[EventType.TIMER_EXPIRED])
    assert len(expired) == 1

    mode_events = await engine.query_events(conv_id, types=[EventType.MODE_CHANGED])
    mode_to_takeover = [e for e in mode_events if e.data.get("new_mode") == "takeover"
                        and e.data.get("trigger") == "auto:takeover_wait_expired"]
    assert len(mode_to_takeover) == 1


# ---- TC-007: on_expire system_message action ----


async def test_tc007_on_expire_system_message(
    engine: LocalEngine,
    participant_customer: Participant,
) -> None:
    conv_id = await _make_active_conv(engine, "timer_007", participant_customer)

    await engine.set_timer(
        conv_id, "sla_onboard", 50,
        on_expire={
            "type": "system_message",
            "params": {"content": "SLA breach: onboard > 3s"},
        },
    )
    await asyncio.sleep(0.15)

    msgs = await engine.get_messages(conv_id)
    sys_msgs = [m for m in msgs if m.visibility == MessageVisibility.SYSTEM]
    assert len(sys_msgs) >= 1
    assert any("SLA breach" in m.content for m in sys_msgs)


# ---- TC-008: on_expire callback action (PluginHook) ----


async def test_tc008_on_expire_callback(
    engine: LocalEngine,
    participant_customer: Participant,
) -> None:
    conv_id = await _make_active_conv(engine, "timer_008", participant_customer)

    mock_hook = MagicMock()
    mock_hook.on_timer_expired = AsyncMock()
    engine.register_hook(mock_hook)

    await engine.set_timer(
        conv_id, "test_cb", 50,
        on_expire={"type": "callback", "params": {}},
    )
    await asyncio.sleep(0.15)

    mock_hook.on_timer_expired.assert_called_once()
    call_args = mock_hook.on_timer_expired.call_args
    assert call_args[0][0].id == conv_id  # conversation
    assert call_args[0][1].name == "test_cb"  # timer


# ---- TC-009: close_conversation auto-cancels all timers ----


async def test_tc009_close_cancels_timers(
    engine: LocalEngine,
    participant_customer: Participant,
) -> None:
    conv_id = await _make_active_conv(engine, "timer_009", participant_customer)

    await engine.set_timer(conv_id, "idle_timeout", 5000, on_expire={"type": "callback", "params": {}})
    await engine.set_timer(conv_id, "close_timeout", 10000, on_expire={"type": "callback", "params": {}})

    await engine.close_conversation(conv_id, outcome=Outcome.RESOLVED, resolved_by="op")
    await asyncio.sleep(0.1)

    expired = await engine.query_events(conv_id, types=[EventType.TIMER_EXPIRED])
    assert len(expired) == 0


# ---- TC-010: set_timer on closed conversation raises ----


async def test_tc010_set_timer_closed_conv(
    engine: LocalEngine,
    participant_customer: Participant,
) -> None:
    conv_id = await _make_active_conv(engine, "timer_010", participant_customer)
    await engine.close_conversation(conv_id, outcome=Outcome.RESOLVED, resolved_by="op")

    with pytest.raises((ConversationAlreadyClosed, ValidationError)):
        await engine.set_timer(
            conv_id, "test", 1000,
            on_expire={"type": "callback", "params": {}},
        )


# ---- TC-011: sla_* timer expired emits sla.breach ----


async def test_tc011_sla_breach_event(
    engine: LocalEngine,
    participant_customer: Participant,
) -> None:
    conv_id = await _make_active_conv(engine, "timer_011", participant_customer)

    await engine.set_timer(
        conv_id, "sla_onboard", 50,
        on_expire={"type": "callback", "params": {}},
    )
    await asyncio.sleep(0.15)

    breach = await engine.query_events(conv_id, types=[EventType.SLA_BREACH])
    assert len(breach) == 1
    assert breach[0].data["name"] == "sla_onboard"


# ---- TC-012: cancelled timer does not fire ----


async def test_tc012_cancelled_timer_no_fire(
    engine: LocalEngine,
    participant_customer: Participant,
) -> None:
    conv_id = await _make_active_conv(engine, "timer_012", participant_customer)

    await engine.set_timer(
        conv_id, "short", 80,
        on_expire={"type": "callback", "params": {}},
    )
    await engine.cancel_timer(conv_id, "short")
    await asyncio.sleep(0.2)

    expired = await engine.query_events(conv_id, types=[EventType.TIMER_EXPIRED])
    assert len(expired) == 0
