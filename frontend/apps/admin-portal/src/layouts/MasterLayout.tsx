/**
 * T1F.5 · MasterLayout — platform operator (A) view
 * T1F.7 · Adds path-aware dispatch for the new-tenant wizard route
 *
 * Renders the existing admin-portal experience (login gate + AdminWorkspace
 * with Dashboard / Proposals / Billing / ManagementChat / Wizard tabs).
 *
 * M1 scope: hosts the current tab tree unchanged. Per-tenant filtering of
 * admin/* tabs is deferred to M2 — in M1 these tabs continue to show
 * platform-level aggregated data (see spec §5.3).
 *
 * Master-level routes (lightweight pathname dispatch; no react-router yet):
 *   /master/tenants/new → WizardTab (new-tenant onboarding wizard)
 *   /admin/wizard       → WizardTab (backward-compat alias)
 *   otherwise           → AdminWorkspace (tab shell)
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.2 / §5.3
 */
import { useEffect } from 'react';
import { useAdminStore } from '../store/adminStore';
import { LoginPage } from '../components/LoginPage';
import { AdminWorkspace } from '../components/AdminWorkspace';
import { WizardTab } from '../components/WizardTab';

/** Paths that should force the wizard view. */
const WIZARD_PATHS = ['/master/tenants/new', '/admin/wizard'];

function pathMatchesWizard(pathname: string): boolean {
  return WIZARD_PATHS.some(
    (p) => pathname === p || pathname.startsWith(p + '/'),
  );
}

export function MasterLayout() {
  const isLoggedIn = useAdminStore((s) => s.isLoggedIn);
  const setActiveTab = useAdminStore((s) => s.setActiveTab);

  const pathname =
    typeof window !== 'undefined' ? window.location.pathname : '/';
  const isWizardRoute = pathMatchesWizard(pathname);

  // When the URL points at the wizard route, keep the tab shell's state in
  // sync so back-navigation and sidebar highlights stay consistent.
  useEffect(() => {
    if (isLoggedIn && isWizardRoute) {
      setActiveTab('wizard');
    }
  }, [isLoggedIn, isWizardRoute, setActiveTab]);

  if (!isLoggedIn) return <LoginPage />;

  // Direct-entry wizard route renders a minimal shell wrapping WizardTab so
  // deep links (e.g. /master/tenants/new) work even before the user enters
  // the main tab tree. AdminWorkspace keeps serving all other paths.
  if (isWizardRoute) {
    return (
      <div data-testid="master-wizard-route" style={{ padding: 16 }}>
        <WizardTab />
      </div>
    );
  }

  return <AdminWorkspace />;
}
