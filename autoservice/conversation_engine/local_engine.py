"""LocalEngine — in-process ConversationEngine implementation (M0-M4).

T1A.1: Mode/Gate/lifecycle/participants/messages.
T1A.2 (Timer) and T1A.3 (full EventBus) remain NotImplementedError.
T2A.1 (handle_command) remains NotImplementedError.

Minimal event buffering (asyncio.Queue fan-out) is included so that
contract tests for mode.noop / message.gated can pass. T1A.3 will
replace this with a full EventBus + SQLite persistence.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Mapping

from autoservice.conversation_engine.errors import (
    ConversationAlreadyClosed,
    ConversationNotFound,
    IllegalModeTransition,
    UnknownParticipant,
    ValidationError,
)
from autoservice.conversation_engine.events import EventType
from autoservice.conversation_engine.protocol import PluginHook
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

# Gate matrix: (mode, sender_role) → should downgrade PUBLIC to SIDE?
_GATE_DOWNGRADE: frozenset[tuple[ConversationMode, ParticipantRole]] = frozenset(
    {
        (ConversationMode.COPILOT, ParticipantRole.OPERATOR),
        (ConversationMode.TAKEOVER, ParticipantRole.AGENT),
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _gen_id() -> str:
    return uuid.uuid4().hex


class LocalEngine:
    """In-process ConversationEngine implementation (M0-M4).

    All state is held in memory (dicts). No persistence — restart clears
    everything. T1A.3 adds SQLite event log; T1A.2 adds timer scheduling.
    """

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self._config = dict(config or {})
        # Core storage
        self._conversations: dict[str, Conversation] = {}
        self._participants: dict[str, list[Participant]] = {}  # conv_id → [Participant]
        self._messages: dict[str, list[Message]] = {}  # conv_id → [Message]
        self._seq: dict[str, int] = {}  # conv_id → next sequence number
        self._event_seq: dict[str, int] = {}  # conv_id → next event sequence
        # Mode serialization locks (§7.1 #3)
        self._mode_locks: dict[str, asyncio.Lock] = {}
        # Minimal event fan-out for subscribe() (replaced by T1A.3 EventBus)
        self._subscribers: list[asyncio.Queue[Event]] = []
        self._events: dict[str, list[Event]] = {}  # conv_id → [Event]
        # Plugin hooks (T1A.3 will expand)
        self._hooks: list[PluginHook] = []

    # ---- internal helpers ----

    def _get_conv(self, conversation_id: str) -> Conversation:
        conv = self._conversations.get(conversation_id)
        if conv is None:
            raise ConversationNotFound(conversation_id)
        return conv

    def _update_conv(self, conv_id: str, **kwargs: Any) -> Conversation:
        old = self._get_conv(conv_id)
        new = dataclasses.replace(old, updated_at=_now(), **kwargs)
        self._conversations[conv_id] = new
        return new

    def _next_seq(self, conv_id: str) -> int:
        self._seq[conv_id] = self._seq.get(conv_id, 0) + 1
        return self._seq[conv_id]

    def _next_event_seq(self, conv_id: str) -> int:
        self._event_seq[conv_id] = self._event_seq.get(conv_id, 0) + 1
        return self._event_seq[conv_id]

    def _emit(self, event_type: str, conv_id: str, data: dict[str, Any]) -> Event:
        ev = Event(
            id=_gen_id(),
            type=event_type,
            conversation_id=conv_id,
            data=data,
            timestamp=_now(),
            sequence_number=self._next_event_seq(conv_id),
        )
        self._events.setdefault(conv_id, []).append(ev)
        for q in self._subscribers:
            q.put_nowait(ev)
        return ev

    def _get_lock(self, conv_id: str) -> asyncio.Lock:
        if conv_id not in self._mode_locks:
            self._mode_locks[conv_id] = asyncio.Lock()
        return self._mode_locks[conv_id]

    async def _call_hooks(self, method_name: str, conv_id: str, *args: Any) -> None:
        """Call all registered hooks, swallowing exceptions (§7.1 #7)."""
        for hook in self._hooks:
            fn = getattr(hook, method_name, None)
            if fn is None:
                continue
            try:
                await fn(*args)
            except Exception as exc:
                self._emit(EventType.HOOK_FAILED, conv_id, {
                    "hook": type(hook).__name__,
                    "method": method_name,
                    "error": str(exc),
                })

    def _role_of(self, conv_id: str, participant_id: str) -> ParticipantRole:
        for p in self._participants.get(conv_id, []):
            if p.id == participant_id:
                return p.role
        raise UnknownParticipant(participant_id)

    def _apply_gate(
        self,
        mode: ConversationMode,
        sender_role: ParticipantRole,
        requested: MessageVisibility,
    ) -> MessageVisibility:
        """§4 Gate: only downgrades PUBLIC → SIDE. SIDE/SYSTEM pass through."""
        if requested != MessageVisibility.PUBLIC:
            return requested
        if (mode, sender_role) in _GATE_DOWNGRADE:
            return MessageVisibility.SIDE
        return MessageVisibility.PUBLIC

    # ---------- Conversation lifecycle ----------

    async def create_conversation(
        self,
        *,
        channel: str,
        external_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Conversation:
        conv_id = f"{channel}_{external_id}"
        existing = self._conversations.get(conv_id)
        if existing is not None and existing.state != ConversationState.CLOSED:
            return existing
        now = _now()
        conv = Conversation(
            id=conv_id,
            state=ConversationState.CREATED,
            mode=ConversationMode.AUTO,
            participants=(),
            created_at=now,
            updated_at=now,
            metadata=dict(metadata) if metadata else {},
        )
        self._conversations[conv_id] = conv
        self._participants[conv_id] = []
        self._messages[conv_id] = []
        self._events[conv_id] = []
        self._emit(EventType.CONVERSATION_CREATED, conv_id, {"channel": channel})
        await self._call_hooks("on_conversation_created", conv_id, conv)
        return conv

    async def get_conversation(self, conversation_id: str) -> Conversation:
        return self._get_conv(conversation_id)

    async def list_active_conversations(
        self,
        *,
        operator_id: str | None = None,
        squad_id: str | None = None,
    ) -> list[Conversation]:
        result = [
            c
            for c in self._conversations.values()
            if c.state != ConversationState.CLOSED
        ]
        if operator_id is not None:
            result = [
                c
                for c in result
                if any(
                    p.id == operator_id
                    for p in self._participants.get(c.id, [])
                )
            ]
        if squad_id is not None:
            result = [
                c
                for c in result
                if c.metadata.get("squad_id") == squad_id
            ]
        return result

    async def close_conversation(
        self,
        conversation_id: str,
        *,
        outcome: Outcome,
        resolved_by: str,
        reason: str | None = None,
    ) -> Conversation:
        conv = self._get_conv(conversation_id)
        if conv.state == ConversationState.CLOSED:
            return conv
        resolution = Resolution(outcome=outcome, resolved_by=resolved_by)
        conv = self._update_conv(
            conversation_id,
            state=ConversationState.CLOSED,
            resolution=resolution,
        )
        self._emit(EventType.CONVERSATION_RESOLVED, conversation_id, {
            "outcome": outcome.value, "resolved_by": resolved_by,
        })
        self._emit(EventType.CONVERSATION_CLOSED, conversation_id, {})
        await self._call_hooks("on_conversation_closed", conversation_id, conv)
        return conv

    async def set_csat(self, conversation_id: str, score: int) -> None:
        if not (1 <= score <= 5):
            raise ValidationError(f"CSAT score must be 1-5, got {score}")
        conv = self._get_conv(conversation_id)
        if conv.resolution is None:
            raise ValidationError("Cannot set CSAT on unresolved conversation")
        new_res = dataclasses.replace(conv.resolution, csat_score=score)
        self._update_conv(conversation_id, resolution=new_res)
        self._emit(EventType.CONVERSATION_CSAT_RECORDED, conversation_id, {
            "score": score,
        })

    # ---------- Participants ----------

    async def join(self, conversation_id: str, participant: Participant) -> None:
        conv = self._get_conv(conversation_id)
        parts = self._participants[conversation_id]
        if any(p.id == participant.id for p in parts):
            return  # idempotent
        parts.append(participant)
        self._update_conv(
            conversation_id,
            participants=tuple(parts),
        )
        self._emit(EventType.PARTICIPANT_JOINED, conversation_id, {
            "participant_id": participant.id, "role": participant.role.value,
        })
        # operator join auto-switches auto → copilot (§3 / §7.1 #8)
        if participant.role == ParticipantRole.OPERATOR and conv.mode == ConversationMode.AUTO:
            await self.switch_mode(
                conversation_id,
                ConversationMode.COPILOT,
                triggered_by=participant.id,
                trigger="auto:operator_join",
            )

    async def leave(self, conversation_id: str, participant_id: str) -> None:
        parts = self._participants.get(conversation_id, [])
        original_len = len(parts)
        parts[:] = [p for p in parts if p.id != participant_id]
        if len(parts) == original_len:
            return  # idempotent
        self._update_conv(conversation_id, participants=tuple(parts))
        self._emit(EventType.PARTICIPANT_LEFT, conversation_id, {
            "participant_id": participant_id,
        })
        # last operator leave: copilot → auto (§7.1 #8)
        conv = self._get_conv(conversation_id)
        if conv.mode == ConversationMode.COPILOT:
            has_operator = any(p.role == ParticipantRole.OPERATOR for p in parts)
            if not has_operator:
                await self.switch_mode(
                    conversation_id,
                    ConversationMode.AUTO,
                    triggered_by=participant_id,
                    trigger="auto:last_operator_left",
                )

    # ---------- Mode ----------

    async def switch_mode(
        self,
        conversation_id: str,
        target: ConversationMode,
        *,
        triggered_by: str,
        trigger: str,
    ) -> None:
        async with self._get_lock(conversation_id):
            conv = self._get_conv(conversation_id)
            if conv.state == ConversationState.CLOSED:
                raise IllegalModeTransition(
                    f"Cannot change mode on closed conversation {conversation_id}"
                )
            if conv.mode == target:
                self._emit(EventType.MODE_NOOP, conversation_id, {
                    "target": target.value, "trigger": trigger,
                })
                return
            old_mode = conv.mode
            self._update_conv(conversation_id, mode=target)
            self._emit(EventType.MODE_CHANGED, conversation_id, {
                "old_mode": old_mode.value,
                "new_mode": target.value,
                "triggered_by": triggered_by,
                "trigger": trigger,
            })

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
        if not content or not content.strip():
            raise ValidationError("Message content must not be empty")
        conv = self._get_conv(conversation_id)
        sender_role = self._role_of(conversation_id, source)
        final_vis = self._apply_gate(conv.mode, sender_role, requested_visibility)
        msg = Message(
            id=_gen_id(),
            conversation_id=conversation_id,
            source=source,
            content=content,
            visibility=final_vis,
            timestamp=_now(),
            sequence_number=self._next_seq(conversation_id),
            metadata=dict(metadata) if metadata else {},
        )
        self._messages[conversation_id].append(msg)
        self._emit(EventType.MESSAGE_SENT, conversation_id, {
            "message_id": msg.id, "visibility": final_vis.value,
        })
        if final_vis != requested_visibility:
            self._emit(EventType.MESSAGE_GATED, conversation_id, {
                "message_id": msg.id,
                "requested": requested_visibility.value,
                "actual": final_vis.value,
            })
        # Activate conversation on first message if CREATED
        if conv.state == ConversationState.CREATED:
            self._update_conv(conversation_id, state=ConversationState.ACTIVE)
            self._emit(EventType.CONVERSATION_ACTIVATED, conversation_id, {})
        return msg

    async def edit_message(
        self,
        conversation_id: str,
        message_id: str,
        *,
        new_content: str,
        edited_by: str,
    ) -> Message:
        self._get_conv(conversation_id)
        msgs = self._messages.get(conversation_id, [])
        idx = next((i for i, m in enumerate(msgs) if m.id == message_id), None)
        if idx is None:
            raise ValidationError(f"Message {message_id} not found")
        old = msgs[idx]
        edited = dataclasses.replace(
            old,
            content=new_content,
            edit_of=old.id,
        )
        msgs[idx] = edited
        self._emit(EventType.MESSAGE_EDITED, conversation_id, {
            "message_id": message_id, "edited_by": edited_by,
        })
        return edited

    async def delete_message(
        self,
        conversation_id: str,
        message_id: str,
        *,
        deleted_by: str,
    ) -> None:
        self._get_conv(conversation_id)
        msgs = self._messages.get(conversation_id, [])
        original_len = len(msgs)
        msgs[:] = [m for m in msgs if m.id != message_id]
        if len(msgs) < original_len:
            self._emit(EventType.MESSAGE_DELETED, conversation_id, {
                "message_id": message_id, "deleted_by": deleted_by,
            })

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
        if since_sequence is not None and before_sequence is not None:
            raise ValidationError("since_sequence and before_sequence are mutually exclusive")
        self._get_conv(conversation_id)
        msgs = list(self._messages.get(conversation_id, []))
        if since_sequence is not None:
            msgs = [m for m in msgs if m.sequence_number > since_sequence]
        if before_sequence is not None:
            msgs = [m for m in msgs if m.sequence_number < before_sequence]
        if until is not None:
            msgs = [m for m in msgs if m.timestamp <= until]
        # Q9: Engine filters SIDE messages for customer viewers
        if viewer_role == ParticipantRole.CUSTOMER:
            msgs = [m for m in msgs if m.visibility != MessageVisibility.SIDE]
        if before_sequence is not None:
            msgs = msgs[-limit:]  # last N before the cursor
        else:
            msgs = msgs[:limit]
        return msgs

    # ---------- Commands (T2A.1) ----------

    async def handle_command(
        self,
        conversation_id: str,
        *,
        actor_id: str,
        command: str,
        args: Mapping[str, Any] | None = None,
    ) -> None:
        raise NotImplementedError("T2A.1: command dispatch")

    # ---------- Timers (T1A.2) ----------

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

    # ---------- Events (minimal fan-out for T1A.1; T1A.3 replaces) ----------

    async def subscribe(
        self,
        *,
        conversation_id: str | None = None,
        squad_id: str | None = None,
        event_types: list[str] | None = None,
        since_sequence: int | str | None = None,
        viewer_role: ParticipantRole | None = None,
    ) -> AsyncIterator[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.append(q)
        try:
            while True:
                ev = await q.get()
                if conversation_id and ev.conversation_id != conversation_id:
                    continue
                if event_types and ev.type not in event_types:
                    continue
                yield ev
        finally:
            self._subscribers.remove(q)

    async def query_events(
        self,
        conversation_id: str,
        *,
        since_sequence: int | None = None,
        until: datetime | None = None,
        types: list[str] | None = None,
        limit: int = 100,
    ) -> list[Event]:
        self._get_conv(conversation_id)
        events = list(self._events.get(conversation_id, []))
        if since_sequence is not None:
            events = [e for e in events if e.sequence_number > since_sequence]
        if until is not None:
            events = [e for e in events if e.timestamp <= until]
        if types is not None:
            events = [e for e in events if e.type in types]
        return events[:limit]

    # ---------- Plugin hooks (minimal for T1A.1; T1A.3 expands) ----------

    def register_hook(self, hook: PluginHook) -> None:
        self._hooks.append(hook)
