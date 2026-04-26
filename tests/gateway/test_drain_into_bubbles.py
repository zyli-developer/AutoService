"""Unit tests for _drain_into_bubbles — the multi-bubble drain.

Mocks the LLM stream + engine; checks segment persistence, frame
ordering, and the persist-on-first-token-of-segment policy from §9.2.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoservice.gateway.message_router import _drain_into_bubbles


class _FakeMsg:
    def __init__(
        self, mid: str, seq: int, content: str = "", source: str = "agent",
        metadata: dict | None = None,
    ) -> None:
        from datetime import datetime, timezone
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
async def test_three_paragraphs_three_persisted_rows(monkeypatch):
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()
    text = (
        "First paragraph here, long enough.\n\n"
        "Second paragraph here, also long enough.\n\n"
        "Third and final paragraph."
    )
    out = await _drain_into_bubbles(
        _aiter(_stream_for(text, 6)),
        engine=engine, conv_id="c1", target_role="customer", ws=ws,
    )
    assert out == text
    # Three rows persisted; trimmed content (no trailing \n\n).
    assert engine.messages[0].content == "First paragraph here, long enough."
    assert engine.messages[1].content == "Second paragraph here, also long enough."
    assert engine.messages[2].content == "Third and final paragraph."
    assert len(engine.messages) == 3


@pytest.mark.asyncio
async def test_single_paragraph_one_row(monkeypatch):
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()
    text = "Single paragraph reply with no break."
    out = await _drain_into_bubbles(
        _aiter(_stream_for(text, 4)),
        engine=engine, conv_id="c1", target_role="customer", ws=ws,
    )
    assert out == text
    assert len(engine.messages) == 1
    assert engine.messages[0].content == text


@pytest.mark.asyncio
async def test_below_min_consumes_boundary(monkeypatch):
    """Spec §9.2 — when candidate segment is below MIN, the \\n\\n is consumed
    and the bubble keeps growing through it. Final result: one bubble."""
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()
    text = "好。\n\nHere is the actually-long-enough rest of the reply."
    out = await _drain_into_bubbles(
        _aiter(_stream_for(text, 4)),
        engine=engine, conv_id="c1", target_role="customer", ws=ws,
    )
    # The "好。" prefix is below MIN=5 → boundary consumed → single bubble.
    # Content has no \n\n in it.
    assert len(engine.messages) == 1
    assert "\n\n" not in engine.messages[0].content


@pytest.mark.asyncio
async def test_typewriter_edits_pushed_during_growth(monkeypatch):
    """Verify message_edited frames are pushed as the bubble grows
    after first persistence. (Frame count > 1 per bubble = typewriter.)"""
    monkeypatch.setenv("MULTI_BUBBLE_ENABLED", "1")
    engine = _FakeEngine()
    ws = MagicMock()
    ws.send_json = AsyncMock()
    # Long single paragraph in many small chunks so several typewriter
    # frames have a chance to fire.
    text = "A" * 80
    await _drain_into_bubbles(
        _aiter(_stream_for(text, 1)),  # one char per chunk
        engine=engine, conv_id="c1", target_role="customer", ws=ws,
    )
    # Initial message frame + N message_edited frames.
    sent = [c.args[0] for c in ws.send_json.await_args_list]
    types = [f.get("type") for f in sent]
    assert types[0] == "message"
    assert "message_edited" in types
