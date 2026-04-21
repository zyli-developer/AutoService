"""FastClassifier keyword-cleanup regression + decision-path tests.

Spec: docs/superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md §4.1
"""
from __future__ import annotations

import pytest

from autoservice.model_router import FastClassifier, Intent, AgentRole


class TestKeywordCleanup:
    """After T0 cleanup, `价格` routes to lead (not product_inquiry)."""

    def setup_method(self):
        # Classifier reads the singleton _config — reset it so each test
        # sees a fresh parse of the yaml on disk.
        import autoservice.model_router as mr
        mr._config = None
        self.clf = FastClassifier()

    def test_price_word_routes_to_lead(self):
        result = self.clf.classify("你们的价格是多少")
        assert result.route_to == AgentRole.LEAD
        assert result.intent == Intent.PURCHASE_INTENT

    def test_bare_question_word_does_not_trigger_complaint(self):
        # "问题" alone is too generic — without "投诉/故障/坏了/refund"
        # it must not yield complaint.
        result = self.clf.classify("有个问题想咨询一下")
        assert result.intent != Intent.COMPLAINT

    def test_how_to_use_routes_to_product_inquiry(self):
        result = self.clf.classify("这个功能怎么用")
        assert result.route_to == AgentRole.CUSTOMER
        assert result.intent == Intent.PRODUCT_INQUIRY

    def test_refund_routes_to_complaint(self):
        result = self.clf.classify("我要退款")
        assert result.intent == Intent.COMPLAINT
