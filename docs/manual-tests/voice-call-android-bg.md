# Manual test — Voice call Android background/foreground cycle

> **Source**: test-plan-004 · TC-022-014 (background switch recovery)
> **Severity**: P2 — failure is acceptable for MVP provided the user
> sees a clear "disconnected, tap to reconnect" state.

## Why manual

Mobile OS may suspend microphone access and WebSocket traffic when the
browser goes to background. The exact suspension window and the
recovery behavior depend on device hardware, OS power mode, and
active background tasks — cannot be faithfully reproduced by emulators.

## Device matrix

| Device | OS | Chrome | Required? |
|---|---|---|---|
| Pixel 7 (or equivalent) | Android 14 | latest stable | Yes (primary) |
| Samsung Galaxy S22 | Android 13 | latest | Nice-to-have |
| older mid-tier Android | Android 12 | latest | Nice-to-have — tests aggressive power management |

## Prerequisites

- customer-chat served over HTTPS
- cc-openclaw voice service reachable at `https://voice.ezagent.chat`
- Call connects successfully before this test (TC-022-003/004 already green)

## Steps

1. Open `https://chat-staging.ezagent.chat/tenant/<tenant>/chat` on Android Chrome
2. Tap the 📞 FAB and **Start Call** inside the iframe
3. Grant microphone permission
4. Wait for the greeting to finish playing
5. Say one sentence to confirm the bot responds (ASR → TTS working)
6. **Press the Home button** — Chrome goes to background
7. Wait **30 seconds** with the phone on the home screen (do not
   reopen Chrome, do not open another app that grabs the microphone)
8. Return to Chrome (tap the icon or swipe to it)

## Expected

One of the following is acceptable:

| Result | Judgement | Action required |
|---|---|---|
| Call resumes seamlessly — bot still listening, user can speak immediately | ✅ best case | No action |
| Call shows "disconnected, tap to reconnect" with a clear button; tapping reconnects | ✅ acceptable for MVP | Document the observation |
| Call UI is frozen, no error, no reconnect option | ❌ fail | File cc-openclaw side ticket for reconnection |
| Browser crashed / page reloaded | ❌ fail | File OS-specific ticket |

## Evidence to capture

- Screen recording of the full Home → wait → return cycle
- Android `adb logcat` capture if a crash occurs
- Chrome DevTools Network panel shortly after return, to confirm WS state

## Pass / Fail record

| Device | OS | Duration in bg | Result | Notes |
|---|---|---|---|---|
| Pixel 7 | Android 14 | 30s | ☐ | |
| Pixel 7 | Android 14 | 2 min | ☐ | |
| Galaxy S22 | Android 13 | 30s | ☐ | |

## Known gaps (per eval-doc-022 §5 TC-14)

Current `voice_gateway/session.py` implements E2E dialog but has **no
reconnection logic**. MediaStream may be suspended by the OS,
WebSocket can drop. Expect the "disconnected, tap to reconnect"
path to become the shipping behavior unless the cc-openclaw side
implements auto-reconnect.

## Related artifacts

- test-plan-004 · `.artifacts/test-plans/test-plan-voice-call-fab.md`
- eval-doc-022 · `.artifacts/eval-docs/eval-voice-call-fab.md`
- Issue #79 · https://github.com/ezagent42/AutoService/issues/79
