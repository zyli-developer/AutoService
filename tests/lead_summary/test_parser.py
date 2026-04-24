"""Tests for ``autoservice.lead_summary`` — parse & strip the lead-role
``[线索] 联系方式: ... | 需求: ... | 预算: ... | 时间线: ... | 意向: ...`` line.

Pattern mirrors :mod:`autoservice.handoff` / :mod:`autoservice.sentiment`:
``(result, cleaned_output)`` — the cleaned output has the directive line
stripped and is what gets sent to the customer.

Source of the directive: ``agents/lead/soul.md`` §输出格式 ("在 side channel
输出结构化摘要"). The soul said side-channel but there was no side-channel
wiring, so the line leaked into the customer-visible message. This parser
is that missing side-channel.
"""
from __future__ import annotations

from autoservice.lead_summary import (
    LeadSummaryResult,
    MAX_FIELD_CHARS,
    VALID_INTENTS,
    parse_lead_summary,
)


# ──────────────────────────────────────────────────────────────────────────
# Happy path — exact shape from soul.md / production screenshot
# ──────────────────────────────────────────────────────────────────────────


def test_parse_real_production_line():
    """The exact line that leaked in the 2026-04-22 copilot screenshot."""
    text = (
        "方便的话，留个联系方式，我们的商务同事可以为您出一份详细的定制报价单 :)\n\n"
        "[线索] 联系方式: 未获取 | 需求: 美国免费电话(Toll-Free)号码及定价 | "
        "预算: 未获取 | 时间线: 未获取 | 意向: warm"
    )
    result, cleaned = parse_lead_summary(text)
    assert result is not None
    assert result.contact == "未获取"
    assert result.demand == "美国免费电话(Toll-Free)号码及定价"
    assert result.budget == "未获取"
    assert result.timeline == "未获取"
    assert result.intent == "warm"
    # Directive line stripped, customer reply preserved
    assert "[线索]" not in cleaned
    assert "方便的话，留个联系方式" in cleaned


def test_parse_hot_intent():
    text = "[线索] 联系方式: 13800138000 | 需求: 企业套餐 | 预算: 5万/月 | 时间线: 本周 | 意向: hot"
    result, cleaned = parse_lead_summary(text)
    assert result is not None
    assert result.contact == "13800138000"
    assert result.demand == "企业套餐"
    assert result.budget == "5万/月"
    assert result.timeline == "本周"
    assert result.intent == "hot"
    assert cleaned == ""  # entire text was the directive


def test_parse_cold_intent():
    text = "[线索] 联系方式: 未获取 | 需求: 一般咨询 | 预算: 未获取 | 时间线: 未获取 | 意向: cold"
    result, _ = parse_lead_summary(text)
    assert result is not None
    assert result.intent == "cold"


# ──────────────────────────────────────────────────────────────────────────
# Intent normalization
# ──────────────────────────────────────────────────────────────────────────


def test_intent_normalized_to_lowercase():
    text = "[线索] 联系方式: a | 需求: b | 预算: c | 时间线: d | 意向: WARM"
    result, _ = parse_lead_summary(text)
    assert result.intent == "warm"


def test_all_valid_intents():
    for intent in VALID_INTENTS:
        text = f"[线索] 联系方式: x | 需求: x | 预算: x | 时间线: x | 意向: {intent}"
        result, _ = parse_lead_summary(text)
        assert result is not None
        assert result.intent == intent


def test_unknown_intent_still_parsed_and_stripped():
    """Unknown intent — we still strip the line (primary goal is no leak).
    ``intent`` holds the raw token; consumers can filter.
    """
    text = "[线索] 联系方式: a | 需求: b | 预算: c | 时间线: d | 意向: lukewarm"
    result, cleaned = parse_lead_summary(text)
    assert result is not None
    assert result.intent == "lukewarm"  # preserved, not validated-away
    assert "[线索]" not in cleaned


# ──────────────────────────────────────────────────────────────────────────
# Stripping behavior
# ──────────────────────────────────────────────────────────────────────────


def test_strips_entire_directive_line_including_surrounding_blank_lines():
    text = (
        "好的，我已经记录您的需求。\n"
        "\n"
        "[线索] 联系方式: test@example.com | 需求: x | 预算: x | 时间线: x | 意向: warm\n"
        "\n"
    )
    _, cleaned = parse_lead_summary(text)
    assert "[线索]" not in cleaned
    assert "联系方式" not in cleaned  # the label must go too
    assert "好的，我已经记录您的需求。" in cleaned
    # No trailing orphaned blank block
    assert cleaned.rstrip() == "好的，我已经记录您的需求。"


def test_directive_at_start_of_output():
    text = "[线索] 联系方式: x | 需求: y | 预算: z | 时间线: w | 意向: hot\n客户您好"
    _, cleaned = parse_lead_summary(text)
    assert "[线索]" not in cleaned
    assert "客户您好" in cleaned


def test_directive_in_middle_of_output():
    text = (
        "前面的话\n"
        "[线索] 联系方式: x | 需求: y | 预算: z | 时间线: w | 意向: warm\n"
        "后面的话"
    )
    _, cleaned = parse_lead_summary(text)
    assert "[线索]" not in cleaned
    assert "前面的话" in cleaned
    assert "后面的话" in cleaned


# ──────────────────────────────────────────────────────────────────────────
# Whitespace / full-width variance
# ──────────────────────────────────────────────────────────────────────────


def test_fullwidth_colon_accepted():
    """LLMs sometimes emit Chinese full-width colon ``：`` instead of ``:``."""
    text = "[线索] 联系方式：a | 需求：b | 预算：c | 时间线：d | 意向：hot"
    result, _ = parse_lead_summary(text)
    assert result is not None
    assert result.contact == "a"
    assert result.intent == "hot"


def test_extra_whitespace_around_separators():
    text = "[线索]    联系方式:  a   |   需求: b  |  预算: c  |  时间线: d  |  意向: warm"
    result, _ = parse_lead_summary(text)
    assert result is not None
    assert result.contact == "a"
    assert result.demand == "b"


def test_values_with_special_chars():
    """Values may contain punctuation, parens, digits, slashes — but NOT the
    pipe separator. Pipe would break the format, so the LLM is told not to
    use it."""
    text = "[线索] 联系方式: 13800138000 / test@example.com | 需求: API + Webhook (v2) | 预算: HKD 50k/月 | 时间线: Q3 2026 | 意向: hot"
    result, _ = parse_lead_summary(text)
    assert result is not None
    assert "@example.com" in result.contact
    assert "Webhook" in result.demand
    assert "HKD" in result.budget
    assert "Q3" in result.timeline


# ──────────────────────────────────────────────────────────────────────────
# Absent / malformed → None, no strip
# ──────────────────────────────────────────────────────────────────────────


def test_no_directive_returns_none():
    text = "just a friendly reply, no lead summary"
    result, cleaned = parse_lead_summary(text)
    assert result is None
    assert cleaned == text  # unchanged


def test_empty_input():
    result, cleaned = parse_lead_summary("")
    assert result is None
    assert cleaned == ""


def test_partial_directive_missing_intent_rejected():
    """Missing required ``意向:`` field → regex fails → treat as free text."""
    text = "[线索] 联系方式: a | 需求: b | 预算: c | 时间线: d"
    result, cleaned = parse_lead_summary(text)
    assert result is None
    assert cleaned == text


def test_wrong_marker_rejected():
    """Only exact ``[线索]`` marker matches. ``[Lead]`` / ``[线]`` do not."""
    text = "[Lead] 联系方式: a | 需求: b | 预算: c | 时间线: d | 意向: hot"
    result, cleaned = parse_lead_summary(text)
    assert result is None
    assert cleaned == text


def test_field_order_is_fixed():
    """Soul-prescribed order: 联系方式 → 需求 → 预算 → 时间线 → 意向.
    Any other order → no match (keeps the regex deterministic)."""
    text = "[线索] 需求: b | 联系方式: a | 预算: c | 时间线: d | 意向: hot"
    result, _ = parse_lead_summary(text)
    assert result is None


# ──────────────────────────────────────────────────────────────────────────
# Multiple occurrences
# ──────────────────────────────────────────────────────────────────────────


def test_multiple_directives_all_stripped_first_returned():
    """If the LLM emits two summaries (rare, but possible on re-seed), first
    wins, all are stripped — mirrors handoff.py behaviour."""
    text = (
        "[线索] 联系方式: a | 需求: b | 预算: c | 时间线: d | 意向: warm\n"
        "[线索] 联系方式: e | 需求: f | 预算: g | 时间线: h | 意向: hot"
    )
    result, cleaned = parse_lead_summary(text)
    assert result is not None
    assert result.contact == "a"  # first wins
    assert "[线索]" not in cleaned


# ──────────────────────────────────────────────────────────────────────────
# Long field truncation
# ──────────────────────────────────────────────────────────────────────────


def test_overlong_field_truncated():
    long_demand = "x" * (MAX_FIELD_CHARS + 100)
    text = f"[线索] 联系方式: a | 需求: {long_demand} | 预算: c | 时间线: d | 意向: warm"
    result, cleaned = parse_lead_summary(text)
    assert result is not None
    assert len(result.demand) == MAX_FIELD_CHARS
    assert "[线索]" not in cleaned


# ──────────────────────────────────────────────────────────────────────────
# Return contract
# ──────────────────────────────────────────────────────────────────────────


def test_result_is_immutable_dataclass():
    import pytest
    text = "[线索] 联系方式: a | 需求: b | 预算: c | 时间线: d | 意向: warm"
    result, _ = parse_lead_summary(text)
    with pytest.raises(Exception):
        result.intent = "hot"  # type: ignore[misc]  # frozen


def test_return_tuple_shape_on_miss():
    out = parse_lead_summary("plain text")
    assert isinstance(out, tuple)
    assert len(out) == 2
    assert out[0] is None
    assert isinstance(out[1], str)


def test_raw_line_captured():
    text = "hi\n[线索] 联系方式: a | 需求: b | 预算: c | 时间线: d | 意向: warm\nbye"
    result, _ = parse_lead_summary(text)
    assert result is not None
    assert "[线索]" in result.raw_line
    assert "意向: warm" in result.raw_line


def test_to_log_fields_returns_flat_dict():
    """Helper for structured logging — caller does ``logger.info(..., extra=r.to_log_fields())``."""
    text = "[线索] 联系方式: a | 需求: b | 预算: c | 时间线: d | 意向: warm"
    result, _ = parse_lead_summary(text)
    fields = result.to_log_fields()
    assert fields == {
        "lead_contact": "a",
        "lead_demand": "b",
        "lead_budget": "c",
        "lead_timeline": "d",
        "lead_intent": "warm",
    }
