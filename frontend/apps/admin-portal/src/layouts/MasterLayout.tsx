/**
 * T1F.5 · MasterLayout — platform operator (A) view
 * T1F.6 · adds `/master/tenants` + `/master/tenants/:id/preview` routes.
 * T1F.7 · adds `/master/tenants/new` (wizard) + `/admin/wizard` compat alias.
 *
 * Routes:
 *   /master/tenants             → TenantListTab   (T1F.6)
 *   /master/tenants/new         → WizardTab       (T1F.7 — new-tenant onboarding)
 *   /master/tenants/:id/preview → TenantPreviewTab (T1F.6)
 *   /admin/wizard               → WizardTab       (T1F.7 — backward-compat alias)
 *   otherwise                   → AdminWorkspace  (legacy tab shell)
 *
 * M1 scope: the legacy tab-based AdminWorkspace continues to be the default
 * view. Per-tenant filtering of admin/* tabs is deferred to M2 — in M1 these
 * tabs continue to show platform-level aggregated data (see spec §5.3).
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.2, §5.3
 */
import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, useLocation, Outlet } from 'react-router-dom';
import { useAdminStore } from '../store/adminStore';
import { AdminWorkspace } from '../components/AdminWorkspace';
import { AdminShell } from '../components/shell/AdminShell';
import { WizardTab } from '../components/WizardTab';
import { TenantListTab } from '../components/master/TenantListTab';
import { TenantPreviewTab } from '../components/master/TenantPreviewTab';

/**
 * Wizard wrapper: renders WizardTab with a minimal direct-entry shell and
 * keeps adminStore.activeTab in sync so sidebar highlighting / back-nav
 * stay consistent when a user deep-links to the wizard route.
 */
function WizardRoute() {
  const setActiveTab = useAdminStore((s) => s.setActiveTab);
  const location = useLocation();
  useEffect(() => {
    setActiveTab('wizard');
  }, [location.pathname, setActiveTab]);

  return (
    <div data-testid="master-wizard-route" style={{ padding: 16 }}>
      <WizardTab />
    </div>
  );
}

/**
 * Layout wrapper so /master/* and /admin/wizard routes share the admin
 * topbar + sidebar (AdminShell) with the rest of the app. Previously these
 * routes rendered bare, losing the header and nav rail.
 */
function MasterShellLayout() {
  const location = useLocation();
  const viewTag = location.pathname.startsWith('/master/tenants/new') || location.pathname === '/admin/wizard'
    ? 'wizard'
    : location.pathname.startsWith('/master/tenants/') && location.pathname.endsWith('/preview')
      ? 'tenant-preview'
      : 'master-tenants';
  return (
    <AdminShell viewTag={viewTag}>
      <Outlet />
    </AdminShell>
  );
}

/**
 * Inner router node. Kept separate so tests can mount this under a
 * `<MemoryRouter>` without having to stub out `BrowserRouter`.
 */
export function MasterRoutes() {
  return (
    <Routes>
      <Route element={<MasterShellLayout />}>
        <Route path="/master/tenants" element={<TenantListTab />} />
        <Route path="/master/tenants/new" element={<WizardRoute />} />
        <Route path="/master/tenants/:id/preview" element={<TenantPreviewTab />} />
        <Route path="/admin/wizard" element={<WizardRoute />} />
      </Route>
      {/* Everything else — including the legacy `/` — keeps the existing
          tab-based admin experience. */}
      <Route path="*" element={<AdminWorkspace />} />
    </Routes>
  );
}

export function MasterLayout() {
  return (
    <BrowserRouter>
      <MasterRoutes />
    </BrowserRouter>
  );
}
