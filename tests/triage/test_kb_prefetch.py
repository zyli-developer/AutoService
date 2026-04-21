"""Tests for _build_customer_prompt — KB pre-fetch + prompt assembly."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_kb_hits_inserted_into_prompt():
    """KB hits become a <kb_context> block with source/section headers."""
    hits = [
        {
            "content": "DID 开通需要 1 个工作日",
            "source_name": "faq",
            "section": "DID",
            "domain": "",
        },
    ]
    with patch("autoservice.dream_agent.kb_search", return_value=hits):
        from autoservice.triage_dispatch import _build_customer_prompt
        prompt = await _build_customer_prompt(
            tenant_id="mystore",
            customer_text="DID 多久开通",
            operator_suggestions="",
        )

    assert "<kb_context>" in prompt
    assert "</kb_context>" in prompt
    assert "[1] faq · DID" in prompt
    assert "DID 开通需要 1 个工作日" in prompt
    assert "Customer message: DID 多久开通" in prompt


@pytest.mark.asyncio
async def test_kb_empty_hits_no_context_block():
    """No KB hits → no <kb_context> block; customer_text + tail only."""
    with patch("autoservice.dream_agent.kb_search", return_value=[]):
        from autoservice.triage_dispatch import _build_customer_prompt
        prompt = await _build_customer_prompt(
            tenant_id="mystore",
            customer_text="hello",
            operator_suggestions="",
        )

    assert "<kb_context>" not in prompt
    assert "Customer message: hello" in prompt


@pytest.mark.asyncio
async def test_kb_not_queried_when_tenant_id_is_none():
    """tenant_id=None → skip KB entirely."""
    called = []

    def spy(*args, **kwargs):
        called.append((args, kwargs))
        return []

    with patch("autoservice.dream_agent.kb_search", side_effect=spy):
        from autoservice.triage_dispatch import _build_customer_prompt
        await _build_customer_prompt(
            tenant_id=None,
            customer_text="hi",
            operator_suggestions="",
        )

    assert called == []


@pytest.mark.asyncio
async def test_kb_prefetch_exception_is_swallowed():
    """KB query exception → prompt built without <kb_context>, no crash."""
    with patch(
        "autoservice.dream_agent.kb_search",
        side_effect=RuntimeError("db missing"),
    ):
        from autoservice.triage_dispatch import _build_customer_prompt
        prompt = await _build_customer_prompt(
            tenant_id="mystore",
            customer_text="hi",
            operator_suggestions="",
        )

    assert "<kb_context>" not in prompt
    assert "Customer message: hi" in prompt


@pytest.mark.asyncio
async def test_operator_suggestions_preserved():
    """If operator_suggestions is non-empty, it appears at the top."""
    with patch("autoservice.dream_agent.kb_search", return_value=[]):
        from autoservice.triage_dispatch import _build_customer_prompt
        prompt = await _build_customer_prompt(
            tenant_id="mystore",
            customer_text="hi",
            operator_suggestions="<operator_suggestions>\nbe terse\n</operator_suggestions>",
        )

    assert prompt.startswith("<operator_suggestions>")
    assert "be terse" in prompt
    assert "Customer message: hi" in prompt


@pytest.mark.asyncio
async def test_kb_content_truncated_to_500_chars():
    """Each hit content is clipped at 500 chars to bound prompt size."""
    long_content = "x" * 800
    hits = [{"content": long_content, "source_name": "big"}]
    with patch("autoservice.dream_agent.kb_search", return_value=hits):
        from autoservice.triage_dispatch import _build_customer_prompt
        prompt = await _build_customer_prompt(
            tenant_id="mystore",
            customer_text="hi",
            operator_suggestions="",
        )

    # content block contains exactly 500 x's, not 800
    assert "x" * 500 in prompt
    assert "x" * 501 not in prompt
