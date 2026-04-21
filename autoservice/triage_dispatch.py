"""triage_and_route — glue between ModelRouter, cc_pool, and conversation_engine.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §1.1 / §2

Flow (one customer message):
  1. ModelRouter.route_message() -> TriageDecision
  2. engine.send_message(source="triage", visibility=SIDE, metadata=...)
  3. engine.update_triage_state(active_role=, detected_language=)
  4. return decision (caller acquires the role instance and produces the reply)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from autoservice.conversation_engine.types import (
    MessageVisibility,
    Participant,
    ParticipantRole,
)
from autoservice.model_router import ModelRouter, TriageDecision

log = logging.getLogger("triage.dispatch")

_HISTORY_FETCH_LIMIT = 20
_CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")
_TRIAGE_SOURCE_ID = ParticipantRole.TRIAGE.value


async def _ensure_triage_participant(engine: Any, conv_id: str) -> None:
    """Idempotently register a synthetic 'triage' participant.

    LocalEngine.send_message() looks up the sender role via _role_of(), which
    raises UnknownParticipant if the id is not joined. The triage orchestrator
    writes SIDE messages on behalf of the router so it must ensure the
    participant exists before sending.
    """
    try:
        conv = await engine.get_conversation(conv_id)
        if any(p.id == _TRIAGE_SOURCE_ID for p in conv.participants):
            return
        await engine.join(
            conv_id,
            Participant(
                id=_TRIAGE_SOURCE_ID,
                role=ParticipantRole.TRIAGE,
                joined_at=datetime.now(timezone.utc),
            ),
        )
    except Exception:
        log.exception("triage: failed to ensure triage participant conv=%s", conv_id)


async def triage_and_route(
    *,
    engine: Any,
    conv_id: str,
    customer_text: str,
    tenant_config: Any,
) -> TriageDecision:
    router = ModelRouter()
    decision = await router.route_message(
        customer_text,
        tenant_config=tenant_config,
        conv_id=conv_id,
        engine=engine,
    )
    await _ensure_triage_participant(engine, conv_id)
    try:
        await engine.send_message(
            conv_id,
            source=_TRIAGE_SOURCE_ID,
            content=_format_triage_side_text(decision),
            requested_visibility=MessageVisibility.SIDE,
            metadata={
                "type": "triage_decision",
                "intent": decision.intent,
                "confidence": decision.confidence,
                "route_to": decision.role,
                "source": decision.source,
                "summary": decision.summary,
                "previous_role": decision.previous_role,
                "detected_language": decision.detected_language,
            },
        )
    except Exception:
        log.exception("triage: failed to write SIDE message conv=%s", conv_id)

    try:
        await engine.update_triage_state(
            conv_id,
            active_role=decision.role,
            detected_language=decision.detected_language,
        )
    except Exception:
        log.exception("triage: failed to update state conv=%s", conv_id)
        raise

    return decision


def _format_triage_side_text(d: TriageDecision) -> str:
    base = (
        f"[分流] 意图: {d.intent} | 信心: {d.confidence:.2f} | "
        f"路由: {d.role} | 源: {d.source}"
    )
    if d.summary:
        base += f' | 摘要: "{d.summary}"'
    return base


def _estimate_tokens(text: str) -> int:
    """Cheap token estimator.

    For Latin-script text, ~4 chars per token is a reasonable heuristic.
    For CJK, tokens are roughly 1 per character — using the Latin ratio
    would underestimate the budget by ~4x. Fall back to len(text) when
    any CJK character is present.
    """
    if _CJK_TOKEN_RE.search(text):
        return max(1, len(text))
    return max(1, len(text) // 4)


async def _build_reseeded_prompt(
    engine: Any,
    conv_id: str,
    customer_text: str,
    previous_role: str | None,
    new_role: str,
    token_limit: int,
) -> str:
    if previous_role is None or previous_role == new_role:
        return customer_text

    history = await engine.get_messages(
        conv_id,
        viewer_role=ParticipantRole.AGENT,
        limit=_HISTORY_FETCH_LIMIT,
    )
    public_msgs = [
        m for m in history if m.visibility == MessageVisibility.PUBLIC
    ]

    lines: list[str] = []
    running_tokens = 0
    for m in reversed(public_msgs):
        line = f"[{m.source}] {m.content}"
        t = _estimate_tokens(line)
        if running_tokens + t > token_limit and lines:
            break
        lines.append(line)
        running_tokens += t
    lines.reverse()

    history_block = "\n".join(lines) if lines else "(no prior messages)"
    return (
        "<conversation_history>\n"
        f"{history_block}\n"
        "</conversation_history>\n\n"
        f"Current customer message: {customer_text}\n\n"
        f"You are now the {new_role} agent. "
        "Continue based on the conversation history above."
    )
