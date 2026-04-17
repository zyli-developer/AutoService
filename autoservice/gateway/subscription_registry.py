"""Subscription registry for WS gateway (T6A.1).

Maintains {subscription_id -> SubscriptionEntry} mapping with reverse indexes
for session-based cleanup and scope-based lookup.

Per T0.2 §4 F6/F7, §5 S13/S14:
- subscribe creates a subscription_id, returns subscription_added
- unsubscribe removes by subscription_id, returns subscription_removed
- connection disconnect evicts all subscriptions for that session
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from .connection import generate_frame_id


@dataclass
class SubscriptionEntry:
    """A single active subscription."""

    subscription_id: str
    session_id: str
    scope: dict[str, Any]  # {conversation_id?, squad_id?, global?}
    viewer_role: str
    since_sequence: int | str | None = None
    event_types: list[str] | None = None
    # The async iterator from engine.subscribe() — held for cancellation
    _iterator: AsyncIterator | None = field(default=None, repr=False)
    # Task running the fan-out loop
    _task: asyncio.Task | None = field(default=None, repr=False)


class SubscriptionRegistry:
    """In-memory subscription registry with session and scope indexes."""

    def __init__(self) -> None:
        self._subs: dict[str, SubscriptionEntry] = {}
        # session_id -> set of subscription_ids (for disconnect cleanup)
        self._by_session: dict[str, set[str]] = {}
        # scope key -> set of subscription_ids (for broadcast routing)
        self._by_scope: dict[str, set[str]] = {}

    def add(self, entry: SubscriptionEntry) -> None:
        """Register a new subscription."""
        sid = entry.subscription_id
        self._subs[sid] = entry

        # Session index
        self._by_session.setdefault(entry.session_id, set()).add(sid)

        # Scope index (keyed by the primary scope identifier)
        scope_key = _scope_key(entry.scope)
        if scope_key:
            self._by_scope.setdefault(scope_key, set()).add(sid)

    def get(self, subscription_id: str) -> SubscriptionEntry | None:
        return self._subs.get(subscription_id)

    def remove(self, subscription_id: str) -> SubscriptionEntry | None:
        """Remove a subscription. Returns the entry or None."""
        entry = self._subs.pop(subscription_id, None)
        if entry is None:
            return None

        # Clean session index
        sess_set = self._by_session.get(entry.session_id)
        if sess_set:
            sess_set.discard(subscription_id)
            if not sess_set:
                del self._by_session[entry.session_id]

        # Clean scope index
        scope_key = _scope_key(entry.scope)
        if scope_key:
            scope_set = self._by_scope.get(scope_key)
            if scope_set:
                scope_set.discard(subscription_id)
                if not scope_set:
                    del self._by_scope[scope_key]

        # Cancel the fan-out task if running
        if entry._task and not entry._task.done():
            entry._task.cancel()

        return entry

    def evict_by_session(self, session_id: str) -> list[SubscriptionEntry]:
        """Remove all subscriptions for a session. Returns evicted entries."""
        sub_ids = list(self._by_session.get(session_id, []))
        evicted = []
        for sid in sub_ids:
            entry = self.remove(sid)
            if entry:
                evicted.append(entry)
        return evicted

    def get_by_scope(self, scope_key: str) -> list[SubscriptionEntry]:
        """Get all subscriptions matching a scope key."""
        sub_ids = self._by_scope.get(scope_key, set())
        return [self._subs[sid] for sid in sub_ids if sid in self._subs]

    def get_by_session(self, session_id: str) -> list[SubscriptionEntry]:
        """Get all subscriptions for a session."""
        sub_ids = self._by_session.get(session_id, set())
        return [self._subs[sid] for sid in sub_ids if sid in self._subs]

    @property
    def count(self) -> int:
        return len(self._subs)


def generate_subscription_id() -> str:
    """Generate a unique subscription_id (ULID-ish hex)."""
    return generate_frame_id()


def _scope_key(scope: dict[str, Any]) -> str | None:
    """Derive a lookup key from a subscription scope."""
    if scope.get("conversation_id"):
        return f"conv:{scope['conversation_id']}"
    if scope.get("squad_id"):
        return f"squad:{scope['squad_id']}"
    if scope.get("global"):
        return "global"
    return None
