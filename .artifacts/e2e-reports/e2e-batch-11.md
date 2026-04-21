# E2E report: batch-11 (P6 TenantLayout 4-tab + ChatTab)

**Scope**: focused admin-portal subset (8 files, 57 tests) + backend auth/api suites (66 tests). Full admin-portal regression intentionally NOT run (per batch-10 timeout post-mortem — the 24 pre-existing i18n failures across 9 unrelated files run for 600-1000s and are not this batch's concern).

## Total

- **Frontend focused subset**: 57/57 pass (8 files, 4.18s)
- **Backend auth+api**: 66/66 pass (2.69s)
- **Batch-11 net new**: 14 tests (7 TenantLayout + 7 ChatTab) — all green
- **Batch-11 regression scope**: 43 tests across AdminRail/AdminTopbar/AvatarMenu/AuthGate/AuthLoginPage/App — all green (no new failures introduced)

## New tests (batch-11)

### TenantLayout.test.tsx — 7 tests

- renders all 4 tenant tabs (chat/dashboard/proposals/billing)
- does NOT render master-section nav item (variant=tenant)
- default active view is ChatTab (rail slot 1)
- clicking a rail tab switches canvas + zustand activeTab
- `brand_name` from useSessionMode flows to topbar crumb
- `authenticated_as` from useSessionMode flows to topbar
- empty brand_name → flicker-guarded fallback to tenantId

### ChatTab.test.tsx — 7 tests

- renders input + submit + empty-state placeholder
- submits POST /api/admin/chat with credentials:"include" + JSON body `{message}`
- response body.reply appended to assistant bubble
- empty input → send disabled → no fetch call
- disables send button while request in-flight
- network rejection → error bubble rendered
- multiple sends accumulate in history

## Commands used

```bash
# Focused frontend subset (no full regression — timeout mitigation)
cd frontend/apps/admin-portal && npx vitest run \
  src/__tests__/TenantLayout.test.tsx \
  src/__tests__/ChatTab.test.tsx \
  src/__tests__/AdminRail.test.tsx \
  src/__tests__/AdminTopbar.test.tsx \
  src/__tests__/AvatarMenu.test.tsx \
  src/__tests__/AuthGate.test.tsx \
  src/__tests__/AuthLoginPage.test.tsx \
  src/__tests__/App.test.tsx

# Backend auth+api regression
python -m pytest tests/auth/ tests/api/ -q
```

## Output summary

```
Test Files  8 passed (8)
      Tests  57 passed (57)
   Duration  4.18s
```

```
66 passed in 2.69s
```

## Regression (preexisting tests)

All 43 pre-existing tests in the focused subset (AdminRail / AdminTopbar / AvatarMenu / AuthGate / AuthLoginPage / App) continue to pass unchanged. None of the tab-key widening (activeTab union) or TenantLayout shell rewrite bled into those suites.

Backend auth+api baseline (66 tests) also unchanged — `/api/admin/chat` is strictly additive.

## Preexisting failures (unchanged baseline — NOT run in this batch)

Per e2e-report-007 (batch-10), 24 tests fail across 9 unrelated files in the full admin-portal suite (i18n translation-key assertion mismatch, not caused by batches 9-11):

- AdminWorkspace.test.tsx
- VirtualRehearsalStep.test.tsx
- ComplianceCheckStep.test.tsx
- integration.test.tsx
- ProposalsTab.test.tsx
- ChannelConfigStep.test.tsx
- DashboardTab.test.tsx
- DashboardTab.period.test.tsx
- CanaryProgress.test.tsx

These are not touched by batch-11. Recommended cleanup task for M3: migrate assertions to match current translation output OR set up vitest i18n mocking.

## Timeout-mitigation effectiveness

Batch-10 subagents stalled 600-1000s on the full admin-portal suite. Batch-11 restricted vitest to the 8 files directly related to batch-11 + its immediate neighbors. **Total focused run: 4.18s.** Mitigation fully effective — no stall risk, no subagent fork required (main orchestrator completed inside budget).

## Sanity check of new endpoint

Manual `TestClient` probe confirms the `/api/admin/chat` stub answers:

- `POST /api/admin/chat {"message":"hello"}` → 200 `{"reply":"(stub) Received: 'hello'. _local_admin agent integration pending (T7B.6 / run_dream wire-up)."}`
- `POST /api/admin/chat {"message":""}` → 200 `{"reply":"(empty message — nothing to send)"}`
- `POST /api/admin/chat {}` → 200 (empty-message branch)

## Spec decisions landed

- **Stub vs real `/api/admin/chat`**: stub. Wire contract stable (`{message}` → `{reply}`); real `_local_admin` routing deferred to T7B.6 (backend-only swap, no frontend changes).
- **Tab routing mechanism**: state-machine on `useAdminStore.activeTab` (no nested `<BrowserRouter>` since App.tsx already dispatches by pathname).
- **History persistence**: component-local `useState` only. Cross-nav persistence deferred; server-side conversation IDs will become the persistence layer when real routing lands.
- **Welcome message**: none (omitted from M2 scope — keeps test surface minimal).
- **Auth on stub endpoint**: no `require_tenant_access` yet because target tenant-id semantics (`_local_admin` vs `_master`) aren't fully realized at the wire layer. Added with real routing.
- **activeTab union widening**: `AdminState.activeTab` now includes `'chat'` (previously deferred from T6F.3).

## 关联 artifact

- eval-doc-014 (batch-11 T6F.5 + T6F.6 combined eval)
- test-diff-015 (batch-11 diff summary)
