"""Tests for ``autoservice.history_compressor`` (M3 T4S.7).

Contract: docs/contracts/m3/e3-triage.md §4.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from autoservice.history_compressor import (
    ALLOWED_MODELS,
    COMPRESSION_THRESHOLD_MESSAGES,
    CompressionBudgetExceeded,
    CompressionResult,
    compress_for_role_switch,
    format_reseed_prompt,
    get_budget,
)


@dataclass
class _Msg:
    role: str
    content: str


def _history(n: int) -> list[_Msg]:
    return [_Msg(role="customer" if i % 2 else "agent", content=f"msg {i}") for i in range(n)]


@pytest.fixture(autouse=True)
def _reset_budget():
    get_budget().reset_for_tests()
    yield


# ──────────────────────────────────────────────────────────────────────────
# Threshold short-circuit
# ──────────────────────────────────────────────────────────────────────────


def test_below_threshold_no_op():
    result = compress_for_role_switch(
        conversation_id="c1", history=_history(5), target_role="lead"
    )
    assert result.compressed is False
    assert result.summary is None
    assert len(result.tail) == 5  # full history as tail
    assert result.tokens_used == 0
    assert result.cost_cents == 0.0
    assert result.model_used is None


def test_exactly_below_threshold_minus_one():
    result = compress_for_role_switch(
        conversation_id="c1",
        history=_history(COMPRESSION_THRESHOLD_MESSAGES - 1),
        target_role="lead",
    )
    assert result.compressed is False


def test_exactly_at_threshold_compresses():
    result = compress_for_role_switch(
        conversation_id="c1",
        history=_history(COMPRESSION_THRESHOLD_MESSAGES),
        target_role="lead",
    )
    assert result.compressed is True
    assert result.summary is not None
    assert len(result.tail) == 3  # default tail size


def test_above_threshold_splits_history_correctly():
    result = compress_for_role_switch(
        conversation_id="c1",
        history=_history(50),
        target_role="lead",
    )
    assert result.compressed is True
    assert len(result.tail) == 3
    # Tail is the LAST 3 messages
    assert result.tail[-1].content == "msg 49"
    assert result.tail[0].content == "msg 47"


# ──────────────────────────────────────────────────────────────────────────
# Model validation + defaults
# ──────────────────────────────────────────────────────────────────────────


def test_default_model_is_haiku():
    result = compress_for_role_switch(
        conversation_id="c1", history=_history(25), target_role="lead"
    )
    assert result.model_used == "haiku"


def test_sonnet_opt_in_accepted():
    result = compress_for_role_switch(
        conversation_id="c1", history=_history(25), target_role="lead",
        model="sonnet",
    )
    assert result.model_used == "sonnet"


def test_unknown_model_rejected():
    with pytest.raises(ValueError, match="model must be"):
        compress_for_role_switch(
            conversation_id="c1", history=_history(25), target_role="lead",
            model="gpt-5",
        )


def test_allowed_models_set():
    assert ALLOWED_MODELS == frozenset({"haiku", "sonnet"})


# ──────────────────────────────────────────────────────────────────────────
# Pluggable compress_fn
# ──────────────────────────────────────────────────────────────────────────


def test_pluggable_compress_fn_called():
    calls = {"n": 0}

    def fake(messages, model):
        calls["n"] += 1
        assert len(messages) == 22  # 25 - 3 tail
        return ("FAKE SUMMARY", 150)

    result = compress_for_role_switch(
        conversation_id="c1", history=_history(25), target_role="lead",
        compress_fn=fake,
    )
    assert calls["n"] == 1
    assert result.summary == "FAKE SUMMARY"
    assert result.tokens_used == 150


def test_compress_fn_not_called_below_threshold():
    calls = {"n": 0}

    def fake(messages, model):
        calls["n"] += 1
        return ("x", 0)

    compress_for_role_switch(
        conversation_id="c1", history=_history(5), target_role="lead",
        compress_fn=fake,
    )
    assert calls["n"] == 0


# ──────────────────────────────────────────────────────────────────────────
# Budget guardrail
# ──────────────────────────────────────────────────────────────────────────


def test_budget_records_cost_on_compression():
    budget = get_budget()
    assert budget.spent_cents == 0.0

    compress_for_role_switch(
        conversation_id="c1", history=_history(25), target_role="lead",
    )
    assert budget.spent_cents > 0.0


def test_budget_exceeded_raises():
    budget = get_budget()
    # Artificially pin budget at ~0 by spending up to the cap
    budget.reset_for_tests()
    # Drain via a fake fn returning huge tokens
    def big_fn(messages, model):
        return ("big", 10_000_000)  # 10M tokens — plenty to blow budget

    with pytest.raises(CompressionBudgetExceeded):
        for _ in range(10):
            compress_for_role_switch(
                conversation_id="c1", history=_history(25), target_role="lead",
                compress_fn=big_fn,
            )


def test_budget_resets_for_tests():
    budget = get_budget()
    compress_for_role_switch(
        conversation_id="c1", history=_history(25), target_role="lead",
    )
    assert budget.spent_cents > 0
    budget.reset_for_tests()
    assert budget.spent_cents == 0.0


# ──────────────────────────────────────────────────────────────────────────
# Re-seed prompt format
# ──────────────────────────────────────────────────────────────────────────


def test_format_reseed_includes_target_role():
    result = compress_for_role_switch(
        conversation_id="c1", history=_history(25), target_role="lead",
    )
    prompt = format_reseed_prompt(result, "lead")
    assert "[Handoff to lead]" in prompt


def test_format_reseed_compressed_has_summary_and_tail():
    result = compress_for_role_switch(
        conversation_id="c1", history=_history(25), target_role="lead",
    )
    prompt = format_reseed_prompt(result, "lead")
    assert "[Conversation summary so far]" in prompt
    assert "[Recent messages]" in prompt
    # Tail messages should be present verbatim
    assert "msg 22" in prompt
    assert "msg 24" in prompt


def test_format_reseed_short_skips_summary_section():
    result = compress_for_role_switch(
        conversation_id="c1", history=_history(5), target_role="lead",
    )
    prompt = format_reseed_prompt(result, "lead")
    assert "[Conversation summary so far]" not in prompt
    assert "[Recent messages]" in prompt
    assert "msg 0" in prompt
    assert "msg 4" in prompt


# ──────────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────────


def test_empty_history_below_threshold():
    result = compress_for_role_switch(
        conversation_id="c1", history=[], target_role="lead",
    )
    assert result.compressed is False
    assert result.tail == []


def test_result_is_frozen():
    result = compress_for_role_switch(
        conversation_id="c1", history=_history(5), target_role="lead",
    )
    with pytest.raises(Exception):
        result.summary = "x"  # type: ignore[misc]


def test_tail_is_copy_not_reference():
    hist = _history(10)
    result = compress_for_role_switch(
        conversation_id="c1", history=hist, target_role="lead",
    )
    # Mutating the original should not affect result
    hist.append(_Msg(role="x", content="late"))
    assert len(result.tail) == 10  # still the original 10
