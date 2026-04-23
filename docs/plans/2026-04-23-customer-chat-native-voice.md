# Customer-chat Native Voice — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the iframe-based voice integration on the `feat/customer-chat-voice-fab` branch with an in-widget native voice experience: mic button in composer, ASR/TTS as stateless services in cc-openclaw, AutoService CC unchanged, context shared via existing `/ws/chat`.

**Architecture:** Browser is the sole orchestrator. cc-openclaw exposes two new stateless WS endpoints (`/asr`, `/tts`) that wrap its existing Volcengine `ASRClient` / `TTSClient` — no SplitSession, no ActorBridge. Customer-chat frontend runs a `VoiceCallController` state machine that loops mic → `/asr` → existing `/ws/chat` → `/tts` → playback, with comfort-text filler masking batch CC latency.

**Tech Stack:** React 18 + TypeScript + Vitest + Zustand (frontend); aiohttp + Volcengine Realtime (backend).

**Design doc:** `docs/plans/2026-04-23-customer-chat-native-voice-design.md`

**Two repos involved:**
- `D:\workspace\zhidaoyuan\AutoService` (branch: `feat/customer-chat-voice-fab`) — most work
- `D:\workspace\zhidaoyuan\cc-openclaw` — new /asr + /tts endpoints (separate commits)

---

## Phase A — Backend: cc-openclaw /asr + /tts endpoints

### Task A1: CORS config + ALLOWED_ORIGINS env

**Files:**
- Modify: `cc-openclaw/voice_gateway/config.py`

**Step 1: Add config entry**

Append to `config.py`:
```python
# CORS allowlist (comma-separated origins) for /asr and /tts browser clients.
# Empty string → disabled (reject all cross-origin). Use "*" only in dev.
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "").split(",")
ALLOWED_ORIGINS = [o.strip() for o in ALLOWED_ORIGINS if o.strip()]
```

**Step 2: Commit (cc-openclaw repo)**

```bash
cd /d/workspace/zhidaoyuan/cc-openclaw
git add voice_gateway/config.py
git commit -m "feat(voice_gateway): add ALLOWED_ORIGINS env for CORS"
```

---

### Task A2: Create `asr_route.py` — WS handler for browser ASR

**Files:**
- Create: `cc-openclaw/voice_gateway/asr_route.py`
- Create: `cc-openclaw/voice_gateway/tests/test_asr_route.py`

**Step 1: Write failing test**

```python
# tests/test_asr_route.py
import asyncio
import json
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from unittest.mock import AsyncMock, patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from asr_route import asr_handler


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


@pytest.mark.asyncio
async def test_asr_route_forwards_final_event_as_simple_frame():
    fake = FakeASRClient()
    fake.enqueue({
        "type": "conversation.item.input_audio_transcription.completed",
        "transcript": "hello world",
    })

    with patch("asr_route.ASRClient", return_value=fake):
        app = web.Application()
        app.router.add_get("/asr", asr_handler)

        async with TestClient(TestServer(app)) as client:
            async with client.ws_connect("/asr") as ws:
                await ws.send_json({"type": "start"})
                msg = await ws.receive(timeout=2.0)
                data = json.loads(msg.data)
                assert data == {"type": "final", "text": "hello world"}
```

**Step 2: Run — expect FAIL**

```bash
cd /d/workspace/zhidaoyuan/cc-openclaw
python -m pytest voice_gateway/tests/test_asr_route.py -v
# Expected: ImportError or file-not-found
```

**Step 3: Implement `asr_route.py`**

```python
"""Stateless ASR WebSocket handler — proxies browser PCM → Volcengine ASR → text frames back."""
import json
import logging

import aiohttp.web

from asr_client import ASRClient

log = logging.getLogger(__name__)


# Volcengine ASR event types we care about
_EV_PARTIAL = "conversation.item.input_audio_transcription.result"
_EV_FINAL = "conversation.item.input_audio_transcription.completed"
_EV_SPEECH_STARTED = "input_audio_buffer.speech_started"


async def asr_handler(request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
    ws = aiohttp.web.WebSocketResponse()
    await ws.prepare(request)
    log.info("[/asr] browser connected")

    asr = ASRClient()
    try:
        # Expect first message to be {"type":"start"}
        first = await ws.receive()
        if first.type != aiohttp.WSMsgType.TEXT:
            await ws.send_json({"type": "error", "message": "expected start frame"})
            return ws
        try:
            data = json.loads(first.data)
        except json.JSONDecodeError:
            await ws.send_json({"type": "error", "message": "invalid start frame"})
            return ws
        if data.get("type") != "start":
            await ws.send_json({"type": "error", "message": "first frame must be type=start"})
            return ws

        await asr.connect()

        import asyncio
        reader_task = asyncio.create_task(_forward_asr_events(asr, ws))
        browser_task = asyncio.create_task(_forward_browser_audio(ws, asr))

        done, pending = await asyncio.wait(
            {reader_task, browser_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
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
        log.info("[/asr] browser disconnected")

    return ws


async def _forward_asr_events(asr: ASRClient, ws: aiohttp.web.WebSocketResponse) -> None:
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
            await ws.send_json({"type": "error", "message": event.get("error", {}).get("message", "ASR error")})


async def _forward_browser_audio(ws: aiohttp.web.WebSocketResponse, asr: ASRClient) -> None:
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.BINARY:
            await asr.send_audio(msg.data)
        elif msg.type == aiohttp.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            if data.get("type") == "stop":
                break
        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
            break
```

**Step 4: Run — expect PASS**

```bash
python -m pytest voice_gateway/tests/test_asr_route.py -v
# Expected: 1 passed
```

**Step 5: Commit**

```bash
git add voice_gateway/asr_route.py voice_gateway/tests/test_asr_route.py
git commit -m "feat(voice_gateway): add stateless /asr WebSocket route"
```

---

### Task A3: Create `tts_route.py` — WS handler for browser TTS

**Files:**
- Create: `cc-openclaw/voice_gateway/tts_route.py`
- Create: `cc-openclaw/voice_gateway/tests/test_tts_route.py`

**Step 1: Write failing test**

```python
# tests/test_tts_route.py
import pytest
import json
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from unittest.mock import patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tts_route import tts_handler


class FakeTTSClient:
    def __init__(self):
        self.connected = False

    async def connect(self):
        self.connected = True

    async def synthesize(self, text: str):
        # Yield two small PCM chunks then stop
        yield b"\x00\x01" * 100
        yield b"\x02\x03" * 100

    async def close(self):
        self.connected = False


@pytest.mark.asyncio
async def test_tts_route_streams_audio_then_done():
    with patch("tts_route.TTSClient", return_value=FakeTTSClient()):
        app = web.Application()
        app.router.add_get("/tts", tts_handler)

        async with TestClient(TestServer(app)) as client:
            async with client.ws_connect("/tts") as ws:
                await ws.send_json({"type": "speak", "text": "hi"})

                binary_chunks = 0
                got_done = False
                for _ in range(10):
                    msg = await ws.receive(timeout=2.0)
                    if msg.type.name == "BINARY":
                        binary_chunks += 1
                    elif msg.type.name == "TEXT":
                        data = json.loads(msg.data)
                        if data.get("type") == "done":
                            got_done = True
                            break

                assert binary_chunks == 2
                assert got_done
```

**Step 2: Run — expect FAIL**

```bash
python -m pytest voice_gateway/tests/test_tts_route.py -v
```

**Step 3: Implement `tts_route.py`**

```python
"""Stateless TTS WebSocket handler — accepts speak/abort, streams PCM back."""
import asyncio
import json
import logging

import aiohttp.web

from tts_client import TTSClient

log = logging.getLogger(__name__)


async def tts_handler(request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
    ws = aiohttp.web.WebSocketResponse()
    await ws.prepare(request)
    log.info("[/tts] browser connected")

    tts = TTSClient()
    current_task: asyncio.Task | None = None

    try:
        await tts.connect()

        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue

            action = data.get("type")
            if action == "speak":
                text = data.get("text", "")
                if current_task and not current_task.done():
                    current_task.cancel()
                current_task = asyncio.create_task(_do_speak(tts, ws, text))
            elif action == "abort":
                if current_task and not current_task.done():
                    current_task.cancel()
    except Exception as e:
        log.exception("[/tts] error")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        if current_task and not current_task.done():
            current_task.cancel()
        try:
            await tts.close()
        except Exception:
            pass
        log.info("[/tts] browser disconnected")

    return ws


async def _do_speak(tts: TTSClient, ws: aiohttp.web.WebSocketResponse, text: str) -> None:
    try:
        async for chunk in tts.synthesize(text):
            await ws.send_bytes(chunk)
        await ws.send_json({"type": "done"})
    except asyncio.CancelledError:
        log.info("[/tts] speak cancelled")
        raise
    except Exception as e:
        log.error(f"[/tts] speak error: {e}")
        await ws.send_json({"type": "error", "message": str(e)})
```

**Step 4: Run — expect PASS**

```bash
python -m pytest voice_gateway/tests/test_tts_route.py -v
```

**Step 5: Commit**

```bash
git add voice_gateway/tts_route.py voice_gateway/tests/test_tts_route.py
git commit -m "feat(voice_gateway): add stateless /tts WebSocket route"
```

---

### Task A4: Wire `/asr` + `/tts` routes + CORS middleware in `server.py`

**Files:**
- Modify: `cc-openclaw/voice_gateway/server.py`

**Step 1: Patch `main()`**

Add imports at top:
```python
from aiohttp import web
from asr_route import asr_handler
from tts_route import tts_handler
from config import ALLOWED_ORIGINS
```

Add middleware factory:
```python
@web.middleware
async def cors_middleware(request: web.Request, handler):
    # Handle CORS preflight
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        resp = await handler(request)

    origin = request.headers.get("Origin", "")
    if ALLOWED_ORIGINS and (origin in ALLOWED_ORIGINS or "*" in ALLOWED_ORIGINS):
        resp.headers["Access-Control-Allow-Origin"] = origin or "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp
```

Update `main()`:
```python
def main():
    # ... existing env-loading code ...

    port = int(os.environ.get("GATEWAY_PORT", "8089"))
    middlewares = [cors_middleware] if ALLOWED_ORIGINS else []
    app = aiohttp.web.Application(middlewares=middlewares)
    app.router.add_get("/ws", ws_handler)      # legacy — cc-openclaw voice-web
    app.router.add_get("/asr", asr_handler)    # new — stateless ASR
    app.router.add_get("/tts", tts_handler)    # new — stateless TTS

    log.info(f"Starting voice gateway on :{port}")
    aiohttp.web.run_app(app, port=port, print=None)
```

**Step 2: Smoke test — run server, curl the routes**

```bash
cd /d/workspace/zhidaoyuan/cc-openclaw
ALLOWED_ORIGINS="http://localhost:5173" GATEWAY_PORT=8089 python voice_gateway/server.py &
SERVER_PID=$!
sleep 2
# Verify 101 Switching Protocols on /asr (WS upgrade)
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" -H "Sec-WebSocket-Version: 13" http://localhost:8089/asr 2>&1 | head -3
# Expected: "HTTP/1.1 101 Switching Protocols"
kill $SERVER_PID
```

**Step 3: Commit**

```bash
git add voice_gateway/server.py
git commit -m "feat(voice_gateway): mount /asr + /tts routes with CORS middleware"
```

---

## Phase B — Frontend: low-level modules (audio + clients)

### Task B1: Port `pcm-processor.js` AudioWorklet

**Files:**
- Create: `frontend/apps/customer-chat/public/pcm-processor.js`

**Step 1: Copy file**

```bash
cp /d/workspace/zhidaoyuan/cc-openclaw/voice-web/public/pcm-processor.js \
   /d/workspace/zhidaoyuan/AutoService/frontend/apps/customer-chat/public/pcm-processor.js
```

**Step 2: Verify content (skim; no modification needed — it's browser-only AudioWorklet code)**

**Step 3: Commit**

```bash
cd /d/workspace/zhidaoyuan/AutoService
git add frontend/apps/customer-chat/public/pcm-processor.js
git commit -m "feat(voice): port pcm-processor AudioWorklet from cc-openclaw voice-web"
```

---

### Task B2: Port `audio-capture.ts` and `audio-playback.ts`

**Files:**
- Create: `frontend/apps/customer-chat/src/voice/audio-capture.ts`
- Create: `frontend/apps/customer-chat/src/voice/audio-playback.ts`
- Create: `frontend/apps/customer-chat/src/__tests__/audio-playback.test.ts`

**Step 1: Copy both files**

```bash
mkdir -p frontend/apps/customer-chat/src/voice
cp /d/workspace/zhidaoyuan/cc-openclaw/voice-web/src/lib/audio-capture.ts \
   frontend/apps/customer-chat/src/voice/audio-capture.ts
cp /d/workspace/zhidaoyuan/cc-openclaw/voice-web/src/lib/audio-playback.ts \
   frontend/apps/customer-chat/src/voice/audio-playback.ts
```

**Step 2: Write test for `clearPlayback` silencing behavior**

```typescript
// src/__tests__/audio-playback.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as playback from '../voice/audio-playback';

describe('audio-playback', () => {
  beforeEach(() => {
    // @ts-expect-error mock AudioContext
    global.AudioContext = vi.fn(() => ({
      currentTime: 0,
      destination: {},
      createGain: () => ({ connect: vi.fn(), gain: { setValueAtTime: vi.fn() } }),
      createBuffer: () => ({ getChannelData: () => new Float32Array(0), duration: 0 }),
      createBufferSource: () => ({ buffer: null, connect: vi.fn(), start: vi.fn(), stop: vi.fn(), disconnect: vi.fn() }),
      close: vi.fn(),
    }));
  });

  it('clearPlayback stops all scheduled sources without throwing', () => {
    playback.createPlayer();
    const pcm = new Uint8Array(640);
    playback.enqueue(pcm);
    expect(() => playback.clearPlayback()).not.toThrow();
  });

  it('closePlayer releases the audio context', () => {
    playback.createPlayer();
    expect(() => playback.closePlayer()).not.toThrow();
  });
});
```

**Step 3: Run — expect PASS** (code is already complete from cc-openclaw)

```bash
cd frontend/apps/customer-chat
pnpm test -- audio-playback
```

**Step 4: Commit**

```bash
cd /d/workspace/zhidaoyuan/AutoService
git add frontend/apps/customer-chat/src/voice/audio-capture.ts \
        frontend/apps/customer-chat/src/voice/audio-playback.ts \
        frontend/apps/customer-chat/src/__tests__/audio-playback.test.ts
git commit -m "feat(voice): port audio-capture + audio-playback from cc-openclaw with test"
```

---

### Task B3: Create `capability.ts` — HTTPS + getUserMedia detection

**Files:**
- Create: `frontend/apps/customer-chat/src/voice/capability.ts`
- Create: `frontend/apps/customer-chat/src/__tests__/capability.test.ts`

**Step 1: Write failing test**

```typescript
// src/__tests__/capability.test.ts
import { describe, it, expect, vi } from 'vitest';
import { checkVoiceCapability } from '../voice/capability';

describe('checkVoiceCapability', () => {
  it('returns supported=false when not secure context', () => {
    vi.stubGlobal('isSecureContext', false);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn() } });
    const result = checkVoiceCapability();
    expect(result.supported).toBe(false);
    expect(result.reason).toBe('insecure_context');
  });

  it('returns supported=false when getUserMedia missing', () => {
    vi.stubGlobal('isSecureContext', true);
    vi.stubGlobal('navigator', { mediaDevices: undefined });
    const result = checkVoiceCapability();
    expect(result.supported).toBe(false);
    expect(result.reason).toBe('no_get_user_media');
  });

  it('returns supported=true when secure + mediaDevices present', () => {
    vi.stubGlobal('isSecureContext', true);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn() } });
    const result = checkVoiceCapability();
    expect(result.supported).toBe(true);
    expect(result.reason).toBeUndefined();
  });
});
```

**Step 2: Run — expect FAIL**

```bash
pnpm test -- capability
```

**Step 3: Implement**

```typescript
// src/voice/capability.ts
export type CapabilityReason = 'insecure_context' | 'no_get_user_media';

export interface CapabilityResult {
  supported: boolean;
  reason?: CapabilityReason;
}

export function checkVoiceCapability(): CapabilityResult {
  const secure = typeof isSecureContext !== 'undefined' ? isSecureContext : false;
  if (!secure) return { supported: false, reason: 'insecure_context' };
  if (!navigator?.mediaDevices?.getUserMedia) return { supported: false, reason: 'no_get_user_media' };
  return { supported: true };
}
```

**Step 4: Run — expect PASS**

**Step 5: Commit**

```bash
git add frontend/apps/customer-chat/src/voice/capability.ts \
        frontend/apps/customer-chat/src/__tests__/capability.test.ts
git commit -m "feat(voice): add capability detection (HTTPS + getUserMedia)"
```

---

### Task B4: Create `asr-client.ts` — /asr WS wrapper

**Files:**
- Create: `frontend/apps/customer-chat/src/voice/asr-client.ts`
- Create: `frontend/apps/customer-chat/src/__tests__/asr-client.test.ts`

**Step 1: Write failing test**

```typescript
// src/__tests__/asr-client.test.ts
import { describe, it, expect, vi } from 'vitest';
import { parseAsrFrame } from '../voice/asr-client';

describe('parseAsrFrame', () => {
  it('parses partial frame', () => {
    expect(parseAsrFrame('{"type":"partial","text":"hel"}')).toEqual({ type: 'partial', text: 'hel' });
  });
  it('parses final frame', () => {
    expect(parseAsrFrame('{"type":"final","text":"hello"}')).toEqual({ type: 'final', text: 'hello' });
  });
  it('parses speech_started frame', () => {
    expect(parseAsrFrame('{"type":"speech_started"}')).toEqual({ type: 'speech_started' });
  });
  it('parses error frame', () => {
    expect(parseAsrFrame('{"type":"error","message":"oops"}')).toEqual({ type: 'error', message: 'oops' });
  });
  it('returns null for invalid JSON', () => {
    expect(parseAsrFrame('not-json')).toBeNull();
  });
  it('returns null for unknown type', () => {
    expect(parseAsrFrame('{"type":"weird"}')).toBeNull();
  });
});
```

**Step 2: Run — expect FAIL**

**Step 3: Implement**

```typescript
// src/voice/asr-client.ts
export type AsrFrame =
  | { type: 'partial'; text: string }
  | { type: 'final'; text: string }
  | { type: 'speech_started' }
  | { type: 'error'; message: string };

export function parseAsrFrame(raw: string): AsrFrame | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!data || typeof data !== 'object') return null;
  const t = (data as { type?: unknown }).type;
  if (t === 'partial' || t === 'final') {
    const text = (data as { text?: unknown }).text;
    return typeof text === 'string' ? { type: t, text } : null;
  }
  if (t === 'speech_started') return { type: 'speech_started' };
  if (t === 'error') {
    const message = (data as { message?: unknown }).message;
    return { type: 'error', message: typeof message === 'string' ? message : '' };
  }
  return null;
}

export interface AsrClientEvents {
  onFrame: (frame: AsrFrame) => void;
  onClose: (reason: string) => void;
  onError: (err: string) => void;
}

export class AsrClient {
  private ws: WebSocket | null = null;

  async connect(url: string): Promise<void> {
    this.ws = new WebSocket(url);
    await new Promise<void>((resolve, reject) => {
      if (!this.ws) return reject(new Error('no ws'));
      this.ws.onopen = () => resolve();
      this.ws.onerror = () => reject(new Error('asr ws connect failed'));
    });
    this.ws.send(JSON.stringify({ type: 'start' }));
  }

  listen(events: AsrClientEvents): void {
    if (!this.ws) throw new Error('not connected');
    this.ws.onmessage = (ev) => {
      if (typeof ev.data !== 'string') return;
      const frame = parseAsrFrame(ev.data);
      if (frame) events.onFrame(frame);
    };
    this.ws.onclose = () => events.onClose('closed');
    this.ws.onerror = () => events.onError('ws error');
  }

  sendAudio(pcm: ArrayBuffer): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(pcm);
    }
  }

  async close(): Promise<void> {
    if (this.ws) {
      try {
        this.ws.send(JSON.stringify({ type: 'stop' }));
      } catch { /* already closed */ }
      this.ws.close();
      this.ws = null;
    }
  }
}
```

**Step 4: Run — expect PASS**

**Step 5: Commit**

```bash
git add frontend/apps/customer-chat/src/voice/asr-client.ts \
        frontend/apps/customer-chat/src/__tests__/asr-client.test.ts
git commit -m "feat(voice): add asr-client with frame parser"
```

---

### Task B5: Create `tts-client.ts` — /tts WS wrapper

**Files:**
- Create: `frontend/apps/customer-chat/src/voice/tts-client.ts`
- Create: `frontend/apps/customer-chat/src/__tests__/tts-client.test.ts`

**Step 1: Write failing test**

```typescript
// src/__tests__/tts-client.test.ts
import { describe, it, expect } from 'vitest';
import { parseTtsFrame } from '../voice/tts-client';

describe('parseTtsFrame', () => {
  it('parses done', () => {
    expect(parseTtsFrame('{"type":"done"}')).toEqual({ type: 'done' });
  });
  it('parses error', () => {
    expect(parseTtsFrame('{"type":"error","message":"x"}')).toEqual({ type: 'error', message: 'x' });
  });
  it('returns null for invalid', () => {
    expect(parseTtsFrame('{}')).toBeNull();
    expect(parseTtsFrame('bad')).toBeNull();
  });
});
```

**Step 2: Run — expect FAIL**

**Step 3: Implement**

```typescript
// src/voice/tts-client.ts
export type TtsFrame = { type: 'done' } | { type: 'error'; message: string };

export function parseTtsFrame(raw: string): TtsFrame | null {
  let data: unknown;
  try { data = JSON.parse(raw); } catch { return null; }
  if (!data || typeof data !== 'object') return null;
  const t = (data as { type?: unknown }).type;
  if (t === 'done') return { type: 'done' };
  if (t === 'error') {
    const m = (data as { message?: unknown }).message;
    return { type: 'error', message: typeof m === 'string' ? m : '' };
  }
  return null;
}

export interface TtsClientEvents {
  onAudio: (pcm: Uint8Array) => void;
  onDone: () => void;
  onError: (err: string) => void;
  onClose: () => void;
}

export class TtsClient {
  private ws: WebSocket | null = null;

  async connect(url: string): Promise<void> {
    this.ws = new WebSocket(url);
    this.ws.binaryType = 'arraybuffer';
    await new Promise<void>((resolve, reject) => {
      if (!this.ws) return reject(new Error('no ws'));
      this.ws.onopen = () => resolve();
      this.ws.onerror = () => reject(new Error('tts ws connect failed'));
    });
  }

  listen(events: TtsClientEvents): void {
    if (!this.ws) throw new Error('not connected');
    this.ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') {
        const frame = parseTtsFrame(ev.data);
        if (frame?.type === 'done') events.onDone();
        else if (frame?.type === 'error') events.onError(frame.message);
      } else if (ev.data instanceof ArrayBuffer) {
        events.onAudio(new Uint8Array(ev.data));
      }
    };
    this.ws.onclose = () => events.onClose();
    this.ws.onerror = () => events.onError('ws error');
  }

  speak(text: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'speak', text }));
    }
  }

  abort(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'abort' }));
    }
  }

  async close(): Promise<void> {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}
```

**Step 4: Run — expect PASS**

**Step 5: Commit**

```bash
git add frontend/apps/customer-chat/src/voice/tts-client.ts \
        frontend/apps/customer-chat/src/__tests__/tts-client.test.ts
git commit -m "feat(voice): add tts-client with frame parser and abort"
```

---

## Phase C — Frontend: state machine + hook

### Task C1: Create `VoiceCallController` skeleton with state machine

**Files:**
- Create: `frontend/apps/customer-chat/src/voice/VoiceCallController.ts`
- Create: `frontend/apps/customer-chat/src/__tests__/VoiceCallController.test.ts`

**Step 1: Write failing state-transition tests**

```typescript
// src/__tests__/VoiceCallController.test.ts
import { describe, it, expect, vi } from 'vitest';
import { VoiceCallController, VoiceState } from '../voice/VoiceCallController';

function makeController(overrides: Partial<ConstructorParameters<typeof VoiceCallController>[0]> = {}) {
  return new VoiceCallController({
    asrUrl: 'ws://fake/asr',
    ttsUrl: 'ws://fake/tts',
    onUserMessage: vi.fn(),
    onSendTextToChat: vi.fn(),
    comfortPool: ['hmm'],
    ...overrides,
  });
}

describe('VoiceCallController state machine', () => {
  it('starts in idle', () => {
    const c = makeController();
    expect(c.state).toBe('idle' as VoiceState);
  });

  it('transitions idle → error on explicit fail', () => {
    const c = makeController();
    c._testForceError('mic_denied');
    expect(c.state).toBe('error');
    expect(c.errorReason).toBe('mic_denied');
  });

  it('from error, retry moves back to preparing', () => {
    const c = makeController();
    c._testForceError('mic_denied');
    c.retry();
    expect(c.state).toBe('preparing');
  });

  it('from listening, ASR final moves to thinking and calls onUserMessage', () => {
    const c = makeController();
    const onUserMessage = vi.fn();
    const onSend = vi.fn();
    const c2 = makeController({ onUserMessage, onSendTextToChat: onSend });
    c2._testForceState('listening');
    c2._testOnAsrFrame({ type: 'final', text: 'hello' });
    expect(c2.state).toBe('thinking');
    expect(onUserMessage).toHaveBeenCalledWith('hello');
    expect(onSend).toHaveBeenCalledWith('hello');
  });

  it('from thinking, CC reply transitions to speaking', () => {
    const c = makeController();
    c._testForceState('thinking');
    c.onCcReply('reply from CC');
    expect(c.state).toBe('speaking');
  });

  it('from speaking, skip moves back to listening', () => {
    const c = makeController();
    c._testForceState('speaking');
    c.skip();
    expect(c.state).toBe('listening');
  });

  it('hangup from any active state moves to ending then idle', () => {
    const c = makeController();
    c._testForceState('listening');
    c.hangup();
    expect(['ending', 'idle']).toContain(c.state);
  });
});
```

**Step 2: Run — expect FAIL**

**Step 3: Implement skeleton with test hooks**

```typescript
// src/voice/VoiceCallController.ts
import { AsrClient, AsrFrame } from './asr-client';
import { TtsClient } from './tts-client';
import * as playback from './audio-playback';

export type VoiceState =
  | 'idle' | 'preparing' | 'listening' | 'thinking'
  | 'speaking' | 'ending' | 'error';

export type VoiceErrorReason =
  | 'mic_denied' | 'asr_unreachable' | 'tts_unreachable'
  | 'asr_dropped' | 'tts_dropped' | 'cc_timeout' | 'unknown';

export interface VoiceControllerOptions {
  asrUrl: string;
  ttsUrl: string;
  onUserMessage: (text: string) => void;    // insert user bubble into chat
  onSendTextToChat: (text: string) => void; // send via existing /ws/chat
  comfortPool: string[];
  onStateChange?: (s: VoiceState, reason?: string) => void;
}

export class VoiceCallController {
  state: VoiceState = 'idle';
  errorReason: VoiceErrorReason | null = null;
  private recentComfort: string[] = [];
  private asr: AsrClient | null = null;
  private tts: TtsClient | null = null;
  private mediaStream: MediaStream | null = null;
  private audioCtx: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;

  constructor(private opts: VoiceControllerOptions) {}

  private setState(s: VoiceState, reason?: string): void {
    this.state = s;
    this.opts.onStateChange?.(s, reason);
    // eslint-disable-next-line no-console
    console.debug('[voice]', 'state →', s, reason ?? '');
  }

  // Public actions (start/hangup/skip/retry/onCcReply) — full impl in next tasks.
  // Keep signatures stable; tests here only verify state transitions via hooks.

  skip(): void {
    if (this.state === 'speaking') {
      this.tts?.abort();
      playback.clearPlayback();
      this.setState('listening', 'user_skip');
    }
  }

  hangup(): void {
    if (this.state === 'idle' || this.state === 'ending') return;
    this.setState('ending', 'user_hangup');
    void this._cleanup().then(() => this.setState('idle'));
  }

  retry(): void {
    if (this.state !== 'error') return;
    this.errorReason = null;
    this.setState('preparing', 'retry');
    // C3 wires real start() — for now just transition.
  }

  onCcReply(text: string): void {
    if (this.state === 'thinking' || this.state === 'listening') {
      this.setState('speaking', 'cc_reply');
      this.tts?.speak(text);
    }
  }

  private pickComfort(): string {
    const pool = this.opts.comfortPool.filter(c => !this.recentComfort.includes(c));
    const choice = (pool.length > 0 ? pool : this.opts.comfortPool)[
      Math.floor(Math.random() * (pool.length > 0 ? pool.length : this.opts.comfortPool.length))
    ];
    this.recentComfort.push(choice);
    if (this.recentComfort.length > 3) this.recentComfort.shift();
    return choice;
  }

  private async _cleanup(): Promise<void> {
    try { await this.asr?.close(); } catch {}
    try { await this.tts?.close(); } catch {}
    try { this.workletNode?.disconnect(); } catch {}
    try { this.mediaStream?.getTracks().forEach(t => t.stop()); } catch {}
    try { playback.closePlayer(); } catch {}
    this.asr = null; this.tts = null;
    this.mediaStream = null; this.audioCtx = null; this.workletNode = null;
  }

  // ---- test-only hooks (prefixed with _test, do NOT use in production) ----
  _testForceError(reason: VoiceErrorReason): void {
    this.errorReason = reason;
    this.setState('error', reason);
  }
  _testForceState(s: VoiceState): void { this.setState(s); }
  _testOnAsrFrame(f: AsrFrame): void { this._onAsrFrame(f); }

  private _onAsrFrame(f: AsrFrame): void {
    if (f.type === 'final' && this.state === 'listening') {
      this.opts.onUserMessage(f.text);
      this.opts.onSendTextToChat(f.text);
      this.setState('thinking', 'asr_final');
      // comfort text play is wired in C2
    } else if (f.type === 'error') {
      this._testForceError('asr_dropped');
    }
  }
}
```

**Step 4: Run — expect PASS**

**Step 5: Commit**

```bash
git add frontend/apps/customer-chat/src/voice/VoiceCallController.ts \
        frontend/apps/customer-chat/src/__tests__/VoiceCallController.test.ts
git commit -m "feat(voice): VoiceCallController state machine skeleton"
```

---

### Task C2: Wire pipeline — start(), comfort, audio capture

**Files:**
- Modify: `frontend/apps/customer-chat/src/voice/VoiceCallController.ts`
- Modify: `frontend/apps/customer-chat/src/__tests__/VoiceCallController.test.ts`

**Step 1: Add start() method test**

```typescript
// add to VoiceCallController.test.ts
it('start() transitions idle → preparing', async () => {
  const c = makeController();
  // Do not await — start is async and will fail without real browser APIs
  void c.start().catch(() => {});
  // allow microtask
  await Promise.resolve();
  expect(['preparing', 'error']).toContain(c.state);
});

it('comfort text pool does not repeat last 3', () => {
  const c = makeController({ comfortPool: ['a', 'b', 'c', 'd'] });
  const seen: string[] = [];
  for (let i = 0; i < 20; i++) {
    // @ts-expect-error access private method through any
    seen.push((c as any).pickComfort());
  }
  // No window of 4 consecutive identical
  for (let i = 0; i + 3 < seen.length; i++) {
    const slice = seen.slice(i, i + 4);
    expect(new Set(slice).size).toBeGreaterThan(1);
  }
});
```

**Step 2: Implement `start()`**

Append to `VoiceCallController.ts`:

```typescript
  async start(): Promise<void> {
    if (this.state !== 'idle' && this.state !== 'error') return;
    this.setState('preparing', 'user_start');

    // 1. AudioContext (in user gesture — browser unlock)
    try {
      this.audioCtx = new AudioContext({ sampleRate: 16000 });
      playback.createPlayer();
    } catch {
      this._testForceError('unknown');
      return;
    }

    // 2. getUserMedia
    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch {
      this._testForceError('mic_denied');
      return;
    }

    // 3. ASR + TTS connect
    this.asr = new AsrClient();
    this.tts = new TtsClient();
    try {
      await this.asr.connect(this.opts.asrUrl);
    } catch {
      this._testForceError('asr_unreachable');
      return;
    }
    try {
      await this.tts.connect(this.opts.ttsUrl);
    } catch {
      this._testForceError('tts_unreachable');
      return;
    }

    this.asr.listen({
      onFrame: f => this._onAsrFrame(f),
      onClose: () => { if (this.state !== 'ending' && this.state !== 'idle') this._testForceError('asr_dropped'); },
      onError: () => this._testForceError('asr_dropped'),
    });
    this.tts.listen({
      onAudio: pcm => playback.enqueue(pcm),
      onDone: () => this._onTtsDone(),
      onError: () => this._testForceError('tts_dropped'),
      onClose: () => { if (this.state !== 'ending' && this.state !== 'idle') this._testForceError('tts_dropped'); },
    });

    // 4. Wire AudioWorklet
    try {
      await this.audioCtx.audioWorklet.addModule('/pcm-processor.js');
      const src = this.audioCtx.createMediaStreamSource(this.mediaStream);
      this.workletNode = new AudioWorkletNode(this.audioCtx, 'pcm-processor');
      this.workletNode.port.onmessage = (ev) => {
        const buf = ev.data as ArrayBuffer;
        this.asr?.sendAudio(buf);
      };
      src.connect(this.workletNode);
    } catch {
      this._testForceError('unknown');
      return;
    }

    this.setState('listening', 'ready');
  }

  private _onTtsDone(): void {
    if (this.state === 'speaking') {
      this.setState('listening', 'tts_done');
    }
    // in 'thinking' (comfort finished), stay in thinking waiting for CC reply
  }
```

Update `_onAsrFrame` to trigger comfort:

```typescript
  private _onAsrFrame(f: AsrFrame): void {
    if (f.type === 'final' && this.state === 'listening') {
      this.opts.onUserMessage(f.text);
      this.opts.onSendTextToChat(f.text);
      this.setState('thinking', 'asr_final');
      const comfort = this.pickComfort();
      this.tts?.speak(comfort);
    } else if (f.type === 'error') {
      this._testForceError('asr_dropped');
    }
  }
```

Update `onCcReply` to queue-after-comfort (refinement):

```typescript
  private pendingCcReply: string | null = null;
  onCcReply(text: string): void {
    if (this.state === 'thinking') {
      // if comfort still playing, queue it — _onTtsDone will promote
      this.pendingCcReply = text;
    } else if (this.state === 'listening' || this.state === 'speaking') {
      this.setState('speaking', 'cc_reply');
      this.tts?.speak(text);
    }
  }
```

Revise `_onTtsDone`:

```typescript
  private _onTtsDone(): void {
    if (this.state === 'speaking') {
      this.setState('listening', 'tts_done');
    } else if (this.state === 'thinking' && this.pendingCcReply) {
      const text = this.pendingCcReply;
      this.pendingCcReply = null;
      this.setState('speaking', 'cc_reply_after_comfort');
      this.tts?.speak(text);
    }
  }
```

**Step 3: Run — expect PASS** (tests still pass; new tests green)

**Step 4: Commit**

```bash
git add frontend/apps/customer-chat/src/voice/VoiceCallController.ts \
        frontend/apps/customer-chat/src/__tests__/VoiceCallController.test.ts
git commit -m "feat(voice): wire VoiceCallController start(), comfort pool, reply handoff"
```

---

### Task C3: Create `useVoiceCall` React hook

**Files:**
- Create: `frontend/apps/customer-chat/src/voice/useVoiceCall.ts`

**Step 1: Implement**

```typescript
// src/voice/useVoiceCall.ts
import { useEffect, useRef, useState } from 'react';
import { VoiceCallController, VoiceState, VoiceErrorReason } from './VoiceCallController';

export interface UseVoiceCallOpts {
  asrUrl: string;
  ttsUrl: string;
  comfortPool: string[];
  onUserMessage: (text: string) => void;
  onSendTextToChat: (text: string) => void;
}

export function useVoiceCall(opts: UseVoiceCallOpts) {
  const [state, setState] = useState<VoiceState>('idle');
  const [errorReason, setErrorReason] = useState<VoiceErrorReason | null>(null);
  const controllerRef = useRef<VoiceCallController | null>(null);

  useEffect(() => {
    const controller = new VoiceCallController({
      ...opts,
      onStateChange: (s) => {
        setState(s);
        if (s === 'error') setErrorReason(controllerRef.current?.errorReason ?? null);
        else setErrorReason(null);
      },
    });
    controllerRef.current = controller;
    return () => {
      controller.hangup();
      controllerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts.asrUrl, opts.ttsUrl]);

  // visibilitychange → auto hangup
  useEffect(() => {
    const handler = () => {
      if (document.visibilityState === 'hidden') controllerRef.current?.hangup();
    };
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
  }, []);

  return {
    state,
    errorReason,
    start: () => controllerRef.current?.start(),
    hangup: () => controllerRef.current?.hangup(),
    skip: () => controllerRef.current?.skip(),
    retry: () => controllerRef.current?.retry(),
    onCcReply: (t: string) => controllerRef.current?.onCcReply(t),
  };
}
```

**Step 2: Commit** (no new tests needed — controller is tested; hook is thin)

```bash
git add frontend/apps/customer-chat/src/voice/useVoiceCall.ts
git commit -m "feat(voice): add useVoiceCall React hook"
```

---

## Phase D — Frontend: UI components

### Task D1: Create `VoiceStatusBar` component

**Files:**
- Create: `frontend/apps/customer-chat/src/voice/VoiceStatusBar.tsx`
- Create: `frontend/apps/customer-chat/src/__tests__/VoiceStatusBar.test.tsx`

**Step 1: Write failing tests**

```typescript
// src/__tests__/VoiceStatusBar.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { VoiceStatusBar } from '../voice/VoiceStatusBar';

describe('VoiceStatusBar', () => {
  it('renders hidden when state is idle', () => {
    const { container } = render(<VoiceStatusBar state="idle" errorReason={null} onSkip={vi.fn()} onHangup={vi.fn()} onRetry={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders listening state text', () => {
    render(<VoiceStatusBar state="listening" errorReason={null} onSkip={vi.fn()} onHangup={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByTestId('voice-status-bar')).toBeInTheDocument();
    expect(screen.getByLabelText(/hang ?up|挂断/i)).toBeInTheDocument();
  });

  it('shows skip button only in speaking state', () => {
    const { rerender } = render(<VoiceStatusBar state="thinking" errorReason={null} onSkip={vi.fn()} onHangup={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.queryByLabelText(/skip|跳过/i)).toBeNull();
    rerender(<VoiceStatusBar state="speaking" errorReason={null} onSkip={vi.fn()} onHangup={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByLabelText(/skip|跳过/i)).toBeInTheDocument();
  });

  it('shows retry button in error state', () => {
    const onRetry = vi.fn();
    render(<VoiceStatusBar state="error" errorReason="mic_denied" onSkip={vi.fn()} onHangup={vi.fn()} onRetry={onRetry} />);
    fireEvent.click(screen.getByLabelText(/retry|重试/i));
    expect(onRetry).toHaveBeenCalled();
  });
});
```

**Step 2: Run — expect FAIL**

**Step 3: Implement**

```tsx
// src/voice/VoiceStatusBar.tsx
import { useTranslation } from '@autoservice/i18n';
import type { VoiceState, VoiceErrorReason } from './VoiceCallController';

interface Props {
  state: VoiceState;
  errorReason: VoiceErrorReason | null;
  onSkip: () => void;
  onHangup: () => void;
  onRetry: () => void;
}

export function VoiceStatusBar({ state, errorReason, onSkip, onHangup, onRetry }: Props) {
  const { t } = useTranslation();
  if (state === 'idle') return null;

  const isError = state === 'error';
  const textMap: Record<VoiceState, string> = {
    idle: '',
    preparing: t('voice.status.preparing'),
    listening: t('voice.status.listening'),
    thinking: t('voice.status.thinking'),
    speaking: t('voice.status.speaking'),
    ending: t('voice.status.ending'),
    error: errorReason === 'mic_denied'
      ? t('voice.status.mic_denied')
      : errorReason === 'asr_unreachable' || errorReason === 'tts_unreachable'
        ? t('voice.status.service_unreachable')
        : errorReason === 'cc_timeout'
          ? t('voice.status.cc_timeout')
          : t('voice.status.unknown_error'),
  };

  return (
    <div
      data-testid="voice-status-bar"
      className={`voice-status-bar ${isError ? 'is-error' : ''}`}
      role="status"
      aria-live="polite"
    >
      <span className="voice-status-text">{textMap[state]}</span>
      <div className="voice-status-actions">
        {state === 'speaking' && (
          <button type="button" onClick={onSkip} aria-label={t('voice.action.skip')}>
            {t('voice.action.skip')}
          </button>
        )}
        {isError && (
          <button type="button" onClick={onRetry} aria-label={t('voice.action.retry')}>
            {t('voice.action.retry')}
          </button>
        )}
        {state !== 'error' && state !== 'ending' && (
          <button type="button" onClick={onHangup} aria-label={t('voice.action.hangup')}>
            {t('voice.action.hangup')}
          </button>
        )}
      </div>
    </div>
  );
}
```

**Step 4: Run — expect PASS**

**Step 5: Commit**

```bash
git add frontend/apps/customer-chat/src/voice/VoiceStatusBar.tsx \
        frontend/apps/customer-chat/src/__tests__/VoiceStatusBar.test.tsx
git commit -m "feat(voice): add VoiceStatusBar with skip/hangup/retry actions"
```

---

### Task D2: Add i18n strings

**Files:**
- Modify: `frontend/packages/i18n/src/locales/zh-CN.json`
- Modify: `frontend/packages/i18n/src/locales/en.json`

**Step 1: Add voice.* keys to both files**

zh-CN.json, under existing structure, add:
```json
{
  "voice": {
    "status": {
      "preparing": "正在准备...",
      "listening": "正在聆听...",
      "thinking": "让我想想...",
      "speaking": "正在回复...",
      "ending": "结束中...",
      "mic_denied": "🎤 麦克风被拒绝",
      "service_unreachable": "语音服务连接失败",
      "cc_timeout": "响应超时，请重试",
      "unknown_error": "语音异常"
    },
    "action": {
      "skip": "跳过",
      "hangup": "挂断",
      "retry": "重试"
    },
    "button": {
      "mic": "开始语音通话",
      "unsupported": "当前环境不支持语音"
    },
    "comfort": ["嗯，我看看...", "让我想想...", "稍等一下", "好的好的"]
  }
}
```

en.json, mirror:
```json
{
  "voice": {
    "status": {
      "preparing": "Preparing...",
      "listening": "Listening...",
      "thinking": "Let me think...",
      "speaking": "Replying...",
      "ending": "Ending...",
      "mic_denied": "🎤 Microphone denied",
      "service_unreachable": "Voice service unavailable",
      "cc_timeout": "Response timed out, please retry",
      "unknown_error": "Voice error"
    },
    "action": {
      "skip": "Skip",
      "hangup": "Hang up",
      "retry": "Retry"
    },
    "button": {
      "mic": "Start voice call",
      "unsupported": "Voice not supported in this environment"
    },
    "comfort": ["Hmm, let me see...", "One moment...", "Let me think...", "Alright..."]
  }
}
```

**Step 2: Run typecheck**

```bash
cd frontend/apps/customer-chat
pnpm typecheck
# Expected: pass
```

**Step 3: Commit**

```bash
git add frontend/packages/i18n/src/locales/zh-CN.json \
        frontend/packages/i18n/src/locales/en.json
git commit -m "feat(voice): add voice.* i18n strings and comfort pool"
```

---

### Task D3: Add mic button to `ChatInput`

**Files:**
- Modify: `frontend/apps/customer-chat/src/components/ChatInput.tsx`
- Modify: `frontend/apps/customer-chat/src/__tests__/ChatInput.test.tsx`

**Step 1: Write test**

```typescript
// add to ChatInput.test.tsx
import { checkVoiceCapability } from '../voice/capability';
vi.mock('../voice/capability');

it('renders mic button when capability.supported', () => {
  (checkVoiceCapability as any).mockReturnValue({ supported: true });
  render(<ChatInput onSend={vi.fn()} onMicClick={vi.fn()} />);
  expect(screen.getByTestId('voice-mic-btn')).toBeEnabled();
});

it('disables mic button when not supported', () => {
  (checkVoiceCapability as any).mockReturnValue({ supported: false, reason: 'insecure_context' });
  render(<ChatInput onSend={vi.fn()} onMicClick={vi.fn()} />);
  expect(screen.getByTestId('voice-mic-btn')).toBeDisabled();
});

it('fires onMicClick when clicked', () => {
  (checkVoiceCapability as any).mockReturnValue({ supported: true });
  const onMic = vi.fn();
  render(<ChatInput onSend={vi.fn()} onMicClick={onMic} />);
  fireEvent.click(screen.getByTestId('voice-mic-btn'));
  expect(onMic).toHaveBeenCalled();
});
```

**Step 2: Run — expect FAIL**

**Step 3: Implement — add mic icon + button + prop**

In `ChatInput.tsx`:
- Add `onMicClick?: () => void` to props
- Add mic icon component:

```tsx
const MicIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4M8 23h8" />
  </svg>
);
```

- Inside `<div className="w-comp-tools">`, after emoji button, add:

```tsx
{(() => {
  const cap = checkVoiceCapability();
  return (
    <button
      type="button"
      className="w-tool-btn"
      data-testid="voice-mic-btn"
      title={cap.supported ? t('voice.button.mic') : t('voice.button.unsupported')}
      aria-label={cap.supported ? t('voice.button.mic') : t('voice.button.unsupported')}
      disabled={disabled || !cap.supported || !onMicClick}
      onClick={onMicClick}
    >
      <MicIcon />
    </button>
  );
})()}
```

Import at top: `import { checkVoiceCapability } from '../voice/capability';`

**Step 4: Run — expect PASS**

**Step 5: Commit**

```bash
git add frontend/apps/customer-chat/src/components/ChatInput.tsx \
        frontend/apps/customer-chat/src/__tests__/ChatInput.test.tsx
git commit -m "feat(voice): add mic button to ChatInput composer"
```

---

## Phase E — Integration + removal

### Task E1: Wire into `App.tsx` + `ChatModal.tsx`

**Files:**
- Modify: `frontend/apps/customer-chat/src/App.tsx`
- Modify: `frontend/apps/customer-chat/src/components/ChatModal.tsx`

**Step 1: Wire `App.tsx`**

Remove the import and state for `VoiceCallModal`:
```typescript
// DELETE:
// import { VoiceCallModal } from './components/VoiceCallModal';
// const [isCallOpen, setIsCallOpen] = useState(false);
// const voiceCtx = useMemo(...)
// <VoiceCallModal .../>
// onCallClick handler
```

Add voice hook + handlers:

```typescript
import { useVoiceCall } from './voice/useVoiceCall';
import { useTranslation } from '@autoservice/i18n';

// inside ChatApp
const { t } = useTranslation();
const comfortPool = (t('voice.comfort', { returnObjects: true }) as unknown as string[]) ?? ['...'];
const asrUrl = resolveVoiceWsUrl('/asr');
const ttsUrl = resolveVoiceWsUrl('/tts');

const voice = useVoiceCall({
  asrUrl,
  ttsUrl,
  comfortPool,
  onUserMessage: (text) => {
    // insert user bubble (same path as text typed)
    chatStore.appendMessage({ role: 'user', content: text });
  },
  onSendTextToChat: (text) => {
    ws.send({ type: 'user_text_submit', text });
  },
});

// When a bot reply arrives via WS (in useWebSocket.ts handler), additionally call:
// voice.onCcReply(text) — only while voice.state !== 'idle'
```

Add URL resolver:

```typescript
function resolveVoiceWsUrl(path: '/asr' | '/tts'): string {
  const env = (import.meta as any).env;
  const base = env?.VITE_VOICE_GATEWAY_URL;
  if (base) return `${base.replace(/\/$/, '')}${path}`;
  // Same-origin fallback
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${path}`;
}
```

**Step 2: Wire `ChatModal.tsx`** — mount `<VoiceStatusBar>` between header and message list

Add props `voiceState`, `voiceErrorReason`, `onVoiceSkip`, `onVoiceHangup`, `onVoiceRetry` — pass from App.
Place `<VoiceStatusBar ... />` after `<ChatHeader>`, before `<MessageList>`.
Pass `disabled={voiceState !== 'idle' && voiceState !== 'error'}` to `<ChatInput>` (via existing `disabled` prop OR, if it has its own connection-derived disabled, OR them).

**Step 3: Update `useWebSocket.ts` to forward bot replies to voice**

Find where `bot_text_delta` is handled — after inserting to chat store, call `voice.onCcReply(content)` (threaded via prop or context).

**Step 4: Run typecheck + existing tests**

```bash
pnpm typecheck && pnpm test
# Expected: PASS (iframe tests now failing — we handle deletion next)
```

**Step 5: Commit** (even if iframe tests fail — fix in next task)

```bash
git add frontend/apps/customer-chat/src/App.tsx \
        frontend/apps/customer-chat/src/components/ChatModal.tsx \
        frontend/apps/customer-chat/src/hooks/useWebSocket.ts
git commit -m "feat(voice): integrate VoiceCallController into App + ChatModal"
```

---

### Task E2: Remove iframe voice integration + its tests + external FAB

**Files (delete):**
- `frontend/apps/customer-chat/src/components/VoiceCallModal.tsx`
- `frontend/apps/customer-chat/src/utils/voice-iframe.ts` (or wherever it lives — check `src/lib/` too)
- `frontend/apps/customer-chat/src/__tests__/VoiceCallModal.test.tsx`
- `frontend/apps/customer-chat/src/__tests__/VoiceCallModal.postmsg.test.tsx`
- `frontend/apps/customer-chat/src/__tests__/voice-iframe.test.ts`

**Files (modify):**
- `frontend/apps/customer-chat/src/components/ChatFAB.tsx` — keep only the chat 💬 button, drop voice FAB
- `frontend/apps/customer-chat/src/__tests__/ChatFAB.test.tsx` — drop `onCallClick` / voice-fab assertions; keep chat-button ones
- `frontend/apps/customer-chat/.env.example` — remove `VITE_VOICE_WEB_URL`; add `VITE_VOICE_GATEWAY_URL=http://localhost:8089`

**Step 1: Delete and modify**

```bash
rm frontend/apps/customer-chat/src/components/VoiceCallModal.tsx
rm frontend/apps/customer-chat/src/lib/voice-iframe.ts 2>/dev/null || rm frontend/apps/customer-chat/src/utils/voice-iframe.ts
rm frontend/apps/customer-chat/src/__tests__/VoiceCallModal.test.tsx
rm frontend/apps/customer-chat/src/__tests__/VoiceCallModal.postmsg.test.tsx
rm frontend/apps/customer-chat/src/__tests__/voice-iframe.test.ts
```

Rewrite `ChatFAB.tsx`:
```tsx
import { useTranslation } from '@autoservice/i18n';

interface ChatFABProps {
  onClick: () => void;
  highlight?: boolean;
}

export function ChatFAB({ onClick, highlight = false }: ChatFABProps) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      className={`web-fab ${highlight ? 'highlight' : ''}`}
      onClick={onClick}
      aria-label={t('customer.chat.open')}
    >
      💬
    </button>
  );
}
```

Trim `ChatFAB.test.tsx`: remove all `onCallClick` / `voice-fab` / `web-fab-call` tests. Keep chat-button tests only.

Update `.env.example`:
```
# Voice gateway base URL (cc-openclaw's voice_gateway). Omit to use same-origin.
VITE_VOICE_GATEWAY_URL=http://localhost:8089
```

Check for other usages of `VITE_VOICE_WEB_URL` / `VoiceCallModal` / `voice-iframe` and remove.

```bash
grep -r "VITE_VOICE_WEB_URL\|VoiceCallModal\|voice-iframe\|onCallClick\|web-fab-call" frontend/apps/customer-chat/src || echo "clean"
```

**Step 2: Run full test suite + typecheck**

```bash
pnpm typecheck && pnpm test
# Expected: all green
```

**Step 3: Run full build**

```bash
pnpm build
# Expected: success
```

**Step 4: Commit**

```bash
git add -A frontend/apps/customer-chat
git commit -m "refactor(voice): remove iframe integration (VoiceCallModal, voice-iframe, external FAB, 3 test files)"
```

---

### Task E3: Add CSS for VoiceStatusBar

**Files:**
- Modify: `frontend/apps/customer-chat/src/index.css`

**Step 1: Append styles**

```css
/* VoiceStatusBar — top bar above message list */
.voice-status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  background: var(--w-bg-subtle, #f6f8fa);
  border-bottom: 1px solid var(--w-border, #e3e6ea);
  font-size: 13px;
}
.voice-status-bar.is-error {
  background: #fde8e8;
  color: #a12a2a;
  border-bottom-color: #f5c2c2;
}
.voice-status-text {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.voice-status-actions {
  display: inline-flex;
  gap: 8px;
}
.voice-status-actions button {
  border: 1px solid currentColor;
  background: transparent;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}
.voice-status-actions button:hover {
  opacity: 0.8;
}
```

**Step 2: Commit**

```bash
git add frontend/apps/customer-chat/src/index.css
git commit -m "feat(voice): add VoiceStatusBar styles"
```

---

## Phase F — Verification

### Task F1: Full-suite verification

**Files:** none (verification only)

**Step 1: Frontend tests + build**

```bash
cd frontend/apps/customer-chat
pnpm test
pnpm typecheck
pnpm build
# Expected: all green
```

**Step 2: Backend tests**

```bash
cd /d/workspace/zhidaoyuan/cc-openclaw
python -m pytest voice_gateway/tests/ -v
# Expected: all tests pass, including new test_asr_route and test_tts_route
```

**Step 3: Smoke via local server**

Terminal A (cc-openclaw):
```bash
cd /d/workspace/zhidaoyuan/cc-openclaw
ALLOWED_ORIGINS="http://localhost:5173" VOLCENGINE_API_KEY=<devkey> python voice_gateway/server.py
```

Terminal B (AutoService):
```bash
cd /d/workspace/zhidaoyuan/AutoService
make run-web   # or pnpm dev in frontend/apps/customer-chat
```

Browser: open the customer-chat URL with a valid tenant. Click the mic button in the composer.

**Expected:**
- Permission prompt → allow → status bar shows "正在聆听..."
- Speak "你好" → partial transcripts → final → user bubble inserts → comfort "嗯，我看看..." plays → CC reply arrives → bubble inserts → TTS plays
- Skip button appears during speaking → click → silent + back to listening
- Hangup button → status bar disappears, composer re-enabled

**Step 4: Capture any regressions** (no commit; move to F2 if issues)

---

### Task F2: Manual test plan document

**Files:**
- Create: `docs/plans/2026-04-23-customer-chat-native-voice-manual-test.md`

**Step 1: Write the plan**

Summarize desktop (Chrome/Safari/Firefox) and mobile (iOS Safari, Android Chrome) checks. Use §6.4 of the design doc as the source.

**Step 2: Commit**

```bash
git add docs/plans/2026-04-23-customer-chat-native-voice-manual-test.md
git commit -m "docs(voice): manual test plan for native voice integration"
```

---

## Appendix — open items tracked for post-ship

- Auto-barge-in using `speech_started` hook (+15 LOC)
- CC streaming (`include_partial_messages=True`) rollout
- Multilingual TTS voice switch
- Mobile keyboard viewport compensation
- Optional auth token on `/asr` + `/tts`
