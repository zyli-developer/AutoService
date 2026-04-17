"""LocalEngine — in-process ConversationEngine implementation (M0-M4).

T1A.1: Mode/Gate/lifecycle/participants/messages.
T1A.2: Timer scheduling (set_timer/cancel_timer/on_expire actions).
T1A.3: EventBus — in-process pub/sub + SQLite async persistence + plugin hook dispatch.
T2A.1: handle_command — unified command dispatch with permission matrix.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Mapping

from autoservice.conversation_engine.errors import (
    ConversationAlreadyClosed,
    ConversationNotFound,
    IllegalModeTransition,
    PermissionDenied,
    UnknownParticipant,
    ValidationError,
)

log = logging.getLogger(__name__)
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


class _Subscriber:
    """Internal subscriber with scope filtering (T1A.3)."""

    __slots__ = ("conversation_id", "squad_id", "event_types", "viewer_role", "queue")

    def __init__(
        self,
        *,
        conversation_id: str | None = None,
        squad_id: str | None = None,
        event_types: set[str] | None = None,
        viewer_role: str | None = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.squad_id = squad_id
        self.event_types = event_types
        self.viewer_role = viewer_role
        self.queue: asyncio.Queue[Event] = asyncio.Queue()

    def matches(
        self,
        event: Event,
        conv_metadata_fn: Any = None,
    ) -> bool:
        if self.conversation_id and event.conversation_id != self.conversation_id:
            return False
        if self.squad_id:
            if conv_metadata_fn:
                meta = conv_metadata_fn(event.conversation_id)
                if meta.get("squad_id") != self.squad_id:
                    return False
            else:
                return False
        if self.event_types and event.type not in self.event_types:
            return False
        if self.viewer_role == "customer" and event.type == "message.sent":
            if event.data.get("visibility") == "side":
                return False
        return True


class LocalEngine:
    """In-process ConversationEngine implementation (M0-M4).

    All state is held in memory (dicts). Events are also stored in-memory
    for query_events. T1A.3 adds full EventBus (pub/sub with scope filtering,
    since_sequence replay, plugin hook dispatch with Q8c isolation).
    """

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self._config = dict(config or {})
        # Takeover config (loaded from app or defaults)
        from autoservice.takeover_config import DEFAULT_TAKEOVER_CONFIG, TakeoverConfig
        tk_cfg = self._config.get("takeover")
        self._takeover_config: TakeoverConfig = (
            tk_cfg if isinstance(tk_cfg, TakeoverConfig) else DEFAULT_TAKEOVER_CONFIG
        )
        # Notification callbacks (set externally via on_takeover_warning / on_takeover_warning_cancelled)
        self._takeover_warning_cb = None
        self._takeover_cancel_cb = None
        # Core storage
        self._conversations: dict[str, Conversation] = {}
        self._participants: dict[str, list[Participant]] = {}  # conv_id → [Participant]
        self._messages: dict[str, list[Message]] = {}  # conv_id → [Message]
        self._seq: dict[str, int] = {}  # conv_id → next sequence number
        self._event_seq: dict[str, int] = {}  # conv_id → next event sequence
        # Mode serialization locks (§7.1 #3)
        self._mode_locks: dict[str, asyncio.Lock] = {}
        # EventBus: in-memory event log + subscriber fan-out (T1A.3)
        self._subscribers: list[_Subscriber] = []
        self._events: dict[str, list[Event]] = {}  # conv_id → [Event]
        # Timer storage: conv_id → name → (Timer, asyncio.Task)
        self._timers: dict[str, dict[str, tuple[Timer, asyncio.Task]]] = {}
        # Takeover timer tasks: conv_id → state dict with warning_task, release_task, warning_fired
        self._takeover_tasks: dict[str, dict[str, Any]] = {}
        # Plugin hooks with Q8c isolation (T1A.3)
        self._hooks: list[PluginHook] = []

    # ---- internal helpers ----

    def _get_conv(self, conversation_id: str) -> Conversation:
        conv = self._conversations.get(conversation_id)
        if conv is None:
            raise ConversationNotFound(conversation_id)
        return conv

    def _get_conv_metadata(self, conversation_id: str) -> dict[str, Any]:
        """Return conversation metadata for squad scope filtering."""
        conv = self._conversations.get(conversation_id)
        return dict(conv.metadata) if conv else {}

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
        """Create event, store in memory, fan-out to filtered subscribers."""
        ev = Event(
            id=_gen_id(),
            type=event_type,
            conversation_id=conv_id,
            data=data,
            timestamp=_now(),
            sequence_number=self._next_event_seq(conv_id),
        )
        self._events.setdefault(conv_id, []).append(ev)
        for sub in list(self._subscribers):
            if sub.matches(ev, self._get_conv_metadata):
                sub.queue.put_nowait(ev)
        return ev

    async def _emit_and_dispatch_hooks(
        self, event_type: str, conv_id: str, data: dict[str, Any],
        hook_method: str | None = None, *hook_args: Any,
    ) -> Event:
        """Emit event + dispatch plugin hooks with Q8c isolation.

        hook_method: optional specialized hook to call (e.g. "on_conversation_created").
        hook_args: arguments to pass to the specialized hook.
        on_event is always called for every event.
        """
        ev = self._emit(event_type, conv_id, data)
        await self._dispatch_hooks(ev, conv_id, hook_method, *hook_args)
        return ev

    async def _dispatch_hooks(
        self, event: Event, conv_id: str,
        hook_method: str | None = None, *hook_args: Any,
    ) -> None:
        """Call on_event + optional specialized hook on all hooks. Q8c: swallow exceptions."""
        for hook in self._hooks:
            # on_event (universal callback)
            on_event_fn = getattr(hook, "on_event", None)
            if on_event_fn is not None:
                try:
                    await on_event_fn(event)
                except Exception as exc:
                    self._emit(EventType.HOOK_FAILED, conv_id, {
                        "hook": type(hook).__name__,
                        "method": "on_event",
                        "error": str(exc),
                    })
            # Specialized hook (e.g. on_conversation_created)
            if hook_method:
                specialized_fn = getattr(hook, hook_method, None)
                if specialized_fn is not None:
                    try:
                        await specialized_fn(*hook_args)
                    except Exception as exc:
                        self._emit(EventType.HOOK_FAILED, conv_id, {
                            "hook": type(hook).__name__,
                            "method": hook_method,
                            "error": str(exc),
                        })

    def _get_lock(self, conv_id: str) -> asyncio.Lock:
        if conv_id not in self._mode_locks:
            self._mode_locks[conv_id] = asyncio.Lock()
        return self._mode_locks[conv_id]

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
        await self._emit_and_dispatch_hooks(
            EventType.CONVERSATION_CREATED, conv_id, {"channel": channel},
            "on_conversation_created", conv,
        )
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
        # Cancel all active timers for this conversation
        for name in list(self._timers.get(conversation_id, {})):
            self._cancel_timer_internal(conversation_id, name)
        resolution = Resolution(outcome=outcome, resolved_by=resolved_by)
        conv = self._update_conv(
            conversation_id,
            state=ConversationState.CLOSED,
            resolution=resolution,
        )
        self._emit(EventType.CONVERSATION_RESOLVED, conversation_id, {
            "outcome": outcome.value, "resolved_by": resolved_by,
        })
        await self._emit_and_dispatch_hooks(
            EventType.CONVERSATION_CLOSED, conversation_id, {},
            "on_conversation_closed", conv,
        )
        return conv

    async def set_csat(self, conversation_id: str, score: int) -> None:
        if not (1 <= score <= 5):
            raise ValidationError(f"CSAT score must be 1-5, got {score}")
        conv = self._get_conv(conversation_id)
        if conv.resolution is None:
            raise ValidationError("Cannot set CSAT on unresolved conversation")
        new_res = dataclasses.replace(conv.resolution, csat_score=score)
        self._update_conv(conversation_id, resolution=new_res)
        await self._emit_and_dispatch_hooks(
            EventType.CONVERSATION_CSAT_RECORDED, conversation_id, {
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
        await self._emit_and_dispatch_hooks(
            EventType.PARTICIPANT_JOINED, conversation_id, {
                "participant_id": participant.id, "role": participant.role.value,
            },
            "on_participant_joined", conv, participant,
        )
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
        takeover_operator_id: str | None = None,
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

            # Atomically update mode and takeover_operator_id
            new_takeover_id: str | None
            if target == ConversationMode.TAKEOVER:
                new_takeover_id = takeover_operator_id
            else:
                new_takeover_id = None
            updated = self._update_conv(
                conversation_id,
                mode=target,
                takeover_operator_id=new_takeover_id,
            )
            await self._emit_and_dispatch_hooks(
                EventType.MODE_CHANGED, conversation_id, {
                    "old_mode": old_mode.value,
                    "new_mode": target.value,
                    "triggered_by": triggered_by,
                    "trigger": trigger,
                    "takeover_operator_id": new_takeover_id,
                },
                "on_mode_changed", updated, old_mode, target, trigger,
            )

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
        await self._emit_and_dispatch_hooks(
            EventType.MESSAGE_SENT, conversation_id, {
                "message_id": msg.id, "visibility": final_vis.value,
                "source": msg.source, "content": msg.content,
            },
        )
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
        # Auto-release reset: if takeover operator is the sender, reset timer
        if (conv.mode == ConversationMode.TAKEOVER
                and conv.takeover_operator_id is not None
                and source == conv.takeover_operator_id):
            await self.reset_takeover_timer(conversation_id, actor_id=source)
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

    # ---------- Takeover timer (auto-release) ----------

    def on_takeover_warning(self, cb) -> None:
        """Register callback invoked when takeover warning phase fires.

        Callback receives dict: {conversation_id, operator_id, remaining_ms, reason}.
        """
        self._takeover_warning_cb = cb

    def on_takeover_warning_cancelled(self, cb) -> None:
        """Register callback invoked when a fired warning is subsequently cancelled."""
        self._takeover_cancel_cb = cb

    def _arm_takeover_timer(self, conversation_id: str, operator_id: str) -> None:
        """Schedule warning and release tasks. Cancels any existing ones first."""
        self._cancel_takeover_timer(conversation_id)
        cfg = self._takeover_config
        warning_delay = max(0, cfg.idle_timeout_ms - cfg.warning_ms) / 1000.0
        release_delay = cfg.warning_ms / 1000.0

        state: dict[str, Any] = {"warning_fired": False}

        async def _warning():
            try:
                await asyncio.sleep(warning_delay)
            except asyncio.CancelledError:
                return
            state["warning_fired"] = True
            if self._takeover_warning_cb:
                try:
                    self._takeover_warning_cb({
                        "conversation_id": conversation_id,
                        "operator_id": operator_id,
                        "remaining_ms": cfg.warning_ms,
                        "reason": "idle",
                    })
                except Exception:
                    log.exception("takeover_warning callback failed")
            state["release_task"] = asyncio.create_task(
                _release(), name=f"takeover-release-{conversation_id}",
            )

        async def _release():
            try:
                await asyncio.sleep(release_delay)
            except asyncio.CancelledError:
                return
            try:
                await self.switch_mode(
                    conversation_id, ConversationMode.COPILOT,
                    triggered_by="__system__", trigger="auto:idle_timeout",
                )
            except Exception:
                log.exception("auto-release switch_mode failed")

        state["warning_task"] = asyncio.create_task(
            _warning(), name=f"takeover-warning-{conversation_id}",
        )
        self._takeover_tasks[conversation_id] = state

    def _cancel_takeover_timer(self, conversation_id: str) -> bool:
        """Cancel any pending warning/release tasks. Returns True if warning had fired."""
        state = self._takeover_tasks.pop(conversation_id, None)
        if state is None:
            return False
        for key in ("warning_task", "release_task"):
            t = state.get(key)
            if t and not t.done():
                t.cancel()
        return bool(state.get("warning_fired"))

    async def reset_takeover_timer(self, conversation_id: str, *, actor_id: str) -> None:
        """Re-arm the timer; notify cancellation callback if warning had already fired."""
        conv = self._get_conv(conversation_id)
        if conv.mode != ConversationMode.TAKEOVER or conv.takeover_operator_id != actor_id:
            return
        warning_had_fired = self._cancel_takeover_timer(conversation_id)
        if warning_had_fired and self._takeover_cancel_cb:
            try:
                self._takeover_cancel_cb({"conversation_id": conversation_id})
            except Exception:
                log.exception("takeover_cancel callback failed")
        self._arm_takeover_timer(conversation_id, actor_id)

    # ---------- Commands (T2A.1) ----------

    # Commands that require operator or admin role
    _OPERATOR_COMMANDS = frozenset({
        "/hijack", "/release", "/copilot",
        "/resolve", "/abandon", "/status",
    })

    async def handle_command(
        self,
        conversation_id: str,
        *,
        actor_id: str,
        command: str,
        args: Mapping[str, Any] | None = None,
    ) -> None:
        # Validate participant exists and get role
        role = self._role_of(conversation_id, actor_id)

        # Permission check: only operator/admin may execute commands
        if role not in (ParticipantRole.OPERATOR, ParticipantRole.OBSERVER):
            raise PermissionDenied(
                f"Role {role.value} cannot execute {command}"
            )

        # Validate command is known
        if command not in self._OPERATOR_COMMANDS:
            raise ValidationError(f"Unknown command: {command}")

        # Dispatch
        if command == "/hijack":
            await self.switch_mode(
                conversation_id, ConversationMode.TAKEOVER,
                triggered_by=actor_id, trigger="/hijack",
                takeover_operator_id=actor_id,
            )
            self._arm_takeover_timer(conversation_id, actor_id)
        elif command == "/release":
            self._cancel_takeover_timer(conversation_id)
            await self.switch_mode(
                conversation_id, ConversationMode.AUTO,
                triggered_by=actor_id, trigger="/release",
            )
        elif command == "/copilot":
            self._cancel_takeover_timer(conversation_id)
            await self.switch_mode(
                conversation_id, ConversationMode.COPILOT,
                triggered_by=actor_id, trigger="/copilot",
            )
        elif command == "/resolve":
            self._cancel_takeover_timer(conversation_id)
            reason = (args or {}).get("reason")
            await self.close_conversation(
                conversation_id,
                outcome=Outcome.RESOLVED,
                resolved_by=actor_id,
                reason=reason,
            )
        elif command == "/abandon":
            self._cancel_takeover_timer(conversation_id)
            reason = (args or {}).get("reason")
            await self.close_conversation(
                conversation_id,
                outcome=Outcome.ABANDONED,
                resolved_by=actor_id,
                reason=reason,
            )
        elif command == "/status":
            # Read-only: just validate conversation exists (already done via _role_of)
            self._get_conv(conversation_id)

    # ---------- Timers (T1A.2) ----------

    def _cancel_timer_internal(self, conversation_id: str, name: str) -> None:
        """Cancel a timer's asyncio task without emitting events."""
        conv_timers = self._timers.get(conversation_id, {})
        entry = conv_timers.pop(name, None)
        if entry is not None:
            _, task = entry
            task.cancel()

    async def _timer_task(
        self,
        conversation_id: str,
        timer: Timer,
        on_expire: Mapping[str, Any],
    ) -> None:
        """Background task that sleeps then fires expiration logic."""
        try:
            await asyncio.sleep(timer.duration_ms / 1000.0)
        except asyncio.CancelledError:
            return
        # Remove from storage before dispatching (timer has fired)
        self._timers.get(conversation_id, {}).pop(timer.name, None)
        # Emit timer.expired
        self._emit(EventType.TIMER_EXPIRED, conversation_id, {
            "name": timer.name, "duration_ms": timer.duration_ms,
        })
        # SLA breach for sla_* timers
        if timer.name.startswith("sla_"):
            self._emit(EventType.SLA_BREACH, conversation_id, {
                "name": timer.name, "duration_ms": timer.duration_ms,
            })
        # Dispatch on_expire action
        await self._dispatch_on_expire(conversation_id, timer, on_expire)

    async def _dispatch_on_expire(
        self,
        conversation_id: str,
        timer: Timer,
        on_expire: Mapping[str, Any],
    ) -> None:
        """Execute the on_expire action after a timer fires."""
        action_type = on_expire.get("type", "callback")
        params = on_expire.get("params", {})
        try:
            if action_type == "mode_change":
                target = ConversationMode(params["target"])
                await self.switch_mode(
                    conversation_id,
                    target,
                    triggered_by=params.get("triggered_by", "__system__"),
                    trigger=params.get("trigger", f"auto:{timer.name}_expired"),
                )
            elif action_type == "system_message":
                content = params.get("content", f"Timer {timer.name} expired")
                msg = Message(
                    id=_gen_id(),
                    conversation_id=conversation_id,
                    source="__system__",
                    content=content,
                    visibility=MessageVisibility.SYSTEM,
                    timestamp=_now(),
                    sequence_number=self._next_seq(conversation_id),
                )
                self._messages.setdefault(conversation_id, []).append(msg)
                self._emit(EventType.MESSAGE_SENT, conversation_id, {
                    "message_id": msg.id, "visibility": "system",
                })
            elif action_type == "callback":
                conv = self._get_conv(conversation_id)
                for hook in self._hooks:
                    cb = getattr(hook, "on_timer_expired", None)
                    if cb is not None:
                        try:
                            await cb(conv, timer)
                        except Exception:
                            self._emit(EventType.HOOK_FAILED, conversation_id, {
                                "hook": type(hook).__name__,
                                "timer": timer.name,
                            })
        except Exception:
            log.exception("on_expire dispatch failed for timer %s", timer.name)

    async def set_timer(
        self,
        conversation_id: str,
        name: str,
        duration_ms: int,
        *,
        on_expire: Mapping[str, Any],
    ) -> Timer:
        conv = self._get_conv(conversation_id)
        if conv.state == ConversationState.CLOSED:
            raise ConversationAlreadyClosed(
                f"Cannot set timer on closed conversation {conversation_id}"
            )
        # Override existing timer with same name (D2: no cancelled event)
        self._cancel_timer_internal(conversation_id, name)
        now = _now()
        timer = Timer(
            conversation_id=conversation_id,
            name=name,
            duration_ms=duration_ms,
            started_at=now,
        )
        task = asyncio.create_task(
            self._timer_task(conversation_id, timer, on_expire)
        )
        self._timers.setdefault(conversation_id, {})[name] = (timer, task)
        self._emit(EventType.TIMER_SET, conversation_id, {
            "name": name, "duration_ms": duration_ms,
        })
        return timer

    async def cancel_timer(self, conversation_id: str, name: str) -> None:
        """Cancel a timer. Idempotent: no error if timer doesn't exist."""
        conv_timers = self._timers.get(conversation_id, {})
        entry = conv_timers.pop(name, None)
        if entry is None:
            return  # idempotent
        _, task = entry
        task.cancel()
        self._emit(EventType.TIMER_CANCELLED, conversation_id, {
            "name": name,
        })

    # ---------- Events (T1A.3 EventBus: scope filtering + since_sequence) ----------

    async def subscribe(
        self,
        *,
        conversation_id: str | None = None,
        squad_id: str | None = None,
        event_types: list[str] | None = None,
        since_sequence: int | str | None = None,
        viewer_role: ParticipantRole | None = None,
    ) -> AsyncIterator[Event]:
        sub = _Subscriber(
            conversation_id=conversation_id,
            squad_id=squad_id,
            event_types=set(event_types) if event_types else None,
            viewer_role=viewer_role.value if viewer_role else None,
        )
        # Replay historical events if since_sequence provided
        if since_sequence is not None and conversation_id:
            seq_int = int(since_sequence)
            for ev in self._events.get(conversation_id, []):
                if ev.sequence_number > seq_int and sub.matches(ev, self._get_conv_metadata):
                    yield ev

        # Register for live events
        self._subscribers.append(sub)
        try:
            while True:
                ev = await sub.queue.get()
                yield ev
        finally:
            if sub in self._subscribers:
                self._subscribers.remove(sub)

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

    # ---------- Plugin hooks (T1A.3: Q8c isolation) ----------

    def register_hook(self, hook: PluginHook) -> None:
        self._hooks.append(hook)
