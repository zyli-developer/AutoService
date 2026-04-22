/**
 * T6F.5 · TenantLayout 4-tab shell tests
 *
 * Covers spec §4.1 + §4.2 + §4.3 expectations:
 *  - 4 rail tabs rendered (chat / dashboard / proposals / billing) —
 *    tenant variant from batch-10 AdminRail, NO master-section.
 *  - Default active tab = Chat (spec §4.2 rail slot 1).
 *  - Tab click switches canvas view.
 *  - brandName from useSessionMode → topbar (spec §4.3 "B 的 brand_name").
 *  - authenticatedAs from useSessionMode → topbar (spec §4.3 Avatar).
 *
 * We mount TenantLayoutBody under MemoryRouter so the AdminRail's
 * react-router hooks resolve without spawning a second BrowserRouter
 * (the production TenantLayout wraps BrowserRouter internally; MemoryRouter
 * is the test-harness swap).
 */
import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { useAdminStore, initialState } from '../store/adminStore';

// Mock useSessionMode so we control brand_name / authenticated_as.
const useSessionModeMock = vi.fn();
vi.mock('@autoservice/shared', () => ({
  useSessionMode: () => useSessionModeMock(),
}));

// Stub the tab content components — we only care about routing, not rendering depth.
vi.mock('../components/tenant/ChatTab', () => ({
  ChatTab: () => <div data-testid="tenant-chat-tab">chat stub</div>,
}));
vi.mock('../components/DashboardTab', () => ({
  DashboardTab: () => <div data-testid="dashboard-tab-stub">dashboard</div>,
}));
vi.mock('../components/ProposalsTab', () => ({
  ProposalsTab: () => <div data-testid="proposals-tab-stub">proposals</div>,
}));
vi.mock('../components/BillingTab', () => ({
  BillingTab: () => <div data-testid="billing-tab-stub">billing</div>,
}));

import { TenantLayoutBody } from '../layouts/TenantLayout';

function renderBody(ui: ReactNode) {
  return render(<MemoryRouter initialEntries={['/']}>{ui}</MemoryRouter>);
}

const defaultSession = {
  mode: 'tenant' as const,
  tenant_id: 'acme',
  authenticated: true,
  authenticated_as: 'admin@acme.com',
  tier: 1 as const,
  brand_name: 'Acme Shop',
};

beforeEach(() => {
  useAdminStore.setState({ ...initialState, tenantId: 'acme' });
  useSessionModeMock.mockReset();
  useSessionModeMock.mockReturnValue({
    data: defaultSession,
    loading: false,
    error: null,
    refetch: () => {},
  });
});

describe('TenantLayout (T6F.5)', () => {
  it('renders all 4 tenant tabs (chat/dashboard/proposals/billing)', () => {
    renderBody(<TenantLayoutBody tenantId="acme" />);
    expect(screen.getByTestId('tab-chat')).toBeInTheDocument();
    expect(screen.getByTestId('tab-dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('tab-proposals')).toBeInTheDocument();
    expect(screen.getByTestId('tab-billing')).toBeInTheDocument();
  });

  it('does NOT render the master-section nav item (tenant variant)', () => {
    renderBody(<TenantLayoutBody tenantId="acme" />);
    // Spec §4.2 row 6 — Tenants list is "去除" in tenant variant.
    expect(screen.queryByTestId('tab-master-tenants')).not.toBeInTheDocument();
  });

  it('default active view is ChatTab (spec §4.2 rail slot 1)', () => {
    renderBody(<TenantLayoutBody tenantId="acme" />);
    expect(screen.getByTestId('tenant-chat-tab')).toBeInTheDocument();
    expect(screen.queryByTestId('dashboard-tab-stub')).not.toBeInTheDocument();
    // useEffect on mount should have coerced activeTab to 'chat'.
    expect(useAdminStore.getState().activeTab).toBe('chat');
  });

  it('clicking a rail tab switches the canvas view', async () => {
    const user = userEvent.setup();
    renderBody(<TenantLayoutBody tenantId="acme" />);
    await user.click(screen.getByTestId('tab-dashboard'));
    expect(useAdminStore.getState().activeTab).toBe('dashboard');
    expect(screen.getByTestId('dashboard-tab-stub')).toBeInTheDocument();
    expect(screen.queryByTestId('tenant-chat-tab')).not.toBeInTheDocument();
  });

  it('wires brand_name from useSessionMode into the topbar crumb', () => {
    renderBody(<TenantLayoutBody tenantId="acme" />);
    // Topbar renders `topbar-tenant` with the brand when brandName prop set.
    expect(screen.getByTestId('topbar-tenant')).toHaveTextContent('Acme Shop');
  });

  it('wires authenticated_as from useSessionMode into the topbar', () => {
    renderBody(<TenantLayoutBody tenantId="acme" />);
    expect(screen.getByTestId('topbar-authed-as')).toHaveTextContent(
      'admin@acme.com',
    );
  });

  it('falls back to tenantId in the crumb when brand_name is empty', () => {
    useSessionModeMock.mockReturnValue({
      data: { ...defaultSession, brand_name: '' },
      loading: false,
      error: null,
      refetch: () => {},
    });
    renderBody(<TenantLayoutBody tenantId="acme" />);
    // With empty brandName, Topbar flicker-guard falls back to tenantIdOverride ('acme').
    expect(screen.getByTestId('topbar-tenant')).toHaveTextContent('acme');
    // And no "Signed in as" block when authenticatedAs is empty either.
    useSessionModeMock.mockReturnValue({
      data: { ...defaultSession, brand_name: '', authenticated_as: '' },
      loading: false,
      error: null,
      refetch: () => {},
    });
  });
});
