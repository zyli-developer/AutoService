"""§2 value objects — pure-data tests, no engine needed."""

from dataclasses import FrozenInstanceError

import pytest

from autoservice.conversation_engine import (
    CONTRACT_VERSION,
    Conversation,
    ConversationMode,
    ConversationState,
    EventType,
    Message,
    MessageVisibility,
    Outcome,
    ParticipantRole,
)
from autoservice.conversation_engine.types import TIMER_DEFAULTS_MS


def test_contract_version_is_frozen():
    assert CONTRACT_VERSION == "1.0"


def test_conversation_state_values():
    assert {s.value for s in ConversationState} == {"created", "active", "idle", "closed"}


def test_conversation_mode_values():
    assert {m.value for m in ConversationMode} == {"auto", "copilot", "takeover"}


def test_participant_role_values():
    assert {r.value for r in ParticipantRole} == {
        "customer",
        "agent",
        "operator",
        "observer",
    }


def test_message_visibility_values():
    assert {v.value for v in MessageVisibility} == {"public", "side", "system"}


def test_outcome_values():
    assert {o.value for o in Outcome} == {"resolved", "abandoned", "escalated"}


def test_timer_defaults_match_spec():
    # §2.3 table
    assert TIMER_DEFAULTS_MS["sla_onboard"] == 3_000
    assert TIMER_DEFAULTS_MS["sla_placeholder"] == 1_000
    assert TIMER_DEFAULTS_MS["sla_slow_query"] == 15_000
    assert TIMER_DEFAULTS_MS["sla_first_reply"] == 60_000
    assert TIMER_DEFAULTS_MS["takeover_wait"] == 180_000
    assert TIMER_DEFAULTS_MS["idle_timeout"] == 300_000
    assert TIMER_DEFAULTS_MS["close_timeout"] == 3_600_000


def test_message_is_frozen():
    from datetime import datetime, timezone

    m = Message(
        id="01HX",
        conversation_id="web_sess_x",
        source="cust_1",
        content="hi",
        visibility=MessageVisibility.PUBLIC,
        timestamp=datetime.now(timezone.utc),
    )
    with pytest.raises(FrozenInstanceError):
        m.content = "edited"  # type: ignore[misc]


def test_conversation_participants_is_tuple():
    """Per §2.2, participants is tuple (immutable)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    c = Conversation(
        id="web_x",
        state=ConversationState.ACTIVE,
        mode=ConversationMode.AUTO,
        participants=(),
        created_at=now,
        updated_at=now,
    )
    assert isinstance(c.participants, tuple)


def test_event_types_include_mode_noop_and_hook_failed():
    # Q4 / Q8c additions
    assert EventType.MODE_NOOP.value == "mode.noop"
    assert EventType.HOOK_FAILED.value == "hook.failed"


def test_all_event_types_namespaced():
    """Every event type must be in `{domain}.{action}` form."""
    for e in EventType:
        assert "." in e.value, f"{e.value} not namespaced"
