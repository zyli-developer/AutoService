# Test diff: batch-9

New frontend tests across 4 files; 2 existing test files updated to new hook contract.

Net new tests: **+22** (13 new cases in packages/shared + 9 new cases in admin-portal).
All files, all cases green.

## 新增文件

- `frontend/apps/admin-portal/src/__tests__/AuthGate.test.tsx` — **5 tests**, AuthGate wrapper (loading/anon/authenticated/error/transition).
- `frontend/apps/admin-portal/src/__tests__/AuthLoginPage.test.tsx` — **4 tests**, magic-link form (happy/error/busy/empty-submit).

## 修改文件

- `frontend/packages/shared/useSessionMode.test.ts` — from 4 tests → **6 tests**. Added `network-error` (fetch rejects) and `refetch` cases. Pre-existing 4 retained with updated payload shape to M2 contract (tenant_id/authenticated/authenticated_as/tier/brand_name).
- `frontend/packages/shared/useTenantId.test.ts` — from 4 tests → **7 tests**. Added 3 cases for session-tenant fallback: mode=tenant fallback, mode=master null, URL path authoritative over session.
- `frontend/apps/admin-portal/src/__tests__/App.test.tsx` — from 6 tests → **7 tests**. Updated all 6 existing cases to new hook payload shape; added `/login` public-route case. "Error → MasterLayout fallback" semantic changed to "error → AuthGate error splash" per spec §9 (no anon content flash).

## 覆盖的场景

From eval-doc-011:

### T6F.1 · useSessionMode
- initial loading=true → flips to false on resolve (M1, retained)
- success → all 6 M2 fields populated
- non-2xx response → error surfaced
- network reject → error surfaced
- refetch re-runs query, returns fresh data

### T6F.1 · useTenantId
- URL path param wins (M1, retained)
- `?tenant=` query fallback (M1, retained)
- null when both URL sources absent (M1, retained)
- path wins over query (M1, retained)
- session.tenant_id fallback when mode=tenant + URL empty
- null when mode=master + URL empty
- URL path param wins over session.tenant_id

### T6F.2 · AuthGate
- loading → Splash, children hidden
- anon → redirector called with `/login?redirect=<path>`, children hidden during redirect
- authenticated → children rendered, splash absent, no redirect
- error → error-variant splash with retry button → refetch()
- loading→authenticated transition never flashes anon content

### T6F.2 · LoginPage
- submit happy path → POST `/api/auth/request-login` `{email, tenant_id: null}` + credentials:include, success UI
- submit 5xx → inline error, form re-submittable
- busy submit → button & input disabled until resolve
- empty submit → no fetch call + inline error

### T6F.2 · App dispatch integration
- loading → auth-splash
- auth + mode=master → MasterLayout
- auth + mode=tenant → TenantLayout with session tenant_id
- error → error-variant auth-splash (changed from M1 "→ MasterLayout fallback")
- `/t/<tid>/admin` path → AuthGate→TenantLayout (path-tenant)
- `/t/a%2Fb/admin` path → tenant id decoded
- `/login` public → LoginPage stub (no gate)

## 未修/复用

- `frontend/apps/admin-portal/src/__tests__/LoginPage.test.tsx` — legacy tenant-id login tests retained unchanged (3 tests); covers `components/LoginPage.tsx` (orthogonal, used by MasterLayout's zustand flow).
- `frontend/apps/admin-portal/src/__tests__/MasterLayout.test.tsx` — unchanged; still green.
- `tests/auth/test_session_mode.py` — backend contract tests (batch-8, 5 tests) re-run to confirm contract consumer (this batch's useSessionMode) reads the right shape.

## 已修 regression bug

None. All 24 pre-existing admin-portal test failures (9 files) are unchanged — same set as batch-8 baseline; none are in files touched by this batch.
