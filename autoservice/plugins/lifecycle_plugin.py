"""Lifecycle plugin — CRM integration on conversation create/close.

Subscribes to ConversationEngine hooks:
- on_conversation_created → upsert CRM contact + log creation
- on_conversation_closed  → update CRM record with resolution info
- on_event(MESSAGE_SENT)  → auto-record turn to memory pool (T6E.5)
"""

from __future__ import annotations

import logging
from typing import Any

from autoservice.conversation_engine.events import EventType
from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    Event,
    Participant,
    Timer,
)
from autoservice.memory_pool import MemoryPool

log = logging.getLogger(__name__)


class LifecyclePlugin:
    """PluginHook implementation for CRM lifecycle tracking.

    Accepts an optional *crm* facade (any object with ``upsert_contact``,
    ``log_message``, ``get_contact``) so callers can inject a mock or the
    real ``autoservice.crm`` module.
    """

    def __init__(self, crm: Any = None, memory_pool: MemoryPool | None = None) -> None:
        if crm is None:
            from autoservice import crm as _crm
            crm = _crm
        self._crm = crm
        self._memory_pool = memory_pool or MemoryPool()
        # Track records created during conversation lifecycle
        self._records: dict[str, dict[str, Any]] = {}

    # --- PluginHook protocol ---

    async def on_conversation_created(self, conv: Conversation) -> None:
        """Create/update CRM contact and record the new conversation.

        For returning customers (those with prior message history in CRM),
        a ``returning_customer_context`` key is injected into
        ``conv.metadata`` so the agent can tailor its greeting (T6E.3).
        """
        customer_id = conv.metadata.get("customer_id", "")
        customer_name = conv.metadata.get("customer_name", "")
        channel = conv.metadata.get("channel", "unknown")

        # Check for existing contact *before* upsert (T6E.3)
        open_id = customer_id or conv.id
        existing_contact = self._crm.get_contact(open_id)

        contact = self._crm.upsert_contact(
            open_id=open_id,
            name=customer_name,
        )

        # --- Returning-customer context injection (T6E.3) ---
        msg_count = 0
        if existing_contact and isinstance(existing_contact, dict):
            msg_count = existing_contact.get("message_count", 0)
        if msg_count > 0:
            history = self._crm.get_contact_history(open_id, limit=5)
            recent_topics = [
                h["text"] for h in history
                if h.get("direction") == "in" and h.get("text")
            ][:3]

            ctx_parts: list[str] = []
            ctx_parts.append(
                f"Returning customer (messages: {existing_contact['message_count']}, "
                f"last seen: {existing_contact['last_seen']})"
            )
            name = existing_contact.get("name", "")
            if name:
                ctx_parts.append(f"Name: {name}")
            company = existing_contact.get("company", "")
            if company:
                ctx_parts.append(f"Company: {company}")
            if recent_topics:
                ctx_parts.append(
                    "Recent topics: " + "; ".join(recent_topics)
                )
            conv.metadata["returning_customer_context"] = "\n".join(ctx_parts)
            log.info(
                "lifecycle: returning customer detected — %s (msgs=%d)",
                open_id,
                existing_contact["message_count"],
            )

        self._records[conv.id] = {
            "contact": contact,
            "channel": channel,
            "created_at": conv.created_at.isoformat(),
        }

        log.info(
            "lifecycle: conversation %s created — contact %s",
            conv.id,
            contact.get("open_id", ""),
        )

    async def on_conversation_closed(self, conv: Conversation) -> None:
        """Update CRM record with resolution details."""
        outcome = ""
        csat: int | None = None
        resolved_by = ""

        if conv.resolution is not None:
            outcome = conv.resolution.outcome.value
            csat = conv.resolution.csat_score
            resolved_by = conv.resolution.resolved_by

        record = self._records.get(conv.id, {})
        record["outcome"] = outcome
        record["csat"] = csat
        record["resolved_by"] = resolved_by
        record["closed_at"] = conv.updated_at.isoformat()
        self._records[conv.id] = record

        # Persist a log entry in CRM conversations table
        customer_id = conv.metadata.get("customer_id", "") or conv.id
        self._crm.log_message(
            open_id=customer_id,
            chat_id=conv.id,
            direction="out",
            text=f"Conversation closed: {outcome}",
        )

        log.info(
            "lifecycle: conversation %s closed — outcome=%s csat=%s",
            conv.id,
            outcome,
            csat,
        )

    async def on_mode_changed(
        self,
        conv: Conversation,
        old_mode: ConversationMode,
        new_mode: ConversationMode,
        trigger: str,
    ) -> None:
        pass

    async def on_participant_joined(self, conv: Conversation, p: Participant) -> None:
        pass

    async def on_timer_expired(self, conv: Conversation, timer: Timer) -> None:
        pass

    async def on_event(self, event: Event) -> None:
        if event.type == EventType.MESSAGE_SENT:
            try:
                self._memory_pool.record_turn(
                    conversation_id=event.conversation_id,
                    role=event.data.get("source", "unknown"),
                    content=event.data.get("content", ""),
                )
            except Exception:
                log.exception(
                    "lifecycle: failed to record turn for conversation %s",
                    event.conversation_id,
                )
