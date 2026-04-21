"""FastClassifier keyword-cleanup regression + decision-path tests.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §4.1
"""
from __future__ import annotations

import pytest

from autoservice.model_router import FastClassifier, Intent, AgentRole


class TestKeywordCleanup:
    """After T0 cleanup, `价格` routes to lead (not product_inquiry)."""

    def setup_method(self):
        # Classifier reads the singleton _config — reset it so each test
        # sees a fresh parse of the yaml on disk.
        import autoservice.model_router as mr
        mr._config = None
        self.clf = FastClassifier()

    def test_price_word_routes_to_lead(self):
        result = self.clf.classify("你们的价格是多少")
        assert result.route_to == AgentRole.LEAD
        assert result.intent == Intent.PURCHASE_INTENT

    def test_bare_question_word_does_not_trigger_complaint(self):
        # "问题" alone is too generic — without "投诉/故障/坏了/refund"
        # it must not yield complaint.
        result = self.clf.classify("有个问题想咨询一下")
        assert result.intent != Intent.COMPLAINT

    def test_how_to_use_routes_to_product_inquiry(self):
        result = self.clf.classify("这个功能怎么用")
        assert result.route_to == AgentRole.CUSTOMER
        assert result.intent == Intent.PRODUCT_INQUIRY

    def test_refund_routes_to_complaint(self):
        result = self.clf.classify("我要退款")
        assert result.intent == Intent.COMPLAINT


import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.model_router import ModelRouter, TriageDecision


@pytest_asyncio.fixture()
async def engine() -> LocalEngine:
    return LocalEngine()


@pytest_asyncio.fixture()
async def conv_id(engine):
    conv = await engine.create_conversation(channel="web", external_id="cdec")
    return conv.id


class _StaticTenantConfig:
    def __init__(self, supported=("zh", "en")):
        self.supported_languages = list(supported)
        self.tenant_id = "acme"


class TestRouteMessage:
    @pytest.mark.asyncio
    async def test_language_barrier_short_circuits_to_translate(self, engine, conv_id):
        r = ModelRouter()
        tc = _StaticTenantConfig(supported=("zh", "en"))
        decision = await r.route_message(
            "こんにちは、助けてください", tenant_config=tc,
            conv_id=conv_id, engine=engine,
        )
        assert isinstance(decision, TriageDecision)
        assert decision.role == "translate"
        assert decision.source == "fastpath"
        assert decision.detected_language == "ja"

    @pytest.mark.asyncio
    async def test_high_confidence_fastpath(self, engine, conv_id):
        r = ModelRouter()
        decision = await r.route_message(
            "我想购买你们的产品,价格多少", tenant_config=_StaticTenantConfig(),
            conv_id=conv_id, engine=engine,
        )
        assert decision.role == "lead"
        assert decision.source == "fastpath"
        assert decision.confidence >= 0.6

    @pytest.mark.asyncio
    async def test_drift_counter_increments_on_mismatch(self, engine, conv_id):
        r = ModelRouter()
        tc = _StaticTenantConfig()
        # Prime active_role = customer
        await engine.update_triage_state(conv_id, active_role="customer")
        # Send a lead-intent message → drift
        decision = await r.route_message(
            "想购买试用一下", tenant_config=tc, conv_id=conv_id, engine=engine,
        )
        state = await engine.get_triage_state(conv_id)
        assert state["drift_counter"] == 1
        assert decision.role in ("lead", "customer")

    @pytest.mark.asyncio
    async def test_drift_resets_on_match(self, engine, conv_id):
        r = ModelRouter()
        tc = _StaticTenantConfig()
        await engine.update_triage_state(conv_id, active_role="customer", drift_counter=3)
        await r.route_message(
            "怎么使用这个功能", tenant_config=tc, conv_id=conv_id, engine=engine,
        )
        state = await engine.get_triage_state(conv_id)
        assert state["drift_counter"] == 0
