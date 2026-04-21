"""Role-switch orchestrator — consume handoff directive + re-seed new role (M3 T3S.2).

Contract: docs/contracts/m3/e3-triage.md §2.3.

Flow (triggered when agent output contains a valid ``<handoff to='X' />``):
  1. Parse handoff via :func:`autoservice.handoff.parse_handoff`
  2. Emit event ``handoff.detected`` with (conversation_id, from, to, reason)
  3. Release sticky cc_pool session: ``cc_pool.release_sticky(conversation_id)``
  4. Acquire new role: ``cc_pool.acquire_sticky(key=conversation_id, role=target, tenant_id=...)``
  5. Re-seed via :func:`autoservice.history_compressor.compress_for_role_switch`
  6. Emit event ``role.switched``

This module is the pure orchestration layer — no HTTP/WS, no DB writes.
Callers (triage pipeline) handle persistence and event emission at their
boundary.  Pool + compressor + event_emitter are injected for testability.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from autoservice.handoff import HandoffResult, parse_handoff
from autoservice.history_compressor import (
    CompressionResult,
    compress_for_role_switch,
    format_reseed_prompt,
)


# ──────────────────────────────────────────────────────────────────────────
# Protocols — inject dependencies
# ──────────────────────────────────────────────────────────────────────────


class _StickyPoolLike(Protocol):
    """Minimum cc_pool surface needed for role switch."""

    async def release_sticky(self, key: str) -> None: ...
    async def acquire_sticky(
        self, key: str, *, role: str | None = None,
        tenant_id: str | None = None, timeout: float | None = None,
    ) -> Any: ...


EventEmitter = Callable[[str, dict], Awaitable[None]]
"""(event_name, payload) -> awaitable  — e.g. bridge to conversation_engine.event_bus."""


# ──────────────────────────────────────────────────────────────────────────
# Result
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RoleSwitchOutcome:
    """Record of a completed role switch."""
    conversation_id: str
    from_role: str
    to_role: str
    reason: str | None
    reseed_prompt: str          # pre-formatted for the new role's first LLM turn
    compression: CompressionResult
    pool_instance: Any           # the new sticky-bound PooledInstance
    cleaned_agent_output: str   # original output with <handoff /> tag stripped


# ──────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────


async def maybe_role_switch(
    *,
    agent_output: str,
    conversation_id: str,
    current_role: str,
    tenant_id: str,
    history: list[Any],
    cc_pool: _StickyPoolLike,
    emit_event: EventEmitter | None = None,
    compression_model: str = "haiku",
    acquire_timeout: float | None = None,
) -> tuple[RoleSwitchOutcome | None, str]:
    """Scan *agent_output* for a handoff directive and execute the switch.

    Returns:
        (RoleSwitchOutcome, cleaned_output) on successful switch.
        (None, agent_output)                when no valid handoff present.
                                            (Malformed / unknown role parsed
                                            as None by handoff.parse_handoff.)

    Called from the agent output-processing pipeline after sentiment parsing.
    The *cleaned_output* has the ``<handoff />`` tag stripped — pass this
    downstream to whatever renders the message to the customer (the tag
    should NOT appear in the customer-visible channel).

    No side-effects if handoff is absent (trust boundary — parser returns
    None for any malformed / adversarial tag, no exception raised).
    """
    handoff, cleaned = parse_handoff(agent_output)
    if handoff is None:
        return None, agent_output

    # Guard: can't switch to the same role (no-op but dispatch would churn pool)
    if handoff.target_role == current_role:
        # Still return cleaned output (strip the tag), but don't switch.
        return None, cleaned

    # Step 2: event emission — tenant-scoped downstream consumers subscribe.
    if emit_event is not None:
        await emit_event(
            "handoff.detected",
            {
                "conversation_id": conversation_id,
                "from_role": current_role,
                "to_role": handoff.target_role,
                "reason": handoff.reason,
                "raw_tag": handoff.raw_tag,
            },
        )

    # Step 3: release sticky binding for the previous role.
    await cc_pool.release_sticky(conversation_id)

    # Step 4: acquire sticky with the new role.
    new_instance = await cc_pool.acquire_sticky(
        conversation_id,
        role=handoff.target_role,
        tenant_id=tenant_id,
        timeout=acquire_timeout,
    )

    # Step 5: compress history for re-seed (threshold check inside).
    compression = compress_for_role_switch(
        conversation_id=conversation_id,
        history=history,
        target_role=handoff.target_role,
        model=compression_model,
    )
    reseed_prompt = format_reseed_prompt(compression, handoff.target_role)

    outcome = RoleSwitchOutcome(
        conversation_id=conversation_id,
        from_role=current_role,
        to_role=handoff.target_role,
        reason=handoff.reason,
        reseed_prompt=reseed_prompt,
        compression=compression,
        pool_instance=new_instance,
        cleaned_agent_output=cleaned,
    )

    # Step 6: downstream event — indicates switch fully completed.
    if emit_event is not None:
        await emit_event(
            "role.switched",
            {
                "conversation_id": conversation_id,
                "from_role": current_role,
                "to_role": handoff.target_role,
                "tokens_used": compression.tokens_used,
                "compressed": compression.compressed,
            },
        )

    return outcome, cleaned
