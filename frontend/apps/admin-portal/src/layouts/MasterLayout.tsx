/**
 * T1F.5 · MasterLayout — platform operator (A) view
 *
 * Renders the existing admin-portal experience (login gate + AdminWorkspace
 * with Dashboard / Proposals / Billing / ManagementChat / Wizard tabs).
 *
 * M1 scope: hosts the current tab tree unchanged. Per-tenant filtering of
 * admin/* tabs is deferred to M2 — in M1 these tabs continue to show
 * platform-level aggregated data (see spec §5.3).
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.3
 */
import { useAdminStore } from '../store/adminStore';
import { LoginPage } from '../components/LoginPage';
import { AdminWorkspace } from '../components/AdminWorkspace';

export function MasterLayout() {
  const isLoggedIn = useAdminStore((s) => s.isLoggedIn);
  return isLoggedIn ? <AdminWorkspace /> : <LoginPage />;
}
