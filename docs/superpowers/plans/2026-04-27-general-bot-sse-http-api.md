# General Bot SSE HTTP API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an inbound HTTP/SSE endpoint `POST /chat/{tenant_id}` so third-party IM platforms (CINNOX-compatible) can post end-user messages and receive a streaming bot reply.

**Architecture:** New module `autoservice/integrations/general_bot/` with route handler → API-key auth → tenant resolver → conversation_engine → transport-agnostic `stream_agent_reply` → `SSEStream`/`JSONSink`. Reuses triage / KB pre-fetch / multi-role pool from the existing WS pipeline; serializes per-conversation turns via the existing `turn_queue`. Two tiny touches to shared code: a metadata guard in `_arm_takeover_timer` and a one-line `include_router` in `web_gateway.create_app`.

**Tech Stack:** Python 3.12, FastAPI/Starlette, pytest, `claude_agent_sdk`, SHA-256 + `secrets.compare_digest` for keys, `asyncio.Queue` for runner→SSE bridge.

**Spec:** [docs/superpowers/specs/2026-04-27-general-bot-sse-http-api-design.md](../specs/2026-04-27-general-bot-sse-http-api-design.md)

**Test conventions:**
- Use `pytest` + `pytest.mark.asyncio` (already configured in repo).
- Integration tests use `starlette.testclient.TestClient` (sync API works for streaming bodies — `r.iter_lines()`).
- For SDK-stream stubs use `claude_agent_sdk.types.StreamEvent` with `event={"type":"content_block_delta","delta":{"type":"text_delta","text":...}}` (pattern in [tests/gateway/test_drain_into_bubbles.py:57](../../../tests/gateway/test_drain_into_bubbles.py#L57)).
- Each task ends with a commit; no batching.

---

## Task 1: Module skeleton + test layout

**Files:**
- Create: `autoservice/integrations/__init__.py`
- Create: `autoservice/integrations/general_bot/__init__.py`
- Create: `autoservice/integrations/general_bot/auth.py`
- Create: `autoservice/integrations/general_bot/sse.py`
- Create: `autoservice/integrations/general_bot/reply_pipeline.py`
- Create: `autoservice/integrations/general_bot/routes.py`
- Create: `tests/integrations/__init__.py`
- Create: `tests/integrations/general_bot/__init__.py`
- Create: `tests/integrations/general_bot/conftest.py`

- [ ] **Step 1: Create the package directories with empty modules**

```python
# autoservice/integrations/__init__.py
```

```python
# autoservice/integrations/general_bot/__init__.py
"""General-bot inbound HTTP/SSE API. Spec: docs/superpowers/specs/2026-04-27-general-bot-sse-http-api-design.md"""
```

```python
# autoservice/integrations/general_bot/auth.py
"""Per-tenant API key load + verify. See spec §5."""
```

```python
# autoservice/integrations/general_bot/sse.py
"""SSE wire format and ReplySink protocol. See spec §7."""
```

```python
# autoservice/integrations/general_bot/reply_pipeline.py
"""Transport-agnostic stream_agent_reply (D3). See spec §6."""
```

```python
# autoservice/integrations/general_bot/routes.py
"""FastAPI router with POST /chat/{tenant_id}. See spec §4."""
```

- [ ] **Step 2: Create the test directories**

```python
# tests/integrations/__init__.py
```

```python
# tests/integrations/general_bot/__init__.py
```

```python
# tests/integrations/general_bot/conftest.py
"""Shared fixtures for general_bot tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sandbox_dir(tmp_path: Path, monkeypatch) -> Path:
    """Point bootstrap at a temp project root so api_keys.json writes
    don't pollute the real .autoservice/ folder."""
    root = tmp_path / "project"
    (root / ".autoservice" / "sandbox").mkdir(parents=True)
    monkeypatch.setattr(
        "autoservice.bootstrap.PROJECT_ROOT", root,
    )
    return root
```

- [ ] **Step 3: Sanity-check the imports**

Run: `python -c "from autoservice.integrations.general_bot import auth, sse, reply_pipeline, routes"`
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add autoservice/integrations/ tests/integrations/
git commit -m "feat(general-bot): module skeleton + test layout"
```

---

## Task 2: `SSEStream` and `JSONSink` (wire format)

**Files:**
- Modify: `autoservice/integrations/general_bot/sse.py`
- Create: `tests/integrations/general_bot/test_sse_sink.py`

- [ ] **Step 1: Write the test file**

```python
# tests/integrations/general_bot/test_sse_sink.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integrations/general_bot/test_sse_sink.py -v`
Expected: ImportError (`MAX_CUMULATIVE_BYTES`, `SSEStream`, `JSONSink` not defined).

- [ ] **Step 3: Implement `sse.py`**

```python
# autoservice/integrations/general_bot/sse.py
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
        if self._cumulative + encoded_len > MAX_CUMULATIVE_BYTES:
            self.truncated = True
            logger.warning(
                "SSE stream truncated at 4MB cumulative cap "
                "(emitted=%d, attempted=%d)",
                self._cumulative, encoded_len,
            )
            return
        self._cumulative += encoded_len
        await self._send_event({"type": 1, "text": text, "streamType": "delta"})

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integrations/general_bot/test_sse_sink.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add autoservice/integrations/general_bot/sse.py tests/integrations/general_bot/test_sse_sink.py
git commit -m "feat(general-bot): SSE/JSON sink wire-format helpers"
```

---

## Task 3: API key auth (load + verify) + key-issuer CLI

**Files:**
- Modify: `autoservice/integrations/general_bot/auth.py`
- Create: `scripts/issue_general_bot_key.py`
- Create: `tests/integrations/general_bot/test_auth.py`

- [ ] **Step 1: Write the auth tests**

```python
# tests/integrations/general_bot/test_auth.py
"""Per-tenant API key auth tests. Spec §5."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoservice.integrations.general_bot.auth import (
    KEY_FILE_NAME,
    issue_key,
    verify_api_key,
    _hash_key,
)


def _seed_keys(sandbox: Path, tid: str, *, key_id: str = "k1", revoked: bool = False) -> str:
    """Seed an api_keys.json with one entry; return raw key."""
    raw = "test_raw_key_" + key_id
    entry = {
        "key_id": key_id,
        "hash": _hash_key(raw),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "revoked_at": datetime.now(timezone.utc).isoformat() if revoked else None,
        "label": "test",
    }
    tdir = sandbox / ".autoservice" / "sandbox" / tid
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / KEY_FILE_NAME).write_text(json.dumps([entry]), encoding="utf-8")
    return raw


def test_verify_valid_key(sandbox_dir: Path):
    raw = _seed_keys(sandbox_dir, "tenantA")
    assert verify_api_key("tenantA", raw) is True


def test_verify_unknown_tenant_returns_false(sandbox_dir: Path):
    # No api_keys.json for tenant "ghost"
    assert verify_api_key("ghost", "anything") is False


def test_verify_wrong_key_returns_false(sandbox_dir: Path):
    _seed_keys(sandbox_dir, "tenantA")
    assert verify_api_key("tenantA", "wrong") is False


def test_verify_revoked_key_returns_false(sandbox_dir: Path):
    raw = _seed_keys(sandbox_dir, "tenantA", revoked=True)
    assert verify_api_key("tenantA", raw) is False


def test_verify_empty_key_returns_false(sandbox_dir: Path):
    _seed_keys(sandbox_dir, "tenantA")
    assert verify_api_key("tenantA", "") is False
    assert verify_api_key("tenantA", None) is False  # type: ignore[arg-type]


def test_issue_key_creates_file_and_returns_raw(sandbox_dir: Path):
    (sandbox_dir / ".autoservice" / "sandbox" / "tenantB").mkdir(parents=True)
    raw, key_id = issue_key("tenantB", label="cinnox-prod")
    assert isinstance(raw, str) and len(raw) >= 32
    assert key_id.startswith("k_")
    # Verify roundtrip
    assert verify_api_key("tenantB", raw) is True


def test_issue_key_appends_not_overwrites(sandbox_dir: Path):
    (sandbox_dir / ".autoservice" / "sandbox" / "tenantC").mkdir(parents=True)
    raw1, _ = issue_key("tenantC", label="first")
    raw2, _ = issue_key("tenantC", label="second")
    assert raw1 != raw2
    assert verify_api_key("tenantC", raw1) is True
    assert verify_api_key("tenantC", raw2) is True


def test_issue_key_creates_sandbox_dir_if_missing(sandbox_dir: Path):
    # Don't pre-create the sandbox/<tid>/ dir
    raw, _ = issue_key("tenantD", label="autocreate")
    assert verify_api_key("tenantD", raw) is True


def test_hash_is_sha256_hex(sandbox_dir: Path):
    h = _hash_key("hello")
    assert len(h) == 64
    int(h, 16)  # raises if not hex
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integrations/general_bot/test_auth.py -v`
Expected: ImportError (functions not defined yet).

- [ ] **Step 3: Implement `auth.py`**

```python
# autoservice/integrations/general_bot/auth.py
"""Per-tenant API key load + verify. Spec §5.

Storage: .autoservice/sandbox/<tenant_id>/api_keys.json
Schema:  [{"key_id","hash","created_at","revoked_at","label"}, ...]
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

from autoservice import bootstrap

logger = logging.getLogger("autoservice.general_bot.auth")

KEY_FILE_NAME = "api_keys.json"


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _keys_path(tenant_id: str) -> Path:
    return (
        bootstrap.PROJECT_ROOT
        / ".autoservice" / "sandbox" / tenant_id / KEY_FILE_NAME
    )


def _load_keys(tenant_id: str) -> list[dict]:
    path = _keys_path(tenant_id)
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("api_keys.json parse failed for tenant=%s", tenant_id)
        return []


def verify_api_key(tenant_id: str, raw_key: str | None) -> bool:
    """Timing-safe verify of raw_key against any non-revoked entry."""
    if not raw_key or not isinstance(raw_key, str):
        return False
    expected_hash = _hash_key(raw_key)
    matched = False
    for entry in _load_keys(tenant_id):
        if entry.get("revoked_at"):
            continue
        stored = entry.get("hash") or ""
        # compare_digest still timing-safe even on length mismatch
        if secrets.compare_digest(expected_hash, stored):
            matched = True
            # do not break — keep loop time constant-ish across hits/misses
    return matched


def issue_key(tenant_id: str, *, label: str = "") -> tuple[str, str]:
    """Generate a new key, append hash to api_keys.json, return (raw, key_id).

    The raw key is returned ONCE. Caller is responsible for showing it to the
    operator who then shares it with the third-party platform; it is never
    stored server-side after this call.
    """
    raw = secrets.token_urlsafe(32)
    key_id = "k_" + secrets.token_hex(8)
    entry = {
        "key_id": key_id,
        "hash": _hash_key(raw),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "revoked_at": None,
        "label": label,
    }
    path = _keys_path(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = _load_keys(tenant_id)
    keys.append(entry)
    path.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    return raw, key_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integrations/general_bot/test_auth.py -v`
Expected: 9 passed.

- [ ] **Step 5: Implement the CLI**

```python
# scripts/issue_general_bot_key.py
"""CLI: mint an API key for a general-bot tenant.

Usage: python scripts/issue_general_bot_key.py <tenant_id> [--label LABEL]

Prints the raw key to stdout (once — never stored). Appends the hash to
.autoservice/sandbox/<tenant_id>/api_keys.json.
"""
from __future__ import annotations

import argparse
import sys

from autoservice.integrations.general_bot.auth import issue_key


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue a general-bot API key")
    parser.add_argument("tenant_id")
    parser.add_argument("--label", default="", help="human-readable label")
    args = parser.parse_args()

    raw, key_id = issue_key(args.tenant_id, label=args.label)
    print(f"key_id: {key_id}")
    print(f"raw key (save now, will not be shown again): {raw}")
    print()
    print("Configure CINNOX (or other platform) with:")
    print(f"  Authorization: Bearer {raw}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Smoke-test the CLI**

Run: `python scripts/issue_general_bot_key.py --help`
Expected: argparse usage line including `tenant_id` and `--label`.

- [ ] **Step 7: Commit**

```bash
git add autoservice/integrations/general_bot/auth.py scripts/issue_general_bot_key.py tests/integrations/general_bot/test_auth.py
git commit -m "feat(general-bot): API key store + verify + issuer CLI"
```

---

## Task 4: Reply pipeline core — drain + persistence

**Files:**
- Modify: `autoservice/integrations/general_bot/reply_pipeline.py`
- Create: `tests/integrations/general_bot/test_reply_pipeline.py`

This task builds the `_drain_to_sink` helper and a stub of `stream_agent_reply` that does NOT yet integrate triage; that lands in Task 5. Splitting keeps each task small.

- [ ] **Step 1: Write the drain test**

```python
# tests/integrations/general_bot/test_reply_pipeline.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integrations/general_bot/test_reply_pipeline.py -v`
Expected: ImportError (`_drain_to_sink` not defined).

- [ ] **Step 3: Implement `_drain_to_sink`**

```python
# autoservice/integrations/general_bot/reply_pipeline.py
"""Transport-agnostic stream_agent_reply (D3). See spec §6.

The pipeline reuses triage + KB pre-fetch + multi-role pool from the WS
flow, but pushes output through a ReplySink instead of WS frames. Single
agent message persisted at end (no multi-bubble — irrelevant for SSE).
"""
from __future__ import annotations

import logging
import time as _time
from typing import Any, AsyncIterator

from autoservice.integrations.general_bot.sse import ReplySink

logger = logging.getLogger("autoservice.general_bot.pipeline")


async def _drain_to_sink(
    iterator: AsyncIterator[Any],
    sink: ReplySink,
    *,
    perf: dict | None = None,
) -> str:
    """Consume claude_agent_sdk stream → ReplySink. Returns full text.

    Mirrors message_router._drain_into_bubbles' SDK-event branching but
    without bubble/edit logic (CINNOX SSE has no edit semantics).
    """
    from claude_agent_sdk.types import AssistantMessage, ResultMessage, StreamEvent

    full = ""
    saw_stream_text = False
    async for item in iterator:
        if isinstance(item, StreamEvent):
            ev = getattr(item, "event", None) or {}
            if ev.get("type") == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta":
                    chunk = delta.get("text") or ""
                    if chunk:
                        if perf is not None and "first_token_t" not in perf:
                            perf["first_token_t"] = _time.perf_counter()
                        saw_stream_text = True
                        full += chunk
                        await sink.emit_delta(chunk)
        elif isinstance(item, AssistantMessage) and item.content and not saw_stream_text:
            for block in item.content:
                text = getattr(block, "text", None)
                if isinstance(text, str) and text:
                    if perf is not None and "first_token_t" not in perf:
                        perf["first_token_t"] = _time.perf_counter()
                    full += text
                    await sink.emit_delta(text)
        elif isinstance(item, ResultMessage) and getattr(item, "result", None) and not saw_stream_text:
            text = item.result
            if perf is not None and "first_token_t" not in perf:
                perf["first_token_t"] = _time.perf_counter()
            full += text
            await sink.emit_delta(text)
    return full
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integrations/general_bot/test_reply_pipeline.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add autoservice/integrations/general_bot/reply_pipeline.py tests/integrations/general_bot/test_reply_pipeline.py
git commit -m "feat(general-bot): SDK stream → ReplySink drain helper"
```

---

## Task 5: Reply pipeline — `stream_agent_reply` with triage + KB + persistence

**Files:**
- Modify: `autoservice/integrations/general_bot/reply_pipeline.py`
- Modify: `tests/integrations/general_bot/test_reply_pipeline.py`

- [ ] **Step 1: Add tests for `stream_agent_reply` covering 3 branches**

Append to `tests/integrations/general_bot/test_reply_pipeline.py`:

```python
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

    _patch_triage_decision(monkeypatch, role="direct", direct_reply="您好,有什么可以帮您?")
    engine = _FakeEngine()
    pool = _FakePool(["should not be called"])
    sink = JSONSink()

    out = await stream_agent_reply(
        engine=engine, pool=pool, conv_id="c1",
        customer_text="你好", tenant_id="tenantA", sink=sink,
    )

    assert out == "您好,有什么可以帮您?"
    assert pool.called_with is None  # short-circuit avoided pool
    assert sink.body == {"message": {"type": 1, "text": "您好,有什么可以帮您?"}}


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

    assert out == "您好,请问有什么可以帮您?"
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

    assert out == "(抱歉,本次未生成有效回复)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integrations/general_bot/test_reply_pipeline.py -v`
Expected: 4 new tests fail (ImportError on `stream_agent_reply`).

- [ ] **Step 3: Implement `stream_agent_reply`**

Append to `autoservice/integrations/general_bot/reply_pipeline.py`:

```python
# --- triage + KB + pool integration ---

# Imports done at module top so monkeypatch in tests can swap them.
from autoservice.triage_dispatch import (
    triage_and_route,
    _build_customer_prompt,
    _build_reseeded_prompt,
)
from autoservice.triage_config_loader import load_tenant_config_for_conv
from autoservice.gateway.message_router import _collect_operator_suggestions


_DIRECT_FALLBACK_TEXT = "您好,请问有什么可以帮您?"
_EMPTY_REPLY_FALLBACK = "(抱歉,本次未生成有效回复)"


def _compose_role_prompt(suggestions: str, customer_text: str) -> str:
    """Non-customer-role prompt shape (mirrors message_router._call_engine)."""
    if suggestions:
        return (
            f"{suggestions}\n"
            f"Customer message: {customer_text}\n\n"
            "You are a customer service AI. The operator has given you "
            "instructions above — follow them when replying to the customer. "
            "Reply in the same language as the customer."
        )
    return (
        f"Customer message: {customer_text}\n\n"
        "Reply briefly in the same language as the customer."
    )


async def _persist_agent_message(engine, conv_id: str, text: str, *, metadata=None):
    """Persist a single agent message row (no segments — spec §6.3)."""
    return await engine.send_message(
        conv_id, source="agent", content=text,
        metadata=dict(metadata) if metadata else {},
    )


async def stream_agent_reply(
    *,
    engine,
    pool,
    conv_id: str,
    customer_text: str,
    tenant_id: str,
    sink: ReplySink,
    perf: dict | None = None,
) -> str:
    """Run triage → KB pre-fetch → pool stream → sink. Persists one final
    agent message. Returns full reply text.

    Errors propagate to the caller (route handler decides how to surface
    them — typically via terminal SSE event since headers are already sent).
    """
    if perf is None:
        perf = {}
    perf["t0"] = _time.perf_counter()

    cfg = await load_tenant_config_for_conv(engine, conv_id)
    decision = await triage_and_route(
        engine=engine, conv_id=conv_id,
        customer_text=customer_text, tenant_config=cfg,
    )
    perf["t_triage"] = _time.perf_counter()

    # Direct-reply short-circuit (spec §6 step 2)
    if decision.role == "direct":
        text = decision.direct_reply or _DIRECT_FALLBACK_TEXT
        if not decision.direct_reply:
            logger.warning(
                "direct route with empty direct_reply conv=%s intent=%s — "
                "using generic fallback", conv_id, decision.intent,
            )
        await sink.emit_terminal(text)
        await _persist_agent_message(engine, conv_id, text)
        return text

    # Reseed history if role switched
    if decision.previous_role and decision.previous_role != decision.role:
        prompt_text = await _build_reseeded_prompt(
            engine, conv_id, customer_text,
            previous_role=decision.previous_role, new_role=decision.role,
            token_limit=getattr(cfg, "history_reseed_token_limit", 2000),
        )
    else:
        prompt_text = customer_text

    suggestions = await _collect_operator_suggestions(engine, conv_id)

    if decision.role == "customer":
        prompt = await _build_customer_prompt(
            tenant_id=tenant_id, customer_text=prompt_text,
            operator_suggestions=suggestions,
        )
    else:
        prompt = _compose_role_prompt(suggestions, prompt_text)

    perf["t_prompt_built"] = _time.perf_counter()

    iterator = pool.session_query(
        conv_id, prompt, tenant_id=tenant_id, tier=decision.tier,
    )

    full_text = await _drain_to_sink(iterator, sink, perf=perf)

    if not full_text.strip():
        logger.warning("stream_agent_reply: empty reply conv=%s", conv_id)
        full_text = _EMPTY_REPLY_FALLBACK
        await sink.emit_terminal(full_text)
        await _persist_agent_message(
            engine, conv_id, full_text, metadata={"is_fallback": True},
        )
        return full_text

    await sink.emit_terminal(full_text)
    await _persist_agent_message(engine, conv_id, full_text)
    perf["t_done"] = _time.perf_counter()
    return full_text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integrations/general_bot/test_reply_pipeline.py -v`
Expected: 8 passed (4 from Task 4 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add autoservice/integrations/general_bot/reply_pipeline.py tests/integrations/general_bot/test_reply_pipeline.py
git commit -m "feat(general-bot): stream_agent_reply pipeline with triage + KB"
```

---

## Task 6: Routes — POST `/chat/{tenant_id}` (auth + tenant + body parse + sink wiring)

**Files:**
- Modify: `autoservice/integrations/general_bot/routes.py`
- Create: `tests/integrations/general_bot/test_routes.py`
- Create: `tests/integrations/general_bot/_helpers.py` (shared fixtures across route tests)

This task wires the route handler end-to-end for the happy path. Concurrency, watchdog, and error edges land in Tasks 8–9.

- [ ] **Step 1: Helper file for shared route fixtures**

```python
# tests/integrations/general_bot/_helpers.py
"""Shared route-test helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoservice.integrations.general_bot.auth import _hash_key, KEY_FILE_NAME


def seed_api_key(sandbox: Path, tenant_id: str, raw: str = "test_key_xyz") -> str:
    import json
    entry = {
        "key_id": "k_test",
        "hash": _hash_key(raw),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "revoked_at": None,
        "label": "test",
    }
    tdir = sandbox / ".autoservice" / "sandbox" / tenant_id
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / KEY_FILE_NAME).write_text(json.dumps([entry]), encoding="utf-8")
    # Also seed a config.json marker so tenant_resolver accepts the tid
    (tdir / "config.json").write_text("{}", encoding="utf-8")
    return raw


def parse_sse_events(body_bytes: bytes) -> list[dict | str]:
    """Decode an SSE response body into a list of events.

    `data:` lines → dicts (JSON-parsed). `:` comment lines → the comment string.
    """
    import json
    out: list[Any] = []
    for chunk in body_bytes.split(b"\n\n"):
        if not chunk:
            continue
        chunk_s = chunk.decode("utf-8").strip()
        if chunk_s.startswith(":"):
            out.append(chunk_s)
        elif chunk_s.startswith("data:"):
            payload = chunk_s[len("data:"):].strip()
            out.append(json.loads(payload))
    return out
```

- [ ] **Step 2: Write the routes happy-path tests**

```python
# tests/integrations/general_bot/test_routes.py
"""POST /chat/{tenant_id} happy-path + body shape tests. Spec §4."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.integrations.general_bot._helpers import (
    parse_sse_events, seed_api_key,
)


@pytest.fixture
def app(sandbox_dir: Path, monkeypatch):
    """FastAPI app with general_bot router mounted, pool stubbed."""
    monkeypatch.setenv("CONV_PERSIST", "0")
    monkeypatch.setenv("DREAM_SCHEDULER_DISABLED", "1")
    monkeypatch.setenv("GENERAL_BOT_ENABLED", "1")
    monkeypatch.setenv("POOL_MODE", "1")

    # Stub _get_pool to a fake pool that yields a fixed reply
    from autoservice.integrations.general_bot import reply_pipeline

    class _FakePool:
        def session_query(self, conv_id, prompt, *, tenant_id=None, tier=None):
            from claude_agent_sdk.types import StreamEvent
            async def _gen():
                for c in ["Hi! ", "I received."]:
                    yield StreamEvent(
                        uuid="u", session_id="s",
                        event={"type": "content_block_delta",
                               "delta": {"type": "text_delta", "text": c}},
                    )
            return _gen()

    async def fake_get_pool():
        return _FakePool()

    monkeypatch.setattr(
        "autoservice.web_gateway._get_pool", fake_get_pool,
    )

    # Stub triage to deterministic customer-route decision
    from autoservice.model_router import TriageDecision

    async def fake_triage(*, engine, conv_id, customer_text, tenant_config):
        return TriageDecision(
            role="customer", intent="general_question", confidence=0.9,
            source="stub", summary=None, detected_language="en",
            previous_role=None, direct_reply=None, tier="fast",
        )
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline.triage_and_route",
        fake_triage,
    )

    async def fake_cfg(engine, conv_id):
        class _C:
            tenant_id = "tenantA"
            triage_dispatch_enabled = True
            history_reseed_token_limit = 2000
        return _C()
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline.load_tenant_config_for_conv",
        fake_cfg,
    )

    async def fake_build_prompt(*, tenant_id, customer_text, operator_suggestions):
        return customer_text
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline._build_customer_prompt",
        fake_build_prompt,
    )

    async def fake_suggestions(*a, **k):
        return ""
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline._collect_operator_suggestions",
        fake_suggestions,
    )

    from autoservice.web_gateway import create_app
    return create_app()


def test_streaming_happy_path(app, sandbox_dir):
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"query": "hello", "inquiryID": "inq-001"},
            headers={
                "Authorization": f"Bearer {raw_key}",
                "Accept": "text/event-stream",
            },
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["x-accel-buffering"] == "no"
    events = parse_sse_events(r.content)
    deltas = [e for e in events if isinstance(e, dict)
              and e["message"].get("streamType") == "delta"]
    terminals = [e for e in events if isinstance(e, dict)
                 and e["message"].get("streamType") is None
                 and e["message"]["type"] == 1]
    assert len(deltas) >= 1
    assert len(terminals) == 1
    assert terminals[0]["message"]["text"] == "Hi! I received."


def test_json_path_no_accept_header(app, sandbox_dir):
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"query": "hello", "inquiryID": "inq-002"},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body == {"message": {"type": 1, "text": "Hi! I received."}}


def test_legacy_query_result_shape_accepted(app, sandbox_dir):
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"queryResult": {"queryText": "hello"}, "inquiryID": "inq-003"},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert r.status_code == 200
    assert r.json()["message"]["text"] == "Hi! I received."


def test_missing_query_returns_422(app, sandbox_dir):
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"inquiryID": "inq-004"},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert r.status_code == 422
    assert "query" in r.json()["error"]


def test_inquiry_id_reuses_conversation(app, sandbox_dir):
    """Same inquiryID across two calls should hit the same conv_id (idempotent
    create_conversation). Test via app.state.engine."""
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        client.post(
            "/chat/tenantA", json={"query": "first", "inquiryID": "inq-multi"},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        client.post(
            "/chat/tenantA", json={"query": "second", "inquiryID": "inq-multi"},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    expected_conv_id = "cinnox_tenantA:inq-multi"
    conv = app.state.engine._conversations.get(expected_conv_id)
    assert conv is not None
    assert conv.metadata["tenant_id"] == "tenantA"
    assert conv.metadata["inquiry_id"] == "inq-multi"
    assert conv.metadata["passive_channel"] is True
    msgs = app.state.engine._messages[expected_conv_id]
    customer_msgs = [m for m in msgs if m.source.startswith("cinnox:")]
    assert len(customer_msgs) == 2  # both turns persisted on same conv


def test_inquiry_id_absent_creates_oneshot(app, sandbox_dir):
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r1 = client.post(
            "/chat/tenantA", json={"query": "first"},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        r2 = client.post(
            "/chat/tenantA", json={"query": "second"},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert r1.status_code == 200 and r2.status_code == 200
    oneshot_convs = [
        c for cid, c in app.state.engine._conversations.items()
        if cid.startswith("cinnox-oneshot_")
    ]
    assert len(oneshot_convs) == 2  # two distinct convs
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/integrations/general_bot/test_routes.py -v`
Expected: ImportError on the route module / 404 because router not mounted yet.

- [ ] **Step 4: Implement `routes.py`**

```python
# autoservice/integrations/general_bot/routes.py
"""FastAPI router with POST /chat/{tenant_id}. Spec §4.

Wires together: API-key auth → tenant resolver → conversation_engine →
turn_queue → stream_agent_reply → SSEStream / JSONSink.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from autoservice.conversation_engine.errors import ConversationNotFound
from autoservice.conversation_engine.types import Participant, ParticipantRole
from autoservice.gateway.message_router import _broadcast_to_squad
from autoservice.gateway.message_router import _message_frame
from autoservice.gateway.tenant_resolver import resolve_customer_tenant
from autoservice.gateway.turn_queue import QueueFullError
from autoservice.integrations.general_bot.auth import verify_api_key
from autoservice.integrations.general_bot.reply_pipeline import stream_agent_reply
from autoservice.integrations.general_bot.sse import (
    SSEStream, JSONSink,
)

logger = logging.getLogger("autoservice.general_bot.routes")

general_bot_router = APIRouter(tags=["general-bot"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_UNAUTHORIZED_BODY = {"error": "unauthorized"}


def _extract_query(body: Any) -> str | None:
    """Accept both modern ({"query": ...}) and legacy ({"queryResult":{"queryText":...}}) shapes."""
    if not isinstance(body, dict):
        return None
    q = body.get("query")
    if isinstance(q, str) and q.strip():
        return q
    qr = body.get("queryResult")
    if isinstance(qr, dict):
        qt = qr.get("queryText")
        if isinstance(qt, str) and qt.strip():
            return qt
    return None


def _wants_streaming(accept_header: str | None) -> bool:
    if not accept_header:
        return False
    return "text/event-stream" in accept_header.lower()


def _bearer_token(auth_header: str | None) -> str | None:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


async def _persist_customer_message(
    engine, *, tenant_id: str, inquiry_id: str | None, query: str,
) -> tuple[str, Any]:
    """Idempotent conv create + customer message persist + squad broadcast.

    Returns (conv_id, customer_msg).
    """
    from autoservice.web_gateway import _get_squad_plugin

    if inquiry_id:
        external_id = f"{tenant_id}:{inquiry_id}"
        channel = "cinnox"
    else:
        external_id = str(uuid.uuid4())
        channel = "cinnox-oneshot"

    sp = _get_squad_plugin()
    squad_id = sp.choose_squad(channel="cinnox") if sp else None

    metadata = {
        "tenant_id": tenant_id,
        "passive_channel": True,
    }
    if inquiry_id:
        metadata["inquiry_id"] = inquiry_id
    if squad_id:
        metadata["squad_id"] = squad_id

    conv = await engine.create_conversation(
        channel=channel, external_id=external_id, metadata=metadata,
    )
    conv_id = conv.id

    # Defensive: on reuse, ensure tenant matches (only fails on data corruption)
    existing_tid = conv.metadata.get("tenant_id")
    if existing_tid and existing_tid != tenant_id:
        logger.error(
            "tenant mismatch on conv reuse: conv=%s expected=%s got=%s",
            conv_id, tenant_id, existing_tid,
        )
        raise HTTPException(status_code=401, detail="unauthorized")

    source = f"cinnox:{inquiry_id or 'anon'}"
    # Auto-join the customer participant on first turn
    try:
        await engine.join(
            conv_id,
            Participant(
                id=source, role=ParticipantRole.CUSTOMER,
                joined_at=datetime.now(timezone.utc),
            ),
        )
    except Exception:
        pass  # already joined

    msg = await engine.send_message(conv_id, source=source, content=query)

    # Broadcast customer message to operator squad (E1)
    try:
        frame = _message_frame(msg)
        frame["payload"]["source_display"] = {"id": source, "role": "customer"}
        if squad_id:
            frame["payload"]["squad_id"] = squad_id
        await _broadcast_to_squad(frame, conv_id)
    except Exception:
        logger.exception("customer broadcast failed conv=%s", conv_id)

    return conv_id, msg


@general_bot_router.post("/chat/{tenant_id}")
async def post_chat(tenant_id: str, request: Request):
    if os.getenv("GENERAL_BOT_ENABLED", "1") != "1":
        return JSONResponse(status_code=503, content={"error": "general_bot disabled"})

    # 1. Auth (verify Bearer key first; same body as 404 → no oracle)
    raw_key = _bearer_token(request.headers.get("authorization"))
    if not raw_key or not verify_api_key(tenant_id, raw_key):
        return JSONResponse(status_code=401, content=_UNAUTHORIZED_BODY)

    # 2. Tenant resolve (registration markers must exist)
    tid, reject_reason = resolve_customer_tenant({"tenant": tenant_id})
    if reject_reason is not None:
        return JSONResponse(status_code=401, content=_UNAUTHORIZED_BODY)

    # 3. Body parse
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(status_code=422, content={"error": "invalid JSON body"})
    query = _extract_query(body)
    if not query:
        return JSONResponse(status_code=422, content={"error": "query required"})
    inquiry_id = body.get("inquiryID") if isinstance(body, dict) else None
    if inquiry_id is not None and not isinstance(inquiry_id, str):
        return JSONResponse(status_code=422, content={"error": "inquiryID must be string"})

    engine = request.app.state.engine
    from autoservice.web_gateway import _get_pool
    pool = await _get_pool()
    if pool is None:
        return JSONResponse(status_code=503, content={"error": "cc_pool unavailable"})

    # 4. Persist customer message + squad broadcast
    conv_id, _customer_msg = await _persist_customer_message(
        engine, tenant_id=tid, inquiry_id=inquiry_id, query=query,
    )

    # 5. Dispatch (streaming or JSON)
    streaming = _wants_streaming(request.headers.get("accept"))
    if streaming:
        return await _dispatch_streaming(
            engine=engine, pool=pool, conv_id=conv_id,
            query=query, tenant_id=tid,
        )
    else:
        return await _dispatch_json(
            engine=engine, pool=pool, conv_id=conv_id,
            query=query, tenant_id=tid,
        )


async def _dispatch_json(*, engine, pool, conv_id, query, tenant_id):
    sink = JSONSink()
    await stream_agent_reply(
        engine=engine, pool=pool, conv_id=conv_id,
        customer_text=query, tenant_id=tenant_id, sink=sink,
    )
    return JSONResponse(content=sink.body)


async def _dispatch_streaming(*, engine, pool, conv_id, query, tenant_id):
    """Bridge the runner → SSE wire via an asyncio.Queue (spec §8)."""
    queue: asyncio.Queue = asyncio.Queue()

    async def _send(line: bytes) -> None:
        await queue.put(line)

    sink = SSEStream(_send)

    async def _runner():
        try:
            await stream_agent_reply(
                engine=engine, pool=pool, conv_id=conv_id,
                customer_text=query, tenant_id=tenant_id, sink=sink,
            )
        except Exception:
            logger.exception("stream_agent_reply failed conv=%s", conv_id)
            try:
                await sink.emit_terminal("(抱歉,本次未能生成完整回复)")
            except Exception:
                pass
        finally:
            await sink.close()
            await queue.put(None)  # sentinel

    runner_task = asyncio.create_task(_runner(), name=f"general-bot-{conv_id}")

    async def _generator():
        # Initial keepalive: defeat LB idle while runner is starting
        yield b": keepalive\n\n"
        try:
            while True:
                line = await queue.get()
                if line is None:
                    return
                yield line
        finally:
            if not runner_task.done():
                runner_task.cancel()

    return StreamingResponse(
        _generator(), media_type="text/event-stream", headers=_SSE_HEADERS,
    )
```

- [ ] **Step 5: Mount the router in `web_gateway.create_app`**

Edit `autoservice/web_gateway.py`. Find the block that includes the existing routers (around line 392–393):

```python
    app.include_router(onboard_router)
    app.include_router(api_router)
```

Add directly after:

```python
    from autoservice.integrations.general_bot.routes import general_bot_router
    app.include_router(general_bot_router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/integrations/general_bot/test_routes.py -v`
Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add autoservice/integrations/general_bot/routes.py autoservice/web_gateway.py tests/integrations/general_bot/test_routes.py tests/integrations/general_bot/_helpers.py
git commit -m "feat(general-bot): POST /chat/{tenant_id} happy-path streaming + JSON"
```

---

## Task 7: Routes — auth + tenant + validation error coverage

**Files:**
- Modify: `tests/integrations/general_bot/test_routes.py` (append)

This task adds tests-only coverage for the error paths we already implemented in Task 6, ensuring no oracle exists between unknown-tenant and bad-key.

- [ ] **Step 1: Append the error-path tests**

```python
# Append to tests/integrations/general_bot/test_routes.py


def test_missing_authorization_returns_401(app, sandbox_dir):
    seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r = client.post("/chat/tenantA", json={"query": "hi"})
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


def test_wrong_authorization_returns_401(app, sandbox_dir):
    seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"query": "hi"},
            headers={"Authorization": "Bearer wrong-key"},
        )
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


def test_unknown_tenant_returns_401_with_same_body(app, sandbox_dir):
    """No oracle: same response shape for bad-key vs unknown-tenant."""
    with TestClient(app) as client:
        r = client.post(
            "/chat/ghost-tenant",
            json={"query": "hi"},
            headers={"Authorization": "Bearer anything"},
        )
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


def test_non_bearer_authorization_returns_401(app, sandbox_dir):
    seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"query": "hi"},
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
    assert r.status_code == 401


def test_invalid_json_body_returns_422(app, sandbox_dir):
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            content=b"{not-json",
            headers={
                "Authorization": f"Bearer {raw_key}",
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 422


def test_inquiry_id_non_string_returns_422(app, sandbox_dir):
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"query": "hi", "inquiryID": 123},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert r.status_code == 422


def test_general_bot_disabled_returns_503(app, sandbox_dir, monkeypatch):
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    monkeypatch.setenv("GENERAL_BOT_ENABLED", "0")
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"query": "hi"},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert r.status_code == 503
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/integrations/general_bot/test_routes.py -v`
Expected: 13 passed (6 from Task 6 + 7 new).

- [ ] **Step 3: Commit**

```bash
git add tests/integrations/general_bot/test_routes.py
git commit -m "test(general-bot): auth/tenant/validation error coverage"
```

---

## Task 8: Concurrency — `turn_queue` integration + queue-full

**Files:**
- Modify: `autoservice/integrations/general_bot/routes.py`
- Create: `tests/integrations/general_bot/test_concurrent.py`

- [ ] **Step 1: Write the concurrency test**

```python
# tests/integrations/general_bot/test_concurrent.py
"""turn_queue serialization + queue-full handling. Spec §8."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.integrations.general_bot._helpers import seed_api_key


@pytest.fixture
def slow_app(sandbox_dir: Path, monkeypatch):
    monkeypatch.setenv("CONV_PERSIST", "0")
    monkeypatch.setenv("DREAM_SCHEDULER_DISABLED", "1")
    monkeypatch.setenv("GENERAL_BOT_ENABLED", "1")
    monkeypatch.setenv("POOL_MODE", "1")
    monkeypatch.setenv("QUEUE_MAX_DEPTH", "2")  # so 3rd queued submit raises
    monkeypatch.setenv("QUEUE_ENABLED", "1")

    # Reset the turn_queue module-level singleton with new depth
    import autoservice.gateway.message_router as mr
    from autoservice.gateway.turn_queue import TurnQueue
    mr._turn_queue = TurnQueue(max_queue_depth=2)
    # Patch routes' import too if any (it imports get_turn_queue indirectly)

    class _SlowPool:
        def session_query(self, conv_id, prompt, *, tenant_id=None, tier=None):
            from claude_agent_sdk.types import StreamEvent
            async def _gen():
                await asyncio.sleep(0.5)  # slow LLM
                yield StreamEvent(
                    uuid="u", session_id="s",
                    event={"type": "content_block_delta",
                           "delta": {"type": "text_delta", "text": "ok"}},
                )
            return _gen()

    async def fake_get_pool():
        return _SlowPool()
    monkeypatch.setattr("autoservice.web_gateway._get_pool", fake_get_pool)

    from autoservice.model_router import TriageDecision

    async def fake_triage(*, engine, conv_id, customer_text, tenant_config):
        return TriageDecision(
            role="customer", intent="general_question", confidence=0.9,
            source="stub", summary=None, detected_language="en",
            previous_role=None, direct_reply=None, tier="fast",
        )
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline.triage_and_route",
        fake_triage,
    )

    async def fake_cfg(engine, conv_id):
        class _C:
            tenant_id = "tenantA"
            triage_dispatch_enabled = True
            history_reseed_token_limit = 2000
        return _C()
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline.load_tenant_config_for_conv",
        fake_cfg,
    )

    async def fake_build_prompt(*, tenant_id, customer_text, operator_suggestions):
        return customer_text
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline._build_customer_prompt",
        fake_build_prompt,
    )

    async def fake_suggestions(*a, **k):
        return ""
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline._collect_operator_suggestions",
        fake_suggestions,
    )

    from autoservice.web_gateway import create_app
    return create_app()


def test_queue_full_returns_429(slow_app, sandbox_dir):
    """Submit 4 concurrent requests to the same conv; 4th gets 429."""
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    import threading

    results: list[int] = []
    lock = threading.Lock()

    def _post():
        with TestClient(slow_app) as client:
            r = client.post(
                "/chat/tenantA",
                json={"query": "hello", "inquiryID": "same"},
                headers={"Authorization": f"Bearer {raw_key}"},
            )
            with lock:
                results.append(r.status_code)

    threads = [threading.Thread(target=_post) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # Up to (max_depth + 1 in_flight) = 3 should succeed; the rest 429
    assert results.count(200) <= 3
    assert results.count(429) >= 1
```

- [ ] **Step 2: Run the test (will fail — runner is not yet on turn_queue)**

Run: `pytest tests/integrations/general_bot/test_concurrent.py -v`
Expected: FAIL — currently no submission goes through turn_queue, so all 4 succeed concurrently.

- [ ] **Step 3: Wire `turn_queue` into the streaming dispatch**

Edit `autoservice/integrations/general_bot/routes.py`. Find `_dispatch_streaming` and replace its body with a turn_queue-submitting version. Also wire JSON path through the same queue.

Replace the existing two dispatch functions with:

```python
async def _dispatch_streaming(*, engine, pool, conv_id, query, tenant_id):
    """Submit runner to turn_queue + bridge to SSE wire via asyncio.Queue."""
    from autoservice.gateway.message_router import get_turn_queue

    sse_queue: asyncio.Queue = asyncio.Queue()

    async def _send(line: bytes) -> None:
        await sse_queue.put(line)

    sink = SSEStream(_send)

    async def _runner() -> None:
        try:
            await stream_agent_reply(
                engine=engine, pool=pool, conv_id=conv_id,
                customer_text=query, tenant_id=tenant_id, sink=sink,
            )
        except Exception:
            logger.exception("stream_agent_reply failed conv=%s", conv_id)
            try:
                await sink.emit_terminal("(抱歉,本次未能生成完整回复)")
            except Exception:
                pass
        finally:
            await sink.close()
            await sse_queue.put(None)

    try:
        await get_turn_queue().submit(conv_id, _runner)
    except QueueFullError:
        return JSONResponse(status_code=429, content={"error": "queue full"})

    async def _generator():
        yield b": keepalive\n\n"
        while True:
            line = await sse_queue.get()
            if line is None:
                return
            yield line

    return StreamingResponse(
        _generator(), media_type="text/event-stream", headers=_SSE_HEADERS,
    )


async def _dispatch_json(*, engine, pool, conv_id, query, tenant_id):
    """JSON path also routes through turn_queue for per-conv FIFO."""
    from autoservice.gateway.message_router import get_turn_queue

    done = asyncio.Event()
    sink = JSONSink()
    runner_exc: list[BaseException] = []

    async def _runner() -> None:
        try:
            await stream_agent_reply(
                engine=engine, pool=pool, conv_id=conv_id,
                customer_text=query, tenant_id=tenant_id, sink=sink,
            )
        except BaseException as exc:  # noqa: BLE001
            runner_exc.append(exc)
            try:
                await sink.emit_terminal("(抱歉,本次未能生成完整回复)")
            except Exception:
                pass
        finally:
            await sink.close()
            done.set()

    try:
        await get_turn_queue().submit(conv_id, _runner)
    except QueueFullError:
        return JSONResponse(status_code=429, content={"error": "queue full"})

    await done.wait()
    if runner_exc:
        logger.exception("json runner failed", exc_info=runner_exc[0])
    return JSONResponse(content=sink.body)
```

- [ ] **Step 4: Run all general-bot tests**

Run: `pytest tests/integrations/general_bot/ -v`
Expected: all previous tests still pass + the new concurrency test passes.

- [ ] **Step 5: Commit**

```bash
git add autoservice/integrations/general_bot/routes.py tests/integrations/general_bot/test_concurrent.py
git commit -m "feat(general-bot): turn_queue serialization + 429 on queue full"
```

---

## Task 9: 120s watchdog + mid-stream error → terminal SSE

**Files:**
- Modify: `autoservice/integrations/general_bot/routes.py`
- Create: `tests/integrations/general_bot/test_error_paths.py`

- [ ] **Step 1: Write timeout + mid-stream error tests**

```python
# tests/integrations/general_bot/test_error_paths.py
"""Watchdog (120s → terminal error) + mid-stream pool failure tests. Spec §4.5/§8."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.integrations.general_bot._helpers import (
    parse_sse_events, seed_api_key,
)


@pytest.fixture
def app_factory(sandbox_dir: Path, monkeypatch):
    """Returns a factory(make_pool) → app. Pool comes from caller."""
    monkeypatch.setenv("CONV_PERSIST", "0")
    monkeypatch.setenv("DREAM_SCHEDULER_DISABLED", "1")
    monkeypatch.setenv("GENERAL_BOT_ENABLED", "1")
    monkeypatch.setenv("POOL_MODE", "1")

    from autoservice.model_router import TriageDecision

    async def fake_triage(*, engine, conv_id, customer_text, tenant_config):
        return TriageDecision(
            role="customer", intent="general_question", confidence=0.9,
            source="stub", summary=None, detected_language="en",
            previous_role=None, direct_reply=None, tier="fast",
        )
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline.triage_and_route",
        fake_triage,
    )

    async def fake_cfg(engine, conv_id):
        class _C:
            tenant_id = "tenantA"
            triage_dispatch_enabled = True
            history_reseed_token_limit = 2000
        return _C()
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline.load_tenant_config_for_conv",
        fake_cfg,
    )

    async def fake_build_prompt(*, tenant_id, customer_text, operator_suggestions):
        return customer_text
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline._build_customer_prompt",
        fake_build_prompt,
    )

    async def fake_suggestions(*a, **k):
        return ""
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline._collect_operator_suggestions",
        fake_suggestions,
    )

    def make(pool):
        async def fake_get_pool():
            return pool
        monkeypatch.setattr("autoservice.web_gateway._get_pool", fake_get_pool)
        from autoservice.web_gateway import create_app
        return create_app()

    return make


def test_mid_stream_pool_error_emits_terminal(app_factory, sandbox_dir):
    class _BoomPool:
        def session_query(self, conv_id, prompt, **kw):
            from claude_agent_sdk.types import StreamEvent
            async def _gen():
                yield StreamEvent(
                    uuid="u", session_id="s",
                    event={"type": "content_block_delta",
                           "delta": {"type": "text_delta", "text": "before-error "}},
                )
                raise RuntimeError("simulated pool failure")
            return _gen()

    app = app_factory(_BoomPool())
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"query": "hi", "inquiryID": "boom"},
            headers={
                "Authorization": f"Bearer {raw_key}",
                "Accept": "text/event-stream",
            },
        )
    assert r.status_code == 200  # SSE already opened, can't change status
    events = parse_sse_events(r.content)
    terminals = [
        e for e in events
        if isinstance(e, dict) and e["message"].get("streamType") is None
    ]
    assert len(terminals) == 1
    assert "未能" in terminals[0]["message"]["text"]


def test_watchdog_timeout_emits_terminal(app_factory, sandbox_dir, monkeypatch):
    """Override default 120s timeout to 0.1s for this test."""
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.routes.RUNNER_TIMEOUT_S", 0.1,
    )

    class _HangPool:
        def session_query(self, conv_id, prompt, **kw):
            async def _gen():
                await asyncio.sleep(10)
                if False:
                    yield None  # make this an async-generator
            return _gen()

    app = app_factory(_HangPool())
    raw_key = seed_api_key(sandbox_dir, "tenantA")
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"query": "hi", "inquiryID": "hang"},
            headers={
                "Authorization": f"Bearer {raw_key}",
                "Accept": "text/event-stream",
            },
        )
    assert r.status_code == 200
    events = parse_sse_events(r.content)
    terminals = [
        e for e in events
        if isinstance(e, dict) and e["message"].get("streamType") is None
    ]
    assert len(terminals) == 1
    assert "超时" in terminals[0]["message"]["text"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integrations/general_bot/test_error_paths.py -v`
Expected: timeout test fails (no watchdog yet); mid-stream-error test may already pass (the existing try/except catches it).

- [ ] **Step 3: Add 120s watchdog to runner**

Edit `autoservice/integrations/general_bot/routes.py`. Add a module constant near the top of the file:

```python
# After the existing imports / _SSE_HEADERS / _UNAUTHORIZED_BODY block:
RUNNER_TIMEOUT_S = 120.0  # spec §8 total response time cap
```

Replace the `_runner` definitions inside `_dispatch_streaming` and `_dispatch_json` so the call to `stream_agent_reply` is wrapped in `asyncio.wait_for`. Replace the streaming `_runner`:

```python
    async def _runner() -> None:
        try:
            await asyncio.wait_for(
                stream_agent_reply(
                    engine=engine, pool=pool, conv_id=conv_id,
                    customer_text=query, tenant_id=tenant_id, sink=sink,
                ),
                timeout=RUNNER_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning("stream_agent_reply timeout conv=%s", conv_id)
            try:
                await sink.emit_terminal("(超时未生成完整回复)")
            except Exception:
                pass
        except Exception:
            logger.exception("stream_agent_reply failed conv=%s", conv_id)
            try:
                await sink.emit_terminal("(抱歉,本次未能生成完整回复)")
            except Exception:
                pass
        finally:
            await sink.close()
            await sse_queue.put(None)
```

And replace the JSON `_runner`:

```python
    async def _runner() -> None:
        try:
            await asyncio.wait_for(
                stream_agent_reply(
                    engine=engine, pool=pool, conv_id=conv_id,
                    customer_text=query, tenant_id=tenant_id, sink=sink,
                ),
                timeout=RUNNER_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            try:
                await sink.emit_terminal("(超时未生成完整回复)")
            except Exception:
                pass
        except BaseException as exc:  # noqa: BLE001
            runner_exc.append(exc)
            try:
                await sink.emit_terminal("(抱歉,本次未能生成完整回复)")
            except Exception:
                pass
        finally:
            await sink.close()
            done.set()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integrations/general_bot/test_error_paths.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run all general-bot tests for regression**

Run: `pytest tests/integrations/general_bot/ -v`
Expected: all earlier tests still pass.

- [ ] **Step 6: Commit**

```bash
git add autoservice/integrations/general_bot/routes.py tests/integrations/general_bot/test_error_paths.py
git commit -m "feat(general-bot): 120s watchdog + mid-stream error → terminal event"
```

---

## Task 10: Passive-channel takeover guard

**Files:**
- Modify: `autoservice/conversation_engine/local_engine.py:766` (add 3-line guard)
- Create: `tests/integrations/general_bot/test_passive_channel.py`

- [ ] **Step 1: Write the guard test**

```python
# tests/integrations/general_bot/test_passive_channel.py
"""Verify _arm_takeover_timer is a no-op for passive_channel conversations."""
from __future__ import annotations

import pytest

from autoservice.conversation_engine import LocalEngine


@pytest.mark.asyncio
async def test_passive_channel_skips_takeover_arm():
    """Passive-channel conv: _arm_takeover_timer should NOT register any state."""
    engine = LocalEngine()
    conv = await engine.create_conversation(
        channel="cinnox", external_id="tA:inq1",
        metadata={"tenant_id": "tA", "passive_channel": True},
    )
    engine._arm_takeover_timer(conv.id, operator_id="op1")
    # Internal state container is _takeover_tasks (verified at line 160 / 827)
    assert conv.id not in engine._takeover_tasks


@pytest.mark.asyncio
async def test_active_channel_still_arms_takeover():
    """Regression: web/feishu conversations (no passive_channel) still arm normally."""
    engine = LocalEngine()
    conv = await engine.create_conversation(
        channel="web", external_id="cust1", metadata={},
    )
    engine._arm_takeover_timer(conv.id, operator_id="op1")
    assert conv.id in engine._takeover_tasks
    # Clean up the scheduled tasks so test teardown doesn't leak warnings
    engine._cancel_takeover_timer(conv.id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integrations/general_bot/test_passive_channel.py -v`
Expected: `test_passive_channel_skips_takeover_arm` fails because the guard is not yet in place — `_cancel_takeover_timer` returns truthy or non-bool because state was scheduled.

- [ ] **Step 3: Add the guard**

Edit `autoservice/conversation_engine/local_engine.py` at line 766 (the `_arm_takeover_timer` definition). Insert the guard at the top of the function body, before the existing `self._cancel_takeover_timer(conversation_id)` line:

```python
    def _arm_takeover_timer(self, conversation_id: str, operator_id: str) -> None:
        """Schedule warning and release tasks. Cancels any existing ones first."""
        # Passive-channel guard: HTTP/SSE inbound channels (e.g. CINNOX general-bot)
        # are one-shot request/response — operator takeover semantics don't apply.
        # Spec: docs/superpowers/specs/2026-04-27-general-bot-sse-http-api-design.md §6.2
        conv = self._conversations.get(conversation_id)
        if conv is not None and conv.metadata.get("passive_channel"):
            return
        self._cancel_takeover_timer(conversation_id)
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integrations/general_bot/test_passive_channel.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the gateway test suite for regression**

Run: `pytest tests/gateway/ -v -x`
Expected: all gateway tests still pass (no test sets `passive_channel=True`, so the guard never trips for them).

- [ ] **Step 6: Commit**

```bash
git add autoservice/conversation_engine/local_engine.py tests/integrations/general_bot/test_passive_channel.py
git commit -m "feat(general-bot): skip takeover scheduler for passive_channel convs"
```

---

## Task 11: SLA hooks + startup logging + final regression sweep

**Files:**
- Modify: `autoservice/integrations/general_bot/routes.py` (record SLA on success)
- Modify: `autoservice/web_gateway.py` (extend startup config dump)
- Create: `tests/integrations/general_bot/test_sla.py`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Write SLA recording test**

```python
# tests/integrations/general_bot/test_sla.py
"""SLA hooks parity with WS path. Spec §11."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.integrations.general_bot._helpers import seed_api_key


@pytest.mark.asyncio
async def test_first_reply_ms_recorded(sandbox_dir: Path, monkeypatch):
    monkeypatch.setenv("CONV_PERSIST", "0")
    monkeypatch.setenv("DREAM_SCHEDULER_DISABLED", "1")
    monkeypatch.setenv("GENERAL_BOT_ENABLED", "1")
    monkeypatch.setenv("POOL_MODE", "1")

    recorded: list[tuple] = []

    class _SLAStub:
        def record(self, metric, value):
            recorded.append((metric, value))

    monkeypatch.setattr(
        "autoservice.api_routes.get_sla_aggregator", lambda: _SLAStub(),
    )

    class _Pool:
        def session_query(self, conv_id, prompt, **kw):
            from claude_agent_sdk.types import StreamEvent
            async def _gen():
                yield StreamEvent(
                    uuid="u", session_id="s",
                    event={"type": "content_block_delta",
                           "delta": {"type": "text_delta", "text": "ok"}},
                )
            return _gen()
    async def fake_get_pool():
        return _Pool()
    monkeypatch.setattr("autoservice.web_gateway._get_pool", fake_get_pool)

    from autoservice.model_router import TriageDecision
    async def fake_triage(*, engine, conv_id, customer_text, tenant_config):
        return TriageDecision(
            role="customer", intent="general_question", confidence=0.9,
            source="stub", summary=None, detected_language="en",
            previous_role=None, direct_reply=None, tier="fast",
        )
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline.triage_and_route",
        fake_triage,
    )
    async def fake_cfg(engine, conv_id):
        class _C:
            tenant_id = "tenantA"; triage_dispatch_enabled = True
            history_reseed_token_limit = 2000
        return _C()
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline.load_tenant_config_for_conv",
        fake_cfg,
    )
    async def fake_build_prompt(*, tenant_id, customer_text, operator_suggestions):
        return customer_text
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline._build_customer_prompt",
        fake_build_prompt,
    )
    async def fake_suggestions(*a, **k):
        return ""
    monkeypatch.setattr(
        "autoservice.integrations.general_bot.reply_pipeline._collect_operator_suggestions",
        fake_suggestions,
    )

    raw_key = seed_api_key(sandbox_dir, "tenantA")
    from autoservice.web_gateway import create_app
    app = create_app()
    with TestClient(app) as client:
        r = client.post(
            "/chat/tenantA",
            json={"query": "hi", "inquiryID": "sla-1"},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert r.status_code == 200
    metric_names = [m.name if hasattr(m, "name") else str(m) for m, _ in recorded]
    assert any("FIRST_REPLY_MS" in n for n in metric_names)
    assert any("TTFB_MS" in n for n in metric_names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integrations/general_bot/test_sla.py -v`
Expected: FAIL — no SLA hooks wired yet, `recorded` stays empty.

- [ ] **Step 3: Add SLA recording to the runner success path**

Edit `autoservice/integrations/general_bot/routes.py`. Add a module-level dict at the top alongside the other constants:

```python
import time as _time

# Track conv creation timestamps for SLA first_reply_ms (mirrors message_router)
_conv_created_at: dict[str, float] = {}
_conv_first_reply_sent: set[str] = set()
```

In `_persist_customer_message`, after `conv = await engine.create_conversation(...)`, record the timestamp on first creation. Replace:

```python
    conv = await engine.create_conversation(
        channel=channel, external_id=external_id, metadata=metadata,
    )
    conv_id = conv.id
```

with:

```python
    conv = await engine.create_conversation(
        channel=channel, external_id=external_id, metadata=metadata,
    )
    conv_id = conv.id
    if conv_id not in _conv_created_at:
        _conv_created_at[conv_id] = _time.time()
```

Add a helper `_record_first_reply_sla` near the bottom of `routes.py`:

```python
def _record_first_reply_sla(conv_id: str) -> None:
    """Record SLA first_reply_ms / TTFB_MS once per conv (mirrors WS path)."""
    if conv_id in _conv_first_reply_sent:
        return
    started = _conv_created_at.get(conv_id)
    if started is None:
        return
    _conv_first_reply_sent.add(conv_id)
    latency_ms = (_time.time() - started) * 1000.0
    try:
        from autoservice.api_routes import get_sla_aggregator
        from autoservice.sla_aggregator import MetricType
        sla = get_sla_aggregator()
        sla.record(MetricType.FIRST_REPLY_MS, latency_ms)
        sla.record(MetricType.TTFB_MS, latency_ms)
    except Exception:
        logger.warning("SLA record failed conv=%s", conv_id, exc_info=True)
```

In both `_dispatch_streaming` and `_dispatch_json` runners, call `_record_first_reply_sla(conv_id)` AFTER `stream_agent_reply` returns successfully (i.e. inside the `try:` block, immediately after the `await asyncio.wait_for(...)` line, before any `except`):

For `_dispatch_streaming`:

```python
    async def _runner() -> None:
        try:
            await asyncio.wait_for(
                stream_agent_reply(
                    engine=engine, pool=pool, conv_id=conv_id,
                    customer_text=query, tenant_id=tenant_id, sink=sink,
                ),
                timeout=RUNNER_TIMEOUT_S,
            )
            _record_first_reply_sla(conv_id)
        except asyncio.TimeoutError:
            ...
```

For `_dispatch_json`:

```python
    async def _runner() -> None:
        try:
            await asyncio.wait_for(
                stream_agent_reply(
                    engine=engine, pool=pool, conv_id=conv_id,
                    customer_text=query, tenant_id=tenant_id, sink=sink,
                ),
                timeout=RUNNER_TIMEOUT_S,
            )
            _record_first_reply_sla(conv_id)
        except asyncio.TimeoutError:
            ...
```

- [ ] **Step 4: Run SLA test to verify it passes**

Run: `pytest tests/integrations/general_bot/test_sla.py -v`
Expected: 1 passed.

- [ ] **Step 5: Add `GENERAL_BOT_ENABLED` to the startup config dump**

Edit `autoservice/web_gateway.py`. Find the `flags = [...]` block inside `_dump_runtime_config` (around line 482–495). Add one line in the list:

```python
        flags = [
            ("INSTANT_ACK_ENABLED",        _e("INSTANT_ACK_ENABLED", "1")),
            ("MULTI_BUBBLE_ENABLED",       _e("MULTI_BUBBLE_ENABLED", "1")),
            ("QUEUE_ENABLED",              _e("QUEUE_ENABLED", "1")),
            ("GENERAL_BOT_ENABLED",        _e("GENERAL_BOT_ENABLED", "1")),
            ("PLACEHOLDER_ENABLED",        _e("PLACEHOLDER_ENABLED", "(deprecated alias)")),
            ("SOOTHE_PLACEHOLDER_ENABLED", _e("SOOTHE_PLACEHOLDER_ENABLED", "(deprecated, ignored)")),
            ("TRIAGE_AGENT_ENABLED",       _e("TRIAGE_AGENT_ENABLED", "0")),
            ("TRIAGE_AGENT_TIMEOUT_S",     _e("TRIAGE_AGENT_TIMEOUT_S", "15.0")),
            ("AUTH_DEV_MODE",              _e("AUTH_DEV_MODE", "(disabled)")),
            ("DREAM_DEV_STUB",             _e("DREAM_DEV_STUB", "(disabled)")),
            ("DREAM_SCHEDULER_DISABLED",   _e("DREAM_SCHEDULER_DISABLED", "(enabled)")),
            ("POOL_MODE",                  _e("POOL_MODE", "1")),
        ]
```

- [ ] **Step 6: Run the full general-bot test directory**

Run: `pytest tests/integrations/general_bot/ -v`
Expected: all green.

- [ ] **Step 7: Run the broader test suites that exercise touched code**

Run: `pytest tests/gateway/ tests/conversation_engine/ -v -x`
Expected: green (no regression).

- [ ] **Step 8: Manual smoke test (optional, requires running server)**

```bash
# Terminal 1: run the gateway
make run-gateway

# Terminal 2: mint a key + curl the endpoint
python scripts/issue_general_bot_key.py _master --label smoke
# Copy the printed raw key into KEY env var
curl -N -X POST http://localhost:8000/chat/_master \
  -H "Authorization: Bearer $KEY" \
  -H "Accept: text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"query":"hello","inquiryID":"smoke-1"}'
```

Expected: progressive `data: ...streamType:"delta"` events followed by one terminal `data: {"message":...}` without `streamType`.

- [ ] **Step 9: Update CLAUDE.md to document the new env flag**

Edit `CLAUDE.md`. Find the section listing kill-switches (after "Instant Ack / Multi-Bubble / Queue Kill-Switches"). Add a new section:

```markdown
## General Bot Inbound API

`GENERAL_BOT_ENABLED` (default **on**) gates `POST /chat/{tenant_id}` —
the inbound HTTP/SSE endpoint for third-party IM platforms (CINNOX-
compatible, see [docs/General-Bot-Streaming-Message(SSE)-API_20260427.md](docs/General-Bot-Streaming-Message(SSE)-API_20260427.md)).
When `0`, the route returns 503. Auth uses per-tenant Bearer keys stored
hashed at `.autoservice/sandbox/<tid>/api_keys.json`; mint a key with
`python scripts/issue_general_bot_key.py <tid> [--label NAME]`.

Spec: `docs/superpowers/specs/2026-04-27-general-bot-sse-http-api-design.md`.
```

- [ ] **Step 10: Commit**

```bash
git add autoservice/integrations/general_bot/routes.py autoservice/web_gateway.py CLAUDE.md tests/integrations/general_bot/test_sla.py
git commit -m "feat(general-bot): SLA hooks + GENERAL_BOT_ENABLED dump + CLAUDE.md"
```

---

## Self-review checklist (run after all tasks)

- [ ] All spec sections covered:
  - §3 module layout — Tasks 1–6, 8, 11
  - §4 endpoint contract — Tasks 6 (happy), 7 (errors), 9 (timeout), 8 (429)
  - §5 auth + key file — Task 3
  - §6 data flow + reused components — Tasks 4, 5, 6
  - §6.2 takeover guard + mount line — Tasks 6, 10
  - §7 sink contract — Task 2
  - §8 concurrency model — Tasks 8, 9
  - §9 edge cases — Tasks 6 (inquiry_id namespace), 9 (mid-stream), 10 (passive)
  - §10 testing strategy — every test file matches a spec entry
  - §11 operational notes — Task 11 (startup dump, CLAUDE.md)
- [ ] No placeholders: every step has explicit code or commands.
- [ ] Type consistency: `ReplySink` used everywhere; `SSEStream` and `JSONSink` both implement `emit_delta`/`emit_terminal`/`close`; `stream_agent_reply` signature matches across Tasks 5–9.

## Risk notes

- The mid-stream error test in Task 9 relies on `parse_sse_events` parsing the response body in one shot; in the rare case a CI machine takes >5s to read the test stream, raise the test timeout. Not affecting the production 120s cap.
- The concurrency test in Task 8 uses threads + `TestClient`; the assertion `results.count(429) >= 1` is robust against a 3-of-4 vs 4-of-4 race because `max_depth=2` + 1 in-flight gives 3 successful slots regardless.
- `stream_agent_reply` deliberately re-imports `triage_and_route` etc. at module top so monkeypatching in tests works. Do not move them inside the function unless you also update the patch paths in tests.
