# Eval: batch-10 T6F.4 AdminTopbar + AvatarMenu extensions

**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §4.3
**Task**: T6F.4 — AdminTopbar new props (`brandName`, `authenticatedAs`) + AvatarMenu Logout
**Batch**: batch-10 · Green · parallel with T6F.3 (AdminRail variant)
**Backend prereqs**: batch-7 `POST /api/auth/logout` (commit `442c02b`) — returns 200 + clears `auth_session` cookie.
**Related**: eval-doc-011 (batch-9 shell hooks — AuthGate + useSessionMode already wire the `brand_name` + `authenticated_as` fields from `/api/session/mode`; this task lands the UI consumer).

## 预期行为

### AdminTopbar — new optional props

- Add `brandName?: string` and `authenticatedAs?: string` (both optional, both string — empty string treated as "not provided" per spec §4.3 tenant-mode fallback).
- **Default (props omitted)**: unchanged M1 rendering — tenant crumb `{tenant} · {topbar.suffix}`, topbar title `{tenant} / {page title}`.
- **When `brandName` provided**: replaces the `tenant` token in the crumb and title — lets tenant-mode display `brand_name` (`B`'s fork brand) instead of the admin tenantId. Spec §4.3: "左：violet dot + B 的 `brand_name`".
- **When `authenticatedAs` provided**: renders near the avatar as "Signed in as ops@example.com" (inline text, data-testid `topbar-authed-as`). Spec §4.3: "右：⌘K 占位 + Avatar（显示 `authenticated_as`）".
- Empty string (`""`) for either prop → treated as omitted (no flicker, no empty div).

### AvatarMenu — Logout item

- Existing dropdown unchanged (tenant-id label, version row) per spec §4.3 Avatar menu.
- Replace the existing "zustand logout" side-effect with a real `POST /api/auth/logout` call:
  - `fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })`
  - On resolve (ok OR error): call `redirector('/login')` — matches batch-9 `AuthGate` pattern (injected redirector prop, defaults to `window.location.assign`).
  - Disabled (`aria-busy`, `disabled`) while in-flight.
  - On fetch rejection: still navigate to `/login` (logout is a best-effort cleanup; backend cookie is HttpOnly so a dead request shouldn't trap the user on the admin UI). No toast — existing UI has no toast primitive; inline error would be invisible after navigation. Decision: graceful redirect beats stuck state.
- `data-testid="btn-logout"` preserved for back-compat with existing batch-9 test.
- Still calls the legacy zustand `logout()` locally so in-memory admin state is cleared before the redirect (defensive; the redirect to `/login` is the true authority).

## 验收标准

### AdminTopbar tests (~5)

- **back-compat**: no `brandName` → renders existing tenant crumb (M1 behaviour preserved — regression guard).
- **brandName provided** → custom brand renders in crumb + title.
- **authenticatedAs provided** → renders inline "Signed in as <email>" block with `data-testid="topbar-authed-as"` near avatar.
- **authenticatedAs empty string** → treated as not provided (no flash of empty "Signed in as").
- **brandName + authenticatedAs combined** → both rendered simultaneously; neither clobbers the other.

### AvatarMenu tests (~4)

- dropdown opens with Logout item (preserves batch-9 assertion).
- Logout click → `fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })`.
- Logout click → `redirector('/login')` called after fetch resolves (test uses injected redirector prop).
- Logout disabled during in-flight request — `btn-logout.disabled === true` between click and resolve; also `aria-busy="true"`.
- (Back-compat, existing) — initial-letter + tenant-id visibility preserved.

## 关键 invariant

- **Back-compat — default rendering unchanged when new props omitted.** M1 `AdminTopbar` tests stay green. No test in `AdminTopbar.test.tsx` at HEAD is touched except additive new cases.
- **CON-03 tech stack** — no new deps. Inline styles OK. Uses existing `i18n` / `useAdminStore` only.
- **Spec §4.3 tenant-mode display semantics** — `brandName` is the B-side brand (tenant fork), not the admin tenantId. Master mode (admin-portal used as /admin on the master host) omits the prop → crumb falls back to store `tenantId`.
- **Spec §9 flicker mitigation (inherited)** — since `authenticatedAs` is populated by `useSessionMode().data.authenticated_as`, AuthGate already guarantees `data.authenticated === true` before the topbar mounts in the authed tree. So we never render a half-authenticated "Signed in as undefined" state.
- **CON-08 cookie** — Logout POST MUST use `credentials: 'include'` so the `auth_session` cookie is sent; backend revokes the row.
- **AvatarMenu `btn-logout` contract** — preserved across batch-9 and T6F.4. Existing batch-9 test asserts `useAdminStore.getState().isLoggedIn === false` after click — we keep the in-memory zustand logout call alongside the new fetch to satisfy that.

## Spec ambiguities resolved

- **authenticatedAs placement** — spec says "Avatar（显示 `authenticated_as`）" which can mean inside the avatar tooltip, next to the avatar, or in the menu. Decision: inline text block to the left of the avatar, hidden when absent. Reasoning: tooltips are a11y-fragile and jsdom doesn't render native `title`; an inline block is testable, screen-reader friendly, and matches the M1 right-side layout.
- **brandName vs topbar crumb token** — crumb format is `{tenant} · {suffix}`. When brandName is set, it substitutes for `{tenant}` (the first token); the suffix (`AutoService 管理后台` / `AutoService Admin`) is unchanged. Tenant-portal users see `B 品牌 · AutoService Admin`. This preserves the "this is an AutoService-hosted admin" cue while prominently showing the tenant brand.
- **Logout error UX** — spec §4.3 doesn't prescribe toast/alert copy; admin-portal has no toast primitive. Decision: redirect to `/login` on both success and error (best-effort cleanup). The backend revoke happens on the server; cookie clearing is HttpOnly (JS can't verify). If fetch fails (network down), the browser will bounce to `/login`, which will fail AuthGate → show the splash with retry. This is fail-loud.
- **redirector test seam** — Batch-9 `AuthGate` already introduced the `redirector?: (to: string) => void` pattern. T6F.4 `AvatarMenu` adopts the same seam (optional prop; default `window.location.assign`) so tests can intercept navigation without unloading jsdom.
- **Back-compat risk for existing test** — `AvatarMenu.test.tsx` asserts `useAdminStore.getState().isLoggedIn === false` after Logout click. We KEEP the zustand `logout()` call before initiating the fetch so the existing assertion still passes. The pre-existing test is NOT modified; additive new cases extend the file.

## Evidence

| Artifact | Location |
|----------|----------|
| Component impl | `frontend/apps/admin-portal/src/components/shell/AdminTopbar.tsx`, `frontend/apps/admin-portal/src/components/shell/AvatarMenu.tsx` |
| Tests | `frontend/apps/admin-portal/src/__tests__/AdminTopbar.test.tsx`, `frontend/apps/admin-portal/src/__tests__/AvatarMenu.test.tsx` |
| Task status row | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 6 — T6F.4 |
