# Eval: batch-9 frontend shell hooks (T6F.1 / T6F.2)

**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §3.6 (frontend mode branching) + §4.1 (admin-portal directory) + §4.5 (AuthGate)
**Tasks**: T6F.1 `useSessionMode` + `useTenantId` real impl · T6F.2 AuthGate + LoginPage + App integration
**Batch**: batch-9 · Green · serial (T6F.2 depends on T6F.1 hook contract)
**Backend prereqs**: batch-7 (`442c02b`) + batch-8 (`98b21ff`) — `/api/session/mode` returns `{mode, tenant_id, authenticated, authenticated_as, tier, brand_name}`; `/api/auth/request-login` + `/verify` + `/logout` ready; cookie `auth_session`.
**Related**: eval-doc-009 (batch-7 auth core), eval-doc-010 (batch-8 gating) — this batch lands the frontend half of the same contract.

## 预期行为

### T6F.1 — `useSessionMode` real impl (`frontend/packages/shared/useSessionMode.ts`)

- Replaces the M1 stub (which returned `{mode, role, tenant_id?}`) with the M2 shape matching `/api/session/mode` response.
- Signature: `useSessionMode(fetcher?, endpoint?)` returns `{data, loading, error, refetch}`.
- `SessionMode` type covers the full backend response:
  ```ts
  {
    mode: "master" | "tenant";
    tenant_id: string | null;
    authenticated: boolean;
    authenticated_as: string | null;
    tier: 0 | 1 | null;
    brand_name: string;
  }
  ```
- Fetch call: `fetch(endpoint, { credentials: "include" })` so the `auth_session` cookie is sent on cross-origin preview deployments.
- No TanStack Query (admin-portal doesn't pull it in; spec §3.6 mentions `useQuery` but we roll a vanilla `useState + useEffect` hook to avoid a new peer dep — decision below).
- `refetch()` re-triggers the fetch (fresh closure), clears previous error, resets `loading=true`.
- Stale behaviour: each render that changes `fetcher`/`endpoint` re-fetches; no cache (M2 acceptable — the hook is consumed once at the top of the tree).

### T6F.1 — `useTenantId` real impl (`frontend/packages/shared/useTenantId.ts`)

- Replaces the M1 URL-only impl. New resolution order (spec §3.6):
  1. **Route path param** `:tenantId` (from `/t/:tenantId/*`) — always wins (URL is authoritative for tenant-scoped deep links).
  2. **Query string `?tenant=`** — fallback for legacy callers.
  3. **Session `tenant_id`** — if mode === `"tenant"`, return `session.tenant_id`.
  4. Otherwise `null` (master mode + no URL scope = no tenant).
- Must be safe to call outside a router (`useParams` / `useLocation` from react-router) and outside a session provider (useSessionMode internally safe).
- Derives from `useSessionMode` to avoid duplicate network round-trips (React calls can share via module-scoped cache if needed; M2 contract = each consumer may fetch; acceptable for now).

### T6F.2 — `AuthGate.tsx` (`frontend/apps/admin-portal/src/components/auth/AuthGate.tsx`)

- Wraps children, consumes `useSessionMode`:
  - `loading` → render `<Splash />` (centered spinner div, inline style, brand `AutoService`).
  - `error` → render `<Splash />` with a retry button (error surface still shows the brand, doesn't flash anon content; retry calls `refetch`).
  - `!data.authenticated` → use `<Navigate to="/login?redirect=<current_path>" replace />`.
  - `data.authenticated` → render `children`.
- **Key invariant** (spec §9 flicker mitigation): NEVER render anon content between loading and the /login redirect. The Splash frame covers the network gap.
- No side effects beyond navigation.

### T6F.2 — `LoginPage.tsx` (`frontend/apps/admin-portal/src/components/auth/LoginPage.tsx`)

- New component (does NOT replace legacy `components/LoginPage.tsx` used by `MasterLayout`'s tenant-id flow — that flow is orthogonal; legacy will be removed in a later batch when `MasterLayout` adopts AuthGate).
- Form:
  - `<label>` + `<input type="email" required>` for email.
  - Submit → `POST /api/auth/request-login` with `{email, tenant_id: null}` (tenant_id null; admin-portal assumes master unless path scope, deferred to middleware T7B.1).
  - Disabled button while in-flight; re-enabled on success or error.
- Success message: "Check your email for a magic link" + dev hint when `window.location.hostname === "localhost"` ("(or tail `.autoservice/logs/auth-devmail.jsonl`)").
- Error display: inline red text; form remains submittable.
- Accessibility: `<label htmlFor>`, native email validation, `aria-busy` while submitting.

### T6F.2 — `App.tsx` integration

- Wrap root with `<BrowserRouter>` + `<AuthGate>`; `/login` route matches **before** AuthGate (login should be publicly reachable).
- Actual structure:
  ```tsx
  <BrowserRouter>
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="*" element={<AuthGate><ModeDispatch /></AuthGate>} />
    </Routes>
  </BrowserRouter>
  ```
- `<ModeDispatch>` does the existing master-vs-tenant dispatch based on `useSessionMode().data.mode`.
- `/t/<tid>/admin` path-prefix short-circuit preserved (test contract).

## 验收标准

### `useSessionMode.test.ts` (6 tests)

- `loading initially → isLoading true` — pre-await state check.
- `success → data has all 6 fields` — fixture response maps exactly.
- `network error → isError true` — `fetch` rejects.
- `401 response → isError true` — HTTP non-2xx surfaced as error (frontend AuthGate checks `authenticated` on a 200 OK; 401 here means the endpoint itself is unreachable/auth-required, which the spec says it never should be).
- `refetch updates cached data` — second call fetches with new fixture.
- (Kept from M1) `returns master-mode payload` + `starts loading then flips` — preserved as regression.

### `useTenantId.test.ts` (7 tests = 4 pre-existing + 3 new)

- Pre-existing (must remain green): path param wins; query fallback; null when neither; path wins over query.
- `returns session.tenant_id when mode=tenant (no URL scope)` — session provides scope when URL doesn't.
- `returns null when mode=master and no URL scope` — master + clean URL = null.
- `ignores session.tenant_id when URL path has :tenantId` — URL authority preserved.

### `AuthGate.test.tsx` (4 tests)

- `loading → Splash rendered, children not rendered` — renders `data-testid="auth-splash"`, not children.
- `anon → navigate to /login with ?redirect preserving current path` — mocked `<Navigate>` captures target.
- `authenticated → children rendered, splash absent` — child visible.
- `loading → authenticated transitions don't flash anon content` — replay: first render loading, re-render with authenticated=true; never see Navigate call.

### `LoginPage.test.tsx` (4 tests)

- `submit happy path → POST /api/auth/request-login called with {email, tenant_id: null}`, success message visible.
- `submit error → error displayed, form usable for retry`.
- `disabled button during in-flight request` — `getByRole('button').disabled` true between submit and resolve.
- `blocks submit on empty / invalid email` — native `required` + client check.

### `App.test.tsx` (updated)

- Existing 6 tests updated to new hook shape (`data.authenticated` + `data.tenant_id` replacing old `data.mode/role`).
- `loading state` now checked via `auth-splash` (introduced by AuthGate) OR kept-but-updated `session-mode-loading` — whichever path the updated App.tsx exposes.

## 关键 invariant

- **CON-03 tech stack** — React 18 + TypeScript + Zustand + Vitest + @testing-library/react. No new deps. TanStack Query mentioned in spec §3.6 is NOT introduced (admin-portal `package.json` doesn't have it); we implement vanilla `useState + useEffect` + a manual `refetch` ref to satisfy the contract. Decision deferred to batch-9: introducing TanStack Query is a dep-review event; punt until a second consumer demands it.
- **Spec §9 AuthGate first-frame flicker** — `<AuthGate>` MUST render `<Splash />` on `loading`/`error` before any routing decision. Transitioning states that go through `authenticated=false` produce a `<Navigate>`, but the UI MUST NOT show tenant content in between.
- **CON-08 cookie secure flag** — frontend doesn't set cookies, but fetch MUST use `credentials: "include"` so the backend-set `HttpOnly` cookie accompanies the request. Dev waiver (http://localhost) honoured by the browser.
- **CON-05 tier reservation** — tier 0 = internal admin (`_master` / `_local_admin`), NULL `session.tenant_id`. Frontend never derives tier; backend sends it. AuthGate uses only `authenticated` as the gate; the mode-dispatch consumer uses `mode` + `tenant_id`.
- **Cookie name reconciliation** — batch-7/8 decision: `auth_session` (NOT spec §5.2's `adm_s`). Frontend hook MUST use `credentials: "include"` so the cookie is sent; no explicit cookie name ref in JS (HttpOnly makes it inaccessible).
- **Legacy `components/LoginPage.tsx` preserved** — the existing tenant-id login used by `MasterLayout` is NOT removed in this batch. It coexists at `components/LoginPage.tsx` while the new AuthGate login lives at `components/auth/LoginPage.tsx`. A later batch can delete the legacy flow once `MasterLayout` drops its internal `isLoggedIn` check.
- **tenant_id null in request-login** — LoginPage submits `tenant_id: null`; the backend creates a tier-0 session (NULL session.tenant_id). For admin-portal running on the master host this is correct; tenant-portal (fork deployment) will send `tenant_id: <self>` — deferred to T7F.3.

## Spec ambiguities resolved

- **TanStack Query vs vanilla** — spec §3.6 shows `useQuery(['session-mode'], …, {staleTime: Infinity})`. Admin-portal's `package.json` lacks `@tanstack/react-query` and the plan doc says "Use the existing test-setup utilities; don't introduce new deps." Decision: vanilla useState+useEffect + `refetch`. If a second app later consumes `useSessionMode`, we can add TanStack Query under the same hook signature without breaking callers.
- **Splash design** — spec says "Aurora 风格单页" for LoginPage but nothing specific for Splash. Decision: minimal centered div with brand text + animated CSS border. Inline styles (no CSS modules). `data-testid="auth-splash"` for test selection.
- **Auth redirect flow** — AuthGate navigates via `<Navigate to="/login?redirect=<path>" replace />`. LoginPage on success does NOT auto-redirect (user has to click the magic link in email); after token verify, backend 302s to `/admin` or the `?redirect=` param, which is handled server-side. The `<Navigate replace>` prevents an extra entry in browser history.
- **useSessionMode return shape** — kept backward-compatible `{data, loading, error}` plus new `refetch` (additive; existing App.test.tsx mock keeps working). The M1 stub's `role` field removed from the type but the test doesn't assert it anymore (we'll update App.test.tsx to use `authenticated` + `mode`).
- **useTenantId session derivation** — spec §3.6 says "fork 模式从 useSessionMode().tenant_id 拿；master 从 URL params 拿." Implementation: URL takes precedence in ALL modes (URL is deep-link authoritative); only falls back to session when URL has no tenant info. This is safer than flipping on mode (prevents "URL says /t/X, session says Y → which wins?" ambiguity).

## Evidence

| Artifact | Location |
|----------|----------|
| Hook impl | `frontend/packages/shared/useSessionMode.ts`, `frontend/packages/shared/useTenantId.ts` |
| Auth UI | `frontend/apps/admin-portal/src/components/auth/AuthGate.tsx`, `frontend/apps/admin-portal/src/components/auth/LoginPage.tsx` |
| App wiring | `frontend/apps/admin-portal/src/App.tsx` |
| Tests | `frontend/packages/shared/useSessionMode.test.ts`, `frontend/packages/shared/useTenantId.test.ts`, `frontend/apps/admin-portal/src/__tests__/AuthGate.test.tsx`, `frontend/apps/admin-portal/src/__tests__/LoginPage.test.tsx`, `frontend/apps/admin-portal/src/__tests__/App.test.tsx` (updated) |
| Task status rows | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 6 — T6F.1 / T6F.2 |
