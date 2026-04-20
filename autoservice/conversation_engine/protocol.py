"""ConversationEngine Protocol v1.0 (frozen 2026-04-15).

See docs/contracts/conversation-engine.md §3 for the authoritative spec.
All methods are async. Error semantics see §6. Invariants see §7.1.
"""

from datetime import datetime
from typing import Any, AsyncIterator, Mapping, Protocol

from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    Message,
    MessageVisibility,
    Outcome,
    Participant,
    ParticipantRole,
    Timer,
    Event,
)


class ConversationEngine(Protocol):
    """Path B core contract. LocalEngine (M0-M4) and ZchatEngine (M5+) both implement."""

    # ---------- Conversation lifecycle ----------

    async def create_conversation(
        self,
        *,
        channel: str,
        external_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Conversation: ...

    async def get_conversation(self, conversation_id: str) -> Conversation:
        """找不到时抛 ConversationNotFound（不返回 None）。"""
        ...

    async def list_active_conversations(
        self,
        *,
        operator_id: str | None = None,
        squad_id: str | None = None,
    ) -> list[Conversation]: ...

    async def list_conversations_in_takeover_by(self, operator_id: str) -> list[Conversation]: ...

    async def close_conversation(
        self,
        conversation_id: str,
        *,
        outcome: Outcome,
        resolved_by: str,
        reason: str | None = None,
    ) -> Conversation: ...

    async def set_csat(self, conversation_id: str, score: int) -> None: ...

    # ---------- Participants ----------

    async def join(self, conversation_id: str, participant: Participant) -> None: ...

    async def leave(self, conversation_id: str, participant_id: str) -> None: ...

    # ---------- Mode ----------

    async def switch_mode(
        self,
        conversation_id: str,
        target: ConversationMode,
        *,
        triggered_by: str,
        trigger: str,
    ) -> None: ...

    # ---------- Messages ----------

    async def send_message(
        self,
        conversation_id: str,
        *,
        source: str,
        content: str,
        requested_visibility: MessageVisibility = MessageVisibility.PUBLIC,
        metadata: Mapping[str, Any] | None = None,
    ) -> Message: ...

    async def edit_message(
        self,
        conversation_id: str,
        message_id: str,
        *,
        new_content: str,
        edited_by: str,
    ) -> Message: ...

    async def delete_message(
        self,
        conversation_id: str,
        message_id: str,
        *,
        deleted_by: str,
    ) -> None: ...

    async def get_messages(
        self,
        conversation_id: str,
        *,
        since_sequence: int | None = None,
        before_sequence: int | None = None,
        until: datetime | None = None,
        viewer_role: ParticipantRole | None = None,
        limit: int = 50,
    ) -> list[Message]: ...

    # ---------- Commands ----------

    async def handle_command(
        self,
        conversation_id: str,
        *,
        actor_id: str,
        command: str,
        args: Mapping[str, Any] | None = None,
    ) -> None: ...

    # ---------- Timers ----------

    async def set_timer(
        self,
        conversation_id: str,
        name: str,
        duration_ms: int,
        *,
        on_expire: Mapping[str, Any],
    ) -> Timer: ...

    async def cancel_timer(self, conversation_id: str, name: str) -> None: ...

    # ---------- Events ----------

    async def subscribe(
        self,
        *,
        conversation_id: str | None = None,
        squad_id: str | None = None,
        event_types: list[str] | None = None,
        since_sequence: int | str | None = None,
        viewer_role: ParticipantRole | None = None,
    ) -> AsyncIterator[Event]: ...

    async def query_events(
        self,
        conversation_id: str,
        *,
        since_sequence: int | None = None,
        until: datetime | None = None,
        types: list[str] | None = None,
        limit: int = 100,
    ) -> list[Event]: ...

    # ---------- Plugin hooks ----------

    def register_hook(self, hook: "PluginHook") -> None: ...


class PluginHook(Protocol):
    """App-layer extension points. All methods optional (None-safe by protocol)."""

    async def on_conversation_created(self, conv: Conversation) -> None: ...
    async def on_conversation_closed(self, conv: Conversation) -> None: ...
    async def on_mode_changed(
        self,
        conv: Conversation,
        old_mode: ConversationMode,
        new_mode: ConversationMode,
        trigger: str,
    ) -> None: ...
    async def on_participant_joined(self, conv: Conversation, p: Participant) -> None: ...
    async def on_timer_expired(self, conv: Conversation, timer: Timer) -> None: ...
    async def on_event(self, event: Event) -> None: ...
