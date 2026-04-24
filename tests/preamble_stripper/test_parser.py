"""Tests for ``autoservice.preamble_stripper`` — strip the "meta monologue"
block some customer-role replies emit before the actual answer.

Anchor case: the 2026-04-23 cinnox screenshot where the model emitted
"根据我的系统提示，作为 CINNOX 客服代理，我可以直接基于知识库给出回复。
让我回应客户：" ahead of the real reply, and the entire block reached
the customer.

Contract (mirrors :mod:`autoservice.lead_summary`): ``(preamble, cleaned)``
— ``preamble`` is None when nothing was stripped; when stripping
happened, the caller emits ``preamble`` on SIDE and ``cleaned`` on
PUBLIC.
"""
from __future__ import annotations

from autoservice.preamble_stripper import parse_customer_preamble


# ──────────────────────────────────────────────────────────────────────────
# Happy path — exact shapes we've observed leak
# ──────────────────────────────────────────────────────────────────────────


def test_strip_production_leak_2026_04_23():
    """Exact wording that reached the customer in the cinnox screenshot."""
    text = (
        "根据我的系统提示，作为 CINNOX 客服代理，我可以直接基于知识库给出回复。"
        "让我回应客户：\n"
        "您好！ 😊 我是 CINNOX 的 AI 助手。\n"
        "我们为企业提供全渠道联络中心平台，主要服务包括：\n"
        "1. 云联络中心 — IVR 自动应答、Enquiry 路由、多角色团队管理"
    )
    preamble, cleaned = parse_customer_preamble(text)
    assert preamble is not None
    assert "作为 CINNOX 客服代理" in preamble
    assert "让我回应客户" in preamble
    # Customer-visible reply preserved intact
    assert cleaned.startswith("您好！")
    assert "CINNOX 的 AI 助手" in cleaned
    assert "云联络中心" in cleaned
    # No meta phrases leak into the cleaned body
    assert "系统提示" not in cleaned
    assert "让我回应客户" not in cleaned


def test_strip_role_self_reference_with_paragraph_break():
    """Preamble ends with period + blank line rather than a colon."""
    text = (
        "作为 AutoService 的 AI 客服助手，我需要先理解客户的问题。\n"
        "\n"
        "您好！关于您询问的开通时效，Professional 套餐下香港 DID "
        "通常 1 个工作日完成 PSTN 对接。"
    )
    preamble, cleaned = parse_customer_preamble(text)
    assert preamble is not None
    assert "作为 AutoService" in preamble
    assert cleaned.startswith("您好！")
    assert "1 个工作日" in cleaned


def test_strip_english_preamble():
    """English-language leak (same shape, different words)."""
    text = (
        "As the customer service assistant, I should consult the "
        "knowledge base before replying. Let me respond to the customer:\n"
        "Hello! Our Professional plan includes 3 local DID numbers "
        "and 500 IDD minutes per month."
    )
    preamble, cleaned = parse_customer_preamble(text)
    assert preamble is not None
    assert "Let me respond to the customer" in preamble
    assert cleaned.startswith("Hello!")
    assert "Professional plan" in cleaned


def test_strip_i_can_directly_based_on_kb():
    """'我可以直接基于知识库回答' variant without the colon 'let me respond:'."""
    text = (
        "我可以直接基于知识库给出回答。\n"
        "\n"
        "香港本地 DID 申请后 1 个工作日内完成 PSTN 对接。"
    )
    preamble, cleaned = parse_customer_preamble(text)
    assert preamble is not None
    assert "知识库" in preamble
    assert cleaned.startswith("香港本地 DID")


# ──────────────────────────────────────────────────────────────────────────
# Fail-closed — must NOT strip
# ──────────────────────────────────────────────────────────────────────────


def test_no_preamble_plain_reply():
    text = "您好！请问有什么可以帮您？"
    preamble, cleaned = parse_customer_preamble(text)
    assert preamble is None
    assert cleaned == text


def test_no_preamble_when_reply_starts_with_greeting():
    """Legitimate greeting reply, no meta narration — must pass through."""
    text = (
        "您好，我是 CINNOX 的 AI 助手。\n"
        "请问您想了解哪方面的服务？"
    )
    preamble, cleaned = parse_customer_preamble(text)
    assert preamble is None
    assert cleaned == text


def test_no_preamble_when_customer_quoted_as_agent_role():
    """Reply mentions 'as an AI assistant' mid-sentence — shouldn't trigger.

    The split-point search requires colon+newline OR paragraph break,
    so a mid-sentence mention without that structure won't match.
    """
    text = "作为 AI 助手我很乐意帮您解答关于套餐的问题。"
    preamble, cleaned = parse_customer_preamble(text)
    assert preamble is None
    assert cleaned == text


def test_no_preamble_when_body_would_be_too_short():
    """Stripping would leave a stump — must fail closed."""
    text = "作为 CINNOX 客服代理，让我回应客户：\n好的。"
    preamble, cleaned = parse_customer_preamble(text)
    # "好的。" is 3 chars, below _MIN_BODY_CHARS — refuse to strip.
    assert preamble is None
    assert cleaned == text


def test_no_preamble_when_split_marker_missing():
    """No colon-newline, no paragraph break — keep everything."""
    text = (
        "作为 CINNOX 的 AI 客服代理，我很乐意帮您解答这个问题。"
        "Professional 套餐包含 3 个本地 DID。"
    )
    preamble, cleaned = parse_customer_preamble(text)
    assert preamble is None
    assert cleaned == text


def test_no_preamble_when_leading_head_has_no_meta_marker():
    """Head has colon+newline split but no meta phrase — leave alone."""
    text = (
        "关于您的问题：\n"
        "Professional 套餐包含 3 个本地 DID 和 500 分钟 IDD。"
    )
    preamble, cleaned = parse_customer_preamble(text)
    assert preamble is None
    assert cleaned == text


def test_empty_input():
    preamble, cleaned = parse_customer_preamble("")
    assert preamble is None
    assert cleaned == ""


def test_whitespace_only_input():
    preamble, cleaned = parse_customer_preamble("   \n\n\t  ")
    assert preamble is None
    assert cleaned == "   \n\n\t  "


# ──────────────────────────────────────────────────────────────────────────
# Robustness
# ──────────────────────────────────────────────────────────────────────────


def test_preserves_body_whitespace_but_trims_edges():
    """Internal newlines / spacing in the body are preserved; outer
    whitespace around the stripped block is trimmed."""
    text = (
        "  根据我的系统提示，让我回应客户：\n\n"
        "第一段内容。\n\n第二段内容，换行也应该保留。  "
    )
    preamble, cleaned = parse_customer_preamble(text)
    assert preamble is not None
    assert cleaned == "第一段内容。\n\n第二段内容，换行也应该保留。"


def test_very_long_preamble_bailout():
    """Preamble longer than the scan window → no split found in window
    → fail-closed (keep text). Prevents adversarial/degenerate input
    from eating a huge chunk."""
    text = "作为 AI 助手 " + ("啊" * 500) + "\n\n真正的回答。"
    preamble, cleaned = parse_customer_preamble(text)
    assert preamble is None
    assert cleaned == text
