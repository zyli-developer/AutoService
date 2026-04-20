/**
 * T1F.5 · MasterLayout — platform operator (A) view
 * T1F.6 · adds `/master/tenants` + `/master/tenants/:id/preview` routes.
 *
 * Renders the existing admin-portal experience (login gate + AdminWorkspace
 * with Dashboard / Proposals / Billing / ManagementChat / Wizard tabs) under
 * the default route, and additionally exposes the Master-view tenant
 * directory and "代入预览" (embody-preview) iframe routes:
 *
 *   /master/tenants            → TenantListTab  (T1F.6)
 *   /master/tenants/:id/preview → TenantPreviewTab (T1F.6)
 *
 * The wizard (and its `/master/tenants/new` route) is wired in by T1F.7.
 *
 * M1 scope: the legacy tab-based AdminWorkspace continues to be the default
 * view. Per-tenant filtering of admin/* tabs is deferred to M2 — in M1 these
 * tabs continue to show platform-level aggregated data (see spec §5.3).
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.2, §5.3
 */
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { useAdminStore } from '../store/adminStore';
import { LoginPage } from '../components/LoginPage';
import { AdminWorkspace } from '../components/AdminWorkspace';
import { TenantListTab } from '../components/master/TenantListTab';
import { TenantPreviewTab } from '../components/master/TenantPreviewTab';

/**
 * Inner router node. Kept separate so tests can mount this under a
 * `<MemoryRouter>` without having to stub out `BrowserRouter`.
 */
export function MasterRoutes() {
  return (
    <Routes>
      <Route path="/master/tenants" element={<TenantListTab />} />
      <Route path="/master/tenants/:id/preview" element={<TenantPreviewTab />} />
      {/* Everything else — including the legacy `/` — keeps the existing
          tab-based admin experience. */}
      <Route path="*" element={<AdminWorkspace />} />
    </Routes>
  );
}

export function MasterLayout() {
  const isLoggedIn = useAdminStore((s) => s.isLoggedIn);
  if (!isLoggedIn) return <LoginPage />;
  return (
    <BrowserRouter>
      <MasterRoutes />
    </BrowserRouter>
  );
}
