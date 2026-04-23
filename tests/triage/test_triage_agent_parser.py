"""Triage agent output parser — §2.1 of the spec."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.model_router import ModelRouter, TriageDecision, _parse_triage_output


class TestParser:
    def test_happy_path(self):
        raw = "[分流] 意图: purchase_intent | 信心: 0.82 | 路由: lead | 原因: 客户询问价格"
        parsed = _parse_triage_output(raw)
        assert parsed["intent"] == "purchase_intent"
        assert parsed["confidence"] == pytest.approx(0.82)
        assert parsed["route_to"] == "lead"
        assert parsed["summary"] is None

    def test_with_summary(self):
        raw = '[分流] 意图: general_question | 信心: 0.45 | 路由: customer | 原因: 消息模糊 | 摘要: "客户说有个事想问一下"'
        parsed = _parse_triage_output(raw)
        assert parsed["confidence"] == pytest.approx(0.45)
        assert parsed["summary"] == "客户说有个事想问一下"

    def test_missing_prefix_returns_none(self):
        assert _parse_triage_output("Hello, I help route") is None

    def test_bad_confidence_returns_default(self):
        raw = "[分流] 意图: complaint | 信心: abc | 路由: customer | 原因: ..."
        parsed = _parse_triage_output(raw)
        assert parsed is not None
        assert parsed["confidence"] == 0.5   # default fallback

    def test_invalid_role_coerced_to_customer(self):
        raw = "[分流] 意图: complaint | 信心: 0.9 | 路由: admin | 原因: ..."
        parsed = _parse_triage_output(raw)
        assert parsed["route_to"] == "customer"


class _FakeTenantConfig:
    tenant_id = "acme"
    supported_languages = ["zh", "en"]


@pytest.mark.asyncio
async def test_low_confidence_triggers_triage_agent_call(monkeypatch):
    """When FastClassifier confidence < medium AND the agent flag is on,
    triage agent is invoked. Default (flag off as of 2026-04-23) skips
    the agent — see test_fastclassifier_coverage.py for that path."""
    monkeypatch.setenv("TRIAGE_AGENT_ENABLED", "1")
    engine = LocalEngine()
    conv = await engine.create_conversation(channel="web", external_id="c-tri")

    captured_prompts: list[str] = []

    async def _fake_one_shot(self, msg: str, tenant_id: str | None) -> str:
        captured_prompts.append(msg)
        return "[分流] 意图: general_question | 信心: 0.7 | 路由: customer | 原因: 消息模糊"

    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter._triage_agent_one_shot",
        _fake_one_shot,
    )

    r = ModelRouter()
    decision = await r.route_message(
        "嗯", tenant_config=_FakeTenantConfig(),
        conv_id=conv.id, engine=engine,
    )
    assert decision.source == "triage_agent"
    assert decision.role == "customer"
    assert captured_prompts, "expected triage agent to be called"


@pytest.mark.asyncio
async def test_triage_agent_timeout_falls_back(monkeypatch):
    monkeypatch.setenv("TRIAGE_AGENT_ENABLED", "1")
    engine = LocalEngine()
    conv = await engine.create_conversation(channel="web", external_id="c-tri2")

    async def _fake_one_shot(self, msg: str, tenant_id: str | None) -> str:
        raise asyncio.TimeoutError("triage too slow")

    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter._triage_agent_one_shot",
        _fake_one_shot,
    )

    r = ModelRouter()
    decision = await r.route_message(
        "嗯", tenant_config=_FakeTenantConfig(),
        conv_id=conv.id, engine=engine,
    )
    assert decision.source == "fallback"
    assert decision.needs_operator_notice is True
