"""LocalEngine skeleton (T0.4).

Protocol-compliant stub; all methods raise NotImplementedError with a
T1A.x / T2A.1 hint pointing to the Phase 1/2 task that will implement them.

See docs/contracts/conversation-engine.md for the authoritative spec
and autoservice/conversation_engine/protocol.py for the frozen Protocol.
"""

from datetime import datetime
from typing import Any, AsyncIterator, Mapping

from autoservice.conversation_engine.protocol import PluginHook
from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    Event,
    Message,
    MessageVisibility,
    Outcome,
    Participant,
    ParticipantRole,
    Timer,
)


class LocalEngine:
    """In-process ConversationEngine implementation (M0-M4).

    T0.4 ships the skeleton only; every method raises NotImplementedError.
    Phase 1 (T1A.1-3, T1A.7) and Phase 2 (T2A.1) replace the bodies.
    """

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self._config = dict(config or {})

    # ---------- Conversation lifecycle ----------

    async def create_conversation(
        self,
        *,
        channel: str,
        external_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Conversation:
        raise NotImplementedError("T1A.1 (lifecycle): conversation lifecycle")

    async def get_conversation(self, conversation_id: str) -> Conversation:
        raise NotImplementedError("T1A.1 (lifecycle): conversation lifecycle")

    async def list_active_conversations(
        self,
        *,
        operator_id: str | None = None,
        squad_id: str | None = None,
    ) -> list[Conversation]:
        raise NotImplementedError("T1A.1 (lifecycle): conversation lifecycle")

    async def close_conversation(
        self,
        conversation_id: str,
        *,
        outcome: Outcome,
        resolved_by: str,
        reason: str | None = None,
    ) -> Conversation:
        raise NotImplementedError("T1A.1 (lifecycle): conversation lifecycle")

    async def set_csat(self, conversation_id: str, score: int) -> None:
        raise NotImplementedError("T1A.1 (lifecycle): conversation lifecycle")

    # ---------- Participants ----------

    async def join(self, conversation_id: str, participant: Participant) -> None:
        raise NotImplementedError("T1A.1 (participant): participant management")

    async def leave(self, conversation_id: str, participant_id: str) -> None:
        raise NotImplementedError("T1A.1 (participant): participant management")

    # ---------- Mode ----------

    async def switch_mode(
        self,
        conversation_id: str,
        target: ConversationMode,
        *,
        triggered_by: str,
        trigger: str,
    ) -> None:
        raise NotImplementedError("T1A.1 (mode): mode transition")

    # ---------- Messages ----------

    async def send_message(
        self,
        conversation_id: str,
        *,
        source: str,
        content: str,
        requested_visibility: MessageVisibility = MessageVisibility.PUBLIC,
        metadata: Mapping[str, Any] | None = None,
    ) -> Message:
        raise NotImplementedError("T1A.1 (messages): message CRUD")

    async def edit_message(
        self,
        conversation_id: str,
        message_id: str,
        *,
        new_content: str,
        edited_by: str,
    ) -> Message:
        raise NotImplementedError("T1A.1 (messages): message CRUD")

    async def delete_message(
        self,
        conversation_id: str,
        message_id: str,
        *,
        deleted_by: str,
    ) -> None:
        raise NotImplementedError("T1A.1 (messages): message CRUD")

    async def get_messages(
        self,
        conversation_id: str,
        *,
        since_sequence: int | None = None,
        before_sequence: int | None = None,
        until: datetime | None = None,
        viewer_role: ParticipantRole | None = None,
        limit: int = 50,
    ) -> list[Message]:
        raise NotImplementedError("T1A.1 (messages): message CRUD")

    # ---------- Commands ----------

    async def handle_command(
        self,
        conversation_id: str,
        *,
        actor_id: str,
        command: str,
        args: Mapping[str, Any] | None = None,
    ) -> None:
        raise NotImplementedError("T2A.1: command dispatch")

    # ---------- Timers ----------

    async def set_timer(
        self,
        conversation_id: str,
        name: str,
        duration_ms: int,
        *,
        on_expire: Mapping[str, Any],
    ) -> Timer:
        raise NotImplementedError("T1A.2: timer scheduling")

    async def cancel_timer(self, conversation_id: str, name: str) -> None:
        raise NotImplementedError("T1A.2: timer scheduling")

    # ---------- Events ----------

    async def subscribe(
        self,
        *,
        conversation_id: str | None = None,
        squad_id: str | None = None,
        event_types: list[str] | None = None,
        since_sequence: int | str | None = None,
        viewer_role: ParticipantRole | None = None,
    ) -> AsyncIterator[Event]:
        raise NotImplementedError("T1A.3: event bus")
        yield  # pragma: no cover -- makes this an async generator for typing

    async def query_events(
        self,
        conversation_id: str,
        *,
        since_sequence: int | None = None,
        until: datetime | None = None,
        types: list[str] | None = None,
        limit: int = 100,
    ) -> list[Event]:
        raise NotImplementedError("T1A.3: event bus")

    # ---------- Plugin hooks ----------

    def register_hook(self, hook: PluginHook) -> None:
        raise NotImplementedError("T1A.3 (hooks): plugin hook registry")
