"""Event type constants for ConversationEngine v1.0.

See docs/contracts/conversation-engine.md §5.
"""

from enum import Enum


class EventType(str, Enum):
    # Conversation lifecycle
    CONVERSATION_CREATED = "conversation.created"
    CONVERSATION_ACTIVATED = "conversation.activated"
    CONVERSATION_IDLED = "conversation.idled"
    CONVERSATION_REACTIVATED = "conversation.reactivated"
    CONVERSATION_CLOSED = "conversation.closed"
    CONVERSATION_RESOLVED = "conversation.resolved"
    CONVERSATION_CSAT_RECORDED = "conversation.csat_recorded"

    # Participants
    PARTICIPANT_JOINED = "participant.joined"
    PARTICIPANT_LEFT = "participant.left"

    # Mode
    MODE_CHANGED = "mode.changed"
    MODE_NOOP = "mode.noop"  # Q4: target == current

    # Messages
    MESSAGE_SENT = "message.sent"
    MESSAGE_GATED = "message.gated"
    MESSAGE_EDITED = "message.edited"
    MESSAGE_DELETED = "message.deleted"

    # Timers
    TIMER_SET = "timer.set"
    TIMER_EXPIRED = "timer.expired"
    TIMER_CANCELLED = "timer.cancelled"

    # SLA
    SLA_BREACH = "sla.breach"

    # Squad (M3+)
    SQUAD_ASSIGNED = "squad.assigned"
    SQUAD_REASSIGNED = "squad.reassigned"

    # Plugin isolation (Q8c)
    HOOK_FAILED = "hook.failed"


ALL_EVENT_TYPES: frozenset[str] = frozenset(e.value for e in EventType)
