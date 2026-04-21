/**
 * T6F.5 · TenantLayout — tenant-mode 4-tab shell (M2 spec §4.1)
 *
 * Rendered when:
 *   - `/api/session/mode` returns `mode === "tenant"` (fork deployment), OR
 *   - URL path matches `/tenant/<tid>/admin` (sandbox preview embedded in a
 *     master admin-portal iframe — see App.tsx short-circuit)
 *
 * Shell structure (distinct from M1 placeholder which delegated to
 * `AdminShell` with `variant="master"` plus hideMasterSection):
 *
 *   ┌───────────────────────────────────────────────┐
 *   │  AdminTopbar (brandName, authenticatedAs)     │
 *   ├──────┬────────────────────────────────────────┤
 *   │ Rail │                                        │
 *   │ var= │  canvas (ChatTab | Dashboard |         │
 *   │ ten- │          Proposals | Billing)          │
 *   │  ant │                                        │
 *   └──────┴────────────────────────────────────────┘
 *
 * The Rail is mounted with `variant="tenant"` (batch-10 T6F.3) so the icon
 * set matches spec §4.2: Chat / Dashboard / Proposals / Billing — no
 * Wizard, no Master-section.
 *
 * The Topbar receives `brandName` and `authenticatedAs` from the
 * session payload (batch-9 `useSessionMode`) — populated by AuthGate
 * upstream, so by the time this component mounts, `data.authenticated ===
 * true` and both strings are meaningful.
 *
 * Tab routing mechanism: state-machine on `useAdminStore.activeTab`
 * (same pattern as MasterLayout's AdminShell). No nested `<BrowserRouter>`
 * — App.tsx already dispatches by pathname and adding another router
 * would break React Router v6.
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §4.1, §4.2, §4.3
 */
import { useEffect, useState } from 'react';
import { BrowserRouter } from 'react-router-dom';
import { useSessionMode } from '@autoservice/shared';
import { useAdminStore } from '../store/adminStore';
import { AdminTopbar } from '../components/shell/AdminTopbar';
import { AdminRail } from '../components/shell/AdminRail';
import { ChatTab } from '../components/tenant/ChatTab';
import { DashboardTab } from '../components/DashboardTab';
import { ProposalsTab } from '../components/ProposalsTab';
import { BillingTab } from '../components/BillingTab';
import { DreamTab } from '../components/DreamTab';

type TenantTabKey = 'chat' | 'dashboard' | 'proposals' | 'dream' | 'billing';

const TENANT_TABS: Record<TenantTabKey, React.ComponentType> = {
  chat: ChatTab,
  dashboard: DashboardTab,
  proposals: ProposalsTab,
  dream: DreamTab,
  billing: BillingTab,
};

interface TenantLayoutProps {
  tenantId?: string;
}

/**
 * Inner body — split out so tests can drop `<BrowserRouter>` in when
 * mounting directly (mirror of the MasterRoutes pattern).
 */
export function TenantLayoutBody({ tenantId }: TenantLayoutProps = {}) {
  const { data } = useSessionMode();
  const activeTab = useAdminStore((s) => s.activeTab);
  const setActiveTab = useAdminStore((s) => s.setActiveTab);
  const [navOpen, setNavOpen] = useState(false);

  // Default tenant-mode landing = Chat (spec §4.2 rail slot 1 — primary
  // entry point). Only flip when the stored value is a non-tenant tab
  // (e.g. 'notifications' inherited from a prior master session in the
  // same browser). Explicit user picks are preserved.
  useEffect(() => {
    const tenantKeys: TenantTabKey[] = ['chat', 'dashboard', 'proposals', 'dream', 'billing'];
    if (!tenantKeys.includes(activeTab as TenantTabKey)) {
      setActiveTab('chat');
    }
    // Run once on mount — user-driven tab changes after that are preserved.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const effectiveTab: TenantTabKey =
    activeTab === 'chat' ||
    activeTab === 'dashboard' ||
    activeTab === 'proposals' ||
    activeTab === 'dream' ||
    activeTab === 'billing'
      ? (activeTab as TenantTabKey)
      : 'chat';

  const View = TENANT_TABS[effectiveTab];

  // Empty-string guard — spec §4.3 flicker mitigation. AuthGate ensures
  // `data.authenticated === true` before this mounts, but `brand_name`
  // may briefly be the default 'AutoService' on a cold session.
  const brandName = data?.brand_name ?? '';
  const authenticatedAs = data?.authenticated_as ?? '';

  return (
    <div
      className="cs-shell"
      data-testid="tenant-layout"
      data-tenant-id={tenantId ?? ''}
    >
      <AdminTopbar
        onToggleNav={() => setNavOpen(true)}
        tenantIdOverride={tenantId}
        brandName={brandName}
        authenticatedAs={authenticatedAs}
      />
      <AdminRail
        variant="tenant"
        open={navOpen}
        onClose={() => setNavOpen(false)}
        tenantIdOverride={tenantId}
      />
      <div
        className={`cs-side-backdrop ${navOpen ? 'on' : ''}`}
        data-testid="cs-side-backdrop"
        onClick={() => setNavOpen(false)}
      />
      <main
        className="cs-canvas"
        data-view={effectiveTab}
        data-testid="tenant-canvas"
      >
        <View />
      </main>
    </div>
  );
}

export function TenantLayout({ tenantId }: TenantLayoutProps = {}) {
  // AdminRail uses react-router hooks (useLocation/useNavigate); wrap in a
  // BrowserRouter so they resolve. Tests that want to bypass the real
  // router can mount `<TenantLayoutBody>` directly under a `<MemoryRouter>`.
  return (
    <BrowserRouter>
      <TenantLayoutBody tenantId={tenantId} />
    </BrowserRouter>
  );
}
