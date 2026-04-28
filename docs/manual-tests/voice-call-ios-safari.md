# Manual test — Voice call on iOS Safari

> **Source**: test-plan-004 · TC-022-012 (AudioContext unlock) + TC-022-013 (autoplay policy)
> **Required before production release** of the customer-chat voice call feature.

## Why this test is manual

iOS Safari has the strictest autoplay and AudioContext policies in any
mainstream browser. Its behavior under iframe embedding cannot be
faithfully simulated by jsdom or headless Chromium — it needs a real
device.

## Device matrix

| Device | OS | Safari | Required? |
|---|---|---|---|
| iPhone (any recent) | iOS 17+ | latest | Yes (primary) |
| iPhone | iOS 16 | bundled | Nice-to-have |
| iPad | iPadOS 17+ | latest | Nice-to-have |

## Prerequisites

- customer-chat served over HTTPS (e.g. `https://chat-staging.ezagent.chat`)
- cc-openclaw voice service reachable at `https://voice.ezagent.chat`
  with `/ws` path correctly routed to voice_gateway
- 豆包 credentials valid; daily quota sufficient for at least 3 calls
- iOS device on a fresh Safari profile (clear Site Settings → Microphone
  for both domains to force the permission prompt)

## TC-022-012 · AudioContext unlock

**Steps**:

1. On the iPhone, open `https://chat-staging.ezagent.chat/tenant/<tenant>/chat`
2. Tap the 📞 button (voice FAB)
3. Inside the iframe, tap **Start Call**
4. Permit microphone when Safari prompts
5. Listen for the greeting voice

**Expected**:
- Microphone prompt appears (not blocked silently)
- After granting, within 3 seconds the greeting "你好，请问有什么可以帮你？" is audible
- `AudioContext.state` transitions to `"running"` (visible in Safari DevTools if connected to a Mac via USB + `develop → <iPhone>`)

**Fail modes to capture**:
- ❌ Microphone prompt doesn't appear → iframe `allow="microphone"` missing OR `Permissions-Policy` header not set on parent
- ❌ Prompt appears but TTS silent → AudioContext stuck in `suspended` state; fix: add "Tap to Start" intermediate button inside the iframe that synchronously calls `audioContext.resume()` in the user click stack

**Pass / Fail record**:

| Device | Safari version | Mic prompt | Greeting audible | Result |
|---|---|---|---|---|
| iPhone 15 Pro | 17.4 | ☐ | ☐ | ☐ |
| iPhone 13 | 17.3 | ☐ | ☐ | ☐ |

## TC-022-013 · Autoplay policy compatibility

Overlaps with TC-022-012: if TC-022-012 passes, TC-022-013 also passes
since TTS is played via the same AudioContext path. Record separately
only if greeting is audible but subsequent TTS chunks are not
(unlikely but possible under iOS memory pressure).

**Pass / Fail record**:

| Device | Greeting plays | Bot response plays | Result |
|---|---|---|---|
| iPhone 15 Pro | ☐ | ☐ | ☐ |

## Evidence

Capture per-device:

- `screenshot-mic-prompt.png` — Safari's permission popup
- `screenshot-call-active.png` — voice modal in talking state
- Screen recording (Control Center → Screen Record) of a full
  one-exchange conversation. Upload to `.artifacts/evidence/voice-ios/`
  or attach to the associated PR.

## Fallback plan if TC-022-012 fails

See eval-doc-022 §6 risk row "iOS Safari AudioContext 解锁". The
mitigation is a cc-openclaw-side change: add a "Tap to Start"
intermediate button inside `voice-web/src/app/page.tsx` that gates
both `new AudioContext()` and `getUserMedia` inside a single
user-activated click handler.

## Related artifacts

- test-plan-004 · `.artifacts/test-plans/test-plan-voice-call-fab.md`
- eval-doc-022 · `.artifacts/eval-docs/eval-voice-call-fab.md`
- Issue #79 · https://github.com/ezagent42/AutoService/issues/79
