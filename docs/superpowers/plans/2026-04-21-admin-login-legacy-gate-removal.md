# Admin Legacy Login Gate Removal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the legacy zustand-based `isLoggedIn` gate in `admin-portal`'s `MasterLayout` that forces already-authenticated admins through a no-op "Tenant ID" form, and delegate all auth to the existing server-side `AuthGate`.

**Architecture:** Delete the second-layer gate in `MasterLayout`; delete the legacy `components/LoginPage.tsx`; replace `adminStore.login()` with a narrower `setTenantId()` action; add a sync `useEffect` at the top of `App` that mirrors `useSessionMode().data.tenant_id` (with `/t/<tid>/admin` URL precedence) into `adminStore.tenantId` so existing consumers (AvatarMenu, AdminRail, AdminTopbar, DreamTab, WizardTab, etc.) keep working.

**Tech Stack:** React 18 + TypeScript, zustand (with persist middleware), vitest + @testing-library/react, pnpm workspaces.

**Spec:** [docs/superpowers/specs/2026-04-21-admin-login-legacy-gate-removal-design.md](../specs/2026-04-21-admin-login-legacy-gate-removal-design.md)

---

## File Structure

### Modified
- `frontend/apps/admin-portal/src/store/adminStore.ts` — add `setTenantId`, later remove `isLoggedIn` + `login`
- `frontend/apps/admin-portal/src/App.tsx` — add sync useEffect
- `frontend/apps/admin-portal/src/layouts/MasterLayout.tsx` — remove `isLoggedIn` gate + `LoginPage` import
- `frontend/apps/admin-portal/src/components/auth/LoginPage.tsx` — remove the "NOTE: this file coexists..." legacy comment
- `frontend/apps/admin-portal/src/__tests__/adminStore.test.ts` — add `setTenantId` TC; later delete `login`/`isLoggedIn` TCs
- `frontend/apps/admin-portal/src/__tests__/App.test.tsx` — add 3 sync-effect TCs
- `frontend/apps/admin-portal/src/__tests__/MasterLayout.test.tsx` — rewrite 2 TCs + drop legacy mock
- `frontend/apps/admin-portal/src/__tests__/integration.test.tsx` — rewrite 3 TCs off legacy form
- 7 test files lose `isLoggedIn: true` setup (one-line each): `AdminRail`, `AdminTopbar`, `AvatarMenu`, `AdminWorkspace`, `TenantLayout`, `InlineWidget`
- `frontend/packages/i18n/src/locales/en.json` + `zh-CN.json` — remove `admin.login.tenant_id` key if unreferenced after Batch 4

### Deleted
- `frontend/apps/admin-portal/src/components/LoginPage.tsx` (legacy tenant-id form)
- `frontend/apps/admin-portal/src/__tests__/LoginPage.test.tsx`

---

## Test Command Reference

Run all admin-portal tests:
```bash
cd frontend/apps/admin-portal && pnpm test
```

Run a single test file:
```bash
cd frontend/apps/admin-portal && npx vitest run src/__tests__/<file>.test.tsx
```

Typecheck the workspace:
```bash
cd frontend && pnpm typecheck
```

---

## Task 1: Add `setTenantId` to adminStore (coexisting with legacy)

**Goal:** Introduce `setTenantId(tenantId: string | null)` action alongside the existing `login`/`isLoggedIn`. No deletion yet — Batches 3–6 need `login` to stay.

**Files:**
- Modify: `frontend/apps/admin-portal/src/__tests__/adminStore.test.ts`
- Modify: `frontend/apps/admin-portal/src/store/adminStore.ts:117,169`

- [ ] **Step 1: Write failing tests for `setTenantId`**

Append to `frontend/apps/admin-portal/src/__tests__/adminStore.test.ts` after the existing `describe` block (stay inside it, add before the closing `});`):

```typescript
  it('TC-05: setTenantId updates tenantId', () => {
    useAdminStore.getState().setTenantId('acme');
    expect(useAdminStore.getState().tenantId).toBe('acme');
  });

  it('TC-06: setTenantId(null) clears tenantId', () => {
    useAdminStore.setState({ ...initialState, tenantId: 'acme' });
    useAdminStore.getState().setTenantId(null);
    expect(useAdminStore.getState().tenantId).toBeNull();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend/apps/admin-portal && npx vitest run src/__tests__/adminStore.test.ts
```

Expected: TC-05 and TC-06 fail with `TypeError: useAdminStore.getState().setTenantId is not a function`. TC-01–TC-04 still pass.

- [ ] **Step 3: Add `setTenantId` action to adminStore**

Edit `frontend/apps/admin-portal/src/store/adminStore.ts`:

In the `AdminState` interface (around line 117), add after `login`:
```typescript
  login: (tenantId: string) => void;
  setTenantId: (tenantId: string | null) => void;
  logout: () => void;
```

In the store body (around line 169), add after the `login` action:
```typescript
      login: (tenantId) => set({ tenantId, isLoggedIn: true }),
      setTenantId: (tenantId) => set({ tenantId }),
      logout: () => set({ ...initialState }),
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend/apps/admin-portal && npx vitest run src/__tests__/adminStore.test.ts
```

Expected: all 6 TCs pass.

- [ ] **Step 5: Typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/apps/admin-portal/src/store/adminStore.ts frontend/apps/admin-portal/src/__tests__/adminStore.test.ts
git commit -m "$(cat <<'EOF'
feat(admin-portal): adminStore — add setTenantId action (coexists with login)

Precursor for removing the legacy isLoggedIn gate: a narrower action
that only updates tenantId without touching the auth flag. The existing
login()/isLoggedIn fields stay for now — downstream MasterLayout and
legacy LoginPage still depend on them until batches 3–6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add App-level sync effect for `adminStore.tenantId`

**Goal:** On every App render, mirror `useSessionMode().data.tenant_id` (or the URL `/t/<tid>/admin` override) into `adminStore.tenantId` via `setTenantId()`. Placed at App top-level to cover both `ModeDispatch` and the path-tenant short-circuit.

**Files:**
- Modify: `frontend/apps/admin-portal/src/__tests__/App.test.tsx` (add 3 TCs)
- Modify: `frontend/apps/admin-portal/src/App.tsx` (add useEffect)

- [ ] **Step 1: Write failing sync-effect tests**

At the top of `frontend/apps/admin-portal/src/__tests__/App.test.tsx`, add this import below the existing imports (around line 17):

```typescript
import { useAdminStore, initialState } from '../store/adminStore';
```

Then append a new `describe` block at the bottom of the file, after the existing `describe('App dispatch (T6F.2 AuthGate + mode)', ...)`:

```typescript
describe('App adminStore.tenantId sync (legacy-gate removal)', () => {
  beforeEach(() => {
    useAdminStore.setState(initialState);
  });

  it('syncs session.tenant_id into adminStore on mount (tenant mode)', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'tenant',
        tenant_id: 'acme',
        authenticated: true,
        authenticated_as: 'admin@acme.com',
        tier: 1,
        brand_name: 'Acme',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    render(<App />);
    expect(useAdminStore.getState().tenantId).toBe('acme');
  });

  it('syncs null when master session has no tenant_id', () => {
    useAdminStore.setState({ ...initialState, tenantId: 'stale' });
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'master',
        tenant_id: null,
        authenticated: true,
        authenticated_as: 'admin@ops.com',
        tier: 0,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    render(<App />);
    expect(useAdminStore.getState().tenantId).toBeNull();
  });

  it('URL /tenant/<tid>/admin wins over session.tenant_id', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'master',
        tenant_id: null,
        authenticated: true,
        authenticated_as: 'admin@ops.com',
        tier: 0,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    setPath('/tenant/path_tenant/admin');
    render(<App />);
    expect(useAdminStore.getState().tenantId).toBe('path_tenant');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend/apps/admin-portal && npx vitest run src/__tests__/App.test.tsx
```

Expected: the 3 new TCs fail (all will show `expected 'acme' to be null` or similar because App doesn't sync yet). The existing 7 TCs still pass.

- [ ] **Step 3: Add sync useEffect to App**

Edit `frontend/apps/admin-portal/src/App.tsx`:

Add to the imports at the top of the file (after line 19):
```typescript
import { useEffect } from 'react';
import { useSessionMode } from '@autoservice/shared';
import { useAdminStore } from './store/adminStore';
import { AuthGate } from './components/auth/AuthGate';
import { LoginPage } from './components/auth/LoginPage';
import { MasterLayout } from './layouts/MasterLayout';
import { TenantLayout } from './layouts/TenantLayout';
```

(Note: `useSessionMode` was only imported inside `ModeDispatch` before. Now it's imported at top-level too — leave the existing `ModeDispatch` usage alone.)

Replace the `export function App()` body (line 46-72) with:

```typescript
export function App() {
  const pathname =
    typeof window !== 'undefined' ? window.location.pathname : '';
  const pathTenantId = tenantIdFromAdminPath(pathname);

  const { data } = useSessionMode();
  const setTenantId = useAdminStore((s) => s.setTenantId);

  useEffect(() => {
    // URL path-tenant wins over session (matches useTenantId semantics at
    // frontend/packages/shared/useTenantId.ts:50-51). When neither is
    // present (anon or master session), clear any stale persisted value.
    setTenantId(pathTenantId ?? data?.tenant_id ?? null);
  }, [pathTenantId, data?.tenant_id, setTenantId]);

  // `/login` public — no gate.
  if (pathname === '/login' || pathname.startsWith('/login/')) {
    return <LoginPage />;
  }

  // `/t/<tid>/admin` path-tenant short-circuit (preserved from M1). Must
  // still pass through AuthGate so anon visitors don't see the tenant
  // shell before the redirect.
  if (pathTenantId) {
    return (
      <AuthGate>
        <TenantLayout tenantId={pathTenantId} />
      </AuthGate>
    );
  }

  return (
    <AuthGate>
      <ModeDispatch />
    </AuthGate>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend/apps/admin-portal && npx vitest run src/__tests__/App.test.tsx
```

Expected: all 10 TCs pass.

- [ ] **Step 5: Run full admin-portal suite (regression check)**

```bash
cd frontend/apps/admin-portal && pnpm test
```

Expected: all tests pass (or at most the known-failing legacy ones — list below, unchanged from baseline).

- [ ] **Step 6: Typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/apps/admin-portal/src/App.tsx frontend/apps/admin-portal/src/__tests__/App.test.tsx
git commit -m "$(cat <<'EOF'
feat(admin-portal): App — sync session.tenant_id into adminStore

Mirrors useSessionMode().data.tenant_id (or the /tenant/<tid>/admin URL
override) into adminStore.tenantId on every App render. Keeps existing
zustand consumers (AvatarMenu, AdminRail, AdminTopbar, DreamTab,
WizardTab, SandboxReady, ComplianceCheckStep) working once the legacy
login form is removed in a later batch.

URL path-tenant wins over session (matches useTenantId semantics).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Remove the legacy gate from `MasterLayout`

**Goal:** Delete the `if (!isLoggedIn) return <LoginPage />` check in `MasterLayout`. After this batch the user-facing bug is fixed — authenticated admins land in `MasterRoutes` directly.

**Files:**
- Modify: `frontend/apps/admin-portal/src/__tests__/MasterLayout.test.tsx` (rewrite 2 TCs, drop legacy mock)
- Modify: `frontend/apps/admin-portal/src/layouts/MasterLayout.tsx` (remove gate + import)

- [ ] **Step 1: Rewrite MasterLayout tests (red)**

Replace the contents of `frontend/apps/admin-portal/src/__tests__/MasterLayout.test.tsx` with:

```typescript
/**
 * T1F.7 · MasterLayout route dispatch tests
 *
 * Covers the pathname-aware dispatch:
 *  - /master/tenants/new  → WizardTab (new-tenant wizard)
 *  - /admin/wizard        → WizardTab (backward-compat alias)
 *  - any other path       → AdminWorkspace (tab shell)
 *
 * Auth is handled upstream by <AuthGate> in App.tsx — MasterLayout itself
 * no longer gates rendering. These tests verify route dispatch unconditionally.
 */
import type { ReactNode } from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useAdminStore, initialState } from '../store/adminStore';

vi.mock('../components/AdminWorkspace', () => ({
  AdminWorkspace: () => <div data-testid="admin-workspace-stub">workspace</div>,
}));
vi.mock('../components/WizardTab', () => ({
  WizardTab: () => <div data-testid="wizard-tab-stub">wizard</div>,
}));
// AdminShell pulls in AdminTopbar/AdminRail which need i18n + the full
// store tree. MasterLayout route dispatch is what we're testing here, so
// replace the shell with a passthrough that still renders its children.
vi.mock('../components/shell/AdminShell', () => ({
  AdminShell: ({ children }: { children?: ReactNode }) => (
    <div data-testid="admin-shell-stub">{children}</div>
  ),
}));

import { MasterLayout } from '../layouts/MasterLayout';

function setPathname(path: string) {
  window.history.replaceState({}, '', path);
}

describe('MasterLayout (T1F.7 route dispatch)', () => {
  beforeEach(() => {
    useAdminStore.setState(initialState);
    setPathname('/');
  });

  it('renders MasterRoutes unconditionally — AuthGate handles auth upstream', () => {
    setPathname('/');
    render(<MasterLayout />);
    expect(screen.getByTestId('admin-workspace-stub')).toBeInTheDocument();
  });

  it('renders AdminWorkspace on the default path', () => {
    setPathname('/');
    render(<MasterLayout />);
    expect(screen.getByTestId('admin-workspace-stub')).toBeInTheDocument();
    expect(screen.queryByTestId('master-wizard-route')).not.toBeInTheDocument();
  });

  it('renders WizardTab under /master/tenants/new', () => {
    setPathname('/master/tenants/new');
    render(<MasterLayout />);
    expect(screen.getByTestId('master-wizard-route')).toBeInTheDocument();
    expect(screen.getByTestId('wizard-tab-stub')).toBeInTheDocument();
    expect(screen.queryByTestId('admin-workspace-stub')).not.toBeInTheDocument();
  });

  it('keeps /admin/wizard working as a backward-compat alias', () => {
    setPathname('/admin/wizard');
    render(<MasterLayout />);
    expect(screen.getByTestId('master-wizard-route')).toBeInTheDocument();
    expect(screen.getByTestId('wizard-tab-stub')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend/apps/admin-portal && npx vitest run src/__tests__/MasterLayout.test.tsx
```

Expected: the first new TC fails because `MasterLayout` still gates on `isLoggedIn=false` and renders the legacy LoginPage (which is no longer mocked, so the real component attempts to mount and either crashes or renders unexpected markup).

- [ ] **Step 3: Remove the gate from MasterLayout**

Edit `frontend/apps/admin-portal/src/layouts/MasterLayout.tsx`:

Remove line 22:
```typescript
import { LoginPage } from '../components/LoginPage';
```

Replace lines 87-95 (the `export function MasterLayout()` block) with:

```typescript
export function MasterLayout() {
  return (
    <BrowserRouter>
      <MasterRoutes />
    </BrowserRouter>
  );
}
```

Also remove the now-unused `useAdminStore` import on line 21 if it's not used elsewhere in the file — grep confirms it isn't:
```typescript
import { useAdminStore } from '../store/adminStore';
```
*(Delete this line.)*

- [ ] **Step 4: Run MasterLayout tests to verify pass**

```bash
cd frontend/apps/admin-portal && npx vitest run src/__tests__/MasterLayout.test.tsx
```

Expected: all 4 TCs pass.

- [ ] **Step 5: Run full admin-portal suite**

```bash
cd frontend/apps/admin-portal && pnpm test
```

Expected: legacy `LoginPage.test.tsx` still passes (not deleted yet); `integration.test.tsx` may now fail TC-13/TC-14/TC-15 because the legacy form is no longer reachable — that's expected and is fixed in Task 7. Note the failure count for comparison with later tasks.

- [ ] **Step 6: Typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/apps/admin-portal/src/layouts/MasterLayout.tsx frontend/apps/admin-portal/src/__tests__/MasterLayout.test.tsx
git commit -m "$(cat <<'EOF'
fix(admin-portal): MasterLayout — drop zustand isLoggedIn gate, trust AuthGate

The zustand isLoggedIn flag was set only by the legacy tenant-id login
form — magic-link callers never flipped it, so authenticated admins got
stuck at a "Tenant ID" prompt after login. AuthGate already gates at
the App level; MasterLayout now renders MasterRoutes unconditionally.

User-facing bug (subtitle says "emailed magic link" but input placeholder
is "Tenant ID") is fixed by this commit. Subsequent batches are cleanup.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Delete the legacy `components/LoginPage.tsx`

**Goal:** Remove the legacy file and its test. Nothing imports it now.

**Files:**
- Delete: `frontend/apps/admin-portal/src/components/LoginPage.tsx`
- Delete: `frontend/apps/admin-portal/src/__tests__/LoginPage.test.tsx`
- Modify: `frontend/apps/admin-portal/src/components/auth/LoginPage.tsx:12-15` (remove stale NOTE)

- [ ] **Step 1: Verify no imports remain before deleting**

```bash
cd frontend && grep -rn "from.*components/LoginPage['\"]" apps/admin-portal/src/ --include="*.ts" --include="*.tsx"
```

Expected: no output (MasterLayout's import was removed in Task 3; nothing else imports the legacy file).

- [ ] **Step 2: Delete the legacy LoginPage and its test**

```bash
rm frontend/apps/admin-portal/src/components/LoginPage.tsx
rm frontend/apps/admin-portal/src/__tests__/LoginPage.test.tsx
```

- [ ] **Step 3: Remove the stale NOTE comment from auth/LoginPage.tsx**

Edit `frontend/apps/admin-portal/src/components/auth/LoginPage.tsx`. Delete lines 12-15 (the 4-line comment starting with "NOTE: this file coexists"):

Before:
```typescript
 * logged when SMTP is not configured (spec §5.6).
 *
 * NOTE: this file coexists with the legacy `components/LoginPage.tsx`
 * (tenant-id-based login used by `MasterLayout`'s zustand `isLoggedIn`
 * flow). M2 will eventually remove the legacy one once `MasterLayout`
 * drops its internal gate and delegates to `<AuthGate>`.
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §4.5, §5.2
```

After:
```typescript
 * logged when SMTP is not configured (spec §5.6).
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §4.5, §5.2
```

- [ ] **Step 4: Run admin-portal suite**

```bash
cd frontend/apps/admin-portal && pnpm test
```

Expected: legacy `LoginPage.test.tsx` is gone; test count drops. `integration.test.tsx` TC-13/TC-14/TC-15 still fail (fixed in Task 7).

- [ ] **Step 5: Typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add -A frontend/apps/admin-portal/src/components/LoginPage.tsx frontend/apps/admin-portal/src/__tests__/LoginPage.test.tsx frontend/apps/admin-portal/src/components/auth/LoginPage.tsx
git commit -m "$(cat <<'EOF'
refactor(admin-portal): delete legacy tenant-id LoginPage + stale comment

The legacy components/LoginPage.tsx (tenant-id form) is no longer
reachable after MasterLayout dropped its isLoggedIn gate in the prior
commit. Deleting the file, its test, and the stale "NOTE: this file
coexists" comment in auth/LoginPage.tsx that flagged the migration.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Remove stale `isLoggedIn: true` setup from consumer tests

**Goal:** 7 test files still pre-seed `isLoggedIn: true` in zustand state. Drop that field from setState calls and drop 2 stray `isLoggedIn` assertions. `isLoggedIn` is still in the store (removed in Task 6), so all tests stay green.

**Files:**
- Modify: `frontend/apps/admin-portal/src/__tests__/AdminRail.test.tsx:23`
- Modify: `frontend/apps/admin-portal/src/__tests__/AdminTopbar.test.tsx:8`
- Modify: `frontend/apps/admin-portal/src/__tests__/AvatarMenu.test.tsx:8, 33, 37`
- Modify: `frontend/apps/admin-portal/src/__tests__/AdminWorkspace.test.tsx:16, 61`
- Modify: `frontend/apps/admin-portal/src/__tests__/TenantLayout.test.tsx:60`
- Modify: `frontend/apps/admin-portal/src/__tests__/InlineWidget.test.tsx:8`

- [ ] **Step 1: AdminRail.test.tsx**

Change line 23:
```typescript
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 't1' });
```
to:
```typescript
  useAdminStore.setState({ ...initialState, tenantId: 't1' });
```

- [ ] **Step 2: AdminTopbar.test.tsx**

Change line 8:
```typescript
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 'acme-corp' });
```
to:
```typescript
  useAdminStore.setState({ ...initialState, tenantId: 'acme-corp' });
```

- [ ] **Step 3: AvatarMenu.test.tsx**

Change line 8:
```typescript
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 'tenant-001' });
```
to:
```typescript
  useAdminStore.setState({ ...initialState, tenantId: 'tenant-001' });
```

Delete the assertion on line 33:
```typescript
    expect(useAdminStore.getState().isLoggedIn).toBe(false);
```
*(delete this line entirely)*

Change line 37:
```typescript
    useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: null });
```
to:
```typescript
    useAdminStore.setState({ ...initialState, tenantId: null });
```

- [ ] **Step 4: AdminWorkspace.test.tsx**

Change line 16:
```typescript
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 'tenant-001' });
```
to:
```typescript
  useAdminStore.setState({ ...initialState, tenantId: 'tenant-001' });
```

Delete the assertion on line 61:
```typescript
    expect(useAdminStore.getState().isLoggedIn).toBe(false);
```
*(delete this line entirely)*

- [ ] **Step 5: TenantLayout.test.tsx**

Change line 60:
```typescript
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 'acme' });
```
to:
```typescript
  useAdminStore.setState({ ...initialState, tenantId: 'acme' });
```

- [ ] **Step 6: InlineWidget.test.tsx**

Change line 8:
```typescript
  useAdminStore.setState({ ...initialState, isLoggedIn: true });
```
to:
```typescript
  useAdminStore.setState({ ...initialState });
```

- [ ] **Step 7: Run admin-portal suite**

```bash
cd frontend/apps/admin-portal && pnpm test
```

Expected: same state as after Task 4 — the 6 files above pass unchanged because `isLoggedIn: true` was a no-op for the gate that no longer exists. `integration.test.tsx` TC-13/14/15 still fail (Task 7).

- [ ] **Step 8: Typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/apps/admin-portal/src/__tests__/AdminRail.test.tsx frontend/apps/admin-portal/src/__tests__/AdminTopbar.test.tsx frontend/apps/admin-portal/src/__tests__/AvatarMenu.test.tsx frontend/apps/admin-portal/src/__tests__/AdminWorkspace.test.tsx frontend/apps/admin-portal/src/__tests__/TenantLayout.test.tsx frontend/apps/admin-portal/src/__tests__/InlineWidget.test.tsx
git commit -m "$(cat <<'EOF'
test(admin-portal): drop stale isLoggedIn:true setup from consumer tests

isLoggedIn has been a dead flag since MasterLayout stopped gating on it.
Removing it from 6 test files' setState setup + 2 stray assertions so
adminStore can drop the field cleanly in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Delete `isLoggedIn` + `login` from adminStore

**Goal:** With Tasks 3–5 done, `isLoggedIn` and `login` have no remaining callers. Delete them.

**Files:**
- Modify: `frontend/apps/admin-portal/src/__tests__/adminStore.test.ts` (delete TC-01, TC-02)
- Modify: `frontend/apps/admin-portal/src/store/adminStore.ts:96, 117, 150, 169` (delete `isLoggedIn` + `login`)

- [ ] **Step 1: Delete adminStore TC-01 and TC-02**

Edit `frontend/apps/admin-portal/src/__tests__/adminStore.test.ts`. Remove lines 9-22 (the two blocks `TC-01: login sets tenantId and isLoggedIn` and `TC-02: logout resets state`).

The file should now contain TC-03, TC-04, TC-05, TC-06 plus a new TC-02-replacement for `logout`:

Add this TC in place of the old TC-02 (after TC-03/TC-04, before TC-05):

```typescript
  it('TC-02: logout resets tenantId', () => {
    useAdminStore.setState({ ...initialState, tenantId: 'tenant-001' });
    useAdminStore.getState().logout();
    expect(useAdminStore.getState().tenantId).toBeNull();
  });
```

- [ ] **Step 2: Run adminStore tests — should still pass before removing the fields**

```bash
cd frontend/apps/admin-portal && npx vitest run src/__tests__/adminStore.test.ts
```

Expected: 5 TCs pass (TC-02 replacement + TC-03/TC-04/TC-05/TC-06).

- [ ] **Step 3: Delete `isLoggedIn` and `login` from adminStore**

Edit `frontend/apps/admin-portal/src/store/adminStore.ts`:

Delete line 96 inside the `AdminState` interface:
```typescript
  isLoggedIn: boolean;
```

Delete the `login` entry around line 117 inside the `AdminState` interface:
```typescript
  login: (tenantId: string) => void;
```

Delete line 150 inside `initialState`:
```typescript
  isLoggedIn: false,
```

Delete the `login` action around line 169 in the store body:
```typescript
      login: (tenantId) => set({ tenantId, isLoggedIn: true }),
```

- [ ] **Step 4: Run adminStore tests + typecheck**

```bash
cd frontend/apps/admin-portal && npx vitest run src/__tests__/adminStore.test.ts
cd frontend && pnpm typecheck
```

Expected: all 5 TCs pass; typecheck clean.

- [ ] **Step 5: Run full admin-portal suite**

```bash
cd frontend/apps/admin-portal && pnpm test
```

Expected: integration.test.tsx TC-13/14/15 still failing (Task 7 fixes). Everything else green.

- [ ] **Step 6: Commit**

```bash
git add frontend/apps/admin-portal/src/store/adminStore.ts frontend/apps/admin-portal/src/__tests__/adminStore.test.ts
git commit -m "$(cat <<'EOF'
refactor(admin-portal): adminStore — drop dead isLoggedIn + login

Both were orphaned after MasterLayout's isLoggedIn gate was removed
and the legacy tenant-id form was deleted. Session authentication
lives entirely in server-side cookies + AuthGate now. zustand persist
silently ignores the stale isLoggedIn field in any user's localStorage
— no migration code needed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Rewrite `integration.test.tsx` off the legacy form

**Goal:** The 3 TCs currently drive the deleted legacy form. Rewrite them to drive adminStore directly + a mocked `useSessionMode`, covering the same flows (anon view, authenticated view, logout).

**Files:**
- Modify: `frontend/apps/admin-portal/src/__tests__/integration.test.tsx`

- [ ] **Step 1: Replace integration.test.tsx wholesale**

Overwrite `frontend/apps/admin-portal/src/__tests__/integration.test.tsx` with:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '../App';
import { useAdminStore, initialState } from '../store/adminStore';

const useSessionModeMock = vi.fn();
vi.mock('@autoservice/shared', () => ({
  useSessionMode: () => useSessionModeMock(),
}));

// Stub out /api/auth/logout so AvatarMenu's logout button doesn't make a
// real network call in jsdom.
const originalFetch = globalThis.fetch;

beforeEach(() => {
  useAdminStore.setState(initialState);
  useSessionModeMock.mockReset();
  globalThis.fetch = vi.fn().mockResolvedValue(
    new Response('{}', { status: 200 })
  ) as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe('integration (admin-portal App flows)', () => {
  it('TC-13: anon session → AuthGate splash, no AdminWorkspace', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        authenticated: false,
        mode: 'master',
        tenant_id: null,
        authenticated_as: null,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    render(<App />);
    expect(screen.getByTestId('auth-splash')).toBeInTheDocument();
    expect(screen.queryByTestId('admin-workspace')).toBeNull();
  });

  it('TC-14: authenticated master session → AdminWorkspace renders', async () => {
    useSessionModeMock.mockReturnValue({
      data: {
        authenticated: true,
        mode: 'master',
        tenant_id: 'tenant-001',
        authenticated_as: 'admin@ops.com',
        tier: 0,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    render(<App />);
    expect(await screen.findByTestId('admin-workspace')).toBeInTheDocument();
    // Sync effect should have mirrored tenant_id into adminStore.
    await waitFor(() => {
      expect(useAdminStore.getState().tenantId).toBe('tenant-001');
    });
  });

  it('TC-15: clicking Logout resets adminStore and calls /api/auth/logout', async () => {
    useSessionModeMock.mockReturnValue({
      data: {
        authenticated: true,
        mode: 'master',
        tenant_id: 'tenant-001',
        authenticated_as: 'admin@ops.com',
        tier: 0,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByTestId('admin-workspace');
    await user.click(screen.getByTestId('avatar-trigger'));
    await user.click(screen.getByTestId('btn-logout'));
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/auth/logout',
        expect.objectContaining({ method: 'POST' }),
      );
    });
    // logout() resets adminStore to initialState — tenantId cleared.
    expect(useAdminStore.getState().tenantId).toBeNull();
  });
});
```

- [ ] **Step 2: Run integration tests**

```bash
cd frontend/apps/admin-portal && npx vitest run src/__tests__/integration.test.tsx
```

Expected: all 3 TCs pass.

- [ ] **Step 3: Run full admin-portal suite**

```bash
cd frontend/apps/admin-portal && pnpm test
```

Expected: all tests green.

- [ ] **Step 4: Typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/admin-portal/src/__tests__/integration.test.tsx
git commit -m "$(cat <<'EOF'
test(admin-portal): integration — rewrite flows off the deleted legacy form

The 3 TCs (anon view, authenticated view, logout) previously drove the
legacy input-tenant-id form. Now they mock useSessionMode for session
state, assert AuthGate splash for anon, AdminWorkspace for authenticated,
and verify the Logout button both resets adminStore and calls
/api/auth/logout.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: i18n key cleanup

**Goal:** Remove `admin.login.tenant_id` from `en.json` + `zh-CN.json` if no live code references it. `operator.login.tenant_id` stays (operator-console is out of scope).

**Files (conditional):**
- Modify: `frontend/packages/i18n/src/locales/en.json:195`
- Modify: `frontend/packages/i18n/src/locales/zh-CN.json:195` *(line approximate — verify with grep)*

- [ ] **Step 1: Scan for remaining `admin.login.tenant_id` references**

```bash
cd frontend && grep -rn "admin\.login\.tenant_id" packages/ apps/ --include="*.ts" --include="*.tsx" --include="*.json"
```

Expected output: only the two i18n JSON entries (en.json and zh-CN.json). If any `.ts`/`.tsx` file still references it, STOP and investigate — something was missed.

- [ ] **Step 2: Also check `admin.login.subtitle` is still referenced**

`admin.login.subtitle` is used by the new `auth/LoginPage.tsx` (verified — keep it).

```bash
cd frontend && grep -rn "admin\.login\.subtitle" apps/admin-portal/src/ --include="*.ts" --include="*.tsx"
```

Expected: at least one hit in `components/auth/LoginPage.tsx`.

- [ ] **Step 3: Remove `admin.login.tenant_id` from en.json**

Edit `frontend/packages/i18n/src/locales/en.json`. Delete line 195:
```json
  "admin.login.tenant_id": "Tenant ID",
```

Verify the surrounding JSON still has valid comma placement (no trailing comma before `}`, no doubled comma after).

- [ ] **Step 4: Remove `admin.login.tenant_id` from zh-CN.json**

Edit `frontend/packages/i18n/src/locales/zh-CN.json`. Find the line with `"admin.login.tenant_id": "Tenant ID"` (approximately line 195) and delete it. Verify JSON comma placement.

- [ ] **Step 5: Sanity check JSON files parse**

```bash
cd frontend && node -e "JSON.parse(require('fs').readFileSync('packages/i18n/src/locales/en.json'))" && node -e "JSON.parse(require('fs').readFileSync('packages/i18n/src/locales/zh-CN.json'))"
```

Expected: no output (both parse cleanly). Any `SyntaxError` means a stray comma.

- [ ] **Step 6: Run admin-portal suite + typecheck**

```bash
cd frontend/apps/admin-portal && pnpm test
cd frontend && pnpm typecheck
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add frontend/packages/i18n/src/locales/en.json frontend/packages/i18n/src/locales/zh-CN.json
git commit -m "$(cat <<'EOF'
chore(i18n): drop orphaned admin.login.tenant_id key

No live references remain after the legacy admin tenant-id login form
was deleted. operator.login.tenant_id stays — operator-console has its
own (separate) legacy form outside this cleanup's scope.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Verification Checklist

After all 8 batches:

- [ ] `cd frontend/apps/admin-portal && pnpm test` — all green
- [ ] `cd frontend && pnpm typecheck` — clean
- [ ] Manual smoke (if backend available): `make run-web`, visit `/admin`, magic-link login flow should land directly on `AdminWorkspace` without seeing a "Tenant ID" form
- [ ] `git log --oneline 243be6c..HEAD` shows 8 cleanly-scoped commits

## Rollback Notes

- **Batch 3 is the user-visible fix** — all later batches are cleanup. If Batch 4–8 reveal problems, the bug is already fixed; the cleanup can be paused / partially reverted.
- **Persist compat**: zustand localStorage schema change (drop `isLoggedIn`) is silently handled by zustand's persist middleware — no migration required.
- **Operator-console is not touched** — if anything in operator-console breaks, it's a coincidence, not this change.
