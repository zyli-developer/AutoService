"""Triage direct-reply path — strategy 2 of the 2026-04-22 design.

Triage can short-circuit the customer/lead pools for pure social-pattern
messages (greeting / thanks / bye). The reply text is a hard-coded
template from classify_intent.yaml — no KB, no LLM generation — so the
"haiku gets business facts wrong" risk doesn't apply.

Coverage map (contract-level, bottom-up):
  1. FastClassifier — keyword match routes greeting/thanks/bye to
     ``AgentRole.DIRECT`` with ``direct_reply`` populated from yaml
  2. _parse_triage_output — accepts the optional `回复:` field for
     future use by a triage-agent soul; backward-compatible with the
     current 4-field + summary format
  3. TriageDecision — ``direct_reply`` propagates from FastClassifier
     through ``ModelRouter.route_message``
"""
from __future__ import annotations

import pytest

from autoservice.model_router import (
    AgentRole,
    FastClassifier,
    Intent,
    _parse_triage_output,
    _TRIAGE_ROLE_WHITELIST,
)


@pytest.fixture(autouse=True)
def _reset_config_singleton():
    """classify_intent.yaml is cached in a module global; reset so each
    test observes the on-disk file fresh."""
    import autoservice.model_router as mr
    mr._config = None
    FastClassifier.clear_tenant_cache()
    yield
    mr._config = None
    FastClassifier.clear_tenant_cache()


# ---------------------------------------------------------------------------
# FastClassifier — greeting / thanks / bye
# ---------------------------------------------------------------------------

class TestFastClassifierDirect:
    def setup_method(self):
        self.clf = FastClassifier()

    def test_greeting_routes_to_direct_with_reply(self):
        result = self.clf.classify("你好")
        assert result.route_to == AgentRole.DIRECT
        assert result.intent == Intent.GREETING
        assert result.direct_reply, "greeting must carry a direct_reply template"
        # Loose content assertion — exact wording lives in yaml.
        assert "您" in result.direct_reply or "hello" in result.direct_reply.lower()

    def test_thanks_routes_to_direct_with_reply(self):
        result = self.clf.classify("谢谢")
        assert result.route_to == AgentRole.DIRECT
        assert result.intent == Intent.THANKS
        assert result.direct_reply

    def test_bye_routes_to_direct_with_reply(self):
        result = self.clf.classify("再见")
        assert result.route_to == AgentRole.DIRECT
        assert result.intent == Intent.BYE
        assert result.direct_reply

    def test_english_greeting_routes_to_direct(self):
        result = self.clf.classify("hello")
        assert result.route_to == AgentRole.DIRECT
        assert result.intent == Intent.GREETING

    def test_non_social_message_has_no_direct_reply(self):
        """Product inquiries must NOT carry a direct_reply — they need
        the real customer agent + KB."""
        result = self.clf.classify("你们的产品怎么用")
        assert result.route_to != AgentRole.DIRECT
        assert result.direct_reply is None

    def test_purchase_intent_has_no_direct_reply(self):
        result = self.clf.classify("你们的价格是多少")
        assert result.route_to == AgentRole.LEAD
        assert result.direct_reply is None


# ---------------------------------------------------------------------------
# FastClassifier — "pure social" guard against direct-route false positives
# ---------------------------------------------------------------------------
# Regression: a message prefixed with "你好" but carrying a substantive
# business question was getting direct-routed to the greeting template
# because the raw keyword match gave greeting 0.65 and no other intent's
# keywords matched. See model_router.py `_is_pure_social`.

class TestFastClassifierPureSocialGuard:
    def setup_method(self):
        self.clf = FastClassifier()

    def test_greeting_prefix_with_business_content_routes_to_customer(self):
        """你好+实质业务内容 不能走 direct 模板。"""
        msg = (
            "你好，我们要从 Professional 升到 Enterprise，"
            "当前剩余 1200 分钟的 IDD 通话余额能跨套餐迁移吗？"
            "另外年付方案能否对公 HKD 结算？"
        )
        result = self.clf.classify(msg)
        assert result.route_to != AgentRole.DIRECT, (
            f"long business message with 你好 prefix must not direct-route "
            f"(got intent={result.intent}, route={result.route_to})"
        )
        assert result.direct_reply is None

    def test_greeting_with_question_mark_routes_to_customer(self):
        """Any `?` or `？` signals a question, not a social greeting."""
        result = self.clf.classify("你好，我能问个事吗？")
        assert result.route_to != AgentRole.DIRECT
        assert result.direct_reply is None

    def test_thanks_with_followup_content_routes_to_customer(self):
        """谢谢+追问 不应该被当作纯致谢短路掉。"""
        msg = "谢谢，但我还想了解一下 Enterprise 套餐的年付折扣政策"
        result = self.clf.classify(msg)
        assert result.route_to != AgentRole.DIRECT
        assert result.direct_reply is None

    def test_hello_with_substantive_english_content_routes_to_customer(self):
        msg = "Hello, can you tell me about the migration timeline for upgrading?"
        result = self.clf.classify(msg)
        assert result.route_to != AgentRole.DIRECT
        assert result.direct_reply is None

    def test_pure_greeting_still_routes_to_direct(self):
        """Regression guard — make sure the fix doesn't break 纯招呼."""
        for msg in ("你好", "你好啊", "您好！", "hi", "hello!"):
            result = self.clf.classify(msg)
            assert result.route_to == AgentRole.DIRECT, (
                f"pure greeting {msg!r} must still direct-route "
                f"(got {result.route_to})"
            )
            assert result.direct_reply, (
                f"pure greeting {msg!r} must carry a reply"
            )

    def test_pure_thanks_still_routes_to_direct(self):
        for msg in ("谢谢", "多谢您", "thanks!", "thank you"):
            result = self.clf.classify(msg)
            assert result.route_to == AgentRole.DIRECT
            assert result.direct_reply

    def test_pure_bye_still_routes_to_direct(self):
        for msg in ("再见", "拜拜", "bye", "goodbye"):
            result = self.clf.classify(msg)
            assert result.route_to == AgentRole.DIRECT
            assert result.direct_reply


# ---------------------------------------------------------------------------
# Triage agent output parser — accept optional `回复:` field
# ---------------------------------------------------------------------------

class TestTriageParserDirect:
    def test_direct_in_role_whitelist(self):
        assert "direct" in _TRIAGE_ROLE_WHITELIST, (
            "triage agent must be allowed to output route=direct"
        )

    def test_parses_direct_route_without_reply_field(self):
        """Backward compat — the original 4-field + summary format still
        parses, even when the role is the new ``direct`` value."""
        raw = "[分流] 意图: greeting | 信心: 0.90 | 路由: direct | 原因: 招呼语"
        parsed = _parse_triage_output(raw)
        assert parsed is not None
        assert parsed["route_to"] == "direct"
        assert parsed.get("direct_reply") is None

    def test_parses_direct_route_with_reply_field(self):
        raw = (
            '[分流] 意图: greeting | 信心: 0.92 | 路由: direct | '
            '原因: 招呼语 | 回复: "您好,请问有什么可以帮您?"'
        )
        parsed = _parse_triage_output(raw)
        assert parsed is not None
        assert parsed["route_to"] == "direct"
        assert parsed["direct_reply"] == "您好,请问有什么可以帮您?"

    def test_parses_summary_and_reply_fields_together(self):
        """Reply can coexist with summary; both are optional."""
        raw = (
            '[分流] 意图: thanks | 信心: 0.88 | 路由: direct | '
            '原因: 致谢 | 摘要: "..." | 回复: "不客气!"'
        )
        parsed = _parse_triage_output(raw)
        assert parsed is not None
        assert parsed["route_to"] == "direct"
        assert parsed["summary"] == "..."
        assert parsed["direct_reply"] == "不客气!"

    def test_existing_customer_route_still_parses_unchanged(self):
        """Ensure the new regex branch doesn't break the M1 format."""
        raw = "[分流] 意图: product_inquiry | 信心: 0.85 | 路由: customer | 原因: 产品咨询"
        parsed = _parse_triage_output(raw)
        assert parsed is not None
        assert parsed["route_to"] == "customer"
        assert parsed.get("direct_reply") is None


# ---------------------------------------------------------------------------
# TriageDecision invariant — route=direct MUST carry direct_reply
# ---------------------------------------------------------------------------
# Regression: triage agent can output "路由: direct" without the optional
# `回复:` field. That produced TriageDecision(role="direct",
# direct_reply=None), which the gateway's short-circuit skipped — falling
# through to pool.acquire(role="direct") → NotImplementedError → SIDE
# warning "[分流警告] target_role=direct 池获取失败". Fix: demote the
# decision to "customer" when the invariant is violated.

class TestTriageAgentInvariant:
    @pytest.mark.asyncio
    async def test_agent_direct_without_reply_field_demotes_to_customer(
        self, monkeypatch
    ):
        """Triage agent returns route=direct with no 回复: → demote."""
        from autoservice.model_router import ModelRouter, FastClassifier

        async def _fake_one_shot(self, message, tenant_id):
            return "[分流] 意图: greeting | 信心: 0.90 | 路由: direct | 原因: 招呼"

        monkeypatch.setattr(
            ModelRouter, "_triage_agent_one_shot", _fake_one_shot,
        )

        router = ModelRouter()
        fast = FastClassifier().classify("模糊的东西")
        decision = await router._invoke_triage_agent(
            message="模糊的东西",
            tenant_id=None,
            fast_result=fast,
            detected_language=None,
            previous_role=None,
        )
        assert decision.role == "customer", (
            f"route=direct without 回复: must demote to customer; got {decision.role}"
        )
        assert decision.direct_reply is None

    @pytest.mark.asyncio
    async def test_agent_direct_with_reply_field_keeps_direct(
        self, monkeypatch
    ):
        """Baseline — valid `回复:` field stays on direct path."""
        from autoservice.model_router import ModelRouter, FastClassifier

        async def _fake_one_shot(self, message, tenant_id):
            return (
                '[分流] 意图: greeting | 信心: 0.90 | 路由: direct | '
                '原因: 招呼 | 回复: "您好,请问有什么可以帮您?"'
            )

        monkeypatch.setattr(
            ModelRouter, "_triage_agent_one_shot", _fake_one_shot,
        )

        router = ModelRouter()
        fast = FastClassifier().classify("模糊")
        decision = await router._invoke_triage_agent(
            message="模糊",
            tenant_id=None,
            fast_result=fast,
            detected_language=None,
            previous_role=None,
        )
        assert decision.role == "direct"
        assert decision.direct_reply == "您好,请问有什么可以帮您?"


# ---------------------------------------------------------------------------
# ModelRouter.route_message — propagates direct_reply to TriageDecision
# ---------------------------------------------------------------------------

import pytest_asyncio
from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.model_router import ModelRouter, TriageDecision


@pytest_asyncio.fixture()
async def engine() -> LocalEngine:
    return LocalEngine()


@pytest_asyncio.fixture()
async def conv_id(engine):
    conv = await engine.create_conversation(channel="web", external_id="direct-test")
    return conv.id


class _StaticTenantConfig:
    supported_languages = ["zh", "en"]
    tenant_id = None


@pytest.mark.asyncio
async def test_route_message_direct_greeting(engine, conv_id):
    router = ModelRouter()
    decision = await router.route_message(
        "你好", tenant_config=_StaticTenantConfig(),
        conv_id=conv_id, engine=engine,
    )
    assert isinstance(decision, TriageDecision)
    assert decision.role == "direct"
    assert decision.intent == "greeting"
    assert decision.direct_reply, (
        "direct route must carry a reply for the gateway to send"
    )


@pytest.mark.asyncio
async def test_route_message_non_direct_has_no_reply(engine, conv_id):
    router = ModelRouter()
    decision = await router.route_message(
        "你们的产品怎么用", tenant_config=_StaticTenantConfig(),
        conv_id=conv_id, engine=engine,
    )
    assert decision.role == "customer"
    assert decision.direct_reply is None
