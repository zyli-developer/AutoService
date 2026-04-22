"""Master (platform-level) dream agent — T4S.4b real LLM tool-loop.

Contract: docs/contracts/m3/e5-dream.md §1.
Design spec: docs/superpowers/specs/2026-04-21-m3-e5-dream-extension-design.md §1.
Latest: M3.5 mini-sprint §1.4 — D5 LLM real-wire (2026-04-22).

**SCOPE — T4S.4b / T5S.14.** This module now:
- Drives a real cross-tenant LLM tool-use loop via the shared
  :func:`dream_agent._run_agent_loop` helper.
- Threads :func:`gather_platform_signals` output into the initial user
  message so the LLM can reason about platform-wide patterns.
- Emits proposals through the same ``emit_proposal`` tool registered in
  :data:`dream_agent._TOOL_SCHEMAS` — hence the same CON-04 path,
  without a new write surface.

🚨 **CON-04 RED LINE**: this module never mutates ``status``. The
``emit_proposal`` tool the LLM calls flows through
:func:`dream_agent.emit_proposal` (signature lock; ``'draft'`` hardcode;
AST guardrail T4S.8). The 5-layer defense is intact:
- Layer 1 signature lock: emit_proposal has no status kwarg
- Layer 2a string hardcode: 'draft' in JSON + SQL
- Layer 2b value rejection (update_status rejects 'applied')
- Layer 3 import cone: proposal_apply.py cannot import this module
- Layer 4 AST guardrail (T4S.8): status-write strings only in approved files
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from autoservice import bootstrap, dream_agent, dream_runs
from autoservice.platform_signals import (
    PlatformSignals,
    gather_platform_signals,
)

logger = logging.getLogger("autoservice.master_dream_agent")


# Re-export PlatformSignals + gather_platform_signals for callers importing
# via master_dream_agent.  Canonical definition is autoservice/platform_signals
# (decoupled per CON-04 5-layer defense rationale — keeps master_dream_agent's
# audited scope focused on proposal emission, not signal collection).
__all__ = [
    "PlatformSignals",
    "gather_platform_signals",
    "run_platform_dream",
]


_MASTER_DREAM_SYSTEM_PROMPT = (
    "You are the platform-level Dream agent. You observe cross-tenant "
    "aggregate signals (never per-user content) and propose improvements "
    "that benefit the platform as a whole.\n"
    "\n"
    "Available tools:\n"
    "- emit_proposal: file a draft finding. Use category='platform_level'. "
    "Every proposal is persisted with status='draft' — admin approval is "
    "mandatory before any effect. Never fabricate evidence.\n"
    "- kb_search / list_souls: inspect KB or soul snippets for context.\n"
    "\n"
    "When you have findings, call emit_proposal once per finding. When you "
    "have nothing meaningful to propose, respond with a brief summary and "
    "stop calling tools."
)


def _render_signal_context(signals: PlatformSignals) -> str:
    """Render cross-tenant signals as a plain-text briefing for the LLM.

    T5S.14 test contract: the rendered text must surface the raw
    ``tenant_count`` and ``total_proposal_count`` values so the LLM
    sees them in its first turn.  Markdown-style bullets keep it
    readable for human debuggers tailing the prompt log.
    """
    pool_line = "yes" if signals.pool_metrics else "no"
    return (
        "## Platform-level dream — cross-tenant observation\n"
        "\n"
        "The following signals summarise the current platform state.\n"
        f"- tenant_count: {signals.tenant_count}\n"
        f"- total_proposal_count: {signals.total_proposal_count}\n"
        f"- pool_metrics_attached: {pool_line}\n"
        f"- snapshot_ts_ms: {signals.emitted_at_ms}\n"
        "\n"
        "Observe these signals. If they suggest a platform-wide pattern "
        "(aggregate CSAT drop, cross-tenant KB gap, SLA breach trend, "
        "pool exhaustion), call `emit_proposal` with "
        "`category='platform_level'` and a descriptive title + evidence. "
        "Otherwise respond with a brief summary and stop."
    )


async def run_platform_dream(
    tenant_id: str,
    cc_pool: Any,
    mempool: Any,
    proposals_conn: sqlite3.Connection,
    runs_conn: sqlite3.Connection,
    max_tool_turns: int = 10,
) -> list[str]:
    """Run the master-side dream via a real LLM tool-loop.

    Post-T5S.14: delegates to :func:`dream_agent._run_agent_loop` so the
    per-tenant and master paths share one audited loop (CON-04 layers 1/2/3
    intact). Signals from :func:`gather_platform_signals` are rendered
    into the initial user message so the LLM sees aggregate cross-tenant
    state up front.

    Args:
        tenant_id: Must be ``bootstrap.MASTER_TENANT_ID`` (``_master``).
                   Guard raises on mismatch — routing bug in scheduler.
        cc_pool:  Dream pool — ``.acquire(role='dream', tenant_id=_master)``
                  yields a client with ``call_with_tools`` (T3B.5 surface).
        mempool:  Not consumed directly today (no per-user content leaves
                  a tenant boundary into the master prompt); kept for
                  API compatibility + future aggregate memory support.
        proposals_conn: SQLite connection for ``proposals`` table.
        runs_conn: SQLite connection for ``dream_runs`` table.
        max_tool_turns: Hard upper bound on LLM tool rounds per run.

    Returns:
        List of emitted proposal IDs (empty when the LLM decides
        nothing is worth proposing this cycle).

    Raises:
        ValueError: if tenant_id is not the master tenant (catches routing bugs).
    """
    if tenant_id != bootstrap.MASTER_TENANT_ID:
        raise ValueError(
            f"run_platform_dream called with non-master tenant_id={tenant_id!r}; "
            f"expected {bootstrap.MASTER_TENANT_ID!r}.  Routing bug in DreamScheduler?"
        )

    logger.info("[master_dream] run starting (T4S.4b tool-loop path)")

    # Cross-tenant aggregate signals (read-only, no PII).
    signals = gather_platform_signals(proposals_conn, cc_pool=cc_pool)
    logger.info(
        "[master_dream] signals: tenants=%d total_proposals=%d pool=%s",
        signals.tenant_count, signals.total_proposal_count,
        "yes" if signals.pool_metrics else "no",
    )

    initial_user_msg = _render_signal_context(signals)

    # Snapshot existing master-tenant proposals so we can report only
    # those emitted during this run without depending on the LLM's own
    # tool_use count (robust against retries / double-emits).
    before_ids = {
        r["id"] for r in proposals_conn.execute(
            "SELECT id FROM proposals WHERE tenant_id = ?",
            (bootstrap.MASTER_TENANT_ID,),
        ).fetchall()
    }

    run_id = dream_runs.start_run(runs_conn, bootstrap.MASTER_TENANT_ID)
    status = "failed"
    tool_calls = 0
    proposals_emitted = 0
    tokens_in = 0
    tokens_out = 0
    error_msg: str | None = None

    try:
        cm = await dream_agent._acquire_dream_client(  # noqa: SLF001 — shared helper
            cc_pool, bootstrap.MASTER_TENANT_ID, _MASTER_DREAM_SYSTEM_PROMPT,
        )
        async with cm as pooled:
            async def _pool_llm_send(*, system, messages, tools):
                return await pooled.client.call_with_tools(
                    system=system, messages=messages, tools=tools,
                )

            status, tool_calls, proposals_emitted, tokens_in, tokens_out = (
                await dream_agent._run_agent_loop(  # noqa: SLF001 — shared helper
                    llm_send=_pool_llm_send,
                    system_prompt=_MASTER_DREAM_SYSTEM_PROMPT,
                    initial_user_msg=initial_user_msg,
                    tenant_id=bootstrap.MASTER_TENANT_ID,
                    proposals_db=proposals_conn,
                    runs_db=runs_conn,
                    run_id=run_id,
                    max_tool_turns=max_tool_turns,
                )
            )
    except Exception as exc:  # noqa: BLE001 — map to run row
        logger.exception(
            "[master_dream] run %s failed: %s", run_id, exc,
        )
        error_msg = f"{type(exc).__name__}: {exc}"
        status = "failed"

    try:
        dream_runs.update_run(
            runs_conn, run_id,
            tool_calls=tool_calls,
            proposals_emitted=proposals_emitted,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        dream_runs.end_run(
            runs_conn, run_id,
            status=status,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error=error_msg,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "[master_dream] failed to finalise run row %s: %s", run_id, exc,
        )

    after_ids = {
        r["id"] for r in proposals_conn.execute(
            "SELECT id FROM proposals WHERE tenant_id = ?",
            (bootstrap.MASTER_TENANT_ID,),
        ).fetchall()
    }
    new_ids = sorted(after_ids - before_ids)

    logger.info(
        "[master_dream] run %s status=%s tool_calls=%d proposals_emitted=%d "
        "new_ids=%d",
        run_id, status, tool_calls, proposals_emitted, len(new_ids),
    )
    return new_ids
