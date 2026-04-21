"""apply_proposal — the ONLY path from 'accepted' to 'applied' (M3 T4S.1).

🔒 **CON-04 SECURITY-CRITICAL MODULE.**

Contract: docs/contracts/m3/e5-dream.md v1.1 §2.

CON-04 red line: dream agents MAY NEVER write non-draft proposal status.
This module is the sole writer of ``status='applied'`` — via the private
``proposal_pipeline._mark_applied_internal`` helper (import cone layer).

5-layer defense (recap):
  1. Signature lock — ``dream_agent.emit_proposal`` has no ``status`` kwarg
     (existing test in tests/dream_agent/test_emit_proposal_tool.py)
  2a. String hardcode — 'draft' literal in dream_agent.py:208, :219
  2b. Value rejection — ``update_status(new_status='applied')`` raises
  3. Import cone — THIS MODULE has no imports from dream_agent or
     master_dream_agent (verified by AST tests T4S.1 + T4S.8)
  4. AST guardrail (T4S.8) — status-write literals only here + in
     proposal_pipeline._mark_applied_internal; 'INSERT INTO proposal_audit'
     only here + in proposal_pipeline + api_routes approve/reject

"Don't Do" list (partial — contract §4):
  * DON'T import from dream_agent / master_dream_agent
  * DON'T call emit_proposal
  * DON'T write status directly via UPDATE SQL (use _mark_applied_internal)
  * DON'T skip audit — _mark_applied_internal writes it in same txn
  * DON'T implement physical side-effects here in M3 — only ``mark_applied``
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# Only import from proposal_pipeline — NOT from dream_agent / master_dream_agent.
from autoservice.proposal_pipeline import (
    ProposalNotFound,
    ProposalPipeline,
    ProposalStateError,
)


# ──────────────────────────────────────────────────────────────────────────
# Result type
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ApplyResult:
    """Return value of :func:`apply_proposal` — serializable via asdict."""
    proposal_id: str
    previous_status: str       # 'accepted' on fresh apply; 'applied' on idempotent
    new_status: str            # always 'applied'
    admin_user_id: str
    applied_at: str | None     # ISO timestamp; None on idempotent
    handler_result: dict       # from category handler (M3: {'marked_applied_at': ...})
    idempotent: bool           # True when proposal was already applied


# ──────────────────────────────────────────────────────────────────────────
# Handler registry — M3 scope: mark_applied only (no physical side effects)
# ──────────────────────────────────────────────────────────────────────────


HandlerFn = Callable[[dict], dict]
"""(proposal_dict) -> handler_result_dict"""


def _mark_applied_handler(proposal: dict) -> dict:
    """M3 no-op handler — audit-only, no physical side effect.

    Contract OQ-E5-1: M3 defers skill-patch / cc_pool-policy / config-mutation
    to M4+.  The audit trail is the security deliverable; physical apply is
    scope for a later milestone.
    """
    from datetime import datetime, timezone
    return {
        "marked_applied_at": datetime.now(tz=timezone.utc).isoformat(),
        "side_effects": None,
        "note": (
            "M3 mark_applied_only — physical apply handler for this category "
            "is a M4+ deliverable (contract e5-dream §2.5)."
        ),
    }


# All categories map to the no-op handler in M3.  T4S.1b/T4S.3-later
# can replace per-category with real implementations.
_HANDLERS: dict[str, HandlerFn] = {
    # Legacy per-tenant categories
    "response_quality": _mark_applied_handler,
    "workflow":         _mark_applied_handler,
    "knowledge_gap":    _mark_applied_handler,
    "tone":             _mark_applied_handler,
    # M3 T2S.8 new category (master dream)
    "platform_level":   _mark_applied_handler,
}


# ──────────────────────────────────────────────────────────────────────────
# Core function
# ──────────────────────────────────────────────────────────────────────────


def apply_proposal(
    pipeline: ProposalPipeline,
    *,
    proposal_id: str,
    admin_user_id: str,
    is_platform_admin: bool = False,
) -> ApplyResult:
    """Apply an accepted proposal — the ONLY status='applied' writer.

    Args:
        pipeline: :class:`ProposalPipeline` instance (owns the DB connection).
        proposal_id: target proposal.
        admin_user_id: identity of the human actor — recorded to
                       proposal_audit for audit trail.  Cannot be empty
                       (defensive; enforced at function entry).
        is_platform_admin: True iff caller holds a tier-0 session
                           (``tenant_id=NULL``).  Required for proposals
                           with category='platform_level' (contract §2.6
                           + §4 rule 12).  tenant_admin (non-platform)
                           is insufficient for platform-level proposals.

    Returns:
        :class:`ApplyResult` with previous_status, new_status, timestamps,
        handler result, and idempotent flag.

    Raises:
        ValueError: admin_user_id empty
        ProposalNotFound: proposal_id doesn't exist
        ProposalStateError: current status != 'accepted' (and != 'applied')
        PermissionError: platform_level proposal + caller not platform admin

    Idempotent: re-applying a proposal already in 'applied' state returns
    ``ApplyResult(idempotent=True, previous_status='applied', ...)`` without
    raising.

    CON-04 invariants enforced:
        * This function and ``ProposalPipeline._mark_applied_internal``
          are the ONLY writers of ``status='applied'``.
        * The SQL ``UPDATE proposals SET status='applied'`` literal
          appears ONLY in :func:`ProposalPipeline._mark_applied_internal`
          (AST guardrail T4S.8 verifies).
        * This module imports nothing from ``dream_agent`` or
          ``master_dream_agent`` (AST test below + T4S.8).
    """
    if not admin_user_id or not admin_user_id.strip():
        raise ValueError("admin_user_id is required for apply_proposal audit")

    # Load to check existence + platform-level scope
    proposal = pipeline.get_proposal(proposal_id)
    if proposal is None:
        raise ProposalNotFound(proposal_id)

    # Contract §4 rule 12: platform_level requires tier-0 admin.
    # Enforced INSIDE this function (not only HTTP layer) so internal
    # callers (jobs, migrations) can't bypass via non-HTTP paths.
    if proposal.get("category") == "platform_level" and not is_platform_admin:
        raise PermissionError(
            f"proposal {proposal_id!r} has category='platform_level' "
            "and requires tier-0 platform admin.  tenant_admin insufficient."
        )

    # Delegate to the private helper that owns the atomic UPDATE + audit write.
    # This is the ONLY call site of _mark_applied_internal in the codebase
    # (Layer 3 import cone — enforced by test below + T4S.8 AST walker).
    outcome = pipeline._mark_applied_internal(proposal_id, admin_user_id)

    # Run handler (M3: mark_applied only — audit-first, no physical side effect)
    category = (outcome["proposal"] or {}).get("category") or "unknown"
    handler = _HANDLERS.get(category, _mark_applied_handler)
    handler_result = handler(outcome["proposal"])

    if outcome["idempotent"]:
        return ApplyResult(
            proposal_id=proposal_id,
            previous_status="applied",
            new_status="applied",
            admin_user_id=admin_user_id,
            applied_at=None,
            handler_result={"note": "already-applied; no-op"},
            idempotent=True,
        )

    return ApplyResult(
        proposal_id=proposal_id,
        previous_status="accepted",
        new_status="applied",
        admin_user_id=admin_user_id,
        applied_at=outcome["applied_at"],
        handler_result=handler_result,
        idempotent=False,
    )
