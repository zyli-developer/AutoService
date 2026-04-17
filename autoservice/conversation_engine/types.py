"""Value objects for ConversationEngine v1.0.

See docs/contracts/conversation-engine.md §2.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


class ConversationState(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    IDLE = "idle"
    CLOSED = "closed"


class ConversationMode(str, Enum):
    AUTO = "auto"
    COPILOT = "copilot"
    TAKEOVER = "takeover"


class ParticipantRole(str, Enum):
    CUSTOMER = "customer"
    AGENT = "agent"
    OPERATOR = "operator"
    OBSERVER = "observer"


class MessageVisibility(str, Enum):
    PUBLIC = "public"
    SIDE = "side"
    SYSTEM = "system"


class Outcome(str, Enum):
    RESOLVED = "resolved"
    ABANDONED = "abandoned"
    ESCALATED = "escalated"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Participant:
    id: str
    role: ParticipantRole
    joined_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    source: str
    content: str
    visibility: MessageVisibility
    timestamp: datetime
    edit_of: str | None = None
    sequence_number: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Resolution:
    outcome: Outcome
    resolved_by: str
    csat_score: int | None = None
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class Conversation:
    id: str
    state: ConversationState
    mode: ConversationMode
    participants: tuple[Participant, ...]
    created_at: datetime
    updated_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)
    resolution: Resolution | None = None
    takeover_operator_id: str | None = None


@dataclass(frozen=True)
class Event:
    id: str
    type: str
    conversation_id: str
    data: Mapping[str, Any]
    timestamp: datetime
    sequence_number: int = 0


@dataclass(frozen=True)
class Timer:
    conversation_id: str
    name: str
    duration_ms: int
    started_at: datetime
    cancelled: bool = False


TIMER_DEFAULTS_MS: Mapping[str, int] = {
    "sla_onboard": 3_000,
    "sla_placeholder": 1_000,
    "sla_slow_query": 15_000,
    "sla_first_reply": 60_000,
    "takeover_wait": 180_000,
    "idle_timeout": 300_000,
    "close_timeout": 3_600_000,
}
