---
type: test-diff
id: test-diff-024
status: draft
producer: skill-3
created_at: "2026-04-22"
updated_at: "2026-04-22"
related:
  - test-plan-004
  - eval-doc-022
  - "issue:79"
branch: feat/customer-chat-voice-fab
evidence:
  - "pnpm --filter customer-chat vitest run src/__tests__/{ChatFAB,voice-iframe,VoiceCallModal,VoiceCallModal.postmsg}.test.* → 17/17 green, 804ms"
---

# Test Diff: customer-chat voice call FAB

## Source

- test-plan: `test-plan-004` (`.artifacts/test-plans/test-plan-voice-call-fab.md`, confirmed)
- eval-doc: `eval-doc-022` (`.artifacts/eval-docs/eval-voice-call-fab.md`)
- issue: https://github.com/ezagent42/AutoService/issues/79

## Branch & commits

Branch `feat/customer-chat-voice-fab` off `dev @ bf15f90`:

| SHA | Message |
|---|---|
| `7402616` | docs(artifacts): eval-doc-022 + test-plan-004 for customer-chat voice FAB |
| `68fffea` | feat(customer-chat): voice call FAB + VoiceCallModal + voice-iframe util |
| `06c6b55` | test(customer-chat): TC-022-001/006-011 for voice call FAB (17 new, all green) |
| `efcb450` | docs(voice): manual test templates + E2E TODO for voice call FAB |

## Changes

### New test cases (17 tests in 4 files — all green)

| File | # Tests | TC mapping | Domain |
|------|---------|------------|--------|
| `frontend/apps/customer-chat/src/__tests__/ChatFAB.test.tsx` | 4 | TC-022-001 | FAB click routing |
| `frontend/apps/customer-chat/src/__tests__/voice-iframe.test.ts` | 6 | TC-022-011, 011-b | URL builder + type guard |
| `frontend/apps/customer-chat/src/__tests__/VoiceCallModal.test.tsx` | 5 | TC-022-006, 007, 008 | Modal lifecycle + error paths |
| `frontend/apps/customer-chat/src/__tests__/VoiceCallModal.postmsg.test.tsx` | 2 | TC-022-010 | listener lifecycle, call_id rotation |

### Production code

| File | Action | Purpose |
|---|---|---|
| `frontend/apps/customer-chat/src/components/ChatFAB.tsx` | edit | `<div>📞</div>` → `<button>`; new `onCallClick` prop; `data-testid="voice-fab"` |
| `frontend/apps/customer-chat/src/components/VoiceCallModal.tsx` | new | Fixed-position modal, iframe, state badge, hangup + error fallback paths |
| `frontend/apps/customer-chat/src/lib/voice-iframe.ts` | new | `buildVoiceIframeUrl`, `VoicePostMessage` union, `isVoiceMessage` guard |
| `frontend/apps/customer-chat/src/App.tsx` | edit | `isCallOpen` state; chat/voice mutually exclusive; `voiceCtx` memo |
| `frontend/apps/customer-chat/src/index.css` | edit | `.web-voice-modal*` styles + `.web-fab-call[disabled]` |
| `frontend/apps/customer-chat/.env.example` | new | Documents `VITE_VOICE_WEB_URL` with default |
| `frontend/packages/i18n/src/locales/en.json` | edit | `customer.voice.*` + `customer.chat.openVoice` (8 new keys) |
| `frontend/packages/i18n/src/locales/zh-CN.json` | edit | Same keys, Chinese |

### Placeholders (non-CI)

| File | Action | Purpose |
|---|---|---|
| `frontend/apps/customer-chat/tests-e2e/README.md` | new | TC-022-002/003/004/005/009 gated behind `RUN_VOICE_E2E=1`; no driver chosen yet |
| `docs/manual-tests/voice-call-ios-safari.md` | new | TC-022-012 + TC-022-013 device-test template |
| `docs/manual-tests/voice-call-android-bg.md` | new | TC-022-014 device-test template |

## Test results

### Focused run — the 4 new test files

```
RUN  v1.6.1 /Users/li.zhenyu/workspace/h2os/AutoService/frontend/apps/customer-chat

 ✓ src/__tests__/voice-iframe.test.ts                 (6 tests)   4ms
 ✓ src/__tests__/VoiceCallModal.postmsg.test.tsx      (2 tests)  45ms
 ✓ src/__tests__/ChatFAB.test.tsx                     (4 tests)  59ms
 ✓ src/__tests__/VoiceCallModal.test.tsx              (5 tests)  81ms

 Test Files  4 passed (4)
      Tests  17 passed (17)
   Duration  804ms
```

### Full customer-chat suite — regression check

| Branch | Total | Passed | Failed | Delta |
|---|---|---|---|---|
| dev (baseline) | 99 | 78 | 21 | — |
| feat/customer-chat-voice-fab | 116 | 95 | 21 | **+17 passing, ±0 failing** |

All 21 remaining failures are pre-existing on `dev` and unrelated to the
voice work. Root cause for 20 of 21 is `Unable to find element by
[data-testid="chat-fab"]` / `"fab-call"` — `ChatFAB.tsx` has never
carried either testid on `dev` or on this branch (the 3rd looks up
Chinese text while `setup.ts` initializes i18n with `en`).

The +17 passing delta equals exactly the new test count. **Zero new
regressions; zero incidentally fixed.** Per-test JSON diff confirmed
by skill-4 and recorded in `.artifacts/e2e-reports/e2e-report-voice-call-fab.md`
(§6 and §7).

> **Correction**: an earlier revision of this section reported
> "**+4 passing, −4 failing**" and claimed "Four integration tests
> ...started passing as a side effect of the ChatFAB `<div>` → `<button>`
> change." That was based on a misread single-run summary. The
> structured per-test JSON diff proves the failing-count delta is 0,
> not −4. See e2e-report-016 §3.

**Zero regression introduced.**

## Known gaps (relayed from eval-doc and test-plan)

1. **TC-022-009 fallback copy** — current `voice_gateway/session.py` has
   no code path for channel_server-timeout fallback. Requires a
   cc-openclaw-side PR before the TC can pass.
2. **TC-022-012/013 AudioContext unlock on iOS Safari** — requires a
   real device test; fallback plan (Tap-to-Start in voice-web) is
   documented but not implemented.
3. **TC-022-014 Android background recovery** — no reconnection logic
   in voice_gateway's E2E session; acceptable MVP behavior is the
   "disconnected, tap to reconnect" prompt.
4. **Cloudflare Tunnel `/ws` path routing** — eval-doc-022 §8 preflight
   check remains unverified. `~h2oslabs/.cloudflared/config.yml` is ops-owned
   (not in cc-openclaw code tree), still unreadable here. Local workaround:
   verify UI-layer via `http://localhost:13036` (localhost is a secure-context
   exception, bypasses the tunnel for dev).

## Validation checklist

- [x] Every CI TC from test-plan §5.A and §5.B has a corresponding test function
- [x] All test functions have explicit TC-ID in the description or test name
- [x] Assertion messages are specific (`toMatch(/microphone|麦克风/i)` etc.)
- [x] No hardcoded credentials / ports — `VITE_VOICE_WEB_URL` has fallback
- [x] `beforeEach` cleanup already covered by `setup.ts` (i18n init, afterEach cleanup)
- [x] Naming follows existing vitest conventions (`ComponentName.test.tsx`)
- [x] Syntax + imports resolve (vitest actually ran them)
- [x] No new test file collides with any existing file
- [x] test-diff artifact registered in `.artifacts/test-diffs/`
- [x] Source test-plan-004 status updated to `executed`

## Next step

- Skill 4 (test-runner) can rerun `pnpm --filter customer-chat test` against CI
  infrastructure to confirm the 17/17 green number holds on a clean env
- Human code review of the 3 feature commits (`68fffea`, `06c6b55`, `efcb450`)
- Merge plan: rebase onto `dev` (currently no conflicts), open PR to `dev`
  once the outstanding 21 pre-existing test failures are triaged separately
- Start cc-openclaw side PR for the complementary voice-web changes
  (page.tsx URL query reader, session.py call_id logging, Makefile
  channel-server target, fallback copy for channel_server timeout)

---

*test-diff-024 · customer-chat voice call FAB · draft*
