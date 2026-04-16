"""Lifecycle plugin — CRM integration on conversation create/close.

Subscribes to ConversationEngine hooks:
- on_conversation_created → upsert CRM contact + log creation
- on_conversation_closed  → update CRM record with resolution info
"""

from __future__ import annotations

import logging
from typing import Any

from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    Event,
    Participant,
    Timer,
)

log = logging.getLogger(__name__)


class LifecyclePlugin:
    """PluginHook implementation for CRM lifecycle tracking.

    Accepts an optional *crm* facade (any object with ``upsert_contact``,
    ``log_message``, ``get_contact``) so callers can inject a mock or the
    real ``autoservice.crm`` module.
    """

    def __init__(self, crm: Any = None) -> None:
        if crm is None:
            from autoservice import crm as _crm
            crm = _crm
        self._crm = crm
        # Track records created during conversation lifecycle
        self._records: dict[str, dict[str, Any]] = {}

    # --- PluginHook protocol ---

    async def on_conversation_created(self, conv: Conversation) -> None:
        """Create/update CRM contact and record the new conversation."""
        customer_id = conv.metadata.get("customer_id", "")
        customer_name = conv.metadata.get("customer_name", "")
        channel = conv.metadata.get("channel", "unknown")

        contact = self._crm.upsert_contact(
            open_id=customer_id or conv.id,
            name=customer_name,
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
        pass
