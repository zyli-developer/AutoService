# Voice Native Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task.

**Goal:** Migrate the E2E-adapter voice gateway from `cc-openclaw/voice_gateway/` into AutoService as `channels/web/voice/`, so customer-chat talks to AutoService's own backend for voice (no separate cc-openclaw process, no separate port, no `VITE_VOICE_GATEWAY_URL`).

**Architecture:** Copy framework-agnostic Doubao clients verbatim from cc-openclaw `feat/voice-doubao @ 8632aa3`. Rewrite the two aiohttp WebSocket routes (`asr_route.py`, `tts_route.py`) as FastAPI WebSocket endpoints mounted on the existing `autoservice.web_gateway.create_app()`. Frontend unchanged except for a vite dev-server proxy rule.

**Tech Stack:** Python 3.14 · FastAPI · `websockets>=12` (upstream Doubao WS client) · pytest + fastapi.testclient · Node 20 · Vite · TypeScript.

**Reference implementation:** `D:\workspace\zhidaoyuan\cc-openclaw\voice_gateway\` at commit `8632aa3` (E2E-adapter mode — `feat/voice-doubao` branch). All Doubao code stays verbatim; only route handlers are rewritten for FastAPI.

**Design doc:** `docs/plans/2026-04-24-voice-native-integrated-design.md`

---

## Task 1: Scaffold `channels/web/voice/` package with framework-agnostic modules

Copy the five framework-agnostic files from cc-openclaw, fix imports to use package-relative form.

**Files:**
- Create: `channels/web/voice/__init__.py`
- Create: `channels/web/voice/protocol.py` (copy verbatim, no import changes — pure stdlib)
- Create: `channels/web/voice/config.py` (strip cc-openclaw-only symbols, keep Doubao only)
- Create: `channels/web/voice/doubao_client.py` (change absolute → relative imports)
- Create: `channels/web/voice/asr_client.py` (change absolute → relative imports)
- Create: `channels/web/voice/tts_client.py` (change absolute → relative imports)

**Step 1: Create the package marker**

```bash
mkdir -p channels/web/voice
```

`channels/web/voice/__init__.py`:
```python
"""Voice gateway — E2E-adapter ASR + TTS via Doubao realtime dialogue API.

Migrated from cc-openclaw/voice_gateway/ at commit 8632aa3 (feat/voice-doubao).
Kept the E2E-adapter pattern: each /asr or /tts WebSocket opens its own Doubao
realtime-dialogue connection and ignores unused event types. Creds come from
DOUBAO_APP_ID + DOUBAO_ACCESS_TOKEN env vars.
"""
```

**Step 2: Copy `protocol.py` verbatim**

Source: `D:\workspace\zhidaoyuan\cc-openclaw\voice_gateway\protocol.py`
Dest: `channels/web/voice/protocol.py`

This file has zero project-internal imports (only `gzip` and `json` from stdlib), so copy byte-for-byte. Do NOT modify.

**Step 3: Copy `config.py`, strip cc-openclaw-only symbols**

Source: `D:\workspace\zhidaoyuan\cc-openclaw\voice_gateway\config.py`
Dest: `channels/web/voice/config.py`

Keep these symbols:
- `DOUBAO_WS_URL`
- `get_ws_headers()`
- `START_SESSION_CONFIG`
- `GREETING_TEXT`, `COMFORT_TEXT`

Delete these (not needed in AutoService — they served cc-openclaw's own demo/legacy flow):
- `REALTIME_ASR_URL`, `REALTIME_TTS_URL`, `REALTIME_TTS_VOICE`, `REALTIME_TTS_SAMPLE_RATE`, `get_realtime_headers()`
- `CHANNEL_SERVER_WS_URL`, `VOICE_INSTANCE_PREFIX`
- `ALLOWED_ORIGINS` (AutoService's gateway handles CORS centrally; same-origin after migration makes this moot)

Final file:
```python
"""Voice gateway configuration. Loads Doubao credentials from environment."""
import os
import uuid

DOUBAO_WS_URL = "wss://openspeech.bytedance.com/api/v3/realtime/dialogue"


def get_ws_headers() -> dict:
    return {
        "X-Api-App-ID": os.environ.get("DOUBAO_APP_ID", ""),
        "X-Api-Access-Key": os.environ.get("DOUBAO_ACCESS_TOKEN", ""),
        "X-Api-Resource-Id": "volc.speech.dialog",
        "X-Api-App-Key": "PlgvMymc7f3tQnJ6",
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }


START_SESSION_CONFIG = {
    "tts": {
        "audio_config": {
            "format": "pcm_s16le",
            "sample_rate": 24000,
            "channel": 1,
        },
        "speaker": "zh_female_vv_jupiter_bigtts",
    },
    "asr": {
        "audio_info": {
            "format": "pcm",
            "sample_rate": 16000,
            "channel": 1,
        },
        "extra": {
            "end_smooth_window_ms": 1500,
        },
    },
    "dialog": {
        "bot_name": "OpenClaw助手",
        "system_role": "你是OpenClaw智能助手。当用户询问商品信息时，请基于提供的知识回答。如果没有相关知识，请如实告知。保持简洁友好。",
        "speaking_style": "语速适中，语调自然，简洁明了。",
        "extra": {
            "input_mod": "keep_alive",
            "recv_timeout": 60,
        },
    },
    "extra": {
        "model": "1.2.1.1",
    },
}

GREETING_TEXT = "你好，请问有什么可以帮你？"
COMFORT_TEXT = "稍等，我帮你查一下。"
```

**Step 4: Copy `doubao_client.py`, change imports to relative**

Source: `D:\workspace\zhidaoyuan\cc-openclaw\voice_gateway\doubao_client.py`
Dest: `channels/web/voice/doubao_client.py`

Only two lines change — the top-level imports:

```python
# Before (cc-openclaw absolute imports):
from config import DOUBAO_WS_URL, get_ws_headers
from protocol import (
    build_client_frame, parse_server_frame,
    ...
)

# After (AutoService relative imports):
from .config import DOUBAO_WS_URL, get_ws_headers
from .protocol import (
    build_client_frame, parse_server_frame,
    ...
)
```

Everything else — the `DoubaoClient` class, all its methods — stays byte-for-byte.

**Step 5: Copy `asr_client.py`, change imports to relative**

Source: `D:\workspace\zhidaoyuan\cc-openclaw\voice_gateway\asr_client.py`
Dest: `channels/web/voice/asr_client.py`

```python
# Before:
from config import START_SESSION_CONFIG
from doubao_client import DoubaoClient
from protocol import (...)

# After:
from .config import START_SESSION_CONFIG
from .doubao_client import DoubaoClient
from .protocol import (...)
```

`ASRClient` class unchanged.

**Step 6: Copy `tts_client.py`, change imports to relative**

Source: `D:\workspace\zhidaoyuan\cc-openclaw\voice_gateway\tts_client.py`
Dest: `channels/web/voice/tts_client.py`

Same pattern — change `from config` → `from .config`, `from doubao_client` → `from .doubao_client`, `from protocol` → `from .protocol`. `TTSClient` class (including `_reopen`, `synthesize`, the `say_hello` workaround) unchanged.

**Step 7: Verify the package imports without errors**

Run:
```bash
uv run python -c "from channels.web.voice import asr_client, tts_client, doubao_client, protocol, config; print('ok')"
```

Expected output: `ok`

Troubleshooting: If you see `ModuleNotFoundError: No module named 'websockets'`, that's expected — Task 6 adds it. For now, skip this verification and rely on Task 2 (protocol test) which has no external deps.

**Step 8: Commit**

```bash
git add channels/web/voice/
git commit -m "feat(voice): scaffold channels/web/voice/ package from cc-openclaw"
```

---

## Task 2: Port `test_protocol.py` (pure-Python, zero-framework test)

Port the protocol binary-frame tests to prove the copied `protocol.py` works in its new home.

**Files:**
- Create: `tests/voice/__init__.py` (empty)
- Create: `tests/voice/test_protocol.py`

**Step 1: Create the tests-voice package marker**

```bash
mkdir -p tests/voice
```

`tests/voice/__init__.py`: empty file.

**Step 2: Copy the protocol test with adjusted import**

Source: `D:\workspace\zhidaoyuan\cc-openclaw\voice_gateway\tests\test_protocol.py`
Dest: `tests/voice/test_protocol.py`

Change the single import line from:
```python
from protocol import (...)  # cc-openclaw with sys.path hack
```
to:
```python
from channels.web.voice.protocol import (...)
```

Delete the `sys.path.insert(...)` at the top of the file (not needed — we're using the proper package path).

**Step 3: Run the test**

```bash
uv run pytest tests/voice/test_protocol.py -v
```

Expected: all tests pass (these tests assert `build_client_frame` round-trips through `parse_server_frame` correctly; no external deps).

**Step 4: Commit**

```bash
git add tests/voice/__init__.py tests/voice/test_protocol.py
git commit -m "test(voice): port protocol binary-frame tests"
```

---

## Task 3: Port `asr_route` to FastAPI with TDD

Write FastAPI test first using `TestClient.websocket_connect`, then implement the route.

**Files:**
- Create: `tests/voice/test_asr_route.py`
- Create: `channels/web/voice/asr_route.py`

**Step 1: Write the failing test**

`tests/voice/test_asr_route.py`:

```python
"""FastAPI WebSocket test for /asr route.

Ported from cc-openclaw/voice_gateway/tests/test_asr_route.py — aiohttp
TestClient replaced with fastapi.testclient.TestClient.websocket_connect.
Uses a FakeASRClient to avoid hitting the real Doubao service.
"""
import json
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from channels.web.voice.asr_route import asr_endpoint


class FakeASRClient:
    def __init__(self):
        self.connected = False
        self.audio_chunks = []
        self._events = []

    async def connect(self):
        self.connected = True

    async def send_audio(self, data: bytes):
        self.audio_chunks.append(data)

    async def receive(self):
        for ev in self._events:
            yield ev

    async def close(self):
        self.connected = False

    def enqueue(self, event: dict):
        self._events.append(event)


def _build_app(fake_cls):
    app = FastAPI()
    # asr_endpoint uses channels.web.voice.asr_route.ASRClient symbol,
    # which we patch to the fake class.
    app.add_api_websocket_route("/asr", asr_endpoint)
    return app


def test_asr_route_forwards_final_event_as_simple_frame():
    fake = FakeASRClient()
    fake.enqueue({
        "type": "conversation.item.input_audio_transcription.completed",
        "transcript": "hello world",
    })

    with patch("channels.web.voice.asr_route.ASRClient", return_value=fake):
        app = _build_app(FakeASRClient)
        with TestClient(app) as client:
            with client.websocket_connect("/asr") as ws:
                ws.send_json({"type": "start"})
                raw = ws.receive_text()
                data = json.loads(raw)
                assert data == {"type": "final", "text": "hello world"}


def test_asr_route_forwards_partial_and_speech_started():
    fake = FakeASRClient()
    fake.enqueue({"type": "input_audio_buffer.speech_started"})
    fake.enqueue({
        "type": "conversation.item.input_audio_transcription.result",
        "transcript": "hel",
    })

    with patch("channels.web.voice.asr_route.ASRClient", return_value=fake):
        app = _build_app(FakeASRClient)
        with TestClient(app) as client:
            with client.websocket_connect("/asr") as ws:
                ws.send_json({"type": "start"})
                got = [json.loads(ws.receive_text()) for _ in range(2)]
                assert {"type": "speech_started"} in got
                assert {"type": "partial", "text": "hel"} in got
```

**Step 2: Run the test — should fail with ImportError**

```bash
uv run pytest tests/voice/test_asr_route.py -v
```

Expected: `ModuleNotFoundError: No module named 'channels.web.voice.asr_route'` (route not created yet).

**Step 3: Implement the FastAPI route**

`channels/web/voice/asr_route.py`:

```python
"""Stateless ASR WebSocket endpoint — proxies browser PCM → Doubao ASR → text frames.

Ported from cc-openclaw/voice_gateway/asr_route.py (aiohttp) to FastAPI.
Logical flow unchanged:
  1. Accept WebSocket.
  2. Wait for {"type": "start"} text frame.
  3. Connect ASRClient to Doubao.
  4. Concurrently:
     - Forward binary PCM frames from browser → Doubao.
     - Forward normalized ASR events from Doubao → browser as
       {"type": "speech_started"|"partial"|"final", ...}.
  5. Stop on {"type": "stop"} text frame, WS close, or ASR error.
"""
import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .asr_client import ASRClient

log = logging.getLogger(__name__)


# Volcengine/Doubao event types emitted by ASRClient.receive()
_EV_PARTIAL = "conversation.item.input_audio_transcription.result"
_EV_FINAL = "conversation.item.input_audio_transcription.completed"
_EV_SPEECH_STARTED = "input_audio_buffer.speech_started"


async def asr_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    log.info("[/asr] browser connected")

    asr = ASRClient()
    try:
        first = await ws.receive_text()
        try:
            data = json.loads(first)
        except json.JSONDecodeError:
            await ws.send_json({"type": "error", "message": "invalid start frame"})
            return
        if data.get("type") != "start":
            await ws.send_json({"type": "error", "message": "first frame must be type=start"})
            return

        await asr.connect()

        reader_task = asyncio.create_task(_forward_asr_events(asr, ws))
        browser_task = asyncio.create_task(_forward_browser_audio(ws, asr))

        done, pending = await asyncio.wait(
            {reader_task, browser_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("[/asr] error")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await asr.close()
        except Exception:
            pass
        if ws.client_state != WebSocketState.DISCONNECTED:
            try:
                await ws.close()
            except Exception:
                pass
        log.info("[/asr] browser disconnected")


async def _forward_asr_events(asr: ASRClient, ws: WebSocket) -> None:
    async for event in asr.receive():
        evt_type = event.get("type", "")
        text = event.get("transcript", "")

        if evt_type == _EV_PARTIAL and text:
            await ws.send_json({"type": "partial", "text": text})
        elif evt_type == _EV_FINAL and text:
            await ws.send_json({"type": "final", "text": text})
        elif evt_type == _EV_SPEECH_STARTED:
            await ws.send_json({"type": "speech_started"})
        elif evt_type.startswith("error") or "error" in event:
            await ws.send_json({
                "type": "error",
                "message": event.get("error", {}).get("message", "ASR error"),
            })


async def _forward_browser_audio(ws: WebSocket, asr: ASRClient) -> None:
    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                return
            if "bytes" in message and message["bytes"] is not None:
                await asr.send_audio(message["bytes"])
            elif "text" in message and message["text"] is not None:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "stop":
                    return
    except WebSocketDisconnect:
        return
```

**Step 4: Run the test — should pass**

```bash
uv run pytest tests/voice/test_asr_route.py -v
```

Expected: both tests pass.

**Step 5: Commit**

```bash
git add channels/web/voice/asr_route.py tests/voice/test_asr_route.py
git commit -m "feat(voice): port /asr route to FastAPI WebSocket endpoint"
```

---

## Task 4: Port `tts_route` to FastAPI with TDD

Same pattern as Task 3. Port both the happy-path test and the abort-then-speak test.

**Files:**
- Create: `tests/voice/test_tts_route.py`
- Create: `channels/web/voice/tts_route.py`

**Step 1: Write the failing tests**

`tests/voice/test_tts_route.py`:

```python
"""FastAPI WebSocket test for /tts route.

Ported from cc-openclaw/voice_gateway/tests/test_tts_route.py — aiohttp
TestClient replaced with fastapi.testclient.TestClient.websocket_connect.
Uses FakeTTSClient / SlowTTS doubles to avoid hitting real Doubao.
"""
import asyncio
import json
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from channels.web.voice.tts_route import tts_endpoint


class FakeTTSClient:
    def __init__(self):
        self.connected = False

    async def connect(self):
        self.connected = True

    async def synthesize(self, text: str):
        yield b"\x00\x01" * 100
        yield b"\x02\x03" * 100

    async def close(self):
        self.connected = False


def _build_app():
    app = FastAPI()
    app.add_api_websocket_route("/tts", tts_endpoint)
    return app


def test_tts_route_streams_audio_then_done():
    with patch("channels.web.voice.tts_route.TTSClient", return_value=FakeTTSClient()):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/tts") as ws:
                ws.send_json({"type": "speak", "text": "hi"})

                binary_chunks = 0
                got_done = False
                for _ in range(10):
                    msg = ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if "bytes" in msg and msg["bytes"] is not None:
                        binary_chunks += 1
                    elif "text" in msg and msg["text"] is not None:
                        data = json.loads(msg["text"])
                        if data.get("type") == "done":
                            got_done = True
                            break

                assert binary_chunks == 2
                assert got_done


def test_tts_route_abort_then_speak_no_interleaved_audio():
    class SlowTTS:
        async def connect(self):
            pass

        async def synthesize(self, text: str):
            if text == "first":
                yield b"A" * 100
                await asyncio.sleep(0.2)
                yield b"A" * 100  # should never reach the browser
            else:
                yield b"B" * 100

        async def close(self):
            pass

    with patch("channels.web.voice.tts_route.TTSClient", return_value=SlowTTS()):
        app = _build_app()
        with TestClient(app) as client:
            with client.websocket_connect("/tts") as ws:
                ws.send_json({"type": "speak", "text": "first"})

                msg = ws.receive()
                assert "bytes" in msg and msg["bytes"] == b"A" * 100

                ws.send_json({"type": "abort"})
                ws.send_json({"type": "speak", "text": "second"})

                stray_A = 0
                got_done = False
                for _ in range(10):
                    msg = ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if "bytes" in msg and msg["bytes"] is not None:
                        if b"A" in msg["bytes"]:
                            stray_A += 1
                        else:
                            assert msg["bytes"] == b"B" * 100
                    elif "text" in msg and msg["text"] is not None:
                        data = json.loads(msg["text"])
                        if data.get("type") == "done":
                            got_done = True
                            break

                assert stray_A == 0, "post-abort PCM from cancelled task leaked"
                assert got_done
```

**Step 2: Run — expect ImportError**

```bash
uv run pytest tests/voice/test_tts_route.py -v
```

Expected: `ModuleNotFoundError: No module named 'channels.web.voice.tts_route'`.

**Step 3: Implement the FastAPI route**

`channels/web/voice/tts_route.py`:

```python
"""Stateless TTS WebSocket endpoint — accepts speak/abort, streams PCM back.

Ported from cc-openclaw/voice_gateway/tts_route.py (aiohttp) to FastAPI.
Cancels in-flight synthesize on abort or on new speak, waits for the
cancelled task to finish before starting the next one to prevent PCM
interleave on the wire.
"""
import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .tts_client import TTSClient

log = logging.getLogger(__name__)


async def _cancel_and_wait(task: asyncio.Task | None) -> None:
    if task and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def tts_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    log.info("[/tts] browser connected")

    tts = TTSClient()
    current_task: asyncio.Task | None = None

    try:
        await tts.connect()

        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
            text = message.get("text")
            if text is None:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue

            action = data.get("type")
            if action == "speak":
                utterance = data.get("text", "")
                await _cancel_and_wait(current_task)
                current_task = asyncio.create_task(_do_speak(tts, ws, utterance))
            elif action == "abort":
                await _cancel_and_wait(current_task)
                current_task = None
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("[/tts] error")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        await _cancel_and_wait(current_task)
        try:
            await tts.close()
        except Exception:
            pass
        if ws.client_state != WebSocketState.DISCONNECTED:
            try:
                await ws.close()
            except Exception:
                pass
        log.info("[/tts] browser disconnected")


async def _do_speak(tts: TTSClient, ws: WebSocket, text: str) -> None:
    try:
        async for chunk in tts.synthesize(text):
            await ws.send_bytes(chunk)
        await ws.send_json({"type": "done"})
    except asyncio.CancelledError:
        log.info("[/tts] speak cancelled")
        raise
    except Exception as e:
        log.error("[/tts] speak error: %s", e)
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
```

**Step 4: Run — should pass**

```bash
uv run pytest tests/voice/test_tts_route.py -v
```

Expected: both tests pass.

**Step 5: Commit**

```bash
git add channels/web/voice/tts_route.py tests/voice/test_tts_route.py
git commit -m "feat(voice): port /tts route to FastAPI WebSocket endpoint"
```

---

## Task 5: Mount `/asr` and `/tts` in `autoservice.web_gateway.create_app`

Register the two new WebSocket endpoints on the same FastAPI app that already serves `/ws/customer`, `/ws/operator`, `/ws/admin`.

**Files:**
- Modify: `autoservice/web_gateway.py:403-408` (the existing loop that registers `/ws/{role}`)

**Step 1: Read the surrounding context**

Look at `autoservice/web_gateway.py` around line 400-410 — that's where `/ws/customer`/`/ws/operator`/`/ws/admin` get registered via `app.add_api_websocket_route`. We add two more registrations right after that loop.

**Step 2: Add the voice route registration**

After the existing loop:
```python
    for role in ("customer", "operator", "admin"):
        app.add_api_websocket_route(
            f"/ws/{role}",
            _make_endpoint(role),
            name=f"ws_{role}",
        )
```

Add:
```python
    # Voice routes — E2E-adapter ASR + TTS, see channels/web/voice/.
    # Migrated from cc-openclaw/voice_gateway/ on 2026-04-24.
    from channels.web.voice.asr_route import asr_endpoint as _asr_endpoint
    from channels.web.voice.tts_route import tts_endpoint as _tts_endpoint
    app.add_api_websocket_route("/asr", _asr_endpoint, name="ws_asr")
    app.add_api_websocket_route("/tts", _tts_endpoint, name="ws_tts")
```

(Late import inside `create_app()` matches the existing pattern — see how `autoservice.onboarding` and `autoservice.api_routes` are imported late in the same function. This avoids importing `websockets` at module load time, which matters for tooling that inspects `autoservice.web_gateway` without the Doubao dependency installed.)

**Step 3: Verify the app still boots**

```bash
uv run python -c "from autoservice.web_gateway import create_app; app = create_app(); print([r.path for r in app.routes if 'asr' in str(r.path) or 'tts' in str(r.path)])"
```

Expected output: `['/asr', '/tts']`

**Step 4: Commit**

```bash
git add autoservice/web_gateway.py
git commit -m "feat(voice): mount /asr and /tts on autoservice.web_gateway"
```

---

## Task 6: Add `websockets` dependency

The Doubao `doubao_client.py` imports `websockets` for the upstream connection to Volcengine. AutoService doesn't already depend on it.

**Files:**
- Modify: `pyproject.toml`

**Step 1: Check current deps**

```bash
grep -A 20 "^dependencies =" pyproject.toml
```

Find the `dependencies = [...]` list.

**Step 2: Add the dependency**

Add this line (alphabetically sorted, follow existing convention):
```toml
    "websockets>=12",
```

**Step 3: Sync the lockfile**

```bash
uv sync
```

Expected: installs `websockets` with no errors.

**Step 4: Verify imports now work end-to-end**

```bash
uv run python -c "from channels.web.voice import asr_client, tts_client, doubao_client; print('ok')"
```

Expected: `ok`.

**Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(voice): add websockets dependency for Doubao upstream"
```

---

## Task 7: Frontend — add vite proxies for `/asr` and `/tts`

`resolveVoiceWsUrl` in `App.tsx` already has a same-origin fallback when `VITE_VOICE_GATEWAY_URL` is unset. The remaining piece is the vite dev server proxy so same-origin WS requests from port 5173 reach the FastAPI backend on port 8000. (`/ws` is already proxied; we add `/asr` and `/tts`.)

**Files:**
- Modify: `frontend/apps/customer-chat/vite.config.ts`

**Step 1: Read the current config**

`frontend/apps/customer-chat/vite.config.ts`:
```ts
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true, changeOrigin: true },
    },
```

**Step 2: Add `/asr` and `/tts` proxies**

Replace the `proxy` block with:
```ts
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true, changeOrigin: true },
      '/asr': { target: 'ws://localhost:8000', ws: true, changeOrigin: true },
      '/tts': { target: 'ws://localhost:8000', ws: true, changeOrigin: true },
    },
```

**Step 3: Verify the dev server routes correctly**

```bash
cd frontend
pnpm --filter customer-chat dev
```

In a second terminal:
```bash
# AutoService gateway running on 8000
curl -I http://localhost:5173/asr -H "Connection: Upgrade" -H "Upgrade: websocket"
```

Expected: handshake should route through to 8000's `/asr` endpoint (you'll see the missing-start-frame error path, which is fine — it proves the proxy works).

**Step 4: Commit**

```bash
git add frontend/apps/customer-chat/vite.config.ts
git commit -m "feat(voice): vite-proxy /asr and /tts to same-origin backend"
```

---

## Task 8: Update manual test plan to reflect single-service startup

Update the existing manual test plan so ops/dev know that voice no longer needs cc-openclaw.

**Files:**
- Modify: `docs/plans/2026-04-23-customer-chat-native-voice-manual-test.md`

**Step 1: Read the existing plan**

Look for any mention of `cc-openclaw`, `voice_gateway/server.py`, or port `8089`.

**Step 2: Replace the "start voice gateway" section**

Before (approx):
```markdown
## Prerequisites
1. Start cc-openclaw voice_gateway on 8089:
   `cd cc-openclaw && .venv/Scripts/python.exe voice_gateway/server.py`
2. Start AutoService gateway on 8000: `make run-gateway`
3. Start customer-chat frontend: `pnpm --filter customer-chat dev`
4. Set `VITE_VOICE_GATEWAY_URL=http://localhost:8089` in `.env.local`.
```

After:
```markdown
## Prerequisites
1. Ensure `DOUBAO_APP_ID` and `DOUBAO_ACCESS_TOKEN` are in env (e.g. `.autoservice/config.local.yaml` or shell export).
2. Start AutoService gateway (serves /ws/customer + /asr + /tts on the same port):
   `make run-gateway`
3. Start customer-chat frontend: `pnpm --filter customer-chat dev`
4. `VITE_VOICE_GATEWAY_URL` is **no longer needed** — remove it from `.env.local` unless you deliberately point voice at a different host.
```

Add a note near the top:
```markdown
**Architecture note (2026-04-24):** Voice ASR+TTS used to run in a separate
cc-openclaw `voice_gateway` process on port 8089. As of this integration PR,
they run in-process on AutoService's FastAPI app (same port as chat). The
cc-openclaw gateway is no longer required for local dev or prod.
```

**Step 3: Commit**

```bash
git add docs/plans/2026-04-23-customer-chat-native-voice-manual-test.md
git commit -m "docs(voice): manual test plan reflects single-service startup"
```

---

## Task 9: End-to-end smoke (manual verification, no commit)

Run the full stack locally and confirm a Chinese voice utterance produces a CC reply.

**Step 1: Kill any old services**

Stop the cc-openclaw `voice_gateway/server.py` if it's still running from the previous setup — the test must prove AutoService serves voice on port 8000.

**Step 2: Start AutoService**

```bash
make run-gateway
```

Wait for `Uvicorn running on http://0.0.0.0:8000`.

**Step 3: Start customer-chat**

```bash
cd frontend && pnpm --filter customer-chat dev
```

**Step 4: Smoke check**

- Open http://localhost:5173/tenant/<your-tenant>/chat
- Click the mic button in the composer.
- Speak one Chinese sentence (~3s).
- Expect: comfort phrase plays → CC reply plays → mic stays available.
- Speak while the CC reply is playing — barge-in should stop TTS and return to listening.

**Step 5: Collect success criteria**

Record in the PR:
- `pytest tests/voice/` green count
- Confirmation that `VITE_VOICE_GATEWAY_URL` is unset (or commented out) in `.env.local` during the test.
- Screenshot/log excerpt from AutoService gateway showing `[/asr] browser connected` and `[/tts] browser connected`.

No commit for this task — mark the PR ready-for-review on success.

---

## Task 10: Mark PR ready for review

**Step 1: Update PR description**

Add the test-plan checkbox results and this line near the top:

> **Status (2026-04-24):** All 10 tasks green. E2E smoke verified — one `make run-gateway` + `pnpm dev` serves chat + voice on port 8000.

**Step 2: Flip from Draft to Ready**

```bash
gh pr ready https://github.com/zyli-developer/AutoService/pull/1
```

---

## Rollback

If any task surfaces a blocker:

1. Keep the commits on `feat/voice-native-integrated` — they're incremental and reversible.
2. Revert the branch pointer: `git reset --hard <last-good-sha>` before the broken task's commit.
3. PR #81 is unaffected — it still works against cc-openclaw's 8089 backend unchanged.

## Definition of done

- All `tests/voice/` tests green.
- `make run-gateway` alone is enough to serve `/ws/customer` + `/asr` + `/tts`.
- Frontend with `.env.local` missing `VITE_VOICE_GATEWAY_URL` still does voice correctly.
- cc-openclaw `voice_gateway/server.py` no longer needed for local dev.
- Design doc and manual test plan reflect the new architecture.
