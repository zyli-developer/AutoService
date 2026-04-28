"""Per-conversation FIFO queue for serialized agent reply turns.

Spec: docs/superpowers/specs/2026-04-26-instant-ack-multi-bubble-queue-design.md §7
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from typing import Awaitable, Callable

log = logging.getLogger("autoservice.gateway.turn_queue")

#: Soft cap on pending (not-yet-in-flight) runners per conversation.
#: 6th submit while 5 queued + 1 in-flight raises QueueFullError.
DEFAULT_MAX_QUEUE_DEPTH = int(os.getenv("QUEUE_MAX_DEPTH", "5"))


class QueueFullError(RuntimeError):
    """Raised by ``TurnQueue.submit`` when MAX_QUEUE_DEPTH is exceeded."""


class _ConvState:
    __slots__ = ("fifo", "in_flight")

    def __init__(self) -> None:
        self.fifo: deque[Callable[[], Awaitable[None]]] = deque()
        self.in_flight: bool = False


class TurnQueue:
    """Serialize agent reply turns per conversation.

    Two-level locking:
    - ``_registry_lock``: a single asyncio.Lock guarding all mutations of
      the ``_state`` dict. Prevents the cleanup-vs-submit race documented
      in §7.5 of the design spec.
    - ``in_flight`` flag in ``_ConvState``: tracks whether a runner is
      currently executing for this conversation. Used by the registry-lock
      check to decide "run now" vs "queue".
    """

    def __init__(
        self,
        max_queue_depth: int = DEFAULT_MAX_QUEUE_DEPTH,
    ) -> None:
        self._state: dict[str, _ConvState] = {}
        self._registry_lock = asyncio.Lock()
        self._max_depth = max_queue_depth

    async def submit(
        self,
        conv_id: str,
        runner: Callable[[], Awaitable[None]],
    ) -> None:
        """Submit a runner. Returns immediately. Either runs now or queues."""
        should_start_loop = False
        async with self._registry_lock:
            st = self._state.get(conv_id)
            if st is None:
                st = self._state[conv_id] = _ConvState()
                st.in_flight = True
                should_start_loop = True
            else:
                if len(st.fifo) >= self._max_depth:
                    raise QueueFullError(
                        f"Queue full for conv={conv_id} (depth={len(st.fifo)})",
                    )
                st.fifo.append(runner)
        if should_start_loop:
            asyncio.create_task(
                self._run_loop(conv_id, runner),
                name=f"turn-loop-{conv_id}",
            )

    async def _run_loop(
        self,
        conv_id: str,
        first_runner: Callable[[], Awaitable[None]],
    ) -> None:
        runner = first_runner
        while runner is not None:
            try:
                await runner()
            except Exception:
                log.exception("turn runner failed conv=%s", conv_id)
            async with self._registry_lock:
                st = self._state.get(conv_id)
                # Invariant: only _run_loop pops conv_id from _state, so st
                # should never be None while this loop is running.
                assert st is not None, (
                    f"TurnQueue invariant violated: state for conv={conv_id} "
                    f"disappeared while _run_loop is still running"
                )
                if st.fifo:
                    runner = st.fifo.popleft()
                else:
                    st.in_flight = False
                    self._state.pop(conv_id, None)
                    runner = None

    def queue_depth(self, conv_id: str) -> int:
        """Return number of queued (not-yet-running) runners for a conv.
        0 if conv has no pending state."""
        st = self._state.get(conv_id)
        return len(st.fifo) if st else 0

    def has_in_flight(self, conv_id: str) -> bool:
        st = self._state.get(conv_id)
        return bool(st and st.in_flight)
