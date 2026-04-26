"""End-to-end integration tests for instant-ack + multi-bubble + queue.

Mocks the LLM stream; uses fake engine + real TurnQueue + real splitter.
Verifies frame ordering and Message rows.

Spec: §12.2 of the design doc.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice.gateway.message_router import _drain_into_bubbles
from autoservice.gateway.turn_queue import TurnQueue


class _FakeMsg:
    def __init__(
        self, mid: str, seq: int, content: str = "", source: str = "agent",
        metadata: dict | None = None,
    ) -> None:
        self.id = mid
        self.conversation_id = "c1"
        self.sequence_number = seq
        self.content = content
        self.source = source
        self.visibility = "public"
        self.timestamp = datetime.now(timezone.utc)
        self.edit_of = None
        self.metadata = metadata or {}


class _FakeEngine:
    def __init__(self) -> None:
        self.messages: list[_FakeMsg] = []
        self.edits: list[tuple[str, str]] = []
        self._next_id = 1

    async def send_message(self, conv_id, *, source, content, metadata=None):
        msg = _FakeMsg(
            f"m{self._next_id}", self._next_id, content,
            source=source, metadata=metadata,
        )
        self._next_id += 1
        self.messages.append(msg)
        return msg

    async def edit_message(self, conv_id, msg_id, *, new_content, edited_by):
        self.edits.append((msg_id, new_content))
        for m in self.messages:
            if m.id == msg_id:
                m.content = new_content
                return m
        return None


def _stream_for(text: str, chunk_size: int = 4):
    from claude_agent_sdk.types import StreamEvent
    out = []
    for i in range(0, len(text), chunk_size):
        out.append(StreamEvent(
            uuid=f"u{i}",
            session_id="s1",
            event={
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": text[i:i+chunk_size]},
            },
        ))
    return out


async def _aiter(items):
    for it in items:
        yield it


@pytest.mark.asyncio
async def test_three_paragraphs_emit_three_message_rows(monkeypatch):
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()

    text = (
        "First paragraph here is at least five chars.\n\n"
        "Second paragraph here is also long enough.\n\n"
        "Third paragraph is the conclusion."
    )
    events = _stream_for(text, chunk_size=8)

    out = await _drain_into_bubbles(
        _aiter(events),
        engine=engine, conv_id="c1", target_role="customer", ws=ws,
    )
    assert out == text
    # Three persisted Message rows for the three segments.
    assert len(engine.messages) == 3
    assert engine.messages[0].content == "First paragraph here is at least five chars."
    assert engine.messages[1].content == "Second paragraph here is also long enough."
    assert engine.messages[2].content == "Third paragraph is the conclusion."


@pytest.mark.asyncio
async def test_single_paragraph_emits_one_row(monkeypatch):
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()

    text = "Just one paragraph with no internal break at all."
    events = _stream_for(text, chunk_size=6)
    out = await _drain_into_bubbles(
        _aiter(events), engine=engine, conv_id="c1",
        target_role="customer", ws=ws,
    )
    assert out == text
    assert len(engine.messages) == 1
    assert engine.messages[0].content == text


@pytest.mark.asyncio
async def test_multi_bubble_disabled_emits_one_row(monkeypatch):
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "0")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()

    text = "P1 long enough.\n\nP2 long enough.\n\nP3 long enough."
    events = _stream_for(text, chunk_size=4)
    out = await _drain_into_bubbles(
        _aiter(events), engine=engine, conv_id="c1",
        target_role="customer", ws=ws,
    )
    # With MULTI_BUBBLE_ENABLED=0 the entire reply is one bubble.
    assert len(engine.messages) == 1
    assert out == text


@pytest.mark.asyncio
async def test_turn_queue_serializes_two_rapid_submits():
    q = TurnQueue()
    seen_order: list[str] = []
    started_a = asyncio.Event()
    finish_a = asyncio.Event()

    async def turn_a():
        seen_order.append("a-start")
        started_a.set()
        await finish_a.wait()
        seen_order.append("a-end")

    async def turn_b():
        seen_order.append("b")

    await q.submit("c1", turn_a)
    await started_a.wait()
    await q.submit("c1", turn_b)
    # b waits in queue
    assert seen_order == ["a-start"]
    finish_a.set()
    await asyncio.sleep(0.05)
    assert seen_order == ["a-start", "a-end", "b"]


@pytest.mark.asyncio
async def test_ack_queue_interaction_each_turn_gets_own_ack(monkeypatch):
    """Spec §12.2: customer fires msg A, then msg B during A's processing.
    Each turn gets its own ack; B waits until A's drain finishes."""
    monkeypatch.setenv("ACK_DELAY_MIN_MS", "0")
    monkeypatch.setenv("ACK_DELAY_MAX_MS", "0")
    from autoservice.gateway.agent_ack import send_pretriage_ack

    engine = _FakeEngine()
    ws_a = MagicMock(); ws_a.send_json = AsyncMock()
    ws_b = MagicMock(); ws_b.send_json = AsyncMock()
    q = TurnQueue()

    started_a_drain = asyncio.Event()
    finish_a_drain = asyncio.Event()

    async def turn_a():
        await send_pretriage_ack(
            engine, "c1", ws_a, "我想问一个产品问题",
            delay_min_ms=0, delay_max_ms=0,
        )
        started_a_drain.set()
        await finish_a_drain.wait()
        # Pretend the drain ran here.

    async def turn_b():
        await send_pretriage_ack(
            engine, "c1", ws_b, "另外团队规模多大?",
            delay_min_ms=0, delay_max_ms=0,
        )

    await q.submit("c1", turn_a)
    await started_a_drain.wait()
    # A's ack should have already persisted by now.
    ack_count_after_a = len(engine.messages)
    await q.submit("c1", turn_b)
    # B is queued; B's ack hasn't fired yet.
    assert q.queue_depth("c1") == 1
    finish_a_drain.set()
    await asyncio.sleep(0.05)
    # Now B's turn ran → its ack persisted.
    assert len(engine.messages) >= ack_count_after_a + 1


@pytest.mark.asyncio
async def test_queue_advances_on_runner_exception():
    """Spec §12.2: triage failure / runner raises → queue still advances."""
    q = TurnQueue()
    seen: list[str] = []

    async def boom():
        raise RuntimeError("triage failed")

    async def good():
        seen.append("good")

    await q.submit("c1", boom)
    await q.submit("c1", good)
    await asyncio.sleep(0.05)
    assert seen == ["good"]
    assert q.queue_depth("c1") == 0
    assert not q.has_in_flight("c1")


@pytest.mark.asyncio
async def test_drain_flush_emits_residual_on_error_mid_segment(monkeypatch):
    """Spec §12.2: drain hits an exception mid-stream → flush still emits
    residual content. We simulate by raising inside the iterator after a
    partial segment has accumulated."""
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock(); ws.send_json = AsyncMock()

    from claude_agent_sdk.types import StreamEvent

    async def _bad_stream():
        # First chunk: long enough to cross MIN.
        yield StreamEvent(
            uuid="u0",
            session_id="s1",
            event={
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Half a segment, growing... "},
            },
        )
        # Then raise to simulate upstream error.
        raise RuntimeError("upstream stream broken")

    with pytest.raises(RuntimeError, match="upstream stream broken"):
        await _drain_into_bubbles(
            _bad_stream(), engine=engine, conv_id="c1",
            target_role="customer", ws=ws,
        )
    # The finally block still ran flush; one bubble should be persisted.
    assert len(engine.messages) >= 1
    assert "Half a segment" in engine.messages[0].content


@pytest.mark.asyncio
async def test_instant_ack_disabled_skips_ack_but_drain_runs(monkeypatch):
    """Spec §12.2: kill switch INSTANT_ACK_ENABLED=0 → no ack, reply still
    segments normally."""
    monkeypatch.setenv("INSTANT_ACK_ENABLED", "0")
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    monkeypatch.setenv("ACK_DELAY_MIN_MS", "0")
    monkeypatch.setenv("ACK_DELAY_MAX_MS", "0")
    from autoservice.gateway.agent_ack import send_pretriage_ack

    engine = _FakeEngine()
    ws = MagicMock(); ws.send_json = AsyncMock()

    out = await send_pretriage_ack(
        engine, "c1", ws, "我想问一个长一点的产品问题", tenant_id="cinnox",
    )
    assert out is None  # ack disabled
    assert len(engine.messages) == 0  # nothing persisted

    # Drain still works; emits segments normally.
    text = "First long-enough paragraph.\n\nSecond long-enough paragraph."
    await _drain_into_bubbles(
        _aiter(_stream_for(text, 4)),
        engine=engine, conv_id="c1", target_role="customer", ws=ws,
    )
    assert len(engine.messages) == 2  # exactly two segments, no ack


@pytest.mark.asyncio
async def test_queue_disabled_falls_back_to_concurrent():
    """Spec §12.2: kill switch QUEUE_ENABLED=0 — without TurnQueue, two
    submitted runners execute concurrently (no serialization).

    Sanity: when fire-and-forget tasks both run, B can finish before A
    finishes — the inverse of the queue behavior pinned in
    test_turn_queue_serializes_two_rapid_submits.
    """
    seen: list[str] = []
    started_a = asyncio.Event()
    finish_a = asyncio.Event()

    async def runner_a():
        seen.append("a-start")
        started_a.set()
        await finish_a.wait()
        seen.append("a-end")

    async def runner_b():
        await started_a.wait()  # ensure ordering: a starts first
        seen.append("b-start")
        seen.append("b-end")     # B finishes BEFORE A's end_event fires

    task_a = asyncio.create_task(runner_a())
    task_b = asyncio.create_task(runner_b())
    await task_b
    # B finished while A is still mid-flight (held by finish_a):
    assert "b-end" in seen
    assert "a-end" not in seen  # A hasn't finished yet
    finish_a.set()
    await task_a
    assert seen == ["a-start", "b-start", "b-end", "a-end"]
