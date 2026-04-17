"""Operator offline watcher: flips TAKEOVER conversations to AUTO after grace period."""
from __future__ import annotations

import asyncio
import logging

from autoservice.conversation_engine.protocol import ConversationEngine
from autoservice.conversation_engine.types import ConversationMode

log = logging.getLogger(__name__)


class OfflineWatcher:
    """Tracks operator WS connect/disconnect. On disconnect, schedules a grace
    timer; if the operator doesn't reconnect in time, all TAKEOVER conversations
    they own are switched back to AUTO with trigger=auto:operator_offline.
    """

    def __init__(self, engine: ConversationEngine, *, grace_ms: int) -> None:
        self._engine = engine
        self._grace_ms = grace_ms
        self._online: set[str] = set()
        self._pending: dict[str, asyncio.Task] = {}

    def on_connect(self, operator_id: str) -> None:
        self._online.add(operator_id)
        task = self._pending.pop(operator_id, None)
        if task and not task.done():
            task.cancel()

    def on_disconnect(self, operator_id: str) -> None:
        self._online.discard(operator_id)
        self._pending[operator_id] = asyncio.create_task(
            self._grace(operator_id), name=f"offline-grace-{operator_id}",
        )

    async def _grace(self, operator_id: str) -> None:
        try:
            await asyncio.sleep(self._grace_ms / 1000.0)
        except asyncio.CancelledError:
            return
        self._pending.pop(operator_id, None)
        if operator_id in self._online:
            return  # reconnected before expiry
        try:
            convs = await self._engine.list_conversations_in_takeover_by(operator_id)
        except Exception:
            log.exception("list_conversations_in_takeover_by failed for %s", operator_id)
            return
        for conv in convs:
            try:
                await self._engine.switch_mode(
                    conv.id,
                    ConversationMode.AUTO,
                    triggered_by="__system__",
                    trigger="auto:operator_offline",
                )
            except Exception:
                log.exception("offline switch_mode failed for conv=%s", conv.id)
