"""SLA hooks parity with WS path. Spec §11."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.integrations.general_bot._helpers import seed_api_key


@pytest.mark.asyncio
async def test_first_reply_ms_recorded(sandbox_dir: Path, monkeypatch):
    monkeypatch.setenv("CONV_PERSIST", "0")
    monkeypatch.setenv("DREAM_SCHEDULER_DISABLED", "1")
    monkeypatch.setenv("GENERAL_BOT_ENABLED", "1")
    monkeypatch.setenv("POOL_MODE", "1")

    recorded: list[tuple] = []

    class _SLAStub:
        def record(self, metric, value):
            recorded.append((metric, value))

    monkeypatch.setattr(
        "autoservice.api_routes.get_sla_aggregator", lambda: _SLAStub(),
    )

    class _Pool:
        def session_query(self, conv_id, prompt, **kw):
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
            tenant_id = "tenantA"; triage_dispatch_enabled = True
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

    raw_key = seed_api_key(sandbox_dir, "tenantA")
    from autoservice.web_gateway import create_app
    app = create_app()
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"query": "hi", "inquiryID": "sla-1"},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert r.status_code == 200
    metric_names = [m.name if hasattr(m, "name") else str(m) for m, _ in recorded]
    assert any("FIRST_REPLY_MS" in n for n in metric_names)
    assert any("TTFB_MS" in n for n in metric_names)
