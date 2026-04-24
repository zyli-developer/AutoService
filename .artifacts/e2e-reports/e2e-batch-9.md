# E2E report: batch-9 (frontend shell hooks)

**Scope**: T6F.1 (useSessionMode + useTenantId real impl) + T6F.2 (AuthGate + LoginPage + App integration).
**Date**: 2026-04-20 · **Runner**: vitest (frontend) + pytest (backend contract).
**Related**: eval-doc-011 · test-diff-013.

## New tests (from this batch)

### `frontend/packages/shared` (vitest)

```
✓ useTenantId.test.ts (7 tests)
✓ useSessionMode.test.ts (6 tests)

Test Files  2 passed (2)
     Tests  13 passed (13)
```

- `useSessionMode` — +2 over M1 (added `network-error`, `refetch`); all 6 cases green.
- `useTenantId` — +3 over M1 (session fallback cases); all 7 cases green.

### `frontend/apps/admin-portal` (vitest — scoped to files this batch touches or provides)

```
✓ src/__tests__/App.test.tsx (7 tests)            — rewritten for new hook shape + /login route
✓ src/__tests__/AuthGate.test.tsx (5 tests)       — new
✓ src/__tests__/AuthLoginPage.test.tsx (4 tests)  — new
✓ src/__tests__/LoginPage.test.tsx (3 tests)      — unchanged (legacy tenant-id flow)
✓ src/__tests__/MasterLayout.test.tsx (4 tests)   — unchanged
✓ src/__tests__/AdminRail.test.tsx (7 tests)      — unchanged
✓ src/__tests__/AdminTopbar.test.tsx (4 tests)    — unchanged

Test Files  7 passed (7)
     Tests  34 passed (34)
```

New cases added by batch-9:
- **AuthGate** (5): loading splash, anon redirect, authenticated passthrough, error retry, transition no-flash.
- **AuthLoginPage** (4): happy path, error retry, busy disabled, empty submit.
- **App** (+1 beyond the 6 rewritten): `/login` public route.
- **useSessionMode** (+2): network error, refetch.
- **useTenantId** (+3): session fallback + master null + URL wins over session.

**Net new tests: +15 vs prior (T6F.1 hooks + T6F.2 components + App rewrite).**

## Backend contract regression (pytest)

Confirms the backend shape batch-9's useSessionMode reads is unchanged:

```
$ python -m pytest tests/auth/ -q
........................................                                 [100%]
36 passed in 1.40s
```

All 36 auth tests green — includes batch-7's 20 (request-login / verify / logout / sessions / tokens) and batch-8's 16 (require_tenant_access + /api/session/mode).

## Full admin-portal regression

```
$ pnpm test --run
Test Files  9 failed | 17 passed (26)
     Tests  24 failed | 107 passed (131)
```

**Pre-existing failures: 24 across 9 files** — identical set to batch-7 / batch-8 baseline (recorded in e2e-report-004 / e2e-report-005 as out-of-scope):

- `AdminWorkspace.test.tsx` (6 fails)
- `VirtualRehearsalStep.test.tsx` (4 fails)
- `ComplianceCheckStep.test.tsx` (4 fails)
- `integration.test.tsx` (3 fails)
- `ProposalsTab.test.tsx` (2 fails)
- `ChannelConfigStep.test.tsx` (2 fails)
- `DashboardTab.test.tsx` (1 fail)
- `DashboardTab.period.test.tsx` (1 fail)
- `CanaryProgress.test.tsx` (1 fail)

None of the 9 failing files are touched by batch-9. Root causes are i18n / translation-key diff (most assertions look for raw keys like `admin.wizard.rehearsal.ai_reply` against English strings); fix is outside batch-9 scope.

**Passing delta**: 97 (baseline) → 107 (post-batch-9) = +10 passing tests.

## Regression (preexisting tests)

- **Green**: `LoginPage.test.tsx`, `MasterLayout.test.tsx`, `AdminRail.test.tsx`, `AdminTopbar.test.tsx`, `BillingTab.test.tsx`, `NotificationsTab.test.tsx`, `SandboxReady.test.tsx`, etc. — all unchanged.
- **Red** (preexisting, unchanged root cause): 24 failures listed above.

## Summary

| Bucket | Before | After | Delta |
|---|---|---|---|
| `packages/shared` total | 8 | 13 | +5 new tests |
| `admin-portal` passing | 97 | 107 | +10 (5 AuthGate + 4 AuthLoginPage + 1 App/login) |
| `admin-portal` failing (preexisting) | 24 | 24 | 0 (no regression) |
| backend `tests/auth/` | 36 | 36 | 0 (contract stable) |

**Gate status**: ✅ all new tests green; 0 new regressions; backend contract stable.

## Spec decisions (flagged during implementation)

1. **TanStack Query vs vanilla** — spec §3.6 suggests `useQuery`; we rolled vanilla useState+useEffect+refetch-nonce because `@tanstack/react-query` is not a dep of admin-portal or shared, and the plan doc forbids adding new deps. Signature compatible with a future TanStack swap.
2. **AuthGate redirect mechanism** — `window.location.assign` (hard redirect) rather than `<Navigate>` because MasterLayout/TenantLayout each wrap their own `<BrowserRouter>`; a router at App level would nest. Test seam via `redirector` prop.
3. **LoginPage filename** — new component at `components/auth/LoginPage.tsx`; test file at `__tests__/AuthLoginPage.test.tsx` (avoids clash with legacy `__tests__/LoginPage.test.tsx` covering the tenant-id zustand flow).
4. **App.test "error → MasterLayout fallback" semantic changed** — M1 silently fell back to MasterLayout on /api/session/mode failure; M2 spec §9 prohibits anon content flashes, so the error branch now renders an error splash with a retry button. Documented in App.test.tsx file header.
5. **`/login` public route** — bypasses AuthGate. Implemented via a top-level pathname check in App.tsx (`/login` or `/login?…`) to avoid nesting BrowserRouter inside MasterLayout/TenantLayout's own routers.
