"""SSE wire format and ReplySink protocol. See spec §7.

Frames per CINNOX spec §3.4:
  - delta:    data: {"message":{"type":1,"text":"<chunk>","streamType":"delta"}}\n\n
  - terminal: data: {"message":{"type":1,"text":"<full>"}}\n\n
  - keepalive: : keepalive\n\n          (comment line, ignored by SSE clients)
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Protocol

logger = logging.getLogger("autoservice.general_bot.sse")

KEEPALIVE_INTERVAL_S = 15
MAX_CUMULATIVE_BYTES = 4 * 1024 * 1024  # spec §8


class ReplySink(Protocol):
    async def emit_delta(self, text: str) -> None: ...
    async def emit_terminal(self, text: str) -> None: ...
    async def close(self) -> None: ...


SendBytes = Callable[[bytes], Awaitable[None]]


class SSEStream:
    """ReplySink that writes CINNOX-shaped SSE events to a byte-sink callable.

    The byte sink is supplied by the FastAPI StreamingResponse generator —
    typically `asyncio.Queue.put`. Keepalive runs in a background task that
    is cancelled on close.
    """

    def __init__(
        self,
        send: SendBytes,
        *,
        keepalive_interval_s: float = KEEPALIVE_INTERVAL_S,
    ) -> None:
        self._send = send
        self._closed = False
        self._cumulative = 0
        self.truncated = False
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(keepalive_interval_s),
        )

    async def emit_delta(self, text: str) -> None:
        if self._closed or not text:
            return
        if self.truncated:
            return
        encoded_len = len(text.encode("utf-8"))
        crosses_cap = self._cumulative + encoded_len > MAX_CUMULATIVE_BYTES
        self._cumulative += encoded_len
        await self._send_event({"type": 1, "text": text, "streamType": "delta"})
        if crosses_cap:
            self.truncated = True
            logger.warning(
                "SSE stream truncated at 4MB cumulative cap "
                "(emitted=%d, last_chunk=%d)",
                self._cumulative, encoded_len,
            )

    async def emit_terminal(self, text: str) -> None:
        if self._closed:
            return
        await self._send_event({"type": 1, "text": text})
        await self.close()

    async def emit_keepalive(self) -> None:
        if self._closed:
            return
        try:
            await self._send(b": keepalive\n\n")
        except Exception:
            self._closed = True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._keepalive_task.cancel()

    async def _send_event(self, message: dict) -> None:
        body = json.dumps({"message": message}, ensure_ascii=False)
        await self._send(b"data: " + body.encode("utf-8") + b"\n\n")

    async def _keepalive_loop(self, interval_s: float) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(interval_s)
                if not self._closed:
                    await self.emit_keepalive()
        except asyncio.CancelledError:
            pass


class JSONSink:
    """ReplySink that buffers deltas + records the terminal text.

    Used by the non-streaming path (Accept: application/json). Route handler
    reads .body after stream_agent_reply returns.
    """

    def __init__(self) -> None:
        self._buf: list[str] = []
        self._final: str | None = None
        self._closed = False

    async def emit_delta(self, text: str) -> None:
        if self._closed:
            return
        self._buf.append(text)

    async def emit_terminal(self, text: str) -> None:
        self._final = text
        await self.close()

    async def close(self) -> None:
        self._closed = True

    @property
    def body(self) -> dict:
        text = self._final if self._final is not None else "".join(self._buf)
        return {"message": {"type": 1, "text": text}}
