"""triage_and_route() orchestrator."""
from __future__ import annotations

import pytest
import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    MessageVisibility,
    ParticipantRole,
)
from autoservice.model_router import TriageDecision
from autoservice.triage_dispatch import triage_and_route


class _FakeTenantConfig:
    tenant_id = "acme"
    supported_languages = ["zh", "en"]
    history_reseed_token_limit = 2000


@pytest_asyncio.fixture()
async def engine():
    return LocalEngine()


@pytest.mark.asyncio
async def test_writes_triage_side_message(engine, monkeypatch):
    conv = await engine.create_conversation(channel="web", external_id="d1")

    async def _fake_route(self, message, **kw):
        return TriageDecision(
            role="lead", confidence=0.9, source="fastpath",
            intent="purchase_intent", detected_language="zh",
            previous_role=None,
        )
    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter.route_message", _fake_route,
    )

    decision = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="我想买一个", tenant_config=_FakeTenantConfig(),
    )
    assert decision.role == "lead"

    msgs = await engine.get_messages(conv.id, limit=50)
    triage_msgs = [m for m in msgs if m.source == "triage"]
    assert len(triage_msgs) == 1
    m = triage_msgs[0]
    assert m.visibility == MessageVisibility.SIDE
    assert m.metadata["type"] == "triage_decision"
    assert m.metadata["route_to"] == "lead"
    assert m.metadata["source"] == "fastpath"


@pytest.mark.asyncio
async def test_updates_active_role_and_resets_drift_on_stable(engine, monkeypatch):
    conv = await engine.create_conversation(channel="web", external_id="d2")
    await engine.update_triage_state(conv.id, active_role="customer", drift_counter=2)

    async def _fake_route(self, message, **kw):
        return TriageDecision(
            role="customer", confidence=0.9, source="fastpath",
            intent="general_question", detected_language="zh",
            previous_role="customer",
        )
    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter.route_message", _fake_route,
    )

    await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="你好", tenant_config=_FakeTenantConfig(),
    )
    st = await engine.get_triage_state(conv.id)
    assert st["active_role"] == "customer"


@pytest.mark.asyncio
async def test_translate_barrier_fastpath(engine, monkeypatch):
    conv = await engine.create_conversation(channel="web", external_id="d3")

    async def _fake_route(self, message, **kw):
        return TriageDecision(
            role="translate", confidence=0.9, source="fastpath",
            intent="language_barrier", detected_language="ja",
            previous_role=None,
        )
    monkeypatch.setattr(
        "autoservice.model_router.ModelRouter.route_message", _fake_route,
    )
    decision = await triage_and_route(
        engine=engine, conv_id=conv.id,
        customer_text="こんにちは", tenant_config=_FakeTenantConfig(),
    )
    assert decision.role == "translate"
