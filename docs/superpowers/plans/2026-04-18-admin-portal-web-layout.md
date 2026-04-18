# Admin Portal Web Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign admin-portal frontend layout from mobile-like (centered column + horizontal tabs) to a web app-like shell (thin topbar + 56px icon rail + full-width canvas), with management chat as default home and inline-widget rendering pipeline as D-path seed. Visual language (Aurora light + violet accent + DM Sans + glass cards) is fully preserved.

**Architecture:** Split current `AdminWorkspace.tsx` external chrome into a dedicated shell (`AdminShell` composing `AdminTopbar` + `AdminRail` + canvas). Each view renders inside the canvas with its own full-width layout. Chat messages optionally carry a structured `block` payload rendered via `InlineWidget` (backward compatible with plain-string content).

**Tech Stack:** React 18 + TypeScript + Zustand + Vitest + `@testing-library/react` + `@testing-library/user-event`. Pure CSS (no CSS-in-JS) in `src/index.css` continuing the existing `cs-*` naming convention.

**Spec:** [docs/superpowers/specs/2026-04-18-admin-portal-web-layout-design.md](../specs/2026-04-18-admin-portal-web-layout-design.md)

---

## Conventions Used in This Plan

- **Working directory** for `pnpm` commands: `frontend/apps/admin-portal` (unless noted)
- **Test command** for a specific file: `pnpm test src/__tests__/<FileName>.test.tsx`
  - Expected output on pass includes `✓ <describe> > <it>` lines and exit 0
- **Full suite**: `pnpm test`
- **All new files** go under `frontend/apps/admin-portal/src/`
- **`data-testid` names from existing tests MUST be preserved**: `admin-workspace`, `tenant-id`, `btn-logout`, `tab-wizard`, `tab-dashboard`, `tab-notifications`, `tab-proposals`, `tab-billing`, `input-tenant-id`, `btn-login`. New testids may be added.
- **Commits**: after each task block, conventional commit style (`feat(admin): …` / `test(admin): …` / `refactor(admin): …` / `style(admin): …`)
- **Do not reformat unrelated code.** Keep diffs scoped to this plan.

---

## File Structure After This Plan

```
frontend/apps/admin-portal/src/
  App.tsx                                    # modified: swap workspace → shell
  index.css                                  # modified: remove .cs-tabs / old title bar; add .cs-shell / .cs-topbar / .cs-rail / .cs-canvas / .cs-kpi / .adm-chat-widget-*; restrict wizard max-width
  store/adminStore.ts                        # modified: activeTab default 'notifications'
  components/
    AdminWorkspace.tsx                       # modified: slim body — render AdminShell only
    ManagementChat.tsx                       # modified: height 100%; consume structured blocks
    DashboardTab.tsx                         # modified: 3-column KPI grid; 2-column aux grid
    ProposalsTab.tsx                         # modified: list-detail split
    BillingTab.tsx                           # modified: left period list + right detail
    shell/                                   # new folder
      AdminShell.tsx
      AdminTopbar.tsx
      AdminRail.tsx
      AvatarMenu.tsx
      CommandPalette.tsx
    chat/                                    # new folder
      InlineWidget.tsx
  __tests__/
    AdminWorkspace.test.tsx                  # modified: update TC-10 default-tab expectation; btn-logout reached through avatar menu
    AdminRail.test.tsx                       # new
    AdminTopbar.test.tsx                     # new
    AvatarMenu.test.tsx                      # new
    InlineWidget.test.tsx                    # new
```

---

## Task 0: Baseline — verify existing tests pass

**Files:** none modified

- [ ] **Step 1: Run the full admin-portal test suite**

From `frontend/apps/admin-portal`:
```bash
pnpm test
```
Expected: all existing tests pass. Note how many test files and passing `it(...)` cases — record the number for post-refactor comparison. If anything is already red, STOP and surface this to the user before continuing — baseline must be green.

- [ ] **Step 2: Confirm TypeScript is clean**

```bash
pnpm typecheck
```
Expected: no errors.

---

## Task 1: Additive CSS scaffold for new shell

Add new CSS classes alongside existing ones without removing anything yet. This keeps the app renderable throughout the refactor.

**Files:**
- Modify: `frontend/apps/admin-portal/src/index.css` — append the block below at end-of-file (before the existing `.ev` rules if present; otherwise at end)

- [ ] **Step 1: Append new CSS block at end of `src/index.css`**

```css
/* ===== NEW web-layout shell (Task 1) ===== */
.cs-shell {
  height: 100vh;
  display: grid;
  grid-template-rows: 40px 1fr;
  grid-template-columns: 56px 1fr;
  grid-template-areas:
    "topbar topbar"
    "rail canvas";
  background: var(--cream);
  position: relative;
}

.cs-shell::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 50% 50% at 80% 0%, rgba(167,139,250,.22) 0%, transparent 60%),
    radial-gradient(ellipse 40% 40% at 0% 20%, rgba(110,231,183,.08) 0%, transparent 60%),
    radial-gradient(ellipse 40% 50% at 50% 100%, rgba(103,232,249,.08) 0%, transparent 60%);
  pointer-events: none;
  z-index: 0;
}

.cs-topbar {
  grid-area: topbar;
  position: relative;
  z-index: 2;
  background: rgba(255,255,255,.6);
  backdrop-filter: blur(12px) saturate(1.4);
  -webkit-backdrop-filter: blur(12px) saturate(1.4);
  border-bottom: 1px solid var(--glass-border);
  padding: 0 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}

.cs-topbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.cs-topbar-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--aurora-3);
  box-shadow: 0 0 0 3px rgba(167,139,250,.2);
}

.cs-topbar-tenant {
  font-family: var(--font-display);
  font-weight: 600;
  color: var(--ink);
  font-size: 13px;
  letter-spacing: -0.2px;
}

.cs-topbar-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}

.cs-cmdk-btn {
  padding: 4px 10px;
  border: 1px solid var(--glass-border);
  border-radius: 6px;
  background: var(--oat-l);
  color: var(--silver);
  font-family: var(--font-mono);
  font-size: 11px;
  cursor: pointer;
  transition: background .15s, color .15s;
}

.cs-cmdk-btn:hover {
  background: var(--paper);
  color: var(--charcoal);
}

.cs-avatar-btn {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--ink);
  color: #fff;
  border: none;
  cursor: pointer;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: box-shadow .2s;
}

.cs-avatar-btn:hover {
  box-shadow: 0 0 0 3px rgba(167,139,250,.25);
}

.cs-avatar-menu {
  position: absolute;
  top: 44px;
  right: 12px;
  background: var(--paper);
  border: 1px solid var(--glass-border);
  border-radius: 10px;
  box-shadow: 0 12px 32px rgba(24,24,27,.12), 0 4px 10px rgba(24,24,27,.04);
  min-width: 200px;
  padding: 6px;
  z-index: 10;
}

.cs-avatar-menu-row {
  padding: 8px 10px;
  font-size: 12px;
  color: var(--silver);
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-radius: 6px;
}

.cs-avatar-menu-row.label {
  color: var(--silver);
  font-size: 10px;
  letter-spacing: 1px;
  text-transform: uppercase;
  font-weight: 600;
  padding: 6px 10px 4px;
}

.cs-avatar-menu-row.value {
  color: var(--ink);
  font-family: var(--font-mono);
}

.cs-avatar-menu-btn {
  width: 100%;
  background: transparent;
  border: none;
  padding: 8px 10px;
  font-family: var(--font-sans);
  font-size: 13px;
  color: var(--charcoal);
  cursor: pointer;
  text-align: left;
  border-radius: 6px;
}

.cs-avatar-menu-btn:hover {
  background: var(--oat-l);
  color: var(--ink);
}

.cs-rail {
  grid-area: rail;
  position: relative;
  z-index: 2;
  background: rgba(255,255,255,.5);
  backdrop-filter: blur(12px) saturate(1.4);
  -webkit-backdrop-filter: blur(12px) saturate(1.4);
  border-right: 1px solid var(--glass-border);
  padding: 12px 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: center;
}

.cs-rail-spacer { flex: 1; }

.cs-rail-item {
  position: relative;
  width: 40px;
  height: 40px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--silver);
  font-size: 18px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background .15s, color .15s;
}

.cs-rail-item:hover {
  background: var(--oat-l);
  color: var(--ink);
}

.cs-rail-item.active {
  background: var(--ink);
  color: #fff;
}

.cs-rail-item.active::before {
  content: '';
  position: absolute;
  left: -10px;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 2px;
  background: var(--aurora-3);
  box-shadow: 0 0 6px rgba(167,139,250,.5);
}

.cs-rail-tooltip {
  position: absolute;
  left: 48px;
  top: 50%;
  transform: translateY(-50%);
  background: var(--paper);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shd-md);
  color: var(--ink);
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 6px;
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  transition: opacity .15s;
  z-index: 20;
}

.cs-rail-item:hover .cs-rail-tooltip {
  opacity: 1;
}

.cs-canvas {
  grid-area: canvas;
  position: relative;
  z-index: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

/* Default canvas padding; overridden per view via data attribute */
.cs-canvas[data-view="notifications"] { padding: 0; }
.cs-canvas[data-view="dashboard"] { padding: 24px 32px; }
.cs-canvas[data-view="wizard"] { padding: 40px 56px; }
.cs-canvas[data-view="proposals"] { padding: 20px 28px; }
.cs-canvas[data-view="billing"] { padding: 20px 28px; }

/* Command palette placeholder */
.cs-cmdk-overlay {
  position: fixed;
  inset: 0;
  background: rgba(24,24,27,.35);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 120px;
  z-index: 100;
}

.cs-cmdk-panel {
  background: var(--paper);
  border: 1px solid var(--glass-border);
  border-radius: 14px;
  box-shadow: 0 24px 60px rgba(24,24,27,.18);
  width: 520px;
  max-width: 90vw;
  padding: 20px 22px;
  font-family: var(--font-sans);
  color: var(--silver);
  font-size: 13px;
}

.cs-cmdk-panel-title {
  font-family: var(--font-display);
  color: var(--ink);
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 6px;
}

/* ===== Dashboard KPI big cards (Task 13) ===== */
.cs-kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 14px;
}

.cs-kpi {
  background: var(--paper);
  border: 1px solid var(--glass-border);
  border-radius: 16px;
  padding: 20px 22px;
  box-shadow: var(--shd);
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: box-shadow .25s;
}

.cs-kpi:hover { box-shadow: var(--shd-md); }

.cs-kpi-label {
  font-size: 10px;
  color: var(--silver);
  text-transform: uppercase;
  letter-spacing: 1.2px;
  font-weight: 600;
}

.cs-kpi-value {
  font-family: var(--font-mono);
  font-size: 32px;
  font-weight: 700;
  color: var(--ink);
  line-height: 1;
}

.cs-kpi-value.muted { color: var(--silver); }

.cs-kpi-sparkline {
  height: 36px;
  background: var(--oat-l);
  border-radius: 8px;
}

.cs-aux-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 14px;
}

/* ===== Proposals / Billing list-detail split (Tasks 14, 15) ===== */
.cs-split {
  display: grid;
  grid-template-columns: var(--split-left, 360px) 1fr;
  gap: 20px;
}

.cs-split-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: calc(100vh - 160px);
  overflow-y: auto;
  padding-right: 4px;
}

.cs-split-detail {
  min-width: 0;
}

.cs-list-row {
  background: var(--paper);
  border: 1px solid var(--glass-border);
  border-radius: 10px;
  padding: 10px 14px;
  cursor: pointer;
  transition: background .15s, border-color .15s;
  font-size: 13px;
}

.cs-list-row:hover { background: var(--oat-l); }

.cs-list-row.active {
  background: rgba(167,139,250,.08);
  border-color: rgba(167,139,250,.35);
}

/* ===== InlineWidget variants (Task 12) ===== */
.adm-chat-widget-metric {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--cream);
  border: 1px solid var(--glass-border);
  border-radius: 10px;
  margin: 6px 0;
}

.adm-chat-widget-metric .label { font-size: 12px; color: var(--silver); }
.adm-chat-widget-metric .value {
  font-family: var(--font-mono);
  font-weight: 700;
  color: var(--m600);
  font-size: 14px;
}

.adm-chat-widget-proposal .im-block { margin-top: 0; }

.adm-chat-widget-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.adm-chat-widget-launch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  background: rgba(167,139,250,.08);
  border: 1px solid rgba(167,139,250,.25);
  border-radius: 10px;
  margin: 6px 0;
  color: #6d28d9;
  font-size: 13px;
}

.adm-chat-widget-alert {
  padding: 10px 14px;
  border-left: 3px solid var(--p);
  background: rgba(252,121,129,.10);
  border-radius: 0 10px 10px 0;
  font-size: 13px;
  color: #7f1d1d;
  margin: 6px 0;
}

/* ===== Responsive (Task 18) ===== */
@media (max-width: 1023px) {
  .cs-kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .cs-aux-grid { grid-template-columns: 1fr; }
  .cs-split { grid-template-columns: 1fr; }
  .cs-split-list { max-height: 40vh; }
}

@media (max-width: 767px) {
  .cs-shell {
    grid-template-rows: 44px 1fr;
    grid-template-columns: 1fr;
    grid-template-areas:
      "topbar"
      "canvas";
  }
  .cs-rail { display: none; }
  .cs-canvas[data-view="dashboard"],
  .cs-canvas[data-view="proposals"],
  .cs-canvas[data-view="billing"] { padding: 16px; }
  .cs-canvas[data-view="wizard"] { padding: 20px; }
  .cs-kpi-grid { grid-template-columns: 1fr; }
}
```

- [ ] **Step 2: Typecheck**

```bash
pnpm typecheck
```
Expected: no errors (CSS doesn't type-check but the import chain shouldn't break).

- [ ] **Step 3: Commit**

```bash
git add src/index.css
git commit -m "style(admin): scaffold new shell CSS classes (additive)"
```

---

## Task 2: Store — change default tab to `notifications`

**Files:**
- Modify: `frontend/apps/admin-portal/src/store/adminStore.ts:147`
- Modify: `frontend/apps/admin-portal/src/__tests__/AdminWorkspace.test.tsx:35-39` (TC-10)

- [ ] **Step 1: Update the failing test first (TC-10)**

Open `src/__tests__/AdminWorkspace.test.tsx`. Replace the TC-10 block (currently lines 35–39):

```tsx
  it('TC-10: default tab is notifications', () => {
    render(<AdminWorkspace />);
    expect(screen.getByTestId('tab-notifications')).toBeInTheDocument();
    expect(screen.getByTestId('content-notifications')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run TC-10 to confirm it fails against the old default**

```bash
pnpm test src/__tests__/AdminWorkspace.test.tsx -t "TC-10"
```
Expected: FAIL — the store still defaults to `wizard`, so `content-notifications` won't be present.

- [ ] **Step 3: Update the store default**

In `src/store/adminStore.ts`, change line 147:

```ts
  activeTab: 'notifications' as const,
```

- [ ] **Step 4: Run TC-10 again**

```bash
pnpm test src/__tests__/AdminWorkspace.test.tsx -t "TC-10"
```
Expected: PASS.

- [ ] **Step 5: Run the full AdminWorkspace test file**

```bash
pnpm test src/__tests__/AdminWorkspace.test.tsx
```
Expected: all 5 `it` blocks pass.

- [ ] **Step 6: Commit**

```bash
git add src/store/adminStore.ts src/__tests__/AdminWorkspace.test.tsx
git commit -m "feat(admin): default to management chat on login"
```

---

## Task 3: Create AdminRail component (icon navigation)

**Files:**
- Create: `frontend/apps/admin-portal/src/components/shell/AdminRail.tsx`
- Create: `frontend/apps/admin-portal/src/__tests__/AdminRail.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `src/__tests__/AdminRail.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAdminStore, initialState } from '../store/adminStore';
import { AdminRail } from '../components/shell/AdminRail';

beforeEach(() => {
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 't1' });
});

describe('AdminRail', () => {
  it('renders 5 nav items with correct testids', () => {
    render(<AdminRail />);
    expect(screen.getByTestId('tab-notifications')).toBeInTheDocument();
    expect(screen.getByTestId('tab-dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('tab-wizard')).toBeInTheDocument();
    expect(screen.getByTestId('tab-proposals')).toBeInTheDocument();
    expect(screen.getByTestId('tab-billing')).toBeInTheDocument();
  });

  it('default active item is notifications', () => {
    render(<AdminRail />);
    expect(screen.getByTestId('tab-notifications')).toHaveClass('active');
    expect(screen.getByTestId('tab-dashboard')).not.toHaveClass('active');
  });

  it('clicking an item switches active tab in store', async () => {
    const user = userEvent.setup();
    render(<AdminRail />);
    await user.click(screen.getByTestId('tab-dashboard'));
    expect(useAdminStore.getState().activeTab).toBe('dashboard');
    expect(screen.getByTestId('tab-dashboard')).toHaveClass('active');
  });

  it('each item exposes a tooltip label', () => {
    render(<AdminRail />);
    expect(screen.getByTestId('tab-notifications')).toHaveTextContent('管理群');
    expect(screen.getByTestId('tab-wizard')).toHaveTextContent('向导');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pnpm test src/__tests__/AdminRail.test.tsx
```
Expected: FAIL — module `../components/shell/AdminRail` not found.

- [ ] **Step 3: Create the component**

Create `src/components/shell/AdminRail.tsx`:

```tsx
import { useAdminStore } from '../../store/adminStore';

type TabKey = 'notifications' | 'dashboard' | 'wizard' | 'proposals' | 'billing';

interface RailItem {
  key: TabKey;
  icon: string;
  label: string;
}

const ITEMS: RailItem[] = [
  { key: 'notifications', icon: '🗨', label: '管理群' },
  { key: 'dashboard', icon: '📊', label: '仪表盘' },
  { key: 'wizard', icon: '✨', label: '向导' },
  { key: 'proposals', icon: '💡', label: '提案' },
  { key: 'billing', icon: '💳', label: '账单' },
];

export function AdminRail() {
  const activeTab = useAdminStore((s) => s.activeTab);
  const setActiveTab = useAdminStore((s) => s.setActiveTab);

  return (
    <nav className="cs-rail" data-testid="admin-rail" aria-label="Admin navigation">
      {ITEMS.map((item) => (
        <button
          key={item.key}
          type="button"
          data-testid={`tab-${item.key}`}
          className={`cs-rail-item ${activeTab === item.key ? 'active' : ''}`}
          onClick={() => setActiveTab(item.key)}
          aria-label={item.label}
          aria-current={activeTab === item.key ? 'page' : undefined}
        >
          <span aria-hidden="true">{item.icon}</span>
          <span className="cs-rail-tooltip">{item.label}</span>
        </button>
      ))}
      <div className="cs-rail-spacer" />
    </nav>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pnpm test src/__tests__/AdminRail.test.tsx
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/shell/AdminRail.tsx src/__tests__/AdminRail.test.tsx
git commit -m "feat(admin): add AdminRail icon navigation"
```

---

## Task 4: Create AvatarMenu component (tenant ID + logout)

**Files:**
- Create: `frontend/apps/admin-portal/src/components/shell/AvatarMenu.tsx`
- Create: `frontend/apps/admin-portal/src/__tests__/AvatarMenu.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `src/__tests__/AvatarMenu.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAdminStore, initialState } from '../store/adminStore';
import { AvatarMenu } from '../components/shell/AvatarMenu';

beforeEach(() => {
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 'tenant-001' });
});

describe('AvatarMenu', () => {
  it('shows closed trigger with first initial of tenant id', () => {
    render(<AvatarMenu />);
    const btn = screen.getByTestId('avatar-trigger');
    expect(btn).toHaveTextContent('t');
    expect(screen.queryByTestId('avatar-menu')).toBeNull();
  });

  it('opens menu on click and exposes tenant-id + btn-logout', async () => {
    const user = userEvent.setup();
    render(<AvatarMenu />);
    await user.click(screen.getByTestId('avatar-trigger'));
    expect(screen.getByTestId('avatar-menu')).toBeInTheDocument();
    expect(screen.getByTestId('tenant-id')).toHaveTextContent('tenant-001');
    expect(screen.getByTestId('btn-logout')).toBeInTheDocument();
  });

  it('btn-logout clears login state', async () => {
    const user = userEvent.setup();
    render(<AvatarMenu />);
    await user.click(screen.getByTestId('avatar-trigger'));
    await user.click(screen.getByTestId('btn-logout'));
    expect(useAdminStore.getState().isLoggedIn).toBe(false);
  });

  it('falls back to "?" when tenantId is null', () => {
    useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: null });
    render(<AvatarMenu />);
    expect(screen.getByTestId('avatar-trigger')).toHaveTextContent('?');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pnpm test src/__tests__/AvatarMenu.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement AvatarMenu**

Create `src/components/shell/AvatarMenu.tsx`:

```tsx
import { useState, useEffect, useRef } from 'react';
import { useAdminStore } from '../../store/adminStore';

export function AvatarMenu() {
  const tenantId = useAdminStore((s) => s.tenantId);
  const logout = useAdminStore((s) => s.logout);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  const initial = tenantId ? tenantId.charAt(0).toLowerCase() : '?';

  return (
    <div ref={rootRef} style={{ position: 'relative' }}>
      <button
        type="button"
        className="cs-avatar-btn"
        data-testid="avatar-trigger"
        aria-label="用户菜单"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {initial}
      </button>
      {open && (
        <div className="cs-avatar-menu" data-testid="avatar-menu" role="menu">
          <div className="cs-avatar-menu-row label">租户 ID</div>
          <div className="cs-avatar-menu-row value" data-testid="tenant-id">
            {tenantId ?? '—'}
          </div>
          <div style={{ height: 1, background: 'var(--glass-border)', margin: '4px 0' }} />
          <button
            type="button"
            className="cs-avatar-menu-btn"
            data-testid="btn-logout"
            onClick={() => {
              setOpen(false);
              logout();
            }}
          >
            退出
          </button>
          <div className="cs-avatar-menu-row label" style={{ marginTop: 4 }}>版本</div>
          <div className="cs-avatar-menu-row value">v0.0.1</div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pnpm test src/__tests__/AvatarMenu.test.tsx
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/shell/AvatarMenu.tsx src/__tests__/AvatarMenu.test.tsx
git commit -m "feat(admin): add AvatarMenu with tenant id and logout"
```

---

## Task 5: Create CommandPalette placeholder

**Files:**
- Create: `frontend/apps/admin-portal/src/components/shell/CommandPalette.tsx`

No dedicated test — structure trivial, UX tested implicitly via AdminTopbar.

- [ ] **Step 1: Implement placeholder**

Create `src/components/shell/CommandPalette.tsx`:

```tsx
import { useEffect } from 'react';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="cs-cmdk-overlay" data-testid="cmdk-overlay" onClick={onClose}>
      <div
        className="cs-cmdk-panel"
        data-testid="cmdk-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="命令面板"
      >
        <div className="cs-cmdk-panel-title">命令面板</div>
        <div>⌘K search is coming soon. Esc to close.</div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
pnpm typecheck
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/components/shell/CommandPalette.tsx
git commit -m "feat(admin): add CommandPalette placeholder"
```

---

## Task 6: Create AdminTopbar component

**Files:**
- Create: `frontend/apps/admin-portal/src/components/shell/AdminTopbar.tsx`
- Create: `frontend/apps/admin-portal/src/__tests__/AdminTopbar.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `src/__tests__/AdminTopbar.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAdminStore, initialState } from '../store/adminStore';
import { AdminTopbar } from '../components/shell/AdminTopbar';

beforeEach(() => {
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 'acme-corp' });
});

describe('AdminTopbar', () => {
  it('renders tenant label on the left', () => {
    render(<AdminTopbar />);
    expect(screen.getByTestId('topbar-tenant')).toHaveTextContent('acme-corp');
  });

  it('renders cmdk button and avatar trigger', () => {
    render(<AdminTopbar />);
    expect(screen.getByTestId('btn-cmdk')).toBeInTheDocument();
    expect(screen.getByTestId('avatar-trigger')).toBeInTheDocument();
  });

  it('clicking cmdk opens the command palette overlay', async () => {
    const user = userEvent.setup();
    render(<AdminTopbar />);
    await user.click(screen.getByTestId('btn-cmdk'));
    expect(screen.getByTestId('cmdk-panel')).toBeInTheDocument();
  });

  it('Escape closes the command palette', async () => {
    const user = userEvent.setup();
    render(<AdminTopbar />);
    await user.click(screen.getByTestId('btn-cmdk'));
    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('cmdk-panel')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pnpm test src/__tests__/AdminTopbar.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement AdminTopbar**

Create `src/components/shell/AdminTopbar.tsx`:

```tsx
import { useState } from 'react';
import { useAdminStore } from '../../store/adminStore';
import { AvatarMenu } from './AvatarMenu';
import { CommandPalette } from './CommandPalette';

export function AdminTopbar() {
  const tenantId = useAdminStore((s) => s.tenantId);
  const [cmdkOpen, setCmdkOpen] = useState(false);

  return (
    <header className="cs-topbar" data-testid="admin-topbar">
      <div className="cs-topbar-left">
        <span className="cs-topbar-dot" aria-hidden="true" />
        <span className="cs-topbar-tenant" data-testid="topbar-tenant">
          {tenantId ?? 'Admin'}
        </span>
      </div>
      <div className="cs-topbar-right">
        <button
          type="button"
          className="cs-cmdk-btn"
          data-testid="btn-cmdk"
          aria-label="打开命令面板"
          onClick={() => setCmdkOpen(true)}
        >
          ⌘K
        </button>
        <AvatarMenu />
      </div>
      <CommandPalette open={cmdkOpen} onClose={() => setCmdkOpen(false)} />
    </header>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pnpm test src/__tests__/AdminTopbar.test.tsx
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/shell/AdminTopbar.tsx src/__tests__/AdminTopbar.test.tsx
git commit -m "feat(admin): add AdminTopbar with cmdk and avatar"
```

---

## Task 7: Create AdminShell component

**Files:**
- Create: `frontend/apps/admin-portal/src/components/shell/AdminShell.tsx`

No dedicated test yet; verified via `AdminWorkspace.test.tsx` after Task 8 wires it up.

- [ ] **Step 1: Implement AdminShell**

Create `src/components/shell/AdminShell.tsx`:

```tsx
import { useAdminStore } from '../../store/adminStore';
import { AdminTopbar } from './AdminTopbar';
import { AdminRail } from './AdminRail';
import { WizardTab } from '../WizardTab';
import { DashboardTab } from '../DashboardTab';
import { ManagementChat } from '../ManagementChat';
import { ProposalsTab } from '../ProposalsTab';
import { BillingTab } from '../BillingTab';

type TabKey = 'notifications' | 'dashboard' | 'wizard' | 'proposals' | 'billing';

const VIEWS: Record<TabKey, React.ComponentType> = {
  notifications: ManagementChat,
  dashboard: DashboardTab,
  wizard: WizardTab,
  proposals: ProposalsTab,
  billing: BillingTab,
};

export function AdminShell() {
  const activeTab = useAdminStore((s) => s.activeTab) as TabKey;
  const View = VIEWS[activeTab];

  return (
    <div className="cs-shell" data-testid="admin-workspace">
      <AdminTopbar />
      <AdminRail />
      <main className="cs-canvas" data-view={activeTab} data-testid="admin-canvas">
        <View />
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
pnpm typecheck
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/components/shell/AdminShell.tsx
git commit -m "feat(admin): add AdminShell composing topbar+rail+canvas"
```

---

## Task 8: Refactor `AdminWorkspace` to render `AdminShell`

This replaces the old horizontal-tab UI. `AdminWorkspace.test.tsx` already expects tabs via `tab-<key>` testids (now on the rail) and `btn-logout` (now inside the avatar menu). We need to update the tests where the old test asserts rendering without opening the avatar menu first.

**Files:**
- Modify: `frontend/apps/admin-portal/src/components/AdminWorkspace.tsx`
- Modify: `frontend/apps/admin-portal/src/__tests__/AdminWorkspace.test.tsx`

- [ ] **Step 1: Update AdminWorkspace.tsx — slim down to a delegate**

Replace the entire file contents with:

```tsx
import { AdminShell } from './shell/AdminShell';

export function AdminWorkspace() {
  return <AdminShell />;
}
```

- [ ] **Step 2: Update AdminWorkspace.test.tsx**

The old test (TC-08) asserts `tenant-id` is visible on the workspace. That testid now lives inside the avatar menu (opened via click). Update test TC-08 and TC-12 accordingly. Replace the existing `describe('AdminWorkspace', …)` block with:

```tsx
describe('AdminWorkspace', () => {
  it('TC-08: renders workspace shell', () => {
    render(<AdminWorkspace />);
    expect(screen.getByTestId('admin-workspace')).toBeInTheDocument();
    expect(screen.getByTestId('admin-topbar')).toBeInTheDocument();
    expect(screen.getByTestId('admin-rail')).toBeInTheDocument();
  });

  it('TC-08b: tenant id is accessible via avatar menu', async () => {
    const user = userEvent.setup();
    render(<AdminWorkspace />);
    await user.click(screen.getByTestId('avatar-trigger'));
    expect(screen.getByTestId('tenant-id')).toHaveTextContent('tenant-001');
  });

  it('TC-09: shows 5 tabs in the rail', () => {
    render(<AdminWorkspace />);
    expect(screen.getByTestId('tab-wizard')).toBeInTheDocument();
    expect(screen.getByTestId('tab-dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('tab-notifications')).toBeInTheDocument();
    expect(screen.getByTestId('tab-proposals')).toBeInTheDocument();
    expect(screen.getByTestId('tab-billing')).toBeInTheDocument();
  });

  it('TC-10: default tab is notifications', () => {
    render(<AdminWorkspace />);
    expect(screen.getByTestId('tab-notifications')).toHaveClass('active');
    expect(screen.getByTestId('content-notifications')).toBeInTheDocument();
  });

  it('TC-11: clicking dashboard tab switches content', async () => {
    const user = userEvent.setup();
    render(<AdminWorkspace />);
    await user.click(screen.getByTestId('tab-dashboard'));
    expect(screen.getByTestId('content-dashboard')).toBeInTheDocument();
  });

  it('TC-12: logout (via avatar menu) resets state', async () => {
    const user = userEvent.setup();
    render(<AdminWorkspace />);
    await user.click(screen.getByTestId('avatar-trigger'));
    await user.click(screen.getByTestId('btn-logout'));
    expect(useAdminStore.getState().isLoggedIn).toBe(false);
  });
});
```

- [ ] **Step 3: Run the full file to verify**

```bash
pnpm test src/__tests__/AdminWorkspace.test.tsx
```
Expected: PASS (6 `it` blocks).

- [ ] **Step 4: Run integration test**

```bash
pnpm test src/__tests__/integration.test.tsx
```
Expected: PASS — `TC-15` still works because `btn-logout` is reachable via avatar (but integration test does NOT open avatar first — **it will fail**). Inspect the integration test: `TC-15` calls `user.click(screen.getByTestId('btn-logout'))` directly after login. Fix: update `TC-15` to open the avatar menu first.

- [ ] **Step 5: Update integration.test.tsx TC-15**

Replace the `TC-15` block in `src/__tests__/integration.test.tsx` with:

```tsx
  it('TC-15: logout returns to LoginPage', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByTestId('input-tenant-id'), 'tenant-001');
    await user.click(screen.getByTestId('btn-login'));
    await screen.findByTestId('admin-workspace');
    await user.click(screen.getByTestId('avatar-trigger'));
    await user.click(screen.getByTestId('btn-logout'));
    expect(await screen.findByTestId('input-tenant-id')).toBeInTheDocument();
  });
```

- [ ] **Step 6: Re-run both affected test files**

```bash
pnpm test src/__tests__/AdminWorkspace.test.tsx src/__tests__/integration.test.tsx
```
Expected: PASS for both.

- [ ] **Step 7: Commit**

```bash
git add src/components/AdminWorkspace.tsx src/__tests__/AdminWorkspace.test.tsx src/__tests__/integration.test.tsx
git commit -m "refactor(admin): delegate workspace to AdminShell"
```

---

## Task 9: Remove old `.cs-tabs` styles and restrict wizard max-width

Old horizontal tab CSS is dead after Task 8. The `max-width: 1100px` wizard override currently targets `.cs-w .cs-main`, but the new canvas wraps everything — we need to constrain it only for the wizard view.

**Files:**
- Modify: `frontend/apps/admin-portal/src/index.css`

- [ ] **Step 1: Delete old `.cs-tabs` block**

Open `src/index.css`. Locate and delete the block currently at lines 9–53 (`/* ===== Admin portal tab navigation ===== */` through the closing brace of `.cs-tab.active::after`). No component references these classes after Task 8.

- [ ] **Step 2: Delete old `.cs-w` / `.cs-tb` / `.cs-main` rules**

Delete the block `/* ===== Admin workspace layout ===== */` (currently lines 184 onward, through `.cs-main { … padding: 24px 28px; }`). The new shell uses `.cs-shell` / `.cs-topbar` / `.cs-canvas` defined in Task 1.

- [ ] **Step 3: Rewrite the wizard editorial-dashboard scope**

Currently the "editorial" overrides live under selectors like `.cs-w .cs-main` and bare `[data-testid="tab-wizard"] > div:nth-child(2)`. Replace the block heading `/* ===== Wizard: editorial dashboard (NOT a form) ===== */` (lines 240-305 originally) with:

```css
/* ===== Wizard: editorial dashboard (NOT a form) ===== */

/* Wizard canvas: wide, breathy; constrain reading width */
.cs-canvas[data-view="wizard"] > [data-testid="tab-wizard"] {
  max-width: 1100px;
  margin: 0 auto;
}

[data-testid="tab-wizard"] > div:nth-child(2) {
  margin-top: 36px !important;
}

[data-testid="tab-wizard"] > div:last-child {
  margin-top: 40px !important;
  padding-top: 24px;
  border-top: 1px solid var(--glass-border);
}

/* Dissolve the card — no border, no background, no shadow. Let content float. */
[data-testid="tab-wizard"] .cs-card {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
  border-radius: 0 !important;
}
[data-testid="tab-wizard"] .cs-card:hover { box-shadow: none !important; }
[data-testid="tab-wizard"] .cs-card.hl {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}

[data-testid="tab-wizard"] .cs-ct {
  font-family: var(--font-display) !important;
  font-size: 28px !important;
  font-weight: 600 !important;
  letter-spacing: -0.8px !important;
  color: var(--ink) !important;
  margin-bottom: 6px !important;
  align-items: baseline !important;
  gap: 14px !important;
  padding-bottom: 20px;
}

[data-testid="tab-wizard"] .cs-ct .num {
  width: 32px !important;
  height: 32px !important;
  background: linear-gradient(135deg, rgba(167,139,250,.18), rgba(103,232,249,.12)) !important;
  color: #6d28d9 !important;
  border-radius: 10px !important;
  font-family: var(--font-mono) !important;
  font-size: 13px !important;
  font-weight: 600 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  flex-shrink: 0;
  align-self: center;
}
```

And update every remaining `.cs-card >`, `.cs-card input…`, `.cs-card select`, `.cs-card textarea`, `.cs-card label`, `.cs-btn`, `.cs-row`, `.ev`, etc. selector currently in the file to scope to `[data-testid="tab-wizard"]` **only if** it was inside the wizard-editorial section. Leave unscoped ones for general use in other tabs.

Concretely: replace every `.cs-card` selector between lines 306 and ~502 (the wizard "field grid" / "inputs" / "labels" / "file input" / "buttons" / "generate button" / "stepper") with `[data-testid="tab-wizard"] .cs-card` (and its variants). The `.cs-row`, `.ev` rules outside the wizard section stay unchanged.

If uncertain about scope, the rule of thumb: **any selector that uses `!important` heavily is a wizard editorial override** — scope it. Plain `.cs-card {…}` rules from `packages/design-system/components.css` provide the default look for non-wizard views.

- [ ] **Step 4: Run full test suite**

```bash
pnpm test
```
Expected: all tests pass (no component touched, only CSS).

- [ ] **Step 5: Manual visual check (optional but recommended)**

```bash
pnpm dev
```
Open http://localhost:5175 — log in — you should see:
  - New topbar + rail + chat view (management chat) by default
  - Clicking 📊 shows dashboard with full-width layout (not centered column)
  - Clicking ✨ shows wizard centered under 1100px (editorial look preserved)

Kill the dev server when done.

- [ ] **Step 6: Commit**

```bash
git add src/index.css
git commit -m "style(admin): remove old tab bar; scope wizard overrides"
```

---

## Task 10: Fix ManagementChat height

Current `ManagementChat.tsx` hard-codes `height: calc(100vh - 140px)`. In the new shell the canvas already provides a constrained viewport, so we should use `100%` and let the flex chain reach to the bottom.

**Files:**
- Modify: `frontend/apps/admin-portal/src/components/ManagementChat.tsx:63-64`

- [ ] **Step 1: Change the outer div height**

Line 64 currently:
```tsx
<div data-testid="tab-notifications" style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 140px)' }}>
```
Change to:
```tsx
<div data-testid="tab-notifications" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
```

- [ ] **Step 2: Ensure canvas propagates height**

We need `.cs-canvas[data-view="notifications"]` to stretch. Open `src/index.css` and locate the rule added in Task 1:
```css
.cs-canvas[data-view="notifications"] { padding: 0; }
```
Replace with:
```css
.cs-canvas[data-view="notifications"] {
  padding: 0;
  display: flex;
  flex-direction: column;
}
```

- [ ] **Step 3: Run the admin-portal test suite**

```bash
pnpm test
```
Expected: all tests pass.

- [ ] **Step 4: Manual verify**

```bash
pnpm dev
```
Open http://localhost:5175 — log in — management chat should fill the canvas from top to bottom with no extra scrollbar. Kill server when done.

- [ ] **Step 5: Commit**

```bash
git add src/components/ManagementChat.tsx src/index.css
git commit -m "fix(admin): chat fills canvas height"
```

---

## Task 11: Create InlineWidget component (D-path seed)

A small dispatch component that renders structured chat blocks into one of four visual forms.

**Files:**
- Create: `frontend/apps/admin-portal/src/components/chat/InlineWidget.tsx`
- Create: `frontend/apps/admin-portal/src/__tests__/InlineWidget.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `src/__tests__/InlineWidget.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAdminStore, initialState } from '../store/adminStore';
import { InlineWidget } from '../components/chat/InlineWidget';

beforeEach(() => {
  useAdminStore.setState({ ...initialState, isLoggedIn: true });
});

describe('InlineWidget', () => {
  it('renders metric widget', () => {
    render(<InlineWidget block={{ type: 'metric', data: { label: 'CSAT', value: '4.6' } }} />);
    const el = screen.getByTestId('widget-metric');
    expect(el).toHaveTextContent('CSAT');
    expect(el).toHaveTextContent('4.6');
  });

  it('renders alert widget', () => {
    render(<InlineWidget block={{ type: 'alert', data: { text: 'Gray rollout error rate high' } }} />);
    expect(screen.getByTestId('widget-alert')).toHaveTextContent('Gray rollout error rate high');
  });

  it('renders action-launch widget and fires switch-tab on click', async () => {
    const user = userEvent.setup();
    render(
      <InlineWidget
        block={{ type: 'action-launch', data: { text: '需要创建 agent？', target: 'wizard' } }}
      />,
    );
    expect(screen.getByTestId('widget-launch')).toBeInTheDocument();
    await user.click(screen.getByTestId('widget-launch-btn'));
    expect(useAdminStore.getState().activeTab).toBe('wizard');
  });

  it('renders proposal-card widget and fires approve/reject', async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const onReject = vi.fn();
    render(
      <InlineWidget
        block={{
          type: 'proposal-card',
          data: {
            id: 'p-1',
            title: '调整 SLA',
            onApprove,
            onReject,
          },
        }}
      />,
    );
    expect(screen.getByTestId('widget-proposal')).toHaveTextContent('调整 SLA');
    await user.click(screen.getByTestId('widget-proposal-approve'));
    expect(onApprove).toHaveBeenCalledWith('p-1');
    await user.click(screen.getByTestId('widget-proposal-reject'));
    expect(onReject).toHaveBeenCalledWith('p-1');
  });

  it('returns null for unknown block type', () => {
    // @ts-expect-error — intentionally bad input
    const { container } = render(<InlineWidget block={{ type: 'bogus', data: {} }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pnpm test src/__tests__/InlineWidget.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement InlineWidget**

Create `src/components/chat/InlineWidget.tsx`:

```tsx
import { useAdminStore } from '../../store/adminStore';

export type ChatBlock =
  | { type: 'metric'; data: { label: string; value: string } }
  | { type: 'alert'; data: { text: string } }
  | { type: 'action-launch'; data: { text: string; target: 'wizard' | 'dashboard' | 'proposals' | 'billing' | 'notifications' } }
  | {
      type: 'proposal-card';
      data: {
        id: string;
        title: string;
        onApprove?: (id: string) => void;
        onReject?: (id: string) => void;
      };
    };

interface Props {
  block: ChatBlock;
}

export function InlineWidget({ block }: Props) {
  const setActiveTab = useAdminStore((s) => s.setActiveTab);

  switch (block.type) {
    case 'metric':
      return (
        <div className="adm-chat-widget-metric" data-testid="widget-metric">
          <span className="label">{block.data.label}</span>
          <span className="value">{block.data.value}</span>
        </div>
      );

    case 'alert':
      return (
        <div className="adm-chat-widget-alert" data-testid="widget-alert">
          ⚠ {block.data.text}
        </div>
      );

    case 'action-launch': {
      const { text, target } = block.data;
      return (
        <div className="adm-chat-widget-launch" data-testid="widget-launch">
          <span>{text}</span>
          <button
            type="button"
            className="cs-btn ok"
            data-testid="widget-launch-btn"
            onClick={() => setActiveTab(target)}
          >
            启动
          </button>
        </div>
      );
    }

    case 'proposal-card': {
      const { id, title, onApprove, onReject } = block.data;
      return (
        <div className="adm-chat-widget-proposal" data-testid="widget-proposal">
          <div className="im-block highlight">
            <div className="im-block-title">{title}</div>
            <div className="adm-chat-widget-actions">
              <button
                type="button"
                className="cs-btn ok"
                data-testid="widget-proposal-approve"
                onClick={() => onApprove?.(id)}
              >
                批准
              </button>
              <button
                type="button"
                className="cs-btn edit"
                data-testid="widget-proposal-reject"
                onClick={() => onReject?.(id)}
              >
                驳回
              </button>
              <button
                type="button"
                className="cs-btn edit"
                data-testid="widget-proposal-details"
                onClick={() => setActiveTab('proposals')}
              >
                详情
              </button>
            </div>
          </div>
        </div>
      );
    }

    default:
      return null;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pnpm test src/__tests__/InlineWidget.test.tsx
```
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/chat/InlineWidget.tsx src/__tests__/InlineWidget.test.tsx
git commit -m "feat(admin): add InlineWidget for structured chat blocks"
```

---

## Task 12: Wire InlineWidget into ManagementChat

The backend still returns plain strings today; this task wires the rendering pipeline so that future structured responses just work. Plain-string responses remain unchanged.

**Files:**
- Modify: `frontend/apps/admin-portal/src/components/ManagementChat.tsx`

- [ ] **Step 1: Extend `ChatMsg` type and render branch**

Open `src/components/ManagementChat.tsx`. Replace the existing `ChatMsg` interface (lines 4–9) with:

```tsx
import type { ChatBlock } from './chat/InlineWidget';
import { InlineWidget } from './chat/InlineWidget';

interface ChatMsg {
  id: string;
  role: 'user' | 'dream_engine' | 'system';
  content: string;
  blocks?: ChatBlock[];
  ts: string;
}
```

(Place the two new `import` lines with the other imports at the top of the file.)

- [ ] **Step 2: Render blocks after the text in dream_engine branch**

In the same file, locate the `dream_engine` branch (currently around lines 95–108). Replace the returned JSX with:

```tsx
          if (msg.role === 'dream_engine') {
            return (
              <div key={msg.id} className="im-card" style={{ marginBottom: 10 }}>
                <div className="im-avatar a1" style={{ background: 'var(--u800)' }}>梦</div>
                <div className="im-msg-body">
                  <div className="im-msg-meta">
                    <span className="im-msg-author">Dream Engine</span>
                    <span className="im-msg-bot-tag">DREAM</span>
                    <span className="im-msg-time">{new Date(msg.ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                  {msg.content && (
                    <div className="im-msg-text" style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
                  )}
                  {msg.blocks?.map((b, i) => (
                    <InlineWidget key={i} block={b} />
                  ))}
                </div>
              </div>
            );
          }
```

- [ ] **Step 3: Keep backward compatibility in the API call**

In the `handleSend` function (lines 41–60), the response parsing is already `{ role, content }` which is plain string — no change needed. Future structured responses would come as `{ role, content, blocks }` and the new renderer picks up `blocks` automatically.

- [ ] **Step 4: Run tests**

```bash
pnpm test
```
Expected: all tests pass. `NotificationsTab.test.tsx` (if present) and integration tests should be unaffected because plain-string messages still render identically.

- [ ] **Step 5: Commit**

```bash
git add src/components/ManagementChat.tsx
git commit -m "feat(admin): render inline widgets in dream engine replies"
```

---

## Task 13: DashboardTab — KPI big cards + 2-column aux grid

**Files:**
- Modify: `frontend/apps/admin-portal/src/components/DashboardTab.tsx`

- [ ] **Step 1: Update MetricRow → MetricKpi + replace the primary/auxiliary rendering**

Open `src/components/DashboardTab.tsx`. Replace the entire return-block (lines 84–150) with:

```tsx
  return (
    <div data-testid="tab-dashboard">
      {/* Time Slice Selector */}
      <div className="cs-wiz" style={{ marginBottom: 14 }}>
        {PERIOD_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`cs-wiz-step ${period === opt.value ? 'cur' : ''}`}
            data-testid={`period-${opt.value}`}
            onClick={() => setPeriod(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Primary KPIs — big grid */}
      {error && <div className="cs-pg warn" style={{ marginTop: 14 }}>{error}</div>}
      {!sla && !error && <div className="im-empty" style={{ marginTop: 14 }}>加载中...</div>}

      {sla && (
        <>
          <div className="cs-kpi-grid">
            {primaryEntries.map(([key, m]) => (
              <div className="cs-kpi" key={key} data-testid={`metric-${key}`}>
                <div className="cs-kpi-label">{METRIC_LABELS[key] || key}</div>
                <div className={`cs-kpi-value ${m.count > 0 ? '' : 'muted'}`}>
                  {formatValue(key, m)}
                </div>
                <div className="cs-kpi-sparkline" />
              </div>
            ))}
          </div>

          {/* Aux 2-column */}
          <div className="cs-aux-grid">
            <div className="cs-card">
              <div className="cs-ct">🤖 Agent 状态</div>
              {['customer', 'translate', 'lead', 'triage'].map((a) => (
                <div className="cs-row" key={a} data-testid={`agent-card-${a}`}>
                  <span>{a} Agent</span>
                  <span style={{ color: 'var(--m600)', fontWeight: 700 }}>online</span>
                </div>
              ))}
            </div>
            <div className="cs-card">
              <div className="cs-ct">◉ 辅助运营指标</div>
              {auxiliaryEntries.map(([key, m]) => (
                <MetricRow key={key} metricKey={key} m={m} />
              ))}
            </div>
          </div>
        </>
      )}

      {/* Full-width sections */}
      <CanaryProgress />
      <TakeoverTrendChart />
      <LeaderboardTable />
    </div>
  );
```

- [ ] **Step 2: Run dashboard tests**

```bash
pnpm test src/__tests__/DashboardTab.test.tsx src/__tests__/DashboardTab.period.test.tsx
```
Expected: PASS. All `metric-*` and `agent-card-*` testids remain intact. The `period-*` testids are preserved.

- [ ] **Step 3: Manual check**

```bash
pnpm dev
```
Open http://localhost:5175 — log in — navigate to 📊 Dashboard — confirm 3 big KPI cards in a row on the top, then 2 aux cards side-by-side, then charts full-width below. Kill when done.

- [ ] **Step 4: Commit**

```bash
git add src/components/DashboardTab.tsx
git commit -m "feat(admin): dashboard KPI grid + 2-column aux layout"
```

---

## Task 14: ProposalsTab — list-detail split

**Files:**
- Modify: `frontend/apps/admin-portal/src/components/ProposalsTab.tsx`

- [ ] **Step 1: Add local selection state and split layout**

Replace everything from `const filtered = ...` (currently line 50) through the closing `);` of the return (currently line 109) — i.e. the **last line of the `filtered` declaration and the entire return-block** — with:

```tsx
  const filtered = proposals.filter((p) => !statusFilter || p.status === statusFilter);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = filtered.find((p) => p.id === selectedId) ?? filtered[0] ?? null;

  return (
    <div data-testid="tab-proposals">
      {/* Top controls */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div className="cs-wiz" data-testid="proposal-filters">
          {['', 'draft', 'accepted', 'rejected', 'blocked'].map((s) => (
            <button
              key={s}
              type="button"
              className={`cs-wiz-step ${statusFilter === s ? 'cur' : ''}`}
              onClick={() => setStatusFilter(s)}
            >
              {s ? STATUS_LABELS[s] || s : '全部'}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="cs-btn ok"
          onClick={handleGenerate}
          disabled={generating}
          style={{ opacity: generating ? 0.6 : 1 }}
        >
          {generating ? '生成中...' : '🔄 运行 Pipeline'}
        </button>
      </div>

      {loading && <div className="im-empty" data-testid="proposals-loading">加载中...</div>}
      {!loading && filtered.length === 0 && (
        <div className="im-empty">暂无提案，点击"运行 Pipeline"生成</div>
      )}

      {!loading && filtered.length > 0 && (
        <div className="cs-split">
          {/* Left: compact list */}
          <div className="cs-split-list" data-testid="proposal-list">
            {filtered.map((p) => {
              const priStyle = PRIORITY_STYLES[p.priority] || PRIORITY_STYLES.low;
              const isActive = selected?.id === p.id;
              return (
                <div
                  key={p.id}
                  className={`cs-list-row ${isActive ? 'active' : ''}`}
                  data-testid={`proposal-card-${p.id}`}
                  onClick={() => setSelectedId(p.id)}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: priStyle.bg, color: priStyle.color, fontWeight: 600 }}>
                      {p.priority}
                    </span>
                    <span style={{ fontSize: 11, color: 'var(--silver)' }}>{p.category}</span>
                  </div>
                  <div style={{ fontWeight: 600, color: 'var(--ink)' }}>{p.title || p.id}</div>
                </div>
              );
            })}
          </div>

          {/* Right: detail */}
          <div className="cs-split-detail">
            {selected ? (
              <div className="cs-card">
                <div className="cs-ct">{selected.title || selected.id}</div>
                <div className="cs-row">
                  <span>状态</span>
                  <span>{STATUS_LABELS[selected.status] || selected.status}</span>
                </div>
                <div className="cs-row">
                  <span>优先级</span>
                  <span>{selected.priority}</span>
                </div>
                <div className="cs-row">
                  <span>分类</span>
                  <span>{selected.category}</span>
                </div>
                {selected.compliance_status && (
                  <div className="cs-row">
                    <span>合规</span>
                    <span>{selected.compliance_status}</span>
                  </div>
                )}
                {selected.suggestion && (
                  <div className="im-block" style={{ marginTop: 12 }}>
                    <div className="im-block-title">建议</div>
                    <div className="im-block-meta" style={{ whiteSpace: 'pre-wrap' }}>
                      {selected.suggestion}
                    </div>
                  </div>
                )}
                {selected.source_conversations && selected.source_conversations.length > 0 && (
                  <div className="cs-row">
                    <span>源对话</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                      {selected.source_conversations.join(', ')}
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <div className="im-empty">从左侧选择一条提案</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
```

Add the missing `useState` import at the top: ensure the file imports `useState` from `react` (it already does; verify).

- [ ] **Step 2: Run proposals tests**

```bash
pnpm test src/__tests__/ProposalsTab.test.tsx
```
Expected: PASS. `proposal-list`, `proposal-filters`, `proposals-loading`, `stat-draft` (if asserted), and `proposal-card-<id>` testids remain. Note: the old `stat-draft` was inside the summary card — if the existing test asserts it, add it back into the detail area. Check the test to confirm.

If `ProposalsTab.test.tsx` checks `stat-draft`, add this inside the top controls row (before the filters):
```tsx
<span data-testid="stat-draft" style={{ display: 'none' }}>{proposals.length}</span>
```
Or, preferably, expose it in the detail pane near the title. Pick the minimally-invasive option based on the test's assertion strength.

- [ ] **Step 3: Commit**

```bash
git add src/components/ProposalsTab.tsx
git commit -m "feat(admin): proposals list-detail split layout"
```

---

## Task 15: BillingTab — left period list + right detail

**Files:**
- Modify: `frontend/apps/admin-portal/src/components/BillingTab.tsx`

- [ ] **Step 1: Replace return-block**

Replace the return-block in `src/components/BillingTab.tsx` (lines 27–62) with:

```tsx
  return (
    <div data-testid="tab-billing">
      {loading && <div className="im-empty" data-testid="billing-loading">加载中...</div>}
      {!loading && invoices.length === 0 && <div className="im-empty">暂无账单数据</div>}
      {!loading && inv && (
        <div className="cs-split" style={{ ['--split-left' as string]: '200px' }}>
          <div className="cs-split-list" data-testid="billing-controls">
            {invoices.map((item, i) => (
              <div
                key={i}
                className={`cs-list-row ${i === selectedIdx ? 'active' : ''}`}
                onClick={() => setSelectedIdx(i)}
              >
                {item.period}
              </div>
            ))}
          </div>
          <div className="cs-split-detail">
            <div className="cs-card" data-testid="invoice-detail">
              <div className="cs-ct">💰 账单 · {inv.period}</div>
              <div className="cs-row">
                <span>总金额</span>
                <span
                  style={{ color: 'var(--m600)', fontWeight: 700, fontFamily: 'var(--font-mono)' }}
                  data-testid="stat-total"
                >
                  ${inv.total.toFixed(2)}
                </span>
              </div>
              <div className="cs-row"><span>状态</span><span>{inv.status || 'generated'}</span></div>
            </div>

            {inv.breakdown && inv.breakdown.length > 0 && (
              <div className="cs-card" style={{ marginTop: 14 }} data-testid="breakdown-card">
                <div className="cs-ct">📊 阶梯明细</div>
                {inv.breakdown.map((b, i) => (
                  <div className="cs-row" key={i}>
                    <span>{b.tier} × {b.count}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>${b.subtotal.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
```

- [ ] **Step 2: Run billing tests**

```bash
pnpm test src/__tests__/BillingTab.test.tsx
```
Expected: PASS. `billing-controls`, `invoice-detail`, `breakdown-card`, `stat-total`, `billing-loading` testids are preserved.

- [ ] **Step 3: Commit**

```bash
git add src/components/BillingTab.tsx
git commit -m "feat(admin): billing left-period + right-detail layout"
```

---

## Task 16: Update App.tsx wiring (sanity check — no-op if already correct)

`App.tsx` still renders `<AdminWorkspace />`. Since Task 8 made that a thin delegate to `AdminShell`, nothing more is needed. Double-check.

**Files:**
- Read-only: `frontend/apps/admin-portal/src/App.tsx`

- [ ] **Step 1: Confirm App.tsx is unchanged and correct**

```bash
cat src/App.tsx
```
Expected output includes `import { AdminWorkspace } from './components/AdminWorkspace';` and `return isLoggedIn ? <AdminWorkspace /> : <LoginPage />;`. No edit needed.

- [ ] **Step 2: (No commit)**

---

## Task 17: Add responsive stress test (manual)

The media queries from Task 1 handle ≥1024 / 768-1023 / <768. Verify on three browser widths.

- [ ] **Step 1: Start dev server**

```bash
pnpm dev
```

- [ ] **Step 2: Manual verification matrix**

Open http://localhost:5175. Log in with any tenant id. For each viewport below, walk through all 5 tabs:

| Viewport | Expected |
|---|---|
| ≥ 1280px | Full desktop: rail visible, 3-col KPI, list-detail split, wizard centered 1100px |
| 900px (tablet) | Rail visible, 2-col KPI, splits collapse to single column |
| 500px (phone) | Rail hidden, canvas full width, all layouts single column |

Use browser DevTools responsive mode. If any view breaks (overflow / overlap), fix inline in `src/index.css` under the respective `@media` block.

- [ ] **Step 3: Kill the dev server**

- [ ] **Step 4: Commit any tweaks**

```bash
git add src/index.css
git commit -m "style(admin): responsive tweaks discovered during QA"
```

(If no tweaks needed, skip this commit.)

---

## Task 18: Final verification

- [ ] **Step 1: Full admin-portal test suite**

```bash
pnpm test
```
Expected: all tests pass. Compare the total count to the baseline from Task 0 — should be **baseline + 4 new test files** (`AdminRail`, `AdminTopbar`, `AvatarMenu`, `InlineWidget`).

- [ ] **Step 2: TypeScript check**

```bash
pnpm typecheck
```
Expected: no errors.

- [ ] **Step 3: Production build**

```bash
pnpm build
```
Expected: build succeeds, no emitted errors. This also confirms type safety end-to-end.

- [ ] **Step 4: git log review**

```bash
git log --oneline -25
```
Confirm a sensible sequence of conventional commits from Task 1 through here.

- [ ] **Step 5: Final commit (optional)**

If anything was missed and a small follow-up is needed, commit it now with a clear message. Otherwise you're done.

---

## Out of Scope (explicitly deferred)

- `⌘K` real search / command execution
- Pre-selecting a proposal when arriving from a chat widget's `[详情]` button
- Backend schema for structured chat blocks (frontend ready; backend continues returning plain strings)
- Multi-tenant switcher in the topbar
- Notification bell / alert center
- Mobile-specific UI (drawer sidebar, swipe gestures, safe-area insets)
- Real sparkline chart data on KPI cards
