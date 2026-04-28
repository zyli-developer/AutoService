"""Reply pipeline (drain + triage integration) tests. Spec §6."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice.integrations.general_bot.reply_pipeline import _drain_to_sink
from autoservice.integrations.general_bot.sse import JSONSink


def _stream_event(text: str):
    from claude_agent_sdk.types import StreamEvent
    return StreamEvent(
        uuid="u1",
        session_id="s1",
        event={
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": text},
        },
    )


async def _aiter(items):
    for it in items:
        yield it


@pytest.mark.asyncio
async def test_drain_emits_each_chunk_and_returns_full_text():
    sink = JSONSink()
    sink_emit = AsyncMock(wraps=sink.emit_delta)
    sink.emit_delta = sink_emit  # type: ignore[method-assign]
    out = await _drain_to_sink(
        _aiter([_stream_event("Hi "), _stream_event("there"), _stream_event("!")]),
        sink,
        perf={},
    )
    assert out == "Hi there!"
    assert sink_emit.await_count == 3


@pytest.mark.asyncio
async def test_drain_handles_empty_stream():
    sink = JSONSink()
    out = await _drain_to_sink(_aiter([]), sink, perf={})
    assert out == ""


@pytest.mark.asyncio
async def test_drain_falls_back_to_assistant_message_when_no_stream_events():
    """When the SDK skips StreamEvent and only returns AssistantMessage."""
    from claude_agent_sdk.types import AssistantMessage, TextBlock
    msg = AssistantMessage(content=[TextBlock(text="full reply")], model="haiku")
    sink = JSONSink()
    out = await _drain_to_sink(_aiter([msg]), sink, perf={})
    assert out == "full reply"


@pytest.mark.asyncio
async def test_drain_records_first_token_perf():
    sink = JSONSink()
    perf = {}
    await _drain_to_sink(_aiter([_stream_event("hi")]), sink, perf=perf)
    assert "first_token_t" in perf


# --- stream_agent_reply branch coverage ---


class _FakePool:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks
        self.called_with: dict | None = None

    def session_query(self, conv_id, prompt, *, tenant_id=None, tier=None):
        self.called_with = {
            "conv_id": conv_id, "prompt": prompt,
            "tenant_id": tenant_id, "tier": tier,
        }
        async def _gen():
            for c in self._chunks:
                yield _stream_event(c)
        return _gen()


class _FakeMsg:
    def __init__(self, mid, seq, content, source="agent", visibility=None):
        from autoservice.conversation_engine.types import MessageVisibility
        self.id = mid
        self.sequence_number = seq
        self.content = content
        self.source = source
        self.visibility = visibility or MessageVisibility.PUBLIC
        from datetime import datetime, timezone
        self.timestamp = datetime.now(timezone.utc)
        self.metadata = {}
        self.conversation_id = "c1"
        self.edit_of = None


class _FakeEngine:
    def __init__(self) -> None:
        self.persisted: list[_FakeMsg] = []
        self._next_id = 1

    async def send_message(self, conv_id, *, source, content, **kwargs):
        m = _FakeMsg(f"m{self._next_id}", self._next_id, content, source=source)
        self._next_id += 1
        self.persisted.append(m)
        return m

    async def get_messages(self, conv_id, **kwargs):
        return []

    async def update_triage_state(self, conv_id, **fields):
        pass

    async def get_triage_state(self, conv_id):
        return {}


def _patch_triage_decision(monkeypatch, *, role="customer", direct_reply=None, tier="fast"):
    """Stub triage_and_route to return a deterministic decision."""
    from autoservice.model_router import TriageDecision

    async def fake_triage(*, engine, conv_id, customer_text, tenant_config):
        return TriageDecision(
            role=role,
            intent="general_question",
            confidence=0.9,
            source="stub",
            summary=None,
            detected_language="en",
            previous_role=None,
            direct_reply=direct_reply,
            tier=tier,
        )

    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline.triage_and_route",
        fake_triage,
    )

    # Stub tenant config loader
    async def fake_cfg(engine, conv_id):
        class _Cfg:
            tenant_id = "tenantA"
            triage_dispatch_enabled = True
            history_reseed_token_limit = 2000
        return _Cfg()
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline.load_tenant_config_for_conv",
        fake_cfg,
    )

    # Stub _build_customer_prompt to a passthrough so we can assert
    async def fake_build_customer_prompt(*, tenant_id, customer_text, operator_suggestions):
        return customer_text
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline._build_customer_prompt",
        fake_build_customer_prompt,
    )

    # Stub operator suggestions to empty
    async def fake_collect(*args, **kwargs):
        return ""
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline._collect_operator_suggestions",
        fake_collect,
    )


@pytest.mark.asyncio
async def test_stream_agent_reply_customer_branch(monkeypatch):
    from autoservice.integrations.general_bot.reply_pipeline import stream_agent_reply

    _patch_triage_decision(monkeypatch, role="customer", tier="fast")
    engine = _FakeEngine()
    pool = _FakePool(["Hello", " world"])
    sink = JSONSink()

    out = await stream_agent_reply(
        engine=engine, pool=pool, conv_id="c1",
        customer_text="hi", tenant_id="tenantA", sink=sink,
    )

    assert out == "Hello world"
    assert sink.body == {"message": {"type": 1, "text": "Hello world"}}
    # Pool was called with tenant + tier
    assert pool.called_with["tenant_id"] == "tenantA"
    assert pool.called_with["tier"] == "fast"
    # One agent message persisted
    agent_rows = [m for m in engine.persisted if m.source == "agent"]
    assert len(agent_rows) == 1
    assert agent_rows[0].content == "Hello world"


@pytest.mark.asyncio
async def test_stream_agent_reply_direct_short_circuit(monkeypatch):
    from autoservice.integrations.general_bot.reply_pipeline import stream_agent_reply

    _patch_triage_decision(monkeypatch, role="direct", direct_reply="Hi, how can I assist you?")
    engine = _FakeEngine()
    pool = _FakePool(["should not be called"])
    sink = JSONSink()

    out = await stream_agent_reply(
        engine=engine, pool=pool, conv_id="c1",
        customer_text="你好", tenant_id="tenantA", sink=sink,
    )

    assert out == "Hi, how can I assist you?"
    assert pool.called_with is None  # short-circuit avoided pool
    assert sink.body == {"message": {"type": 1, "text": "Hi, how can I assist you?"}}


@pytest.mark.asyncio
async def test_stream_agent_reply_direct_empty_uses_fallback_template(monkeypatch):
    from autoservice.integrations.general_bot.reply_pipeline import stream_agent_reply

    _patch_triage_decision(monkeypatch, role="direct", direct_reply=None)
    engine = _FakeEngine()
    pool = _FakePool([])
    sink = JSONSink()

    out = await stream_agent_reply(
        engine=engine, pool=pool, conv_id="c1",
        customer_text="你好", tenant_id="tenantA", sink=sink,
    )

    assert out == "Hello, how can I help you?"
    assert pool.called_with is None


@pytest.mark.asyncio
async def test_stream_agent_reply_empty_text_uses_fallback(monkeypatch):
    from autoservice.integrations.general_bot.reply_pipeline import stream_agent_reply

    _patch_triage_decision(monkeypatch, role="customer", tier="fast")
    engine = _FakeEngine()
    pool = _FakePool([])  # no chunks → empty reply
    sink = JSONSink()

    out = await stream_agent_reply(
        engine=engine, pool=pool, conv_id="c1",
        customer_text="hi", tenant_id="tenantA", sink=sink,
    )

    assert out == "(Sorry, no valid reply was generated.)"
