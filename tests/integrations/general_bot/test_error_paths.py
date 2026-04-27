"""Watchdog (120s → terminal error) + mid-stream pool failure tests. Spec §4.5/§8."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.integrations.general_bot._helpers import (
    parse_sse_events, seed_api_key,
)


@pytest.fixture
def app_factory(sandbox_dir: Path, monkeypatch):
    """Returns a factory(make_pool) → app. Pool comes from caller."""
    monkeypatch.setenv("CONV_PERSIST", "0")
    monkeypatch.setenv("DREAM_SCHEDULER_DISABLED", "1")
    monkeypatch.setenv("GENERAL_BOT_ENABLED", "1")
    monkeypatch.setenv("POOL_MODE", "1")

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

    def make(pool):
        async def fake_get_pool():
            return pool
        monkeypatch.setattr("autoservice.web_gateway._get_pool", fake_get_pool)
        from autoservice.web_gateway import create_app
        return create_app()

    return make


def test_mid_stream_pool_error_emits_terminal(app_factory, sandbox_dir):
    class _BoomPool:
        def session_query(self, conv_id, prompt, **kw):
            from claude_agent_sdk.types import StreamEvent
            async def _gen():
                yield StreamEvent(
                    uuid="u", session_id="s",
                    event={"type": "content_block_delta",
                           "delta": {"type": "text_delta", "text": "before-error "}},
                )
                raise RuntimeError("simulated pool failure")
            return _gen()

    app = app_factory(_BoomPool())
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"query": "hi", "inquiryID": "boom"},
            headers={
                "Authorization": f"Bearer {raw_key}",
                "Accept": "text/event-stream",
            },
        )
    assert r.status_code == 200  # SSE already opened, can't change status
    events = parse_sse_events(r.content)
    terminals = [
        e for e in events
        if isinstance(e, dict) and e["message"].get("streamType") is None
    ]
    assert len(terminals) == 1
    assert "未能" in terminals[0]["message"]["text"]


def test_watchdog_timeout_emits_terminal(app_factory, sandbox_dir, monkeypatch):
    """Override default 120s timeout to 0.1s for this test."""
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.routes.RUNNER_TIMEOUT_S", 0.1,
    )

    class _HangPool:
        def session_query(self, conv_id, prompt, **kw):
            async def _gen():
                await asyncio.sleep(10)
                if False:
                    yield None  # make this an async-generator
            return _gen()

    app = app_factory(_HangPool())
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"query": "hi", "inquiryID": "hang"},
            headers={
                "Authorization": f"Bearer {raw_key}",
                "Accept": "text/event-stream",
            },
        )
    assert r.status_code == 200
    events = parse_sse_events(r.content)
    terminals = [
        e for e in events
        if isinstance(e, dict) and e["message"].get("streamType") is None
    ]
    assert len(terminals) == 1
    assert "超时" in terminals[0]["message"]["text"]
