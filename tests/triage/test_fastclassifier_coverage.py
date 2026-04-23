"""Regression lock for the 2026-04-23 FastClassifier keyword expansion.

Background: the haiku-backed triage agent was reliably hitting the 2 s
`_TRIAGE_AGENT_TIMEOUT` before inference could finish, so every low-
confidence message paid 2 s of latency. Expanding the FastClassifier
keyword sets lets most real cinnox / CSR messages hit ``fastpath``
directly and bypass the agent call entirely.

Covers the typical messages that used to fall through to
``general_question``: ticket numbers, P1 urgency, PSTN outages,
open-ended questions ("多久", "区别", "流程"), and Chinese pricing
synonyms ("多少钱", "套餐", "订阅").
"""
from __future__ import annotations

from autoservice.model_router import AgentRole, FastClassifier, Intent


class TestKeywordExpansion:
    """Messages that should now hit ``fastpath`` instead of falling through
    to ``general_question``. Each case previously produced a ~0.4 confidence
    and invoked the triage agent (~2 s waste)."""

    def setup_method(self):
        # Classifier reads the singleton _config — reset so each test
        # parses the current yaml from disk.
        import autoservice.model_router as mr
        mr._config = None
        self.clf = FastClassifier()

    # -- complaint / urgency ------------------------------------------------

    def test_ticket_number_routes_to_complaint(self):
        r = self.clf.classify("工单 TK-1234 一直没人处理")
        assert r.intent == Intent.COMPLAINT
        assert r.route_to == AgentRole.CUSTOMER

    def test_p1_urgency_routes_to_complaint(self):
        r = self.clf.classify("这个问题 P1 级别,今晚必须解决")
        assert r.intent == Intent.COMPLAINT

    def test_pstn_outage_phrasing_routes_to_complaint(self):
        r = self.clf.classify("PSTN 断了,客户电话打不通")
        assert r.intent == Intent.COMPLAINT

    def test_urgent_keyword_routes_to_complaint(self):
        r = self.clf.classify("紧急!IVR 流程不工作了")
        assert r.intent == Intent.COMPLAINT

    # -- product_inquiry / open-ended questions -----------------------------

    def test_how_long_routes_to_product_inquiry(self):
        r = self.clf.classify("DID 号码申请多久可以开通")
        assert r.intent == Intent.PRODUCT_INQUIRY
        assert r.route_to == AgentRole.CUSTOMER

    def test_comparison_routes_to_product_inquiry(self):
        r = self.clf.classify("Professional 和 Enterprise 的区别是什么")
        assert r.intent == Intent.PRODUCT_INQUIRY

    def test_process_routes_to_product_inquiry(self):
        r = self.clf.classify("SSO 对接的流程是怎样的")
        # Should hit "流程" + "怎样" — definitely product_inquiry now.
        assert r.intent == Intent.PRODUCT_INQUIRY

    def test_howto_manual_routes_to_product_inquiry(self):
        r = self.clf.classify("有没有 IVR 编排的文档或教程")
        assert r.intent == Intent.PRODUCT_INQUIRY

    # -- purchase_intent / pricing synonyms ---------------------------------

    def test_how_much_money_routes_to_lead(self):
        r = self.clf.classify("Professional 套餐多少钱一个月")
        assert r.route_to == AgentRole.LEAD
        assert r.intent == Intent.PURCHASE_INTENT

    def test_subscription_routes_to_lead(self):
        r = self.clf.classify("我们公司想订阅你们的服务")
        assert r.intent == Intent.PURCHASE_INTENT

    def test_tao_can_routes_to_lead(self):
        # "套餐" is the natural cinnox buying term.
        r = self.clf.classify("介绍一下你们的套餐")
        assert r.intent == Intent.PURCHASE_INTENT
