"""Feature-flag rollback (§7.3)."""
from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import Participant, ParticipantRole
from autoservice.model_router import FastClassifier
from autoservice.triage_dispatch import triage_and_route
from autoservice.triage_config_loader import TenantTriageConfig


@pytest.fixture(autouse=True)
def _clear_classifier_cache():
    FastClassifier.clear_tenant_cache()
    yield
    FastClassifier.clear_tenant_cache()


@pytest_asyncio.fixture()
async def engine():
    return LocalEngine()


async def _seed_participants(engine: LocalEngine, conv_id: str) -> None:
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
async def test_triage_still_writes_decision_when_flag_is_true(engine):
    conv = await engine.create_conversation(channel="web", external_id="f1")
    await _seed_participants(engine, conv.id)
    cfg = TenantTriageConfig(tenant_id="acme", triage_dispatch_enabled=True)
    await triage_and_route(engine=engine, conv_id=conv.id,
                           customer_text="我想买", tenant_config=cfg)
    msgs = await engine.get_messages(conv.id, limit=50)
    assert any(m.source == "triage" for m in msgs)


@pytest.mark.asyncio
async def test_feature_flag_default_true(engine):
    cfg = TenantTriageConfig(tenant_id="acme")
    assert cfg.triage_dispatch_enabled is True
