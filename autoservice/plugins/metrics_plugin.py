"""Metrics plugin — collects in-memory operational counters (T1A.8).

Implements the PluginHook protocol to track conversation lifecycle,
mode changes, CSAT scores, and message counts.
"""

from __future__ import annotations

from autoservice.conversation_engine.events import EventType
from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    Event,
    Participant,
    Timer,
)


class MetricsPlugin:
    """In-memory metrics collector implementing PluginHook."""

    def __init__(self) -> None:
        self.conversations_created: int = 0
        self.conversations_closed: int = 0
        self.mode_changes: dict[str, int] = {}
        self.csat_scores: list[int] = []
        self.messages_sent: int = 0

    # -- PluginHook callbacks --

    async def on_conversation_created(self, conv: Conversation) -> None:
        self.conversations_created += 1

    async def on_conversation_closed(self, conv: Conversation) -> None:
        self.conversations_closed += 1

    async def on_mode_changed(
        self,
        conv: Conversation,
        old_mode: ConversationMode,
        new_mode: ConversationMode,
        trigger: str,
    ) -> None:
        key = f"{old_mode.value}\u2192{new_mode.value}"
        self.mode_changes[key] = self.mode_changes.get(key, 0) + 1

    async def on_participant_joined(self, conv: Conversation, p: Participant) -> None:
        pass  # not tracked

    async def on_timer_expired(self, conv: Conversation, timer: Timer) -> None:
        pass  # not tracked

    async def on_event(self, event: Event) -> None:
        if event.type == EventType.CONVERSATION_CSAT_RECORDED:
            score = event.data.get("score")
            if score is not None:
                self.csat_scores.append(score)
        elif event.type == EventType.MESSAGE_SENT:
            self.messages_sent += 1

    # -- Public API --

    def get_metrics(self) -> dict:
        """Return a snapshot of all collected counters."""
        return {
            "conversations_created": self.conversations_created,
            "conversations_closed": self.conversations_closed,
            "mode_changes": dict(self.mode_changes),
            "csat_scores": list(self.csat_scores),
            "messages_sent": self.messages_sent,
        }

    def reset(self) -> None:
        """Clear all counters."""
        self.conversations_created = 0
        self.conversations_closed = 0
        self.mode_changes.clear()
        self.csat_scores.clear()
        self.messages_sent = 0
