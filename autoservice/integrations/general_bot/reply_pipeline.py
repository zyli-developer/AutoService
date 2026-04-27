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

# Imports done at module top so monkeypatch in tests can swap them.
from autoservice.triage_dispatch import (
    triage_and_route,
    _build_customer_prompt,
    _build_reseeded_prompt,
)
from autoservice.triage_config_loader import load_tenant_config_for_conv
from autoservice.gateway.message_router import _collect_operator_suggestions

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


# --- triage + KB + pool integration ---


_DIRECT_FALLBACK_TEXT = "您好,请问有什么可以帮您?"
_EMPTY_REPLY_FALLBACK = "(抱歉,本次未生成有效回复)"


def _compose_role_prompt(suggestions: str, customer_text: str) -> str:
    """Non-customer-role prompt shape (mirrors message_router._call_engine)."""
    if suggestions:
        return (
            f"{suggestions}\n"
            f"Customer message: {customer_text}\n\n"
            "You are a customer service AI. The operator has given you "
            "instructions above — follow them when replying to the customer. "
            "Reply in the same language as the customer."
        )
    return (
        f"Customer message: {customer_text}\n\n"
        "Reply briefly in the same language as the customer."
    )


async def _persist_agent_message(engine, conv_id: str, text: str, *, metadata=None):
    """Persist a single agent message row (no segments — spec §6.3)."""
    return await engine.send_message(
        conv_id, source="agent", content=text,
        metadata=dict(metadata) if metadata else {},
    )


async def stream_agent_reply(
    *,
    engine,
    pool,
    conv_id: str,
    customer_text: str,
    tenant_id: str,
    sink: ReplySink,
    perf: dict | None = None,
) -> str:
    """Run triage → KB pre-fetch → pool stream → sink. Persists one final
    agent message. Returns full reply text.

    Errors propagate to the caller (route handler decides how to surface
    them — typically via terminal SSE event since headers are already sent).
    """
    if perf is None:
        perf = {}
    perf["t0"] = _time.perf_counter()

    cfg = await load_tenant_config_for_conv(engine, conv_id)
    decision = await triage_and_route(
        engine=engine, conv_id=conv_id,
        customer_text=customer_text, tenant_config=cfg,
    )
    perf["t_triage"] = _time.perf_counter()

    # Direct-reply short-circuit (spec §6 step 2)
    if decision.role == "direct":
        text = decision.direct_reply or _DIRECT_FALLBACK_TEXT
        if not decision.direct_reply:
            logger.warning(
                "direct route with empty direct_reply conv=%s intent=%s — "
                "using generic fallback", conv_id, decision.intent,
            )
        await sink.emit_terminal(text)
        await _persist_agent_message(engine, conv_id, text)
        return text

    # Reseed history if role switched
    if decision.previous_role and decision.previous_role != decision.role:
        prompt_text = await _build_reseeded_prompt(
            engine, conv_id, customer_text,
            previous_role=decision.previous_role, new_role=decision.role,
            token_limit=getattr(cfg, "history_reseed_token_limit", 2000),
        )
    else:
        prompt_text = customer_text

    suggestions = await _collect_operator_suggestions(engine, conv_id)

    if decision.role == "customer":
        prompt = await _build_customer_prompt(
            tenant_id=tenant_id, customer_text=prompt_text,
            operator_suggestions=suggestions,
        )
    else:
        prompt = _compose_role_prompt(suggestions, prompt_text)

    perf["t_prompt_built"] = _time.perf_counter()

    iterator = pool.session_query(
        conv_id, prompt, tenant_id=tenant_id, tier=decision.tier,
    )

    full_text = await _drain_to_sink(iterator, sink, perf=perf)

    if not full_text.strip():
        logger.warning("stream_agent_reply: empty reply conv=%s", conv_id)
        full_text = _EMPTY_REPLY_FALLBACK
        await sink.emit_terminal(full_text)
        await _persist_agent_message(
            engine, conv_id, full_text, metadata={"is_fallback": True},
        )
        return full_text

    await sink.emit_terminal(full_text)
    await _persist_agent_message(engine, conv_id, full_text)
    perf["t_done"] = _time.perf_counter()
    return full_text
