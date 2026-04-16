"""CcPoolPlugin — manages CC instance pool bindings per conversation.

When a conversation is created, acquires a sticky CC instance.
When a conversation is closed, releases the sticky CC instance.
Key stays as chat_id this period (conv.id is used as chat_id).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from autoservice.conversation_engine.types import (
    Conversation,
    ConversationMode,
    Event,
    Participant,
    Timer,
)

log = logging.getLogger(__name__)


@runtime_checkable
class StickyPool(Protocol):
    """Minimal interface for sticky pool operations (testable with stubs)."""

    async def acquire_sticky(self, key: str) -> Any: ...
    async def release_sticky(self, key: str) -> None: ...


class CcPoolPlugin:
    """PluginHook that manages CC pool sticky bindings for conversations.

    Args:
        pool: Optional StickyPool-compatible object (e.g. CCPool).
              If None, binding tracking still works but no pool calls are made.
    """

    def __init__(self, pool: StickyPool | None = None) -> None:
        self._pool = pool
        # conv_id → chat_id mapping
        self._bindings: dict[str, str] = {}

    # -- PluginHook interface --

    async def on_conversation_created(self, conv: Conversation) -> None:
        chat_id = conv.id
        self._bindings[conv.id] = chat_id
        if self._pool is not None:
            try:
                await self._pool.acquire_sticky(chat_id)
                log.debug("Acquired sticky CC instance for chat_id=%s", chat_id)
            except Exception:
                log.exception("Failed to acquire sticky CC instance for %s", chat_id)

    async def on_conversation_closed(self, conv: Conversation) -> None:
        chat_id = self._bindings.pop(conv.id, None)
        if chat_id is None:
            return  # already removed or never tracked — idempotent
        if self._pool is not None:
            try:
                await self._pool.release_sticky(chat_id)
                log.debug("Released sticky CC instance for chat_id=%s", chat_id)
            except Exception:
                log.exception("Failed to release sticky CC instance for %s", chat_id)

    async def on_mode_changed(
        self,
        conv: Conversation,
        old_mode: ConversationMode,
        new_mode: ConversationMode,
        trigger: str,
    ) -> None:
        pass  # no-op for this plugin

    async def on_participant_joined(self, conv: Conversation, p: Participant) -> None:
        pass  # no-op for this plugin

    async def on_timer_expired(self, conv: Conversation, timer: Timer) -> None:
        pass  # no-op for this plugin

    async def on_event(self, event: Event) -> None:
        pass  # no-op for this plugin

    # -- Public API --

    def get_binding(self, conv_id: str) -> str | None:
        """Return the chat_id bound to a conversation, or None."""
        return self._bindings.get(conv_id)
