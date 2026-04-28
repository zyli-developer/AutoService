# Voice Native Integration — Design

**Date:** 2026-04-24
**Status:** Approved, pending implementation
**Stacks on:** PR #81 (`feat/customer-chat-voice-fab`)

## Goal

Migrate the E2E-adapter voice gateway from `cc-openclaw/voice_gateway/` into AutoService so customer-chat can talk to its own backend for voice — no separate cc-openclaw process, no separate port, no `VITE_VOICE_GATEWAY_URL`.

**After this lands, one command runs everything:**

```bash
make run-gateway   # port 8000 serves /ws/customer + /asr + /tts
pnpm --filter customer-chat dev
```

## Non-goals

- **Not migrating split mode.** PR #81 uses E2E-adapter (two frontend WebSockets, each carrying a Doubao realtime-dialogue product connection underneath). The split-mode work on `cc-openclaw/feat/voice-split-mode` is a separate follow-up.
- **Not removing cc-openclaw/voice_gateway/ yet.** Keep it as a reference until AutoService's copy is validated in 1–2 full flows, then address it separately.
- **Not reworking the frontend voice architecture.** The PR #81 `VoiceCallController` + `asr-client` / `tts-client` / `audio-playback` stay as-is. Only the URL resolution changes.

## Architecture

**Tech stack:** AutoService's existing FastAPI + uvicorn + websockets. The cc-openclaw gateway is aiohttp; the route handlers get ported to FastAPI WebSocket endpoints. Upstream Doubao clients (`asr_client.py`, `tts_client.py`, `doubao_client.py`, `protocol.py`) are framework-agnostic and copied verbatim (only imports change).

**Landing location:** `channels/web/voice/` — new sibling package under the web channel (voice is a web-channel concern per our three-layer framework; voice clients live in a web customer-chat app, not in Feishu or any plugin).

```
channels/web/
├── app.py              # existing — register /asr and /tts on the same FastAPI app
└── voice/              # NEW
    ├── __init__.py
    ├── asr_route.py    # FastAPI WebSocket endpoint → ASRClient
    ├── tts_route.py    # FastAPI WebSocket endpoint → TTSClient
    ├── asr_client.py   # copied from cc-openclaw (E2E-adapter variant)
    ├── tts_client.py   # copied from cc-openclaw (E2E-adapter variant)
    ├── doubao_client.py
    ├── protocol.py
    └── config.py       # Doubao URL + creds loader
```

**Config:** `DOUBAO_APP_ID` + `DOUBAO_ACCESS_TOKEN` read from environment (already gitignored). The existing `.autoservice/config.local.yaml` is the natural place if we want YAML, but env vars match cc-openclaw's convention and minimize churn. Design choice: **env vars only**, loaded via `channels/web/voice/config.py`.

**Frontend URL resolution:** `resolveVoiceWsUrl` in `App.tsx` currently falls back to `VITE_VOICE_GATEWAY_URL`. Change logic to: if the env var is set, honor it (dev override / separate voice host); otherwise use same-origin `ws://${window.location.host}`. Default dev setup no longer needs `.env.local` for voice.

## Data flow (unchanged from PR #81 conceptually)

```
customer-chat (5173)
    │
    ├── WS /ws/customer ──────── FastAPI (port 8000) ── autoservice.web_gateway
    │
    ├── WS /asr ──────────── FastAPI (port 8000) ── NEW channels/web/voice/asr_route
    │                                                       │
    │                                                       └── ASRClient → Doubao realtime/dialogue
    │
    └── WS /tts ──────────── FastAPI (port 8000) ── NEW channels/web/voice/tts_route
                                                            │
                                                            └── TTSClient → Doubao realtime/dialogue
```

Both `/asr` and `/tts` open their own Doubao dialogue connections (E2E-adapter pattern). No changes to `VoiceCallController` state machine, comfort pool, barge-in logic, or early-comfort optimization — those already work.

## Routes (FastAPI rewrite)

Current aiohttp shape (`asr_route.py`):
```python
async def asr_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ...
```

FastAPI equivalent:
```python
from fastapi import APIRouter, WebSocket

router = APIRouter()

@router.websocket("/asr")
async def asr_endpoint(ws: WebSocket):
    await ws.accept()
    client = ASRClient()
    try:
        await client.connect()
        receive_task = asyncio.create_task(_pump_client_to_ws(client, ws))
        async for message in ws.iter_bytes():
            await client.send_audio(message)
        await receive_task
    finally:
        await client.close()
```

Same pattern for `/tts` (text in → audio frames out). Both endpoints register on the main FastAPI app via `channels/web/app.py`'s existing `include_router(...)` mechanism.

## Dependencies

- `websockets>=12` — already in cc-openclaw's `pyproject.toml`; add to AutoService root.
- No `volcengine-audio` needed (that's for split-mode binary protocol, not this migration).
- No `aiohttp` added — we drop it by rewriting routes to FastAPI.

## CORS

PR #81 needed cc-openclaw to allow origin `http://localhost:5173` because they were cross-origin. Post-migration same-origin, so no CORS-specific config is needed for `/asr` and `/tts`. They inherit whatever `channels/web/app.py` already has for `/ws/customer`.

## Error handling

Port the existing cc-openclaw behavior:
- Missing creds → close WS with 1008, message `"DOUBAO_APP_ID / DOUBAO_ACCESS_TOKEN missing"`.
- Upstream WS dropped → propagate close to frontend (it maps to `asr_dropped` / `tts_dropped` via the onClose handler).
- First audio timeout (15s TTS) → explicit WS close with code 1011.

The frontend `_setError('asr_unreachable' | 'tts_unreachable')` paths already handle these — no frontend changes here.

## Testing

**Unit/integration tests** (ported from cc-openclaw):
- `tests/voice/test_asr_route.py` — FastAPI `TestClient` WS connect, send frames, receive transcript events.
- `tests/voice/test_tts_route.py` — FastAPI `TestClient` WS connect, send text, receive audio frames.
- `tests/voice/test_protocol.py` — pure-Python, framework-free (straight copy).

**Manual smoke test** (one command): `make run-gateway` + `pnpm dev` → click mic → Chinese sentence → comfort plays → CC reply plays → barge-in works.

Frontend Vitest tests do not change — they mock `WebSocket`, not the server.

## Migration sequence

Each step is its own commit:

1. Copy framework-agnostic files from cc-openclaw — `asr_client.py`, `tts_client.py`, `doubao_client.py`, `protocol.py`, `config.py` into `channels/web/voice/` (imports fixed).
2. Port `asr_route.py` from aiohttp to FastAPI WebSocket endpoint.
3. Port `tts_route.py` from aiohttp to FastAPI WebSocket endpoint.
4. Register both endpoints in `channels/web/app.py` (include_router).
5. Port tests to `tests/voice/` using FastAPI `TestClient`.
6. Add `websockets` dep to `pyproject.toml`.
7. Frontend — update `resolveVoiceWsUrl` in `App.tsx` to default to same-origin.
8. Remove `VITE_VOICE_GATEWAY_URL` from `frontend/apps/customer-chat/.env.local` (keep `.env.local.example` pointing to same-origin default).
9. Update `README` / manual test plan — one command startup.

## Risks and fallback

- **FastAPI WebSocket receive semantics differ from aiohttp** (`iter_bytes()` vs `receive()`, close frames). Mitigation: port one route fully with tests before the second.
- **Doubao connection lifecycle** under FastAPI — if a request is cancelled, the upstream WS needs to close too. Mitigation: wrap in `try/finally` and use `anyio.CancelScope` pattern already used elsewhere in the channel.
- **If migration breaks**, we revert by reverting the branch; PR #81 still works against cc-openclaw's backend unchanged.

## Open questions (tracked, not blocking)

- Does voice need its own session module in AutoService (like the CRM session hooks), or is a plain per-WS `ASRClient` enough? Answer for this PR: plain per-WS is enough. If we later want to correlate voice + chat sessions, we add it then.
- Should creds move from env to `.autoservice/config.local.yaml`? Out of scope for this PR (CLAUDE.md already documents both conventions coexisting).
