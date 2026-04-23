"""Regression lock for the ``TRIAGE_AGENT_ENABLED`` kill-switch
(2026-04-23, updated same day to flip default back to on).

Default: **enabled**. The agent is invoked when FastClassifier
confidence is below the medium threshold — it provides semantic
classification + tier selection for keyword-miss messages.

Flag off (``TRIAGE_AGENT_ENABLED=0``): ``ModelRouter.route_message``
skips the agent branch and returns a decision built from the fast
result via ``_triage_fallback``. Use when you want to strictly cap
latency at the cost of tier accuracy on ambiguous messages.

Also covers the companion ``TRIAGE_AGENT_TIMEOUT_S`` env override for
the agent round-trip budget (default 8 s).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.model_router import (
    FastClassifier,
    ModelRouter,
    TriageDecision,
    _triage_agent_timeout_s,
)


@pytest.fixture(autouse=True)
def _reset_classifier_cache():
    """Other tests mutate FastClassifier._tenant_cache (overlay tests in
    particular cache an 'acme' classifier with their own intent set).
    Clearing here guarantees each kill-switch test sees the current yaml
    keyword set instead of a stale cached overlay."""
    FastClassifier.clear_tenant_cache()
    import autoservice.model_router as mr
    mr._config = None
    yield
    FastClassifier.clear_tenant_cache()
    mr._config = None


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
    async def test_agent_invoked_by_default_when_low_confidence(
        self, engine, conv_id, monkeypatch,
    ):
        """Default (no env var set): agent SHOULD be invoked on low
        confidence — needed for tier decision on keyword-miss messages."""
        monkeypatch.delenv("TRIAGE_AGENT_ENABLED", raising=False)

        r = ModelRouter()
        tc = _StaticTenantConfig()

        # "嗯嗯" hits no keywords → general_question @ 0.4 < medium (0.6).
        # Agent invocation returns a benign fallback for test isolation.
        async def _fake_agent(**kwargs):
            return r._triage_fallback(
                kwargs["message"], kwargs["fast_result"],
                kwargs["detected_language"], kwargs["previous_role"],
            )

        with patch.object(
            r, "_invoke_triage_agent", new=AsyncMock(side_effect=_fake_agent),
        ) as mk:
            decision = await r.route_message(
                "嗯嗯", tenant_config=tc, conv_id=conv_id, engine=engine,
            )

        mk.assert_called_once()
        assert isinstance(decision, TriageDecision)
        assert decision.role == "customer"

    @pytest.mark.asyncio
    async def test_agent_skipped_when_flag_off(
        self, engine, conv_id, monkeypatch,
    ):
        """Explicit opt-out: TRIAGE_AGENT_ENABLED=0 skips the agent even
        when FastClassifier confidence is below the medium threshold.
        Decision comes from _triage_fallback on the fast result."""
        monkeypatch.setenv("TRIAGE_AGENT_ENABLED", "0")

        r = ModelRouter()
        tc = _StaticTenantConfig()

        with patch.object(
            r, "_invoke_triage_agent",
            new=AsyncMock(side_effect=AssertionError("agent must be skipped")),
        ) as mk:
            decision = await r.route_message(
                "嗯嗯", tenant_config=tc, conv_id=conv_id, engine=engine,
            )

        mk.assert_not_called()
        assert decision.source == "fallback"
        assert decision.role == "customer"

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


class TestTriageAgentTimeout:
    """Regression lock for ``_triage_agent_timeout_s()`` env helper."""

    def test_default_matches_class_attribute(self, monkeypatch):
        monkeypatch.delenv("TRIAGE_AGENT_TIMEOUT_S", raising=False)
        assert _triage_agent_timeout_s() == ModelRouter._TRIAGE_AGENT_TIMEOUT

    def test_default_is_15s_on_2026_04_23(self, monkeypatch):
        """Document the bumped-to-15s default. Update if the design
        changes, but this test catches accidental reverts."""
        monkeypatch.delenv("TRIAGE_AGENT_TIMEOUT_S", raising=False)
        assert _triage_agent_timeout_s() == 15.0

    def test_env_override_parsed(self, monkeypatch):
        monkeypatch.setenv("TRIAGE_AGENT_TIMEOUT_S", "12")
        assert _triage_agent_timeout_s() == 12.0

    def test_env_accepts_float(self, monkeypatch):
        monkeypatch.setenv("TRIAGE_AGENT_TIMEOUT_S", "0.05")
        assert _triage_agent_timeout_s() == 0.05

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("TRIAGE_AGENT_TIMEOUT_S", "not-a-number")
        assert _triage_agent_timeout_s() == ModelRouter._TRIAGE_AGENT_TIMEOUT

    def test_class_attr_monkey_patch_still_wins_without_env(self, monkeypatch):
        """The E2E suite monkey-patches ``_TRIAGE_AGENT_TIMEOUT`` directly
        to 0.05 s. That path must keep working even after the env helper
        was added."""
        monkeypatch.delenv("TRIAGE_AGENT_TIMEOUT_S", raising=False)
        monkeypatch.setattr(ModelRouter, "_TRIAGE_AGENT_TIMEOUT", 0.05)
        assert _triage_agent_timeout_s() == 0.05
