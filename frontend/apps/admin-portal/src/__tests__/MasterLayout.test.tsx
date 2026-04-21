/**
 * T1F.7 · MasterLayout route dispatch tests
 *
 * Covers the pathname-aware dispatch introduced in T1F.7:
 *  - /master/tenants/new  → WizardTab (new-tenant wizard)
 *  - /admin/wizard        → WizardTab (backward-compat alias)
 *  - any other path        → AdminWorkspace (tab shell)
 *  - unauthenticated       → LoginPage
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useAdminStore, initialState } from '../store/adminStore';

vi.mock('../components/LoginPage', () => ({
  LoginPage: () => <div data-testid="login-page">login</div>,
}));
vi.mock('../components/AdminWorkspace', () => ({
  AdminWorkspace: () => <div data-testid="admin-workspace-stub">workspace</div>,
}));
vi.mock('../components/WizardTab', () => ({
  WizardTab: () => <div data-testid="wizard-tab-stub">wizard</div>,
}));

import { MasterLayout } from '../layouts/MasterLayout';

function setPathname(path: string) {
  // jsdom allows location mutation via assignment on pathname through history.
  window.history.replaceState({}, '', path);
}

describe('MasterLayout (T1F.7 route dispatch)', () => {
  beforeEach(() => {
    useAdminStore.setState({ ...initialState, isLoggedIn: true });
    setPathname('/');
  });

  it('renders LoginPage when not authenticated regardless of path', () => {
    useAdminStore.setState({ ...initialState, isLoggedIn: false });
    setPathname('/master/tenants/new');
    render(<MasterLayout />);
    expect(screen.getByTestId('login-page')).toBeInTheDocument();
    expect(screen.queryByTestId('master-wizard-route')).not.toBeInTheDocument();
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
