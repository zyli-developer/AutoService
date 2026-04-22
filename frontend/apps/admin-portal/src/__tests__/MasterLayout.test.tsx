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
