# Customer-chat Native Voice — Manual Test Plan

**Linked design:** `2026-04-23-customer-chat-native-voice-design.md`
**Linked implementation plan:** `2026-04-23-customer-chat-native-voice.md`
**Branch:** `feat/customer-chat-voice-fab`
**Scope:** manual acceptance tests that can't be automated in Vitest — real mic, real cc-openclaw backend, real mobile browsers.

---

## Setup

### 1. Start cc-openclaw voice gateway

```bash
cd D:/workspace/zhidaoyuan/cc-openclaw
ALLOWED_ORIGINS="http://localhost:5173" \
VOLCENGINE_API_KEY=<your dev key> \
GATEWAY_PORT=8089 \
python voice_gateway/server.py
```

Expect: `Starting voice gateway on :8089` in logs. No errors.

### 2. Start AutoService customer-chat dev server

Terminal B:
```bash
cd D:/workspace/zhidaoyuan/AutoService
VITE_VOICE_GATEWAY_URL=http://localhost:8089 make run-web
```

Or directly:
```bash
cd frontend/apps/customer-chat
# Write env into .env.local (inline `VAR=value pnpm dev` is flaky on Windows bash)
echo "VITE_VOICE_GATEWAY_URL=http://localhost:8089" > .env.local
pnpm dev
```

Expect: `http://localhost:5173` serves the customer-chat SPA.

### 3. Open the chat

Browser: `http://localhost:5173/tenant/<your-test-tenant>/chat`

Chat widget should render in the bottom-right. On mobile viewports it opens automatically.

---

## Desktop — Chrome (HTTPS or localhost)

### TC-DESKTOP-01 — Full happy-path turn
1. Open chat, click 💬 FAB.
2. Click 🎤 mic button in composer.
3. Browser requests mic permission → **Allow**.
4. Expect: composer disables, status bar shows `正在聆听…`.
5. Say `这款多少钱？`.
6. Expect: within ~2s, a user bubble `这款多少钱？` appears.
7. Expect: status bar switches to `让我想想…` and a short comfort TTS plays (`嗯，我看看...` or similar from pool).
8. Wait for CC reply. Bot bubble appears. TTS plays the reply.
9. After TTS finishes, status bar returns to `正在聆听…`.
10. Click **挂断**. Status bar disappears, composer re-enables.

**Pass criteria:** all steps complete within expected timing. No console errors.

### TC-DESKTOP-02 — Mic permission denied
1. Fresh browser profile (or site permissions cleared).
2. Click 🎤 → browser prompt → **Block**.
3. Expect: status bar shows `🎤 麦克风被拒绝` (red background).
4. Expect: hint bubble / text is visible explaining how to re-enable.
5. Click **重试** → permission prompt does NOT reappear (browser remembers block). Status bar stays in error.
6. Manually clear permission in browser settings → click **重试** → flow recovers.

### TC-DESKTOP-03 — Skip button mid-reply
1. Start call, speak a question that elicits a long reply (e.g., `介绍一下你们的产品`).
2. During TTS playback of the reply, click **跳过**.
3. Expect: audio stops immediately (no fade beyond the 50ms crossfade).
4. Expect: status bar returns to `正在聆听…`.
5. Expect: the full bot text is still in the chat stream (not truncated visually).

### TC-DESKTOP-04 — Gateway down (asr unreachable)
1. Stop the voice_gateway server.
2. Click 🎤.
3. Expect: status bar shows `语音服务连接失败` (red) with **重试** button.
4. Start server again → click **重试** → flow recovers.

### TC-DESKTOP-05 — Network drop mid-call
1. Start call; during `listening` state, disable WiFi or use browser DevTools → Network → Offline.
2. Expect: status bar shows reconnecting / error indication.
3. Re-enable network → click retry / restart.
4. Expect: chat stream from before disconnect is preserved.

### TC-DESKTOP-06 — 30s silence — Volcengine behavior probe
1. Start call; don't speak for 30s.
2. Observe: does Volcengine send a spurious `final` event on silence?
3. If yes: the controller should transition to `thinking` with empty-ish text. Verify this doesn't cause a crash or loop; verify `onSendTextToChat` isn't called with empty string.
4. If the probe surfaces real brokenness, capture and file a bug.

### TC-DESKTOP-07 — Long CC reply (>500 chars)
1. Ask something like `请详细说明你们的所有产品和价格`.
2. Observe perceived latency between ASR-final and first TTS audible.
3. Observe whether comfort text fully covers the waiting time.
4. Pass criteria: no audible gap between comfort finishing and formal reply starting; no click/pop at the boundary.

### TC-DESKTOP-08 — CC returns English
1. Ask a question in English: `what is your return policy?` (set i18n to en or speak English).
2. Verify: ASR captures English correctly.
3. Verify: CC reply arrives in English; TTS pronounces English — **if pronunciation is severely broken**, flag the follow-up item documented in design §Known Follow-ups (voice-language binding).

### TC-DESKTOP-09 — Multiple turns, context preserved
1. Turn 1: `给我看看你们的 iPhone`.
2. Wait for reply.
3. Turn 2: `那个多少钱？`.
4. Pass criteria: bot correctly understands "那个" = iPhone (proves context sharing via /ws/chat works).

### TC-DESKTOP-10 — Hangup during `thinking`
1. Start call, speak.
2. Immediately after ASR final, click **挂断** (before comfort finishes).
3. Expect: audio stops, state → idle.
4. Expect: CC reply that was already in-flight lands as a normal text message in chat stream after hangup (no voice playback, just text).

### TC-DESKTOP-11 — Composer disabled during call
1. Start call.
2. Try to click in the text input area.
3. Expect: textarea is disabled (cursor doesn't appear), send button is disabled, image/attach/emoji buttons are disabled.

### TC-DESKTOP-12 — Browsers
Repeat TC-DESKTOP-01 on:
- Chrome (latest stable)
- Safari (latest stable, macOS)
- Firefox (latest stable)

Edge cases per browser:
- Firefox: verify AudioWorklet loading doesn't produce CSP warnings
- Safari: verify first-click unlocks AudioContext cleanly (no silent first playback)

---

## Mobile

### TC-MOBILE-01 — iOS Safari (iPhone, iOS 17+, HTTPS)
1. Serve customer-chat over HTTPS (use a tunnel like ngrok with an HTTPS upstream if local).
2. Open in iOS Safari.
3. Tap mic button.
4. Expect: iOS mic permission prompt → Allow.
5. Expect: status bar appears, first AudioContext unlocks on tap.
6. Speak, expect TTS playback audible (not silent).

### TC-MOBILE-02 — iOS Safari lock-screen
1. Start call.
2. Lock the phone (side button).
3. Unlock phone.
4. Expect: status bar shows "通话已暂停 · 点此继续" OR call auto-hung-up to `idle` (visibility change behavior).
5. Verify no mic indicator stays active after hangup.

### TC-MOBILE-03 — Android Chrome background
1. Start call on Android device.
2. Switch apps (home button + another app).
3. Return to browser.
4. Expect: call auto-hung-up (visibilitychange = 'hidden' triggers hangup).
5. Chat stream preserved.

### TC-MOBILE-04 — Keyboard overlap
1. Rotate phone to portrait (or use small viewport).
2. Click text input to open keyboard.
3. Start a voice call.
4. Observe: status bar position vs. keyboard — is the status bar still visible or occluded?
5. This is a known deferred concern (design doc §8); document what you see.

### TC-MOBILE-05 — Non-HTTPS detection
1. Serve via plain HTTP (not HTTPS, not localhost) on mobile.
2. Open in mobile browser.
3. Expect: 🎤 mic button is grayed out. Tap it → hover tooltip / title says `当前环境不支持语音` (or English equivalent).

---

## Post-launch observation items

Capture in a log after real users start using the feature:

1. **Batch-CC latency p50/p95** — if p95 > 5s, consider enabling CC streaming (see design §Known Follow-ups).
2. **Comfort text repetition complaints** — if user complaints surface, expand comfort pool.
3. **Barge-in demand** — if users try to interrupt mid-reply by speaking (and are frustrated that it doesn't work), upgrade to auto-barge-in (speech_started hook is ready).
4. **Mixed-language utterances** — track TTS mispronunciation on bilingual replies; if frequent, add per-utterance language detection.

---

## Verification sign-off

- [ ] All TC-DESKTOP-01 through TC-DESKTOP-12 pass on Chrome
- [ ] TC-MOBILE-01 passes on iOS Safari
- [ ] TC-MOBILE-03 passes on Android Chrome
- [ ] TC-MOBILE-05 passes (feature-detect grays out mic on HTTP)
- [ ] No console errors in happy-path turn
- [ ] No hung mic indicators after hangup
- [ ] Voice + text messages visible in the same chat stream in persistence check (refresh page mid-session)
