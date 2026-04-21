"""Conversation history compressor for role-switch re-seed (M3 T4S.7).

Contract: docs/contracts/m3/e3-triage.md §4.

**Scope (CON-11)**: M3 only invokes this for role-switch re-seed — NOT for
routine dream-agent context pruning.  Broad roll-out deferred to M4+.

Design invariants (OQ-E3-3 defaults):
- Default LLM: ``haiku`` (cheap/fast).  Tenant opt-in to ``sonnet`` via
  tenant config (not yet wired; caller passes ``model`` explicitly in M3).
- Trigger threshold: ≥20 messages in history.  <20 → return (None, full history)
  no-op (cheaper than compression for short conversations).
- Return format: ``CompressionResult(summary, tail=last_N=3, tokens_used, cost_cents)``
- Cost budget: enforced via a per-process daily counter that raises
  ``CompressionBudgetExceeded`` when exceeded.  Budget default is generous
  (10 USD/day); tuned via env var ``COMPRESSION_DAILY_BUDGET_CENTS``.

The actual LLM call is pluggable via ``compress_fn`` param so tests don't
need network + API keys.  Production call uses
:mod:`autoservice.cc_pool` via a minimal prompt helper.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


# ──────────────────────────────────────────────────────────────────────────
# Constants (OQ-E3-3 defaults)
# ──────────────────────────────────────────────────────────────────────────

COMPRESSION_THRESHOLD_MESSAGES = 20
DEFAULT_TAIL_SIZE = 3
DEFAULT_MODEL = "haiku"
SONNET_OPT_IN_MODEL = "sonnet"
ALLOWED_MODELS: frozenset[str] = frozenset({DEFAULT_MODEL, SONNET_OPT_IN_MODEL})


# ──────────────────────────────────────────────────────────────────────────
# Return types
# ──────────────────────────────────────────────────────────────────────────


class _MessageLike(Protocol):
    """Structural type — any object with .role and .content attributes."""
    role: str
    content: str


@dataclass(frozen=True)
class CompressionResult:
    """Compressed conversation representation for role-switch re-seed.

    Consumers (T3S.2 re-triage) format this as:
        [Conversation summary so far]
        {summary}
        [Recent messages]
        {tail messages verbatim}
    """
    summary: str | None          # None if skipped (below threshold)
    tail: list[Any]              # last N raw messages (same type as input)
    tokens_used: int             # 0 if skipped
    cost_cents: float            # 0.0 if skipped
    compressed: bool             # False if skipped
    model_used: str | None       # None if skipped


# ──────────────────────────────────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────────────────────────────────


class CompressionBudgetExceeded(RuntimeError):
    """Raised when daily compression cost budget is exhausted."""


# ──────────────────────────────────────────────────────────────────────────
# Budget tracker — per-process; resets daily (UTC midnight)
# ──────────────────────────────────────────────────────────────────────────


class _DailyBudget:
    """Tracks cumulative cost for the current UTC day.  Resets on day change."""

    def __init__(self, daily_limit_cents: float = 1000.0):
        self._limit = daily_limit_cents
        self._spent = 0.0
        self._day_key = self._current_day_key()

    @staticmethod
    def _current_day_key() -> str:
        from datetime import datetime, timezone
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    def _maybe_reset(self) -> None:
        today = self._current_day_key()
        if today != self._day_key:
            self._day_key = today
            self._spent = 0.0

    def check(self, est_cost_cents: float) -> None:
        self._maybe_reset()
        if self._spent + est_cost_cents > self._limit:
            raise CompressionBudgetExceeded(
                f"Daily compression budget exceeded: "
                f"spent={self._spent:.2f}¢ + new={est_cost_cents:.2f}¢ > "
                f"limit={self._limit:.2f}¢"
            )

    def record(self, cost_cents: float) -> None:
        self._maybe_reset()
        self._spent += cost_cents

    @property
    def spent_cents(self) -> float:
        self._maybe_reset()
        return self._spent

    def reset_for_tests(self) -> None:
        """Test hook — zero out spend immediately."""
        self._spent = 0.0


_budget = _DailyBudget(
    daily_limit_cents=float(os.environ.get(
        "COMPRESSION_DAILY_BUDGET_CENTS", "1000"
    ))
)


def get_budget() -> _DailyBudget:
    """Expose the shared budget tracker (for tests + observability)."""
    return _budget


# ──────────────────────────────────────────────────────────────────────────
# Compression entry point
# ──────────────────────────────────────────────────────────────────────────


CompressFn = Callable[[list[Any], str], tuple[str, int]]
"""Pluggable LLM call: (messages, model) -> (summary_text, tokens_used)."""


def _estimate_cost_cents(tokens: int, model: str) -> float:
    """Back-of-envelope cost estimate. M3 numbers; refine in M4."""
    # Haiku: ~$0.25 / 1M input tokens → 0.000025¢ per token
    # Sonnet: ~$3 / 1M input tokens → 0.0003¢ per token
    per_token = 0.000025 if model == DEFAULT_MODEL else 0.0003
    return tokens * per_token


def compress_for_role_switch(
    *,
    conversation_id: str,
    history: list[Any],
    target_role: str,
    model: str = DEFAULT_MODEL,
    tail_size: int = DEFAULT_TAIL_SIZE,
    compress_fn: CompressFn | None = None,
) -> CompressionResult:
    """Compress *history* for a role-switch re-seed.

    Short-circuit: if ``len(history) < COMPRESSION_THRESHOLD_MESSAGES``,
    returns a no-op result (``compressed=False``, full history as tail).
    No LLM call, no cost.

    Otherwise: the first ``len(history) - tail_size`` messages are
    summarized by calling ``compress_fn`` (or the default LLM caller).
    Budget is checked BEFORE the call and recorded AFTER.

    Args:
        conversation_id: for log correlation.
        history: message list (any object with .role + .content).
        target_role: the AgentRole to re-seed; included in the prompt
                     so the summary is oriented to what matters for X.
        model: 'haiku' (default) or 'sonnet' (tenant opt-in).
        tail_size: how many recent messages to keep verbatim (default 3).
        compress_fn: optional pluggable LLM call.  If None, uses the
                     default implementation which requires an API key
                     (only use in production).

    Raises:
        ValueError: if model is not in ``ALLOWED_MODELS``.
        CompressionBudgetExceeded: if the daily cost budget is spent.
    """
    if model not in ALLOWED_MODELS:
        raise ValueError(
            f"model must be one of {sorted(ALLOWED_MODELS)}, got {model!r}"
        )

    n = len(history)
    if n < COMPRESSION_THRESHOLD_MESSAGES:
        # Below threshold — no-op (caller gets full history back as tail).
        return CompressionResult(
            summary=None,
            tail=list(history),
            tokens_used=0,
            cost_cents=0.0,
            compressed=False,
            model_used=None,
        )

    # Split: everything except last tail_size → summarize; last tail_size kept raw
    to_summarize = history[:-tail_size] if tail_size > 0 else list(history)
    tail = history[-tail_size:] if tail_size > 0 else []

    # Pre-call budget check: use a conservative estimate (10 tokens per message)
    est_tokens = max(100, len(to_summarize) * 10)
    est_cost = _estimate_cost_cents(est_tokens, model)
    _budget.check(est_cost)

    fn = compress_fn or _default_compress_fn
    summary_text, tokens_used = fn(to_summarize, model)

    actual_cost = _estimate_cost_cents(tokens_used, model)
    _budget.record(actual_cost)

    return CompressionResult(
        summary=summary_text,
        tail=tail,
        tokens_used=tokens_used,
        cost_cents=actual_cost,
        compressed=True,
        model_used=model,
    )


def format_reseed_prompt(
    result: CompressionResult,
    target_role: str,
) -> str:
    """Render a re-seed prompt string for the new role's first turn.

    If ``result.compressed`` is False (no-op), formats the tail directly.
    Otherwise: "[Summary so far] ... [Recent messages] ...".

    The concrete text is deterministic — tests assert on the exact shape.
    """
    lines: list[str] = [f"[Handoff to {target_role}]"]
    if result.compressed and result.summary:
        lines.append("")
        lines.append("[Conversation summary so far]")
        lines.append(result.summary)
    lines.append("")
    lines.append("[Recent messages]")
    for msg in result.tail:
        role = getattr(msg, "role", "unknown")
        content = getattr(msg, "content", "")
        lines.append(f"  {role}: {content}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# Default LLM caller (production) — stub for M3; real impl via cc_pool T4S.7b
# ──────────────────────────────────────────────────────────────────────────


def _default_compress_fn(messages: list[Any], model: str) -> tuple[str, int]:
    """Default compression LLM call.  M3 stub — returns a deterministic
    heuristic summary so the plumbing works without network.

    Production integration with cc_pool.acquire(role='dream') is a T4S.7b
    follow-up (after M3-2 acceptance of the integration surface).  The
    stub here is deliberate: it guarantees the compressor ships with a
    working default even when API keys are missing, and lets tests cover
    the full compressor path without injecting a mock each time.
    """
    # Crude heuristic: concatenate first 200 chars of each message
    chunks: list[str] = []
    for msg in messages:
        role = getattr(msg, "role", "unknown")
        content = getattr(msg, "content", "")[:200]
        chunks.append(f"- {role}: {content}")
    summary = (
        f"[Heuristic summary of {len(messages)} messages — "
        f"M3 stub pending T4S.7b cc_pool integration]\n"
        + "\n".join(chunks[:10])  # cap visible lines
        + (f"\n...and {len(chunks) - 10} more." if len(chunks) > 10 else "")
    )
    # Approximate tokens (1 token ≈ 4 chars for English; CJK is ~1 char/token)
    tokens_used = max(1, len(summary) // 3)
    return summary, tokens_used
