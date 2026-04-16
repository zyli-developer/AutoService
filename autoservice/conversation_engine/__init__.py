"""ConversationEngine contract v1.0 (frozen 2026-04-15).

See docs/contracts/conversation-engine.md for the authoritative spec.
All implementations (LocalEngine, ZchatEngine) must satisfy the Protocol
defined here and pass tests in tests/contract/.
"""

from autoservice.conversation_engine.errors import (
    ConversationAlreadyClosed,
    ConversationNotFound,
    EngineError,
    IllegalModeTransition,
    PermissionDenied,
    TimerNotFound,
    UnknownParticipant,
    ValidationError,
)
from autoservice.conversation_engine.event_bus import EventBus
from autoservice.conversation_engine.events import EventType
from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.protocol import ConversationEngine, PluginHook
from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    ConversationState,
    Event,
    Message,
    MessageVisibility,
    Outcome,
    Participant,
    ParticipantRole,
    Resolution,
    Timer,
)

__all__ = [
    "ConversationEngine",
    "EventBus",
    "LocalEngine",
    "PluginHook",
    "Conversation",
    "ConversationMode",
    "ConversationState",
    "Event",
    "EventType",
    "Message",
    "MessageVisibility",
    "Outcome",
    "Participant",
    "ParticipantRole",
    "Resolution",
    "Timer",
    "EngineError",
    "ConversationNotFound",
    "ConversationAlreadyClosed",
    "IllegalModeTransition",
    "PermissionDenied",
    "TimerNotFound",
    "UnknownParticipant",
    "ValidationError",
]

CONTRACT_VERSION = "1.0"
