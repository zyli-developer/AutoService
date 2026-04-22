---
type: e2e-report
id: e2e-report-016
status: executed
producer: skill-4
created_at: "2026-04-22"
updated_at: "2026-04-22"
related:
  - test-diff-024
  - test-plan-004
  - eval-doc-022
  - "issue:79"
gate: pass
---

# E2E Report: customer-chat voice call FAB

## 1. Run metadata

| Field | Value |
|---|---|
| Date | 2026-04-22 |
| Host | darwin 25.2.0 (arm64) |
| Node | v25.9.0 |
| pnpm | 10.20.0 |
| Vitest | 1.6.1 |
| Branch | `feat/customer-chat-voice-fab` |
| HEAD | `cb1f905e0349a77d8966a78048ab4cc7019d8a90` |
| Base | `dev @ bf15f90` |

## 2. Command

```bash
COREPACK_ENABLE_STRICT=0 pnpm --filter customer-chat --config.engine-strict=false \
  exec vitest run --reporter=json --outputFile=/tmp/vitest-branch.json
```

**Why the env override**: repo's `engines.node` requires `>=20 <25`; local Node is v25.9.0. The override is a shell-level bypass and does not modify the repo. Production CI typically pins Node 20 LTS or 22 LTS, where this override is unnecessary.

## 3. Summary (customer-chat only)

| Metric | dev baseline | feat/customer-chat-voice-fab | Delta |
|---|---|---|---|
| Total tests | 99 | 116 | +17 |
| Passed | 78 | 95 | **+17** |
| Failed | 21 | 21 | **±0** |
| Skipped | 0 | 0 | 0 |
| Test files | 14 | 18 | +4 |

The 21 failing tests on the branch are **the same 21 tests** that fail on `dev`. Zero regression. Zero incidental fixes. The +17 delta is exactly the new test count in test-diff-024.

> **Note on earlier claim**: `test-diff-024` (commit `06c6b55`) and the commit message for `06c6b55` asserted "4 pre-existing integration failures incidentally fixed". That number was based on a misread early run and is incorrect. The correct number, verified via per-test diff of structured JSON reports against `dev`, is **0 incidental fixes**. The net improvement is purely the 17 new passing tests. The test-diff will be amended in a follow-up commit; no code needs to change.

## 4. New test cases (17/17 green)

All of these are authored on this branch; none exist on `dev`.

### TC-022-001 · ChatFAB click routing (4 tests, all pass)

| File | Test | Status |
|---|---|---|
| `src/__tests__/ChatFAB.test.tsx` | TC-022-001: clicking the voice FAB fires onCallClick and not onClick | ✅ |
| `src/__tests__/ChatFAB.test.tsx` | renders a real <button> (not a <div>) for the voice FAB | ✅ |
| `src/__tests__/ChatFAB.test.tsx` | disables the voice FAB when onCallClick is not provided | ✅ |
| `src/__tests__/ChatFAB.test.tsx` | chat FAB still fires onClick independently | ✅ |

### TC-022-006/007/008 · VoiceCallModal lifecycle + errors (5 tests, all pass)

| File | Test | Status |
|---|---|---|
| `src/__tests__/VoiceCallModal.test.tsx` | TC-022-006: hangup button fires onClose and iframe unmounts when open flips to false | ✅ |
| `src/__tests__/VoiceCallModal.test.tsx` | TC-022-006: message listener is removed when the modal unmounts | ✅ |
| `src/__tests__/VoiceCallModal.test.tsx` | TC-022-007: NotAllowedError shows the microphone guidance text without a retry button | ✅ |
| `src/__tests__/VoiceCallModal.test.tsx` | TC-022-008: ws_connect_failed shows a "cannot connect" message with a retry button | ✅ |
| `src/__tests__/VoiceCallModal.test.tsx` | iframe carries embed=1 + call_id + ctx params | ✅ |

### TC-022-010 · postMessage listener lifecycle (2 tests, all pass)

| File | Test | Status |
|---|---|---|
| `src/__tests__/VoiceCallModal.postmsg.test.tsx` | TC-022-010: 5x open/close cycles — message listener add/remove counts match, iframe fully torn down each time | ✅ |
| `src/__tests__/VoiceCallModal.postmsg.test.tsx` | rotates call_id on every open (not reusing stale id across calls) | ✅ |

### TC-022-011 / 011-b · URL builder + message guard (6 tests, all pass)

| File | Test | Status |
|---|---|---|
| `src/__tests__/voice-iframe.test.ts` | buildVoiceIframeUrl TC-022-011: omits tenant_id / customer_id when not provided; always sets embed=1 + call_id | ✅ |
| `src/__tests__/voice-iframe.test.ts` | buildVoiceIframeUrl TC-022-011: includes all provided fields | ✅ |
| `src/__tests__/voice-iframe.test.ts` | buildVoiceIframeUrl TC-022-011-b: non-ASCII greeting is URL-encoded and round-trips cleanly | ✅ |
| `src/__tests__/voice-iframe.test.ts` | buildVoiceIframeUrl TC-022-011: empty-string options are treated as absent | ✅ |
| `src/__tests__/voice-iframe.test.ts` | isVoiceMessage accepts known voice message types | ✅ |
| `src/__tests__/voice-iframe.test.ts` | isVoiceMessage rejects unrelated messages | ✅ |

## 5. Pre-existing failures (21 — identical on dev and this branch)

**Root cause in 20 of 21 cases**: integration tests look for `data-testid="chat-fab"` on the chat 💬 button (and `data-testid="fab-call"` on the 📞 button), but `ChatFAB.tsx` has never carried either `data-testid` — neither on `dev` nor on this branch. This branch added `data-testid="voice-fab"` (a different name) on the voice button only. These failures existed before this PR and are unrelated to it.

### Cluster A · `MessageGroup.test.tsx` (5) — misnamed file

File name is `MessageGroup.test.tsx` but the `describe` block is `ChatFAB`. Looks like a copy/paste mistake in the existing suite. All 5 tests fail with `Unable to find an element by: [data-testid="chat-fab"]` or `"fab-call"`.

| Test |
|---|
| `ChatFAB renders the FAB button` |
| `ChatFAB calls onClick when clicked` |
| `ChatFAB adds highlight class when highlight=true` |
| `ChatFAB does not have highlight class when highlight=false` |
| `ChatFAB renders the call button` |

### Cluster B · `MessageList.test.tsx` (3) — wrong locale text

Looks up Chinese text (`欢迎光临`, `套餐 A`, `首页`) while `setup.ts` initializes i18n with **English** (`initGlobalI18n('en')`). Also looks like a mislabeled file (describes `MerchantSite`, not `MessageList`).

| Test |
|---|
| `MerchantSite renders hero section` |
| `MerchantSite renders navigation links` |
| `MerchantSite renders product cards` |

### Cluster C · `integration.test.tsx` (13) — same missing testid

Every failure in this file traces to the same `getByTestId('chat-fab')` lookup.

| Test |
|---|
| `Integration TC-021: full render — FAB visible; after open modal shows; ...` |
| `Integration TC-022: receiving a message frame adds it to the UI` |
| `Integration TC-023: typing indicator appears after send, ...` |
| `TC-034: placeholder message shows streaming cursor` |
| `TC-035: message_edited replaces content in-place, cursor disappears` |
| `TC-036: after message_edited, edited class is visible` |
| `TC-037: 500ms later, edited class disappears` |
| `TC-038: normal message without is_placeholder has no streaming cursor` |
| `TC-057: pushClose non-1000 shows reconnecting banner` |
| `TC-058: wasReconnect flag causes setReplaying on next open` |
| `TC-059: replay_complete removes banner` |
| `TC-060: replayed message does not duplicate existing bubble` |
| `TC-061: 4041_REPLAY_GAP sends history_request; snapshot renders messages` |

## 6. Incidentally fixed (dev fail → branch pass)

**0 tests.** Earlier claim of 4 was incorrect.

## 7. New regressions (dev pass → branch fail)

**0 tests.** Confirmed by diffing per-test outcomes.

## 8. Gate decision: **PASS for this PR**

Criteria:

| Gate criterion | Target | Actual | Pass? |
|---|---|---|---|
| All new TCs from test-plan-004 CI group green | 17/17 | 17/17 | ✅ |
| Zero new regressions (dev-pass → branch-fail) | 0 | 0 | ✅ |
| No pre-existing failure count increase | ≤ 21 | 21 | ✅ |
| New tests have TC-ID mapping back to plan | yes | yes | ✅ |

**Recommendation**: open a PR against `dev`. The 21 pre-existing failures are out of scope for this PR and should be tracked separately.

## 9. Suggested follow-ups (out of scope for this PR)

These would close most of the pre-existing failures with low effort but **do not block this PR**:

1. **Add `data-testid="chat-fab"` to the 💬 button and `data-testid="fab-call"` to the 📞 button** in `ChatFAB.tsx`. This single edit fixes **18 of 21** pre-existing tests (5 in MessageGroup.test.tsx + 13 in integration.test.tsx). Estimated effort: 5 minutes. Recommend filing a separate issue.
2. **Rename misnamed test files**: `MessageGroup.test.tsx` → `ChatFAB.test-legacy.tsx` (or merge into the new `ChatFAB.test.tsx`); `MessageList.test.tsx` → `MerchantSite.test.tsx`. Also fix the Chinese-text lookups to use the i18n key lookup pattern. Estimated effort: 30 minutes.
3. **Cleanup**: the existing `MessageGroup.test.tsx` has duplicate coverage with the new `ChatFAB.test.tsx` on this branch. After items 1+2, consider deleting the legacy tests to avoid drift.

None of these are done by this skill because they would expand the PR beyond test-plan-004. Recommend filing a dedicated `test/` cleanup issue.

## 10. Evidence manifest

| File | Purpose |
|---|---|
| `/tmp/vitest-branch.json` | Full structured vitest report for `feat/customer-chat-voice-fab @ cb1f905` |
| `/tmp/vitest-dev.json` | Full structured vitest report for `dev @ bf15f90` |
| `/tmp/failing-tests.txt` | Extracted failing test names with first-line failure messages |

These are ephemeral local files (not committed). The structured JSON can be reproduced by re-running the commands in §2 on each branch. In CI this would be captured as build artifacts; for the current MVP we keep them at the `/tmp/` level for auditability during review.

## 11. Known limitations of this run

- Local developer machine (darwin 25.2.0, Node 25) — not a real CI container. The 21 pre-existing failures are deterministic (text / testid lookups), so environment differences are unlikely to flip them, but a fresh CI run is still recommended as the canonical gate.
- E2E group (TC-022-002/003/004/005/009) was **not executed** — they are gated behind `RUN_VOICE_E2E=1` and require live `voice_gateway` / `channel_server` / 豆包 credentials. Per test-plan-004, these TCs remain in `.artifacts/test-diffs/test-diff-voice-call-fab.md` as TODO; their readiness is tracked by eval-doc-022 §8 preflight check.
- Manual group (TC-022-012/013/014) was not executed — these are real-device tests. Templates at `docs/manual-tests/voice-call-{ios-safari,android-bg}.md` are to be filled in before production release.

---

*e2e-report-016 · customer-chat voice call FAB · executed · gate: PASS*
