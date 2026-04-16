"""Squad assignment plugin for ConversationEngine.

Manages squad routing: assigns conversations to squads on creation,
tracks assignments, and supports reassignment.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from autoservice.conversation_engine.types import Conversation, Event

log = logging.getLogger(__name__)


class SquadPlugin:
    """PluginHook that manages squad assignment for conversations.

    squad_config schema::

        {
            "default_squad": "general",
            "channel_routing": {
                "feishu": "cn-support",
                "web": "en-support",
            },
        }
    """

    def __init__(self, squad_config: dict[str, Any] | None = None) -> None:
        self._config = squad_config or {}
        self._default_squad: str = self._config.get("default_squad", "general")
        self._channel_routing: dict[str, str] = self._config.get("channel_routing", {})
        # conv_id → squad_id
        self._assignments: dict[str, str] = {}

    # ---------- PluginHook callbacks ----------

    async def on_conversation_created(self, conv: Conversation) -> None:
        meta = conv.metadata or {}
        # Priority: explicit squad_id > channel routing > default
        squad_id = meta.get("squad_id")
        if not squad_id:
            channel = meta.get("channel") or conv.id.split("_", 1)[0]
            squad_id = self._channel_routing.get(channel)
        if not squad_id:
            squad_id = self._default_squad
        self._assignments[conv.id] = squad_id

    async def on_conversation_closed(self, conv: Conversation) -> None:
        self._assignments.pop(conv.id, None)

    async def on_event(self, event: Event) -> None:
        pass  # no-op; required by protocol

    # ---------- Public API ----------

    def get_squad(self, conv_id: str) -> str | None:
        """Return current squad for a conversation, or None if not tracked."""
        return self._assignments.get(conv_id)

    def list_conversations(self, squad_id: str) -> list[str]:
        """Return all conversation IDs assigned to the given squad."""
        return [cid for cid, sid in self._assignments.items() if sid == squad_id]

    def reassign(self, conv_id: str, new_squad_id: str) -> None:
        """Move a conversation to a different squad.

        Raises KeyError if conv_id is not tracked.
        """
        if conv_id not in self._assignments:
            raise KeyError(f"Conversation {conv_id} not tracked by SquadPlugin")
        self._assignments[conv_id] = new_squad_id
