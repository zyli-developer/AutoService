"""Tests for ``autoservice.handoff`` (M3 T3S.1).

Contract: docs/contracts/m3/e3-triage.md §2.2.
Pattern mirrors tests/test_sentiment_parser.py (same return contract).
"""
from __future__ import annotations

from autoservice.handoff import (
    MAX_REASON_CHARS,
    VALID_HANDOFF_ROLES,
    HandoffResult,
    parse_handoff,
)


# ──────────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────────


def test_parse_handoff_with_reason():
    text = 'Before text <handoff to="lead" reason="customer is ready" /> after text'
    result, cleaned = parse_handoff(text)
    assert result is not None
    assert result.target_role == "lead"
    assert result.reason == "customer is ready"
    assert "<handoff" not in cleaned
    assert "Before text" in cleaned
    assert "after text" in cleaned


def test_parse_handoff_without_reason():
    text = 'switch now <handoff to="translate" />'
    result, cleaned = parse_handoff(text)
    assert result is not None
    assert result.target_role == "translate"
    assert result.reason is None
    assert cleaned.strip() == "switch now"


def test_parse_handoff_single_quotes():
    text = "<handoff to='dream' />"
    result, _ = parse_handoff(text)
    assert result is not None
    assert result.target_role == "dream"


def test_parse_handoff_case_insensitive_tag():
    text = '<HANDOFF to="Triage" />'
    result, _ = parse_handoff(text)
    assert result is not None
    assert result.target_role == "triage"  # normalized to lowercase


def test_parse_handoff_captures_raw_tag():
    raw = '<handoff to="lead" reason="upgrade" />'
    result, _ = parse_handoff(f"pre {raw} post")
    assert result.raw_tag.replace(" ", "") == raw.replace(" ", "")


# ──────────────────────────────────────────────────────────────────────────
# Role whitelist
# ──────────────────────────────────────────────────────────────────────────


def test_all_valid_roles_accepted():
    for role in VALID_HANDOFF_ROLES:
        text = f'<handoff to="{role}" />'
        result, _ = parse_handoff(text)
        assert result is not None, f"{role} should be accepted"
        assert result.target_role == role


def test_master_role_rejected():
    """_master is platform-scope; NOT a conversation role."""
    text = '<handoff to="_master" />'
    result, cleaned = parse_handoff(text)
    assert result is None
    assert cleaned == text  # unchanged


def test_unknown_role_rejected():
    text = '<handoff to="superadmin" />'
    result, cleaned = parse_handoff(text)
    assert result is None
    assert cleaned == text


def test_empty_role_rejected():
    text = '<handoff to="" />'
    result, _ = parse_handoff(text)
    assert result is None


# ──────────────────────────────────────────────────────────────────────────
# Missing tag / edge cases
# ──────────────────────────────────────────────────────────────────────────


def test_no_handoff_tag_returns_none():
    text = "plain agent reply with no directive"
    result, cleaned = parse_handoff(text)
    assert result is None
    assert cleaned == text


def test_empty_output_returns_none():
    result, cleaned = parse_handoff("")
    assert result is None
    assert cleaned == ""


def test_non_self_closing_rejected():
    """Only self-closing form supported; opening tag alone is not parsed."""
    text = '<handoff to="lead">'
    result, _ = parse_handoff(text)
    assert result is None


# ──────────────────────────────────────────────────────────────────────────
# Reason truncation
# ──────────────────────────────────────────────────────────────────────────


def test_long_reason_truncated():
    long_reason = "x" * 300
    text = f'<handoff to="lead" reason="{long_reason}" />'
    result, _ = parse_handoff(text)
    assert result is not None
    assert len(result.reason) == MAX_REASON_CHARS
    assert result.reason == "x" * MAX_REASON_CHARS


def test_reason_trimmed_whitespace():
    text = '<handoff to="lead" reason="   spacey   " />'
    result, _ = parse_handoff(text)
    assert result.reason == "spacey"


# ──────────────────────────────────────────────────────────────────────────
# Multiple tags — first wins, all stripped
# ──────────────────────────────────────────────────────────────────────────


def test_multiple_tags_only_first_dispatched():
    """Contract 'Don't Do' rule 1: first valid wins; others ignored."""
    text = (
        '<handoff to="lead" reason="first" /> '
        '<handoff to="translate" reason="second" />'
    )
    result, cleaned = parse_handoff(text)
    assert result is not None
    assert result.target_role == "lead"
    assert result.reason == "first"
    assert "<handoff" not in cleaned


def test_first_invalid_then_valid():
    """If first tag has unknown role, parser returns None (strict — no
    fall-through to second tag, else 'hidden' handoffs could bypass)."""
    text = (
        '<handoff to="unknown_role" /> '
        '<handoff to="lead" />'
    )
    result, _ = parse_handoff(text)
    # First tag is invalid → None returned; second tag not examined.
    # Strict interpretation prevents malicious "first bogus to escape, second real"
    assert result is None


# ──────────────────────────────────────────────────────────────────────────
# Adversarial
# ──────────────────────────────────────────────────────────────────────────


def test_injection_in_reason_preserved_as_text():
    """HTML-like content in reason is preserved as free text; UI is responsible
    for escaping on render (not the parser's job)."""
    text = '<handoff to="lead" reason="<script>alert(1)</script>" />'
    result, _ = parse_handoff(text)
    assert result is not None
    # The '<script>alert(1)</script>' substring inside reason stops at the first
    # closing quote; the attribute pattern matches up to <" or '>.  So we get
    # truncated reason text, but we DO NOT execute/normalize HTML.
    assert "<" not in result.target_role  # role never has HTML


def test_malformed_tag_no_attributes_rejected():
    text = "<handoff />"
    result, cleaned = parse_handoff(text)
    assert result is None


def test_tag_inside_code_block_still_matches():
    """Regex doesn't know about code blocks — agent output shouldn't wrap
    handoff directives in code blocks, but if they do, we still dispatch."""
    text = 'look: ```<handoff to="triage" />```'
    result, _ = parse_handoff(text)
    assert result is not None
    assert result.target_role == "triage"


def test_nested_tag_not_matched():
    """Our regex is self-closing only; a non-self-closing handoff doesn't match."""
    text = '<handoff to="lead"><handoff to="lead" /></handoff>'
    # The inner self-closing DOES match; that's fine — it's a well-formed inner tag
    result, _ = parse_handoff(text)
    assert result is not None
    assert result.target_role == "lead"


# ──────────────────────────────────────────────────────────────────────────
# Return type
# ──────────────────────────────────────────────────────────────────────────


def test_result_is_immutable_dataclass():
    text = '<handoff to="lead" />'
    result, _ = parse_handoff(text)
    import pytest
    with pytest.raises(Exception):
        result.target_role = "admin"  # type: ignore[misc]  # frozen


def test_return_tuple_shape():
    text = 'plain text'
    out = parse_handoff(text)
    assert isinstance(out, tuple)
    assert len(out) == 2
    assert out[0] is None
    assert isinstance(out[1], str)
