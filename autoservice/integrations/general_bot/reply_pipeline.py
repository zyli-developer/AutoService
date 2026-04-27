"""Transport-agnostic stream_agent_reply (D3). See spec §6.

The pipeline reuses triage + KB pre-fetch + multi-role pool from the WS
flow, but pushes output through a ReplySink instead of WS frames. Single
agent message persisted at end (no multi-bubble — irrelevant for SSE).
"""
from __future__ import annotations

import logging
import time as _time
from typing import Any, AsyncIterator

from autoservice.integrations.general_bot.sse import ReplySink

logger = logging.getLogger("autoservice.general_bot.pipeline")


async def _drain_to_sink(
    iterator: AsyncIterator[Any],
    sink: ReplySink,
    *,
    perf: dict | None = None,
) -> str:
    """Consume claude_agent_sdk stream → ReplySink. Returns full text.

    Mirrors message_router._drain_into_bubbles' SDK-event branching but
    without bubble/edit logic (CINNOX SSE has no edit semantics).
    """
    from claude_agent_sdk.types import AssistantMessage, ResultMessage, StreamEvent

    full = ""
    saw_stream_text = False
    async for item in iterator:
        if isinstance(item, StreamEvent):
            ev = getattr(item, "event", None) or {}
            if ev.get("type") == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta":
                    chunk = delta.get("text") or ""
                    if chunk:
                        if perf is not None and "first_token_t" not in perf:
                            perf["first_token_t"] = _time.perf_counter()
                        saw_stream_text = True
                        full += chunk
                        await sink.emit_delta(chunk)
        elif isinstance(item, AssistantMessage) and item.content and not saw_stream_text:
            for block in item.content:
                text = getattr(block, "text", None)
                if isinstance(text, str) and text:
                    if perf is not None and "first_token_t" not in perf:
                        perf["first_token_t"] = _time.perf_counter()
                    full += text
                    await sink.emit_delta(text)
        elif isinstance(item, ResultMessage) and getattr(item, "result", None) and not saw_stream_text:
            text = item.result
            if perf is not None and "first_token_t" not in perf:
                perf["first_token_t"] = _time.perf_counter()
            full += text
            await sink.emit_delta(text)
    return full
