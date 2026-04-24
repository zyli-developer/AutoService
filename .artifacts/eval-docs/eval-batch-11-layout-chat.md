# Eval: batch-11 — T6F.5 TenantLayout 4-tab + T6F.6 ChatTab → /api/admin/chat

**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §4.1 + §4.4
**Tasks**: T6F.5 (TenantLayout — 4-tab tenant shell) + T6F.6 (ChatTab — `_local_admin` chat)
**Batch**: batch-11 · Green · serial (T6F.6 depends on T6F.5)
**Backend prereqs**:
- batch-8 `GET /api/session/mode` → returns `brand_name` + `authenticated_as` (commit `98b21ff`)
- batch-10 `AdminRail variant="tenant"` + `AdminTopbar brandName/authenticatedAs` props
- **This batch**: adds `POST /api/admin/chat` (stub — full run_dream wiring deferred)
**Related**: eval-doc-011/012/013 (batch-9/10 shell hooks + AdminRail variant + Topbar/AvatarMenu extensions).

## 预期行为

### T6F.5 — TenantLayout (spec §4.1)

Replaces the batch-9 placeholder TenantLayout (which just delegated to `AdminShell` with `hideMasterSection`). New behaviour:

- Renders `<AdminRail variant="tenant">` + `<AdminTopbar brandName={session.brand_name} authenticatedAs={session.authenticated_as}>` directly (not wrapped in `AdminShell` because the shell mounts `variant="master"` rail unconditionally).
- 4 tabs driven by `useAdminStore.activeTab`:
  - `chat` → ChatTab (new — T6F.6)
  - `dashboard` → placeholder (spec §4 doesn't pin M2 tenant-side content; reuse master `DashboardTab` as-is — same data, backend scopes by session tenant_id per spec §4.1 closing paragraph)
  - `proposals` → placeholder (reuse master `ProposalsTab`)
  - `billing` → placeholder (reuse master `BillingTab`)
- Default active tab: `chat` (spec §4.2 rail slot 1 is the primary tenant-mode entry point).
- `brandName` + `authenticatedAs` come from `useSessionMode()` so they reflect the live backend state (populated by AuthGate upstream; by the time TenantLayout mounts, `data.authenticated === true`).
- Mobile rail toggle reuses the batch-10 hamburger pattern (`navOpen` state).

### T6F.6 — ChatTab (spec §4.4)

Minimal but fully wired chat pane (distinct from `ManagementChat` which targets master's `/api/management/chat` with slash-command routing):

- Text input + Send button.
- On submit:
  - `fetch('/api/admin/chat', { method: 'POST', body: JSON.stringify({ message }), headers: { 'Content-Type': 'application/json' }, credentials: 'include' })`
  - Response shape: `{ reply: string }` — appended to local message history.
- Local history state (array of `{role: 'user'|'assistant', text}`). No persistence — M2 scope is per-session view; cross-nav persistence deferred to a future batch if product wants it.
- Loading state: Send button disabled + shows a pending indicator (inline text `"…"`) while request in-flight.
- Error state: if `fetch` rejects OR `resp.ok === false`, append a system-ish error bubble `"(error: <msg>)"`.
- Empty/whitespace-only input is a no-op (prevents accidental double-send).
- A11y: input has `aria-label="chat message"`; form has `role="form"`; history pane has `role="log"` + `aria-live="polite"`.

### `/api/admin/chat` backend stub

Added to `autoservice/api_routes.py`:

```python
@api_router.post("/admin/chat")
async def admin_chat(body: dict = Body(...)) -> dict[str, Any]:
    """M2 stub — full _local_admin run_dream integration deferred.

    Accepts {message: str}, returns {reply: str}. Routes to _local_admin
    agent when wired up in a future batch (T3B.4-style run_dream hook).
    """
    message = (body.get("message") or "").strip()
    if not message:
        return {"reply": "(empty message — nothing to send)"}
    return {"reply": f"(stub) Received: {message!r}. _local_admin agent integration pending."}
```

**Decision — stub vs real**: per prompt guidance and spec §4.4 closing line ("ChatTab 实现 = 复用 M1 的 ManagementChat 组件"), we ship the stub in this batch. Real wiring to `_local_admin` via run_dream requires `ensure_local_admin()` (T1B.4 — landed) plus a run_dream-style dispatcher (T7B.6 — pending); keeping that boundary clean means this batch stays Green. Flagged in artifacts.

**Auth stance**: no `Depends(auth.require_tenant_access)` on the stub because the spec §4.4 target-tenant semantics (`_local_admin` for tenant mode, `_master` for master mode) aren't fully realized yet. Adding the dep here without the tenant-id in the body/path would return 401 for all callers and break the M2 smoke flow. Future batch adds the dep alongside the real routing logic.

## 验收标准

### TenantLayout.test.tsx (~5-6 tests)

- all 4 tabs rendered in the rail (chat / dashboard / proposals / billing) — asserts `tab-chat`, `tab-dashboard`, `tab-proposals`, `tab-billing` testids from batch-10 AdminRail variant.
- default view = ChatTab (canvas shows `data-testid="tenant-chat-tab"`).
- tab click switches view (click Dashboard → `DashboardTab` stub renders; chat tab no longer active).
- brandName from `useSessionMode` flows to topbar — `topbar-tenant` text equals `session.brand_name`.
- authenticatedAs from `useSessionMode` flows to topbar — `topbar-authed-as` visible, contains the email.
- Master section NOT rendered (rail is variant="tenant", batch-10 forces master section hidden).

### ChatTab.test.tsx (~6-7 tests)

- Renders input + submit button; history is initially empty (or welcome-free per M2 scope).
- Submit POSTs `/api/admin/chat` with `credentials: 'include'`, `Content-Type: application/json`, and body `{message: <text>}`.
- Response `body.reply` gets appended to history as an assistant bubble.
- Empty input → no fetch call (button disabled OR submit is a no-op).
- Loading state while in-flight: submit button disabled.
- Network error appends an error message to history (no unhandled promise rejection).
- Multiple sends accumulate in history (first message still visible after second send).

## 关键 invariant

- **Spec §4.4 target-tenant semantics** — ChatTab is the tenant-mode entry point; it talks to `_local_admin` (not the customer tenant). For M2 this is a stub; the boundary contract (ChatTab posts `{message}` and expects `{reply}`) is stable so the future real impl is a backend-only swap.
- **Spec §9 flicker guard** — TenantLayout ONLY mounts inside AuthGate (via App.tsx dispatch). So `session.authenticated === true` is a pre-condition; we read `brand_name`/`authenticated_as` straight from the session without re-checking. No blank-topbar flash.
- **Batch-10 contract preservation** — `AdminRail variant="tenant"` + `AdminTopbar brandName=.../authenticatedAs=...` props are consumed as-designed; no rewrites of those components. Zero regression in AdminRail.test.tsx / AdminTopbar.test.tsx.
- **CON-03 tech stack** — no new deps. Uses existing vitest + RTL; inline styles OK; `fetch` via `vi.stubGlobal`.
- **Tab routing mechanism** — uses `useAdminStore.activeTab` (same state machine as MasterLayout's `AdminShell`). No nested `<BrowserRouter>` (App-level router already present; adding a second would break React Router v6). Rail items still point to `/admin/chat` etc. as navigable href strings for visual feedback, but the canvas swap is state-driven.
- **Store compatibility** — `AdminState.activeTab` union is currently `'wizard' | 'dashboard' | 'notifications' | 'proposals' | 'billing'`. Tenant variant introduces `'chat'`. T6F.3 (batch-10) flagged that widening `AdminState.activeTab` to include `'chat'` was deferred to T6F.5 (this batch). **Decision**: widen the union here so TypeScript is honest. Back-compat: `setActiveTab('notifications')` still accepted; pre-existing tests unchanged.
- **Store is persisted only for `wizardStep` + `generationResult`** (see adminStore `partialize`) — so widening the `activeTab` union won't leak stale `'chat'` into saved state for master users.

## Spec ambiguities resolved

- **ChatTab history persistence** — spec is silent. Decision: component-local state (`useState`) only. Cross-navigation rehydration is out of M2 scope; when we wire the real `_local_admin` backend, server-side conversation IDs will be the persistence layer.
- **ChatTab welcome message** — spec mentions "对称 master 的 ManagementChat" which seeds a welcome bot message. Decision: NO welcome message. Rationale: ManagementChat's welcome is an i18n string (`admin.dream.welcome`); duplicating that wiring adds test surface without product value for M2. Empty history + placeholder input copy `"Ask _local_admin anything…"` is enough signal. Easy future add-on.
- **Routing — React Router vs state machine** — spec §4.1 diagram shows tabs but doesn't mandate URL reflection. Decision: state-machine (activeTab in zustand) matching master's AdminShell pattern. Adding nested `<Routes>` inside TenantLayout would conflict with the outer `<BrowserRouter>` that MasterLayout already spawns; and App.tsx's dispatch is pathname-based so tenant-mode doesn't have its own top-level router yet. Keeping tabs state-driven unblocks M2 without infra churn.
- **Stub endpoint placement** — spec §4.4 says "POST 端点从 `/api/management/chat` 改为 `/api/admin/chat`". `api_router` prefix is `/api`, so `POST /admin/chat` under the router resolves to `POST /api/admin/chat` at the HTTP layer — matches spec.

## Evidence

| Artifact | Location |
|----------|----------|
| TenantLayout impl | `frontend/apps/admin-portal/src/layouts/TenantLayout.tsx` |
| ChatTab impl | `frontend/apps/admin-portal/src/components/tenant/ChatTab.tsx` |
| Backend stub | `autoservice/api_routes.py` (new `POST /api/admin/chat`) |
| Frontend tests | `frontend/apps/admin-portal/src/__tests__/TenantLayout.test.tsx`, `frontend/apps/admin-portal/src/__tests__/ChatTab.test.tsx` |
| Task status row | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 6 — T6F.5 + T6F.6 |

## Future work (flagged)

- **T7B.6** will replace the stub with `_local_admin` routing — once that lands, ChatTab stays untouched (backend-only change).
- **Dashboard/Proposals/Billing tenant-side polish** — current plan reuses master components as-is; if product wants tenant-specific treatments, add a dedicated task under Phase 6.
