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
