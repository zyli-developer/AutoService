"""SSEStream / JSONSink wire-format tests. Spec §3.4 / §7."""
from __future__ import annotations

import asyncio
import json

import pytest

from autoservice.integrations.general_bot.sse import (
    SSEStream, JSONSink, MAX_CUMULATIVE_BYTES,
)


class _Wire:
    """Captures bytes written by SSEStream so tests can assert frame-by-frame."""
    def __init__(self) -> None:
        self.lines: list[bytes] = []

    async def send(self, line: bytes) -> None:
        self.lines.append(line)


@pytest.mark.asyncio
async def test_sse_delta_format():
    wire = _Wire()
    s = SSEStream(wire.send, keepalive_interval_s=999)
    await s.emit_delta("Hi")
    await s.close()
    assert wire.lines == [
        b'data: {"message": {"type": 1, "text": "Hi", "streamType": "delta"}}\n\n',
    ]


@pytest.mark.asyncio
async def test_sse_terminal_format_no_streamtype():
    wire = _Wire()
    s = SSEStream(wire.send, keepalive_interval_s=999)
    await s.emit_terminal("Hi! I received.")
    assert wire.lines == [
        b'data: {"message": {"type": 1, "text": "Hi! I received."}}\n\n',
    ]


@pytest.mark.asyncio
async def test_sse_unicode_no_ascii_escape():
    """ensure_ascii=False so CJK is sent as UTF-8 not \\uXXXX."""
    wire = _Wire()
    s = SSEStream(wire.send, keepalive_interval_s=999)
    await s.emit_delta("你好")
    await s.close()
    assert b"\\u" not in wire.lines[0]
    assert "你好".encode("utf-8") in wire.lines[0]


@pytest.mark.asyncio
async def test_sse_terminal_closes_keepalive_loop():
    wire = _Wire()
    s = SSEStream(wire.send, keepalive_interval_s=0.01)
    await asyncio.sleep(0.05)  # let keepalive loop tick once
    await s.emit_terminal("done")
    # After terminal, no more keepalives even if we wait
    count_before = len(wire.lines)
    await asyncio.sleep(0.05)
    assert len(wire.lines) == count_before


@pytest.mark.asyncio
async def test_sse_keepalive_comment_format():
    wire = _Wire()
    s = SSEStream(wire.send, keepalive_interval_s=0.01)
    await asyncio.sleep(0.025)  # ~2 ticks
    await s.close()
    keepalives = [ln for ln in wire.lines if ln.startswith(b":")]
    assert len(keepalives) >= 1
    for ln in keepalives:
        assert ln == b": keepalive\n\n"


@pytest.mark.asyncio
async def test_sse_4mb_truncation():
    wire = _Wire()
    s = SSEStream(wire.send, keepalive_interval_s=999)
    big = "x" * (MAX_CUMULATIVE_BYTES + 1024)
    await s.emit_delta(big)            # first delta is allowed; flag set
    await s.emit_delta("more")         # silently dropped
    await s.emit_terminal("final")
    delta_lines = [ln for ln in wire.lines if ln.startswith(b"data:") and b"streamType" in ln]
    assert len(delta_lines) == 1       # only the first delta, "more" dropped
    assert s.truncated is True


@pytest.mark.asyncio
async def test_json_sink_collects_and_returns_full():
    sink = JSONSink()
    await sink.emit_delta("Hi")
    await sink.emit_delta(" there")
    await sink.emit_terminal("Hi there!")
    await sink.close()
    assert sink.body == {"message": {"type": 1, "text": "Hi there!"}}


@pytest.mark.asyncio
async def test_json_sink_no_terminal_falls_back_to_concat():
    """If runner errors before emit_terminal, JSONSink still has accumulated deltas."""
    sink = JSONSink()
    await sink.emit_delta("partial")
    await sink.close()
    assert sink.body == {"message": {"type": 1, "text": "partial"}}
