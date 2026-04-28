"""Transport-agnostic stream_agent_reply (D3). See spec §6.

The pipeline reuses triage + KB pre-fetch + multi-role pool from the WS
flow, but pushes output through a ReplySink instead of WS frames. Single
agent message persisted at end (no multi-bubble — irrelevant for SSE).
"""
from __future__ import annotations

import logging
import time as _time
from typing import AsyncIterator

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
    iterator: AsyncIterator,
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


_DIRECT_FALLBACK_TEXT = "Hello, how can I help you?"
_EMPTY_REPLY_FALLBACK = "(Sorry, no valid reply was generated.)"


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
    """Persist a single agent message row (no segments — spec §6.3) and
    broadcast to the operator squad (decision E1 — full operator visibility)."""
    msg = await engine.send_message(
        conv_id, source="agent", content=text,
        metadata=dict(metadata) if metadata else {},
    )
    # Broadcast to operator squad. Best-effort — broadcast errors must not
    # break the customer reply path.
    try:
        from autoservice.gateway.message_router import (
            _broadcast_to_squad, _message_frame,
        )
        frame = _message_frame(msg)
        frame["payload"]["source_display"] = {"id": "agent", "role": "agent"}
        await _broadcast_to_squad(frame, conv_id)
    except Exception:
        logger.exception("agent broadcast failed conv=%s", conv_id)
    return msg


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
        perf["t_done"] = _time.perf_counter()
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

    # v1 simplification (CINNOX): all non-direct roles route through the
    # customer sticky pool, regardless of decision.role. The WS path
    # (gateway/message_router._generate_agent_reply) uses pool.acquire(role=…)
    # for lead/translate roles to bind to the right sub-pool's soul + KB.
    # We accept the degradation here because (a) CINNOX traffic is dominated
    # by customer-role, (b) the role-shaped prompt built above still nudges
    # the model toward the right voice. Port _role_stream if/when CINNOX
    # needs lead/translate routing. Tracked: spec §6 step 4.
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
        perf["t_done"] = _time.perf_counter()
        return full_text

    # Spec §9 4MB-cumulative cap: when the sink truncated mid-stream,
    # also truncate the terminal text and persisted row so neither blows
    # the cap nor exceeds CINNOX's 1MB-per-event limit.
    if getattr(sink, "truncated", False):
        from autoservice.integrations.general_bot.sse import MAX_CUMULATIVE_BYTES
        suffix = "\n(reply truncated)"
        # Reserve room for the suffix in the byte budget.
        budget = MAX_CUMULATIVE_BYTES - len(suffix.encode("utf-8"))
        encoded = full_text.encode("utf-8")
        if len(encoded) > budget:
            # Truncate at byte boundary, then drop trailing partial UTF-8.
            truncated = encoded[:budget].decode("utf-8", errors="ignore")
            full_text = truncated + suffix
        else:
            full_text = full_text + suffix
        logger.warning(
            "stream_agent_reply: truncated to 4MB cap conv=%s len=%d",
            conv_id, len(full_text.encode("utf-8")),
        )

    await sink.emit_terminal(full_text)
    await _persist_agent_message(engine, conv_id, full_text)
    perf["t_done"] = _time.perf_counter()
    return full_text
