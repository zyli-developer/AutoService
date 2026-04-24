"""End-to-end triage dispatch smoke tests.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §8.2

These exercise triage_and_route() in realistic conversation flows but stub
the CC subprocess layer — no real Claude process is spawned.
"""
from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    MessageVisibility, Participant, ParticipantRole,
)
from autoservice.model_router import FastClassifier, TriageDecision
from autoservice.triage_dispatch import triage_and_route
from autoservice.triage_config_loader import TenantTriageConfig


@pytest.fixture(autouse=True)
def _clear_classifier_cache():
    """Ensure no stale per-tenant classifier leaks from earlier test modules."""
    FastClassifier.clear_tenant_cache()
    yield
    FastClassifier.clear_tenant_cache()


@pytest_asyncio.fixture()
async def engine():
    return LocalEngine()


async def _seed_participants(engine: LocalEngine, conv_id: str) -> None:
    """Join customer/agent/triage participants so send_message doesn't reject."""
    for pid, prole in [
        ("cust", ParticipantRole.CUSTOMER),
        ("bot", ParticipantRole.AGENT),
        ("triage", ParticipantRole.TRIAGE),
    ]:
        await engine.join(
            conv_id,
            Participant(id=pid, role=prole, joined_at=datetime.now(timezone.utc)),
        )


@pytest.mark.asyncio
async def test_customer_only_unchanged(engine):
    """Keyword with unambiguous customer intent -> single customer route, no switch."""
    conv = await engine.create_conversation(channel="web", external_id="e1")
    await _seed_participants(engine, conv.id)
    cfg = TenantTriageConfig(tenant_id="acme")

    d1 = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="这个功能怎么用",  # product_inquiry -> customer
        tenant_config=cfg,
    )
    assert d1.role == "customer"
    d2 = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="还有其他功能吗",
        tenant_config=cfg,
    )
    assert d2.role == "customer"
    st = await engine.get_triage_state(conv.id)
    assert st["active_role"] == "customer"


@pytest.mark.asyncio
async def test_sales_intent_routes_to_lead(engine):
    conv = await engine.create_conversation(channel="web", external_id="e2")
    await _seed_participants(engine, conv.id)
    d = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="请问价格是多少,可以报价吗",
        tenant_config=TenantTriageConfig(tenant_id="acme"),
    )
    assert d.role == "lead"
    assert d.intent == "purchase_intent"


@pytest.mark.asyncio
async def test_language_barrier_routes_to_translate(engine):
    conv = await engine.create_conversation(channel="web", external_id="e3")
    await _seed_participants(engine, conv.id)
    d = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="こんにちは、助けてください",
        tenant_config=TenantTriageConfig(
            tenant_id="acme", supported_languages=["zh", "en"],
        ),
    )
    assert d.role == "translate"


@pytest.mark.asyncio
async def test_drift_invalidates_cache_and_switches(engine):
    conv = await engine.create_conversation(channel="web", external_id="e4")
    await _seed_participants(engine, conv.id)
    cfg = TenantTriageConfig(tenant_id="acme")
    # two product_inquiry messages establish active_role=customer
    for txt in ["怎么用", "如何使用"]:
        await triage_and_route(engine=engine, conv_id=conv.id,
                                customer_text=txt, tenant_config=cfg)
    # two purchase-intent messages should eventually flip to lead.
    # High-confidence fastpath: drift_count=1 on first (< 2, still fastpath).
    # On second: drift_count=2; can_fastpath condition fails → _invoke_triage_agent
    # is called. That raises (no CC pool in tests) → fallback returns role="lead"
    # (fast_result.route_to.value). update_triage_state then sets active_role="lead".
    for txt in ["想买一个", "给我报价"]:
        d = await triage_and_route(engine=engine, conv_id=conv.id,
                                    customer_text=txt, tenant_config=cfg)
    assert d.role == "lead"
    st = await engine.get_triage_state(conv.id)
    assert st["active_role"] == "lead"


@pytest.mark.asyncio
async def test_low_confidence_calls_triage_agent(engine, monkeypatch):
    conv = await engine.create_conversation(channel="web", external_id="e5")
    await _seed_participants(engine, conv.id)

    async def _fake_one_shot(self, message, tenant_id):
        return "[分流] 意图: general_question | 信心: 0.75 | 路由: customer | 原因: 语义不足"
    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter._triage_agent_one_shot",
        _fake_one_shot,
    )

    d = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="嗯",
        tenant_config=TenantTriageConfig(tenant_id="acme"),
    )
    assert d.source == "triage_agent"
    assert d.role == "customer"


@pytest.mark.asyncio
async def test_triage_agent_timeout_fallback(engine, monkeypatch):
    conv = await engine.create_conversation(channel="web", external_id="e6")
    await _seed_participants(engine, conv.id)

    async def _slow(self, message, tenant_id):
        await asyncio.sleep(5)
        return ""
    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter._triage_agent_one_shot",
        _slow,
    )
    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter._TRIAGE_AGENT_TIMEOUT", 0.05,
    )

    d = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="嗯",
        tenant_config=TenantTriageConfig(tenant_id="acme"),
    )
    assert d.source == "fallback"
    assert d.needs_operator_notice is True
    # SIDE message records the fallback source for operator visibility.
    msgs = await engine.get_messages(conv.id, limit=50)
    triage_msgs = [m for m in msgs if m.source == "triage"]
    assert triage_msgs and triage_msgs[-1].metadata["source"] == "fallback"


@pytest.mark.asyncio
async def test_side_visible_to_operator_only(engine):
    conv = await engine.create_conversation(channel="web", external_id="e7")
    await _seed_participants(engine, conv.id)
    await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="想买", tenant_config=TenantTriageConfig(tenant_id="acme"),
    )
    customer_view = await engine.get_messages(
        conv.id, viewer_role=ParticipantRole.CUSTOMER, limit=50,
    )
    operator_view = await engine.get_messages(
        conv.id, viewer_role=ParticipantRole.OPERATOR, limit=50,
    )
    assert not any(m.source == "triage" for m in customer_view)
    assert any(m.source == "triage" for m in operator_view)
