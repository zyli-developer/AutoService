# Eval: T7F.3 — customer-chat + operator-console mode-based routing

**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §3.6 (frontend deployment-mode branching)
**Task**: T7F.3 · Phase 7 · Green · paired with T7S.4 (setup.sh mode-aware) as batch-13
**Producer**: main orchestrator (no reviewer; Green task)
**Related**: eval-doc-011 (batch-9 `useSessionMode` + `useTenantId` real impl) · eval-doc-015 (batch-12 TenantContext middleware — the backend half that rewrites `/t/<self>/*` → `/*` in tenant mode, making URL-flat safe on the fork)

## 预期行为

### Single source of truth for deployment mode

Both SPA entry points (`customer-chat/src/main.tsx`, `operator-console/src/main.tsx`) consume the **real** `useSessionMode` hook (batch-9) as the sole source of truth for `mode`. No new env vars, no `import.meta.env` branches at the module level — the deployment identity is decided by the backend at `/api/session/mode` and reaches the frontend exactly once per page load.

### Routing policy by mode

Mirrors spec §3.6 and the backend middleware contract (spec §3.2, eval-doc-015):

| Mode | customer-chat canonical paths | operator-console canonical paths |
|------|-------------------------------|----------------------------------|
| `master` | `/t/<tid>/chat` (required; `/chat` falls through to the no-tenant fallback) | `/t/<tid>/operator` (required; `/` → `NoTenantFallback`) |
| `tenant` | **URL-flat** `/chat` (backend middleware already rewrote `/t/<self>/chat` → `/chat`); also accept `/t/:tid/chat` so deep links keep working in tenant mode before the middleware rewrite reaches this process | **URL-flat** `/operator`; also accept `/t/:tid/operator` for the same reason |

Key technique: compute a `basename` for `<BrowserRouter>` from the mode + session.tenant_id. This keeps `<Routes>` trees identical across modes — each app renders the same canonical sub-tree, and the router automatically prepends `/t/<tid>` only when we're in master mode and a tenant is in session context.

**Simplification adopted** — the sub-Routes tree stays tolerant of both shapes (URL-flat AND `/t/:tenantId/<leaf>`) in BOTH modes, because:

- In master mode the backend never rewrites, so `/t/<tid>/*` is the primary URL shape; `/<leaf>` is a graceful fall-through.
- In tenant mode the backend rewrites `/t/<self>/*` → `/<leaf>` before the SPA even loads; but if a deep link lands before the middleware runs (e.g., in dev or via static hosting), the tolerant Route keeps it working.

So the mode-branch chooses the **basename**, and the Routes tree is a single superset. Reduces divergence; keeps one code path.

### Bootstrap lifecycle

Because `useSessionMode()` is async (fetches `/api/session/mode`), each app wraps the render tree in a thin `<RouteBootstrap />` component that:

1. Calls `useSessionMode()`.
2. While `loading` → renders a Splash frame (inline spinner, no anon content flash — matches AuthGate pattern from batch-9 T6F.2).
3. On `error` → renders Splash with `error` variant + Retry button (calls `refetch`).
4. On success → renders `<BrowserRouter basename={derivedBasename}>` with the Routes tree.

The Splash is a local, self-contained component (customer-chat and operator-console don't depend on admin-portal). Inline styles; no new deps.

### `basename` derivation

```ts
function deriveBasename(mode, tenantId) {
  if (mode === "tenant") return ""; // URL-flat, backend already rewrote
  // master mode — if we know the tenant_id from session (rare), prefix it so
  // relative `<Link to="/chat">` -style consumers resolve correctly; otherwise
  // leave empty and rely on absolute `/t/:tenantId/<leaf>` URLs.
  if (mode === "master" && tenantId) return `/t/${tenantId}`;
  return "";
}
```

For customer-chat, `session.tenant_id` is typically null in master mode (the *end user*, not an admin, sees the widget via `/t/<brand>/chat`); that's fine — `basename=""` keeps URL-flat and absolute `/t/:tid/chat` working.

For operator-console, the operator is authenticated as a tenant operator; in master mode the session may carry their tenant_id; basename then prefixes to `/t/<tid>` so relative links stay inside that scope.

## 验收标准

### customer-chat tests (`frontend/apps/customer-chat/src/__tests__/mainRouting.test.tsx`, ~4-5)

| # | Scenario | Expected |
|---|----------|----------|
| 1 | `deriveBasename('master', 'acme')` | `'/t/acme'` |
| 2 | `deriveBasename('master', null)` | `''` (absolute `/t/:tid/chat` URLs handle it) |
| 3 | `deriveBasename('tenant', 'acme')` | `''` (URL-flat; backend middleware already rewrote) |
| 4 | `<RouteBootstrap>` while `loading` | renders `data-testid="chat-splash"` (no `data-testid="tenant-fallback"`, no ChatApp) |
| 5 | `<RouteBootstrap>` on `error` | renders Splash `error` variant + `Retry` button |

### operator-console tests (`frontend/apps/operator-console/src/__tests__/mainRouting.test.tsx`, ~4-5)

| # | Scenario | Expected |
|---|----------|----------|
| 1 | `deriveBasename('master', 'acme')` | `'/t/acme'` |
| 2 | `deriveBasename('master', null)` | `''` |
| 3 | `deriveBasename('tenant', 'acme')` | `''` |
| 4 | `<RouteBootstrap>` while `loading` | renders `data-testid="operator-splash"` (no App / no NoTenantFallback) |
| 5 | `<RouteBootstrap>` on `error` | renders Splash `error` variant + `Retry` button |

Tests use a fake `fetch` (`vi.fn()`) passed into `useSessionMode` via the dependency-injection prop, matching the batch-9 pattern. They render `<RouteBootstrap>` in isolation — not through `main.tsx` — so no `ReactDOM.createRoot` side-effects during tests.

### Pre-existing tests preserved

- Customer-chat `ChatInput.test.tsx`, `integration.test.tsx`, etc. continue to pass — the new bootstrap wraps the router; does not alter `App`.
- Operator-console `tenantRouting.test.tsx` (TC-TEN-01..07) continues to pass — `useTenantId` + WS URL derivation unchanged.

## 关键 invariant

- **Single source of truth for mode** — `useSessionMode` (batch-9) is consumed exactly once per app root; no parallel env/bootstrap fetch.
- **No new dependency** — no TanStack Query, no new npm packages. Vanilla React `useState` + `useEffect` + existing `react-router-dom@6`.
- **Match backend middleware** — URL-flat in tenant mode is correct because eval-doc-015's TenantContext middleware rewrites `/t/<self>/*` → `/*` before the FastAPI router matches. If that invariant breaks, both apps degrade gracefully via the tolerant Routes tree (accepts both shapes).
- **Flicker mitigation (spec §9)** — mirror of AuthGate: render Splash during `loading`; never expose the raw pre-mode render tree. Same rationale as AuthGate — anon content flash is UX-harmful and the network gap on `/api/session/mode` is measurable.
- **Error recovery** — Splash error variant with Retry binds to `refetch()`. No silent failure; no automatic retry (that would mask backend downtime).
- **Idempotent main.tsx** — `ReactDOM.createRoot(...).render(<RouteBootstrap />)` is the single entry; testable unit is `RouteBootstrap` + `deriveBasename`, not the root mount.

## Spec ambiguities resolved

- **Spec §3.6 example uses `<Redirect>` (`react-router-dom@5` API)** — rejected as literally transcribed; `react-router-dom@6` uses `<Navigate>`. We instead drive routing via `basename` + a superset Routes tree, avoiding redirects altogether. Net effect is equivalent for deep links; cleaner for relative-link resolution.
- **Spec §3.6 master-mode Routes tree omits `/chat` (URL-flat)** — added graceful fall-through to the existing `NoTenantFallback` / `TenantFallback` components. Users reaching `/chat` on master get a "select tenant" message, not a 404.
- **`selfTid` in spec snippet** — spec says `<Redirect to={/t/${selfTid}/chat} />`. In tenant mode the SPA rarely needs to emit this URL (backend middleware handles `/t/<self>/*` → `/*`); we keep `basename=""` in tenant mode and leave absolute-URL emission to admin-portal (which already handles tenant-scoped links via `window.location`).
- **`session.tenant_id` null for customer-chat viewers** — in master mode, the customer is anonymous and the session cookie is irrelevant; `/api/session/mode` returns `authenticated: false`. We DO NOT gate the SPA (customer-chat is public); we simply use mode to pick routing, ignoring authentication. This differs from admin-portal where AuthGate gates render. Confirmed by reading the spec's mode table (§3.6) where customer-chat is *not* AuthGate-wrapped.

## Evidence

| Artifact | Location |
|----------|----------|
| customer-chat main.tsx | `frontend/apps/customer-chat/src/main.tsx` |
| operator-console main.tsx | `frontend/apps/operator-console/src/main.tsx` |
| customer-chat tests | `frontend/apps/customer-chat/src/__tests__/mainRouting.test.tsx` |
| operator-console tests | `frontend/apps/operator-console/src/__tests__/mainRouting.test.tsx` |
| Task status row | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 7 — T7F.3 |

## Future work (flagged)

- **Env-var override** — if future Fork packaging ships the static assets via a CDN that can't call `/api/session/mode` synchronously, a compile-time `import.meta.env.VITE_DEPLOYMENT_MODE` override could replace the runtime fetch. Not needed now — dev + prod both serve the SPA behind the FastAPI gateway.
- **Splash reuse** — extract the local Splash into `@autoservice/design-system` when a third SPA appears. Out of scope for M2.
