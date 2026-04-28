"""Unit tests for pre-triage acknowledgement.

Spec: §5 / §5.1.1 of the design doc.
"""
from __future__ import annotations

import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice.gateway.agent_ack import (
    detect_lang,
    pick_ack_text,
    send_pretriage_ack,
    should_skip_ack,
)


def test_detect_lang_chinese_text_returns_zh():
    assert detect_lang("你好，请问产品多少钱?") == "zh"


def test_detect_lang_english_text_returns_en():
    assert detect_lang("Hi, how much does the product cost?") == "en"


def test_detect_lang_cinnox_default_to_zh_on_ambiguous():
    # All-punctuation, no ASCII letters → cinnox bias kicks in.
    assert detect_lang("？？？", tenant_id="cinnox") == "zh"
    # Same text, different tenant: falls through to en default.
    assert detect_lang("???", tenant_id="other") == "en"


def test_detect_lang_japanese_hiragana():
    assert detect_lang("こんにちは") == "zh"  # CJK ranges include hiragana


def test_should_skip_ack_short_zh_skipped():
    # 3 chars (< 8) → skip
    assert should_skip_ack("你好啊", "zh") is True


def test_should_skip_ack_long_zh_not_skipped():
    # 9 chars (>= 8) → don't skip
    assert should_skip_ack("我想问一个产品问题", "zh") is False


def test_should_skip_ack_short_en_skipped():
    assert should_skip_ack("Hi there", "en") is True  # 8 < 15


def test_should_skip_ack_long_en_not_skipped():
    text = "What is the cost of your enterprise plan?"
    assert should_skip_ack(text, "en") is False


def test_pick_ack_text_returns_from_zh_bank():
    rng = random.Random(42)
    out = pick_ack_text("zh", rng=rng)
    assert isinstance(out, str)
    assert len(out) > 0


def test_pick_ack_text_returns_from_en_bank():
    rng = random.Random(42)
    out = pick_ack_text("en", rng=rng)
    assert isinstance(out, str)
    assert len(out) > 0


@pytest.mark.asyncio
async def test_send_pretriage_ack_persists_and_pushes(monkeypatch):
    # Speed up: zero delay
    monkeypatch.setenv("ACK_DELAY_MIN_MS", "0")
    monkeypatch.setenv("ACK_DELAY_MAX_MS", "0")

    engine = MagicMock()
    fake_msg = MagicMock(id="msg-1", conversation_id="c1", sequence_number=2)
    engine.send_message = AsyncMock(return_value=fake_msg)
    ws = MagicMock()
    ws.send_json = AsyncMock()

    out = await send_pretriage_ack(
        engine, "c1", ws, "我想问一个长一点的产品问题", tenant_id="cinnox",
    )
    assert out is fake_msg
    engine.send_message.assert_awaited_once()
    args, kwargs = engine.send_message.await_args
    assert kwargs.get("metadata") == {"is_ack": True}


@pytest.mark.asyncio
async def test_send_pretriage_ack_skipped_on_short_msg(monkeypatch):
    monkeypatch.setenv("ACK_DELAY_MIN_MS", "0")
    monkeypatch.setenv("ACK_DELAY_MAX_MS", "0")

    engine = MagicMock()
    engine.send_message = AsyncMock()
    ws = MagicMock()
    ws.send_json = AsyncMock()

    out = await send_pretriage_ack(engine, "c1", ws, "你好", tenant_id="cinnox")
    assert out is None
    engine.send_message.assert_not_awaited()
    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_pretriage_ack_engine_failure_swallowed(monkeypatch):
    monkeypatch.setenv("ACK_DELAY_MIN_MS", "0")
    monkeypatch.setenv("ACK_DELAY_MAX_MS", "0")
    engine = MagicMock()
    engine.send_message = AsyncMock(side_effect=RuntimeError("db down"))
    ws = MagicMock()
    ws.send_json = AsyncMock()
    out = await send_pretriage_ack(engine, "c1", ws, "我想问一个长一点的问题")
    assert out is None
    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_pretriage_ack_disabled_via_env(monkeypatch):
    monkeypatch.setenv("INSTANT_ACK_ENABLED", "0")
    engine = MagicMock()
    engine.send_message = AsyncMock()
    ws = MagicMock()
    ws.send_json = AsyncMock()
    out = await send_pretriage_ack(engine, "c1", ws, "我想问一个长一点的问题")
    assert out is None
    engine.send_message.assert_not_awaited()
