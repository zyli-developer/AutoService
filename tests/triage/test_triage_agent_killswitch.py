"""Regression lock for the ``TRIAGE_AGENT_ENABLED`` kill-switch
(2026-04-23).

When the env flag is off (the new default), ``ModelRouter.route_message``
must skip the haiku triage agent fallback even if FastClassifier
confidence is below the medium threshold, and return a decision built
from the fast result via ``_triage_fallback``. When the flag is on,
legacy behavior is preserved (agent invoked on low confidence).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.model_router import ModelRouter, TriageDecision


class _StaticTenantConfig:
    def __init__(self, supported=("zh", "en")):
        self.supported_languages = list(supported)
        self.tenant_id = "acme"


@pytest_asyncio.fixture()
async def engine() -> LocalEngine:
    return LocalEngine()


@pytest_asyncio.fixture()
async def conv_id(engine):
    conv = await engine.create_conversation(channel="web", external_id="cdec")
    return conv.id


class TestTriageAgentKillSwitch:

    @pytest.mark.asyncio
    async def test_agent_skipped_by_default_when_low_confidence(
        self, engine, conv_id, monkeypatch,
    ):
        monkeypatch.delenv("TRIAGE_AGENT_ENABLED", raising=False)

        r = ModelRouter()
        tc = _StaticTenantConfig()

        # "嗯嗯" hits no keywords → general_question @ 0.4 < medium (0.6).
        # Patch the agent call to blow up so we prove it was NOT called.
        with patch.object(
            r, "_invoke_triage_agent",
            new=AsyncMock(side_effect=AssertionError("agent must be skipped")),
        ) as mk:
            decision = await r.route_message(
                "嗯嗯", tenant_config=tc, conv_id=conv_id, engine=engine,
            )

        mk.assert_not_called()
        assert isinstance(decision, TriageDecision)
        assert decision.source == "fallback"
        # FastClassifier resolved to general_question → customer.
        assert decision.role == "customer"

    @pytest.mark.asyncio
    async def test_agent_still_invoked_when_flag_on(
        self, engine, conv_id, monkeypatch,
    ):
        monkeypatch.setenv("TRIAGE_AGENT_ENABLED", "1")

        r = ModelRouter()
        tc = _StaticTenantConfig()

        # Same low-confidence message — with the flag explicitly on, the
        # agent SHOULD be invoked. Patch to return a benign fallback so
        # the test doesn't require a live pool.
        async def _fake_agent(**kwargs):
            return r._triage_fallback(
                kwargs["message"], kwargs["fast_result"],
                kwargs["detected_language"], kwargs["previous_role"],
            )

        with patch.object(
            r, "_invoke_triage_agent", new=AsyncMock(side_effect=_fake_agent),
        ) as mk:
            await r.route_message(
                "嗯嗯", tenant_config=tc, conv_id=conv_id, engine=engine,
            )

        mk.assert_called_once()

    @pytest.mark.asyncio
    async def test_fastpath_bypasses_agent_regardless_of_flag(
        self, engine, conv_id, monkeypatch,
    ):
        """High-confidence message must always go fastpath — the flag
        only controls the low-confidence branch."""
        monkeypatch.setenv("TRIAGE_AGENT_ENABLED", "1")

        r = ModelRouter()
        tc = _StaticTenantConfig()

        with patch.object(
            r, "_invoke_triage_agent",
            new=AsyncMock(side_effect=AssertionError("fastpath must skip agent")),
        ) as mk:
            decision = await r.route_message(
                "我想购买,价格多少",  # clear purchase_intent
                tenant_config=tc, conv_id=conv_id, engine=engine,
            )

        mk.assert_not_called()
        assert decision.source == "fastpath"
        assert decision.role == "lead"
