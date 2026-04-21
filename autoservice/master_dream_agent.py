"""Master (platform-level) dream agent — skeleton (M3 T2S.8).

Contract: docs/contracts/m3/e5-dream.md §1.
Design spec: docs/superpowers/specs/2026-04-21-m3-e5-dream-extension-design.md §1.

**SCOPE — T2S.8 skeleton only.** This module establishes:
- The module boundary between per-tenant dream and platform-level dream.
- Scheduler routing: ``tenant_id == bootstrap.MASTER_TENANT_ID`` dispatches
  here instead of the per-tenant ``dream_agent.run_dream``.
- Proof of CON-04 enforcement: emitted proposals use the shared
  ``emit_proposal()`` (no status kwarg, hardcoded ``draft``) via a new
  ``category='platform_level'``.

Cross-tenant signal aggregation (cc_pool utilization, SLA breaches, etc.)
and the full LLM tool-use loop are T4S.4 (batch-10).

🚨 **CON-04 RED LINE**: this module imports :func:`dream_agent.emit_proposal`
and uses it AS-IS.  The 5-layer defense (contract §3) applies:
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

from autoservice import bootstrap, dream_agent

logger = logging.getLogger("autoservice.master_dream_agent")


async def run_platform_dream(
    tenant_id: str,
    cc_pool: Any,
    mempool: Any,
    proposals_conn: sqlite3.Connection,
    runs_conn: sqlite3.Connection,
    max_tool_turns: int = 10,
) -> list[str]:
    """Run the master-side dream.  Returns IDs of emitted proposals.

    Skeleton for M3 T2S.8: emits a single minimal ``platform_level`` proposal
    as proof of plumbing.  Full implementation (cross-tenant signal
    aggregation + LLM tool-use loop) lands in T4S.4.

    Args:
        tenant_id: Must be ``bootstrap.MASTER_TENANT_ID`` (``_master``).
                   Guard raises on mismatch — routing bug in scheduler.
        cc_pool:  Reserved for T4S.4 (LLM tool-use); unused in skeleton.
        mempool:  Reserved for T4S.4 (cross-tenant memory aggregation).
        proposals_conn: SQLite connection for ``proposals`` table.
        runs_conn: SQLite connection for ``dream_runs`` table.
        max_tool_turns: Reserved for T4S.4 LLM loop.

    Returns:
        List of emitted proposal IDs (single-element in skeleton).

    Raises:
        ValueError: if tenant_id is not the master tenant (catches routing bugs).
    """
    if tenant_id != bootstrap.MASTER_TENANT_ID:
        raise ValueError(
            f"run_platform_dream called with non-master tenant_id={tenant_id!r}; "
            f"expected {bootstrap.MASTER_TENANT_ID!r}.  Routing bug in DreamScheduler?"
        )

    logger.info("[master_dream] skeleton run starting (T2S.8)")

    # Skeleton: emit one hardcoded platform_level proposal to prove the
    # pipeline end-to-end.  Full cross-tenant signal aggregation lands in
    # T4S.4 — until then this is a no-op marker that the scheduler routing
    # works and the CON-04 red line holds for platform_level category.
    proposal_id = dream_agent.emit_proposal(
        proposals_conn,
        tenant_id=bootstrap.MASTER_TENANT_ID,
        category="platform_level",
        title="[T2S.8 skeleton] platform-level dream plumbing established",
        description=(
            "Master dream agent skeleton emitted this proposal as proof that "
            "DreamScheduler routes _master to master_dream_agent and that "
            "emit_proposal still enforces CON-04 (status='draft' hardcoded) "
            "when called from the master-side path.  Full cross-tenant signal "
            "aggregation + LLM loop lands in T4S.4 (batch-10)."
        ),
        suggestion="No action.  This is a marker proposal for plumbing validation.",
        evidence="M3 T2S.8 milestone — see docs/plans/m3/tasks.yaml.",
        risk_level="low",
        target_role="dream",  # existing AGENT_ROLES set; platform-level is a CATEGORY, role points at the dream agent itself
    )

    logger.info(
        "[master_dream] skeleton emitted proposal %s (category=platform_level, status=draft)",
        proposal_id,
    )
    return [proposal_id]
