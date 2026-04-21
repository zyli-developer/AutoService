# Test Diff: T7F.3 — customer-chat + operator-console mode-based routing

**Artifact ID**: test-diff-018
**Related eval**: [eval-doc-017](../eval-docs/eval-t7f-3-routing.md)
**Task**: T7F.3 · Phase 7 · Green · batch-13 (parallel with T7S.4 — test-diff-017)
**Producer**: phase-7-main

## Files added

| File | Tests | Notes |
|------|-------|-------|
| `frontend/apps/customer-chat/src/__tests__/mainRouting.test.tsx` | 5 | `deriveBasename` unit tests + `RouteBootstrap` loading/error states |
| `frontend/apps/operator-console/src/__tests__/mainRouting.test.tsx` | 5 | same shape as customer-chat; uses `operator-splash` testids |

## Files modified

| File | Change |
|------|--------|
| `frontend/apps/customer-chat/src/main.tsx` | Wrap `<App/>` in a `<RouteBootstrap>` that reads `useSessionMode` and picks `basename` for `<BrowserRouter>` based on deployment mode. Add tolerant `/chat` + `/t/:tid/chat` routes (superset across modes). Expose `deriveBasename` + `RouteBootstrap` for unit tests. Guard `ReactDOM.createRoot(...)` behind `document.getElementById('root')` so test imports don't mount. |
| `frontend/apps/operator-console/src/main.tsx` | Same shape as customer-chat — `RouteBootstrap` + `deriveBasename` + guarded mount. Preserves existing `NoTenantFallback` / `Navigate` fall-through. |

## Test scenarios (TC-IDs)

### customer-chat (`mainRouting.test.tsx`)

| TC | Scenario | Assertion |
|----|----------|-----------|
| TC-T7F3-CC-01 | `deriveBasename('master', 'acme')` | returns `/t/acme` |
| TC-T7F3-CC-02 | `deriveBasename('master', null)` | returns `''` (URL-flat absolute path handles) |
| TC-T7F3-CC-03 | `deriveBasename('tenant', *)` | returns `''` (both with and without tenant id — URL-flat in fork) |
| TC-T7F3-CC-04 | `<RouteBootstrap>` while `useSessionMode.loading` | renders `data-testid="chat-splash"` with `data-variant="loading"`; no router content |
| TC-T7F3-CC-05 | `<RouteBootstrap>` on `useSessionMode.error` | Splash `error` variant + clickable `chat-splash-retry` that calls `refetch` |

### operator-console (`mainRouting.test.tsx`)

| TC | Scenario | Assertion |
|----|----------|-----------|
| TC-T7F3-OC-01 | `deriveBasename('master', 'acme')` | returns `/t/acme` |
| TC-T7F3-OC-02 | `deriveBasename('master', null)` | returns `''` |
| TC-T7F3-OC-03 | `deriveBasename('tenant', *)` | returns `''` |
| TC-T7F3-OC-04 | `<RouteBootstrap>` while `useSessionMode.loading` | renders `data-testid="operator-splash"` with `data-variant="loading"` |
| TC-T7F3-OC-05 | `<RouteBootstrap>` on `useSessionMode.error` | Splash `error` variant + clickable `operator-splash-retry` that calls `refetch` |

## Test run — focused scope

```
$ cd frontend/apps/customer-chat
$ npx vitest run src/__tests__/mainRouting.test.tsx
✓ src/__tests__/mainRouting.test.tsx (5 tests) 170ms
Test Files: 1 passed (1)
Tests: 5 passed (5)
Duration: 3.73s

$ cd frontend/apps/operator-console
$ npx vitest run src/__tests__/mainRouting.test.tsx
✓ src/__tests__/mainRouting.test.tsx (5 tests) 161ms
Test Files: 1 passed (1)
Tests: 5 passed (5)
Duration: 5.69s
```

## Regression check — full-app vitest

Both apps have a pre-existing i18n baseline of failing tests (21 in customer-chat, 11 in operator-console) that are unrelated to T7F.3. I verified this by running the full suite with my changes stashed:

| App | Pre-existing failures (baseline) | With T7F.3 changes | Net new regression |
|-----|----------------------------------|--------------------|--------------------|
| customer-chat | 21 failed / 73 passed (94) | 21 failed / 78 passed (99) | **0** — my 5 tests add to pass count only |
| operator-console | 11 failed / 88 passed (99) | 11 failed / 95 passed (106) | **0** — my 5 tests add to pass count only |

Baseline numbers preserved exactly; the +5 tests per app show up in the pass count. No new regressions.

## Key invariants exercised

- **Basename derivation is pure** — three tests per app pin the function's branches; no hidden dependency on router context or window state.
- **Splash renders during `useSessionMode.loading`** — spec §9 flicker mitigation invariant; asserted via absence of tenant-fallback / no-tenant-fallback markers in the same render.
- **Retry path wires to `refetch`** — keeps the error state actionable; no silent failure, no automatic retry.
- **Module import is side-effect-free** — tests assert by importing `RouteBootstrap`/`deriveBasename` from `main`; the guarded `ReactDOM.createRoot(...)` mount does not fire because the `#root` element doesn't exist in jsdom tests.

## Evidence

- Source commits: see `docs/plans/m2/task-status.md` Phase 7 row for T7F.3 commit hash.
- Focused run logs are captured above; full-suite runs confirm zero regression vs. baseline.

## Consumers

- `e2e-report-010` (batch-13 combined e2e report, produced by main orchestrator after T7F.3 + T7S.4 both land)
