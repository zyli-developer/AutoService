"""QUEUE_ENABLED=0 falls back to fire-and-forget concurrent dispatch."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.integrations.general_bot._helpers import seed_api_key


@pytest.fixture
def queueless_app(sandbox_dir: Path, monkeypatch):
    monkeypatch.setenv("CONV_PERSIST", "0")
    monkeypatch.setenv("DREAM_SCHEDULER_DISABLED", "1")
    monkeypatch.setenv("GENERAL_BOT_ENABLED", "1")
    monkeypatch.setenv("POOL_MODE", "1")
    monkeypatch.setenv("QUEUE_ENABLED", "0")  # the switch under test

    class _Pool:
        def session_query(self, conv_id, prompt, *, tenant_id=None, tier=None):
            from claude_agent_sdk.types import StreamEvent
            async def _gen():
                yield StreamEvent(
                    uuid="u", session_id="s",
                    event={"type": "content_block_delta",
                           "delta": {"type": "text_delta", "text": "ok"}},
                )
            return _gen()
    async def fake_get_pool():
        return _Pool()
    monkeypatch.setattr("autoservice.web_gateway._get_pool", fake_get_pool)

    from autoservice.model_router import TriageDecision
    async def fake_triage(*, engine, conv_id, customer_text, tenant_config):
        return TriageDecision(
            role="customer", intent="general_question", confidence=0.9,
            source="stub", summary=None, detected_language="en",
            previous_role=None, direct_reply=None, tier="fast",
        )
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline.triage_and_route",
        fake_triage,
    )
    async def fake_cfg(engine, conv_id):
        class _C:
            tenant_id = "tenantA"
            triage_dispatch_enabled = True
            history_reseed_token_limit = 2000
        return _C()
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline.load_tenant_config_for_conv",
        fake_cfg,
    )
    async def fake_build_prompt(*, tenant_id, customer_text, operator_suggestions):
        return customer_text
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline._build_customer_prompt",
        fake_build_prompt,
    )
    async def fake_suggestions(*a, **k):
        return ""
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline._collect_operator_suggestions",
        fake_suggestions,
    )

    from autoservice.web_gateway import create_app
    return create_app()


def test_queue_disabled_still_serves_request(queueless_app, sandbox_dir):
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    with TestClient(queueless_app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"query": "hi", "inquiryID": "noqueue-1"},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert r.status_code == 200
    assert r.json() == {"message": {"type": 1, "text": "ok"}}
