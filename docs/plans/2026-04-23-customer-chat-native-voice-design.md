# Customer-chat Native Voice — Design

**Date:** 2026-04-23
**Branch:** `feat/customer-chat-voice-fab`
**Status:** approved (brainstorming complete, ready for writing-plans)
**Supersedes:** prior iframe-based integration (VoiceCallModal + voice-iframe.ts) on same branch

## 1. Context

The `feat/customer-chat-voice-fab` branch shipped an iframe-based voice integration that opens `cc-openclaw/voice-web` in a floating modal above the customer-chat widget. The voice stack (ASR + LLM + TTS) all runs inside cc-openclaw; AutoService just forwards tenant/customer context via iframe URL params and relays `postMessage` state.

This design replaces that integration with an **in-widget native voice** experience:

- Voice entry point is a mic button **inside** the chat composer icon row (alongside image/attach/emoji).
- No iframe, no separate modal. Voice state renders inside the existing chat widget.
- ASR-recognized user speech and AI text replies appear as **real chat messages** in the same conversation as text input — voice is an I/O modality on top of the existing text chat, not a parallel channel.
- cc-openclaw is reduced from a full "voice app" to two stateless audio-I/O services: `WS /asr` and `WS /tts`. AutoService CC remains the only LLM.

## 2. Architecture

### 2.1 Three-party topology

```
┌──────────────────────────────────┐
│  customer-chat frontend (React)  │  ← sole orchestrator
│                                  │
│  ┌────────────────────────────┐ │
│  │  VoiceCallController       │ │   state machine
│  │  - mic capture pipeline    │ │
│  │  - comfort-text scheduling │ │
│  │  - playback control        │ │
│  └──┬──────────────┬──────────┘ │
│     │              │             │
│  [WS /asr]    [WS /chat]         │
│  [WS /tts]                       │
└─────┼──────────────┼─────────────┘
      │              │
      ▼              ▼
┌──────────────┐ ┌──────────────────┐
│ cc-openclaw  │ │ AutoService      │
│ voice_gateway│ │ /ws/chat         │
│ (stateless)  │ │ → cc_pool        │
│ /asr /tts    │ │ (unchanged)      │
└──────────────┘ └──────────────────┘
```

### 2.2 Key architectural decisions

| Decision | Choice | Rationale |
|---|---|---|
| Who orchestrates | **Browser** | cc-openclaw stays application-agnostic; keeps future reuse by other L2 apps open |
| cc-openclaw role | **Stateless ASR + TTS endpoints** | SplitSession / ActorBridge stays for cc-openclaw's own voice-web; our two new endpoints don't touch them |
| AutoService CC | **Zero change** | `include_partial_messages=False` remains; voice loops through the same `/ws/chat` that text chat uses |
| Context sharing | **Free — voice goes through the same /ws/chat as text** | The CC sees a single continuous conversation; no session-linkage code needed |
| Latency strategy | **Comfort-text filler** (no streaming in MVP) | `/ws/chat` is batch today; enabling streaming is ~60 LOC across 4 files — defer until data shows it's needed |
| Barge-in | **Explicit skip button** (reuse `clearPlayback()`) | MVP cheap; leave Volcengine `speech_started` event transit as hook for future auto-barge-in |
| Language | **Passthrough — no session-level lang param** | TTS synthesizes whatever CC returned; status-bar UI follows customer-chat locale |
| Mobile | **Feature-detect + graceful degrade** | Gray mic button with tooltip when HTTPS / getUserMedia unavailable |

### 2.3 Migration shape — delete + add + modify

**Delete:**
- `frontend/apps/customer-chat/src/components/VoiceCallModal.tsx`
- `frontend/apps/customer-chat/src/utils/voice-iframe.ts`
- Voice FAB branch in `ChatFAB.tsx` (only the chat 💬 FAB remains)
- `VITE_VOICE_WEB_URL` from `.env.example`
- 17 iframe-related tests (TC-022-001, 006–011 and siblings)

**New (see §3 for detail):**
- Frontend: `voice/` folder (~450 LOC) + 1 AudioWorklet in `public/`
- Backend: `voice_gateway/asr_route.py` + `voice_gateway/tts_route.py` + routing in `server.py` (~120 LOC)

**Modify:**
- `ChatInput.tsx` — add mic button (4th composer icon)
- `App.tsx` — remove iframe state; mount `VoiceStatusBar` + wire `useVoiceCall` hook
- `ChatModal.tsx` — slot for status bar above message list
- i18n locales — ~10 new strings + comfort-text pool

## 3. Components

### 3.1 Frontend (`frontend/apps/customer-chat/`)

| File | Responsibility | LOC |
|---|---|---|
| `src/voice/VoiceCallController.ts` | State machine + pipeline orchestration | ~180 |
| `src/voice/useVoiceCall.ts` | React hook exposing controller state | ~40 |
| `src/voice/VoiceStatusBar.tsx` | Top bar: state text, skip button, hangup button, error state, permission-hint bubble | ~100 |
| `src/voice/audio-capture.ts` | Ported from `cc-openclaw/voice-web/src/lib/audio-capture.ts` | ~50 |
| `src/voice/audio-playback.ts` | Ported from cc-openclaw; includes `clearPlayback()` | ~75 |
| `src/voice/asr-client.ts` | WS client for `/asr` | ~50 |
| `src/voice/tts-client.ts` | WS client for `/tts`; supports abort | ~60 |
| `src/voice/capability.ts` | HTTPS + `navigator.mediaDevices` detection | ~20 |
| `public/pcm-processor.js` | AudioWorklet processor (20ms frames, 16kHz → int16) | ~30 |

### 3.2 Backend (`cc-openclaw/voice_gateway/`)

| File | Responsibility | LOC |
|---|---|---|
| `server.py` (patch) | Mount `WS /asr` and `WS /tts` routes; add CORS middleware | ~20 |
| `asr_route.py` (new) | Thin: accept browser WS, proxy to `ASRClient`, forward partial/final + `speech_started` events | ~50 |
| `tts_route.py` (new) | Thin: accept `{speak,text}` / `{abort}`, proxy to `TTSClient`, stream PCM | ~50 |
| `config.py` (patch) | `ALLOWED_ORIGINS` env var | ~5 |

### 3.3 State machine (`VoiceCallController`)

```
idle ──(click mic)──► preparing
preparing ──(mic ok + ws ok)──► listening
preparing ──(mic denied / ws fail)──► error

listening ──(ASR final)──► thinking
thinking ──(comfort TTS starts)──► thinking (still)
thinking ──(CC reply + formal TTS)──► speaking
speaking ──(TTS done)──► listening
speaking ──(user click skip)──► listening
*        ──(user click hangup)──► ending ──► idle
*        ──(network / upstream error)──► error ──(click retry)──► preparing
```

## 4. Data flow

### 4.1 Protocol: `WS /asr`

**Browser → Server**
| Kind | Payload | When |
|---|---|---|
| text | `{"type":"start"}` | After connect, opens Volcengine ASR session |
| binary | raw PCM-S16LE, 16kHz, 20ms frames (640 bytes) | Continuous while mic is on |
| text | `{"type":"stop"}` | Before graceful disconnect |

**Server → Browser**
| Kind | Payload | Purpose |
|---|---|---|
| text | `{"type":"partial","text":"..."}` | Interim transcript (optional display) |
| text | `{"type":"final","text":"..."}` | **Turn-end signal** — browser triggers next step |
| text | `{"type":"speech_started"}` | Volcengine VAD event (reserved for auto-bargein; MVP logs only) |
| text | `{"type":"error","message":"..."}` | Upstream error |

### 4.2 Protocol: `WS /tts`

**Browser → Server**
| Kind | Payload |
|---|---|
| text | `{"type":"speak","text":"..."}` |
| text | `{"type":"abort"}` |

**Server → Browser**
| Kind | Payload |
|---|---|
| binary | PCM-S16LE, 24kHz chunks |
| text | `{"type":"done"}` |
| text | `{"type":"error","message":"..."}` |

### 4.3 Protocol: `/ws/chat` (AutoService, unchanged)

- Browser → Server: `{"type":"user_text_submit","text":"..."}`
- Server → Browser: `{"type":"bot_text_delta","content":"..."}` + `{"type":"done"}`

### 4.4 Turn timeline (example: "这款多少钱？")

```
t=0ms      click mic
           ├── new AudioContext() (user-gesture)
           ├── getUserMedia({audio:16kHz,mono,echo+noise})
           ├── connect /asr WS → {"type":"start"}
           ├── connect /tts WS
           └── state → listening; ChatInput → disabled

t=2400ms   /asr → {"type":"final","text":"这款多少钱？"}
           ├── state → thinking; VoiceStatusBar shows "让我想想…"
           ├── insert user bubble into ChatModal message list
           ├── /ws/chat → {"type":"user_text_submit","text":"这款多少钱？"}
           └── /tts speak with random comfort from pool

t=2500ms   /tts begins streaming PCM → audio-playback.enqueue()

t=3200ms   /tts → {"type":"done"} (comfort finished)
           └── silence-hold until CC replies

t=5800ms   /ws/chat → {"type":"bot_text_delta","content":"..."}
           ├── state → speaking; skip button appears
           ├── insert bot bubble into ChatModal
           └── /tts speak(CC reply)

t=6100ms   /tts begins streaming formal reply

t=12000ms  /tts done → state → listening
```

### 4.5 Comfort / formal-reply handoff rules

- Comfort TTS **starts the instant** `ASR final` arrives — never wait for CC.
- If comfort finishes **before** CC reply arrives → hold in silence (status bar stays "让我想想…").
- If CC reply arrives **while** comfort is still playing → enqueue and wait for comfort's `done` before starting formal TTS (do not interrupt ourselves).
- Modeled as a two-promise join in `VoiceCallController`.

### 4.6 Context sharing — the architectural payoff

Voice each-turn flow:
```
ASR final text  →  /ws/chat user_text_submit  →  AutoService CC
bot_text_delta  →  render + /tts speak
```

The CC sees **exactly the same chat history** whether the user typed or spoke. "Tell me about the red one" after "I want an iPhone" works identically across modes. No session-linkage code, no chat-id plumbing.

## 5. Error handling

### 5.1 Error matrix

| Scenario | Detection | Recovery | Status-bar display |
|---|---|---|---|
| Mic permission denied | `getUserMedia` reject (`NotAllowedError`) | Not auto-recoverable; guide user to browser settings | 🔴 "🎤 麦克风被拒绝" + expandable hint bubble |
| Non-HTTPS / no getUserMedia | `capability.ts` at startup | Mic button grayed from the start | Gray button + hover tooltip |
| `/asr` initial connect fails | WebSocket error/close on open | "Retry" button → back to `preparing` | 🔴 "语音服务连接失败 · 重试" |
| `/tts` initial connect fails | Same | Same | 🔴 Same |
| `/asr` drops mid-call | `onclose` | 1 auto-reconnect attempt; then error | Transient "重新连接中…"; fail → 🔴 "连接中断 · 重试" |
| `/tts` drops mid-call | Same | Current reply's remaining audio lost; reconnect next turn | 🔴 "语音中断 · 重试" (chat stream preserved) |
| `/ws/chat` CC timeout (>30s) | Frontend `setTimeout` | Play fallback TTS: "抱歉我走神了，请再说一次？" → listening | Amber "响应超时，请重试" |
| Volcengine ASR upstream error | `{type:"error"}` from server | Same as `/asr` drop | 🔴 "语音识别异常 · 重试" |
| Volcengine TTS upstream error | `{type:"error"}` from server | Degrade to text-only (reply already in chat) → back to listening | Orange "语音播放失败，请查看文字" (2s) |
| AudioContext suspended (iOS backgrounded) | `state === 'suspended'` poll | Foreground → `resume()`; fail → ask user to tap "继续" | Gray "通话已暂停 · 点此继续" |
| User hangs up mid-ending | State-machine guard | Mic button disabled in `ending` state | — |
| Rapid double-click on mic | Controller idempotency | Second click in `preparing` no-ops | — |

### 5.2 Edge cases — explicit decisions

1. **Network drop while user is speaking** — in-flight PCM dropped; during reconnect, mic continues sampling but discards frames (avoid backlog). After reconnect, status shows "网络恢复，请重新说一遍" (do not retroactively backfill audio).

2. **Comfort still playing when CC errors** — comfort finishes normally → then error state. The user bubble (inserted on ASR final) already shows in the chat stream, so the user has a visual record.

3. **CC reply arrived but `/tts` is broken** — text reply shown as normal chat bubble; orange toast "语音播放失败，请查看文字" for 2s → back to listening. Do **not** exit the call.

4. **User hangs up during `thinking`** — abort comfort TTS; the CC request is already in-flight and will land as a text message in the chat stream after hangup. Controller goes `ending → idle`.

5. **Tab backgrounded / minimized** — on `visibilitychange` to `hidden`: **actively hang up**. Avoids hidden-mic-recording concerns. Chat stream preserved; user taps mic again to resume (new WS session; full context still in `/ws/chat`).

6. **Multiple tabs with active calls** — MVP does not lock. If observed in production, add `sessionStorage` mutex.

7. **Auto-barge-in hook preserved** — `/asr` forwards `speech_started` events; controller logs only in MVP. Future upgrade: in `speaking` state, trigger `clearPlayback()` + `/tts abort` + transition to `listening`. Estimated +15 LOC.

### 5.3 Observability

| Signal | Where |
|---|---|
| State transitions | `console.debug('[voice]', from, to, reason)` + optional analytics hook |
| WS connect/first-byte/close timing | `/asr` and `/tts` access logs with `session_id` (uuid4) |
| Upstream error stack | aiohttp exception handler logs |

**Not captured:** raw audio (privacy); full transcripts (already persisted via `/ws/chat` in AutoService conversation storage).

### 5.4 Security & privacy

| Item | Handling |
|---|---|
| Mic permission | Native browser prompt; no custom wrapper |
| Transport | wss:// in production; Volcengine credentials server-side only |
| Cross-origin | CORS allowlist in cc-openclaw (`ALLOWED_ORIGINS` env) |
| Recording notice | Deferred to product/legal decision pre-launch |

## 6. Testing strategy

### 6.1 Unit tests (Vitest)

- `VoiceCallController` — all state transitions, guards, error branches (~15 tests)
- `asr-client.ts` — frame parsing, partial/final/error dispatch (~6)
- `tts-client.ts` — binary/text demux, abort signal (~5)
- `audio-capture.ts` — PCM format (mocked AudioWorkletNode) (~3)
- `audio-playback.ts` — enqueue scheduling, `clearPlayback` silences everything (~5)
- `capability.ts` — HTTPS, `getUserMedia` presence, tooltip strings (~4)
- Comfort-text pool — no-repeat-last-3 policy (~2)

### 6.2 Integration tests (React Testing Library)

- Click composer mic → status bar appears, composer disables
- Skip button → `clearPlayback` invoked, state returns to `listening`
- Hangup → all WS closed, AudioContext closed, state back to `idle`
- CC reply arrives → message bubble inserted, `/tts speak` sent
- Mic permission denied → red status bar + hint bubble rendered
- Non-HTTPS environment → mic button grayed, tooltip shown

### 6.3 Backend tests (`cc-openclaw/voice_gateway/tests/`)

- `/asr` accepts WS, forwards Volcengine events (mock upstream)
- `/asr` forwards `speech_started` (verify event shape)
- `/tts` `speak` + `abort` correctly terminates synthesis
- CORS only permits allowlisted origins

### 6.4 Manual test plan

Recorded separately at `docs/plans/manual-test-plans/2026-04-23-customer-chat-native-voice.md` (or similar). Covers:

**Desktop (Chrome, Safari, Firefox):**
- First-time mic grant → deny → re-grant → permission-hint flow
- Mid-call network drop → reconnect indication
- 30s silence → Volcengine false-positive final? (observe)
- Long CC reply (500+ chars) → user perception of wait (validates 4b=B+Comfort assumption)
- CC returns English → does TTS speak it? (Q7 follow-up)
- Comfort still playing when CC reply arrives → smooth handoff, no click/pop

**Mobile:**
- iOS Safari HTTPS: mic → AudioContext unlock → record → playback
- iOS lock-screen → unlock (expects suspended → error)
- Android Chrome background → foreground (expects auto-hangup)
- iOS/Android keyboard up → does status bar stay visible?

### 6.5 Tests deleted (not migrated)

17 iframe-scoped tests (TC-022-001, 006–011 and neighbors) validate `postMessage` protocol and `VoiceCallModal` — both gone. New tests cover the native surface.

## 7. Acceptance criteria

### 7.1 Must pass
- [ ] Desktop Chrome HTTPS: full turn — "click mic → speak → ASR final → comfort plays → CC reply → formal TTS → back to listening"
- [ ] iOS Safari HTTPS: same scenario
- [ ] Mic denied → red status bar + hint bubble
- [ ] Non-HTTPS local env: mic button grayed + tooltip
- [ ] Skip during TTS: instant silence + back to listening
- [ ] Hangup: all WS close, AudioContext close, no leak (DevTools Performance)
- [ ] Voice-generated user/bot messages persist via `/ws/chat` (survive refresh)
- [ ] Context sharing: type "how much is this one" → speak "what color" → CC resolves "this one" correctly
- [ ] Unit + integration tests green
- [ ] Old iframe code deleted; `npm run build` passes; only chat 💬 FAB remains

### 7.2 Performance baseline
- [ ] Desktop: **ASR final → comfort plays ≤ 200ms**
- [ ] Desktop: **CC reply arrives → formal TTS plays ≤ 500ms** (comfort → formal with no audible gap)
- [ ] Mobile 4G: relaxed to 500ms / 1000ms

### 7.3 Observability
- [ ] Frontend `console.debug('[voice]', ...)` at every state transition
- [ ] Backend `/asr` and `/tts` logs include `session_id`, `connect_ms`, `duration_ms`

### 7.4 Explicitly out of scope (post-ship decisions)
- [ ] Auto barge-in (hook reserved via `speech_started` forwarding)
- [ ] CC streaming (`include_partial_messages=True`) — second phase
- [ ] Audio recording / session archival — product decision
- [ ] Multilingual TTS voice switching — observe real zh/en mix usage

## 8. Known follow-ups

- **TTS voice-language binding** — Volcengine TTS `voice` parameter is typically language-bound; mixed zh/en CC replies may pronounce poorly on a single voice. Record actual occurrence rate post-launch; if significant, add per-reply language detection + voice switch (~40 LOC).
- **Mobile status-bar positioning with keyboard** — deferred to implementation; may need `visualViewport` API if status bar obscured.
- **Auth on `/asr` and `/tts`** — currently open (CORS + network isolation only). Add token auth when multi-tenant deployment requires it.

## 9. Brainstorming Q&A (for traceability)

| # | Question | Choice |
|---|---|---|
| 1 | Transcript rendering | C — top status bar + transcript bubbles stream into chat |
| 2 | Composer during call | A — disabled |
| 3 | Mic UX | A — toggle / call-style |
| 4 | Context sharing | D — browser-orchestrated (auto-shared via `/ws/chat`) |
| 4a | cc-openclaw change | B — new thin `/asr` + `/tts` endpoints |
| 4b | AutoService CC streaming | B + Comfort — no streaming now; comfort-text filler masks batch latency |
| 5 | Error UX | A — red top status bar + inline hint for permission case |
| 6 | Barge-in | C — explicit skip button (reuse `clearPlayback()`); auto-bargein path preserved via `speech_started` hook |
| 7 | i18n | Passthrough — no session-level lang param; TTS plays whatever CC returned |
| 8 | Mobile | B — feature-detect HTTPS + getUserMedia; gray button when unavailable |
