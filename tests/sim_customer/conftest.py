"""Fixtures for sim_customer tests.

Provides mock LLM client, fixture KB, and pre-built SimConfig.
"""

import json
import sqlite3
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from autoservice.sim_customer import (
    Persona,
    Scenario,
    SimConfig,
    SimDialog,
    SimTurn,
    load_sim_config,
)


# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------


class MockLLMClient:
    """Mock LLM client that returns deterministic responses."""

    def __init__(self):
        self.calls: list[dict] = []
        self._scenario_response: str | None = None
        self._customer_turns_response: str | None = None
        self._agent_response: str = "您好，我来为您处理这个问题。"
        self._call_count = 0
        self._max_concurrent = 0
        self._current_concurrent = 0

    async def generate(self, prompt: str, system: str | None = None) -> str:
        self._current_concurrent += 1
        if self._current_concurrent > self._max_concurrent:
            self._max_concurrent = self._current_concurrent

        self.calls.append({"prompt": prompt, "system": system})
        self._call_count += 1

        try:
            # Scenario extraction call
            if "分析以下知识库内容" in prompt:
                return self._scenario_response or json.dumps([
                    {
                        "id": "return-policy",
                        "name_zh": "退款政策",
                        "intent": "complaint",
                        "keywords": ["退款", "退货"],
                        "trap_question": "退款后积分还在吗？"
                    },
                    {
                        "id": "product-features",
                        "name_zh": "产品功能",
                        "intent": "product_inquiry",
                        "keywords": ["功能", "怎么用"],
                        "trap_question": "支持离线模式吗？"
                    },
                    {
                        "id": "pricing",
                        "name_zh": "价格咨询",
                        "intent": "purchase_intent",
                        "keywords": ["价格", "报价"],
                        "trap_question": "有教育优惠吗？"
                    },
                    {
                        "id": "shipping",
                        "name_zh": "配送信息",
                        "intent": "general_question",
                        "keywords": ["配送", "物流"],
                        "trap_question": "支持送到海外吗？"
                    },
                    {
                        "id": "multilingual",
                        "name_zh": "多语言支持",
                        "intent": "language_barrier",
                        "keywords": [],
                        "trap_question": "Do you support Arabic?"
                    },
                ], ensure_ascii=False)

            # Customer turns generation call
            if "虚拟客户模拟器" in prompt:
                return self._customer_turns_response or json.dumps([
                    {"role": "customer", "content": "你好，我想问一下退款政策", "metadata": {"is_trap": False}},
                    {"role": "customer", "content": "我上周买的东西想退", "metadata": {"is_trap": False}},
                    {"role": "customer", "content": "退款后积分还在吗？", "metadata": {"is_trap": True}},
                    {"role": "customer", "content": "好的谢谢", "metadata": {"is_trap": False}},
                ], ensure_ascii=False)

            # AI agent response call
            return self._agent_response
        finally:
            self._current_concurrent -= 1


@pytest.fixture
def mock_llm():
    return MockLLMClient()


# ---------------------------------------------------------------------------
# Fixture KB (SQLite FTS5)
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_kb(tmp_path) -> Path:
    """Create a test FTS5 knowledge base with 20+ entries across 3 topics."""
    db_path = tmp_path / "test_kb.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE VIRTUAL TABLE kb_chunks USING fts5(content, source, country)"
    )

    entries = [
        # Topic 1: Return/Refund policy (7 entries)
        ("退款政策：购买后7天内可无理由退款。", "faq", "CN"),
        ("退货流程：联系客服→确认退货→寄回商品→退款到账。", "faq", "CN"),
        ("退款通常3-5个工作日到账。", "faq", "CN"),
        ("运费说明：非质量问题退货由买家承担运费。", "faq", "CN"),
        ("退款申请需提供订单号和退款原因。", "faq", "CN"),
        ("超过7天退款需要提供质量问题证明。", "faq", "CN"),
        ("退款金额不含优惠券抵扣部分。", "faq", "CN"),
        # Topic 2: Product features (7 entries)
        ("产品支持中英双语界面。", "product", "CN"),
        ("基础版支持5个用户同时在线。", "product", "CN"),
        ("高级版支持无限用户和API访问。", "product", "CN"),
        ("产品提供7×24小时技术支持。", "product", "CN"),
        ("数据导出支持CSV和Excel格式。", "product", "CN"),
        ("移动端支持iOS 14+和Android 10+。", "product", "CN"),
        ("自动备份每天凌晨2点执行。", "product", "CN"),
        # Topic 3: Shipping/delivery (6 entries)
        ("国内配送：下单后2-3个工作日送达。", "shipping", "CN"),
        ("支持顺丰和京东快递。", "shipping", "CN"),
        ("满99元包邮（偏远地区除外）。", "shipping", "CN"),
        ("配送范围覆盖中国大陆全境。", "shipping", "CN"),
        ("可在订单页面实时查看物流状态。", "shipping", "CN"),
        ("节假日期间配送时间可能延长1-2天。", "shipping", "CN"),
    ]

    conn.executemany(
        "INSERT INTO kb_chunks(content, source, country) VALUES (?, ?, ?)",
        entries,
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def empty_kb(tmp_path) -> Path:
    """Create an empty FTS5 knowledge base."""
    db_path = tmp_path / "empty_kb.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE VIRTUAL TABLE kb_chunks USING fts5(content, source, country)"
    )
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Pre-built config
# ---------------------------------------------------------------------------


@pytest.fixture
def sim_config() -> SimConfig:
    return load_sim_config()


@pytest.fixture
def sample_scenario() -> Scenario:
    return Scenario(
        id="return-policy",
        name_zh="退款政策",
        intent="complaint",
        keywords=["退款", "退货"],
        trap_question="退款后积分还在吗？",
    )


@pytest.fixture
def sample_persona() -> Persona:
    return Persona(
        id="angry-refund",
        name_zh="愤怒退款客户",
        traits=["情绪激动", "用词尖锐", "要求立即处理"],
        communication_style="aggressive",
    )


@pytest.fixture
def sample_dialog(sample_scenario, sample_persona) -> SimDialog:
    return SimDialog(
        id="test-001",
        scenario=sample_scenario,
        persona=sample_persona,
        turns=[
            SimTurn(role="customer", content="我要退款！", metadata={"is_trap": False}),
            SimTurn(role="agent", content="好的，请提供订单号。", metadata={"model_tier": "slow"}),
            SimTurn(role="customer", content="订单号123456", metadata={"is_trap": False}),
            SimTurn(role="agent", content="已为您提交退款申请。", metadata={"model_tier": "slow"}),
            SimTurn(role="customer", content="退款后积分还在吗？", metadata={"is_trap": True}),
            SimTurn(role="agent", content="这个问题我需要确认后回复您。", metadata={"model_tier": "slow"}),
        ],
        language="zh",
    )
