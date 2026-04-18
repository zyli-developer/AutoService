import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAdminStore, initialState } from '../store/adminStore';

// Mock child components to avoid duplicate testid collisions and API calls
vi.mock('../components/WizardTab', () => ({ WizardTab: () => <div data-testid="content-wizard">wizard content</div> }));
vi.mock('../components/DashboardTab', () => ({ DashboardTab: () => <div data-testid="content-dashboard">dashboard content</div> }));
vi.mock('../components/ManagementChat', () => ({ ManagementChat: () => <div data-testid="content-notifications">chat content</div> }));
vi.mock('../components/ProposalsTab', () => ({ ProposalsTab: () => <div data-testid="content-proposals">proposals content</div> }));
vi.mock('../components/BillingTab', () => ({ BillingTab: () => <div data-testid="content-billing">billing content</div> }));

import { AdminWorkspace } from '../components/AdminWorkspace';

beforeEach(() => {
  useAdminStore.setState({ ...initialState, isLoggedIn: true, tenantId: 'tenant-001' });
});

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
