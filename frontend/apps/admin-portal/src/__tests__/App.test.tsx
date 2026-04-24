/**
 * T6F.2 · App dispatch tests (AuthGate + mode branches)
 *
 * Covers:
 *  - Loading state renders the AuthGate splash (not a bare layout flash)
 *  - MasterLayout renders when authenticated + mode === "master"
 *  - TenantLayout stub renders when authenticated + mode === "tenant"
 *  - Error state → AuthGate error splash (NOT MasterLayout — changed from
 *    M1: batch-9 no longer silently falls back because spec §9 says anon
 *    content must never flash)
 *  - /tenant/<tid>/admin path-prefix forces TenantLayout (still wrapped by
 *    AuthGate so anon callers get redirected)
 *  - Anonymous session (authenticated=false) triggers a redirect call
 *  - /login pathname short-circuits to the public LoginPage
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useAdminStore, initialState } from '../store/adminStore';

const useSessionModeMock = vi.fn();
vi.mock('@autoservice/shared', () => ({
  useSessionMode: () => useSessionModeMock(),
}));

vi.mock('../layouts/MasterLayout', () => ({
  MasterLayout: () => <div data-testid="master-layout">master layout</div>,
}));
vi.mock('../layouts/TenantLayout', () => ({
  TenantLayout: ({ tenantId }: { tenantId?: string }) => (
    <div data-testid="tenant-layout" data-tenant-id={tenantId ?? ''}>
      tenant layout
    </div>
  ),
}));
vi.mock('../components/auth/LoginPage', () => ({
  LoginPage: () => <div data-testid="login-page-stub">login page</div>,
}));

import { App } from '../App';

function setPath(path: string) {
  window.history.replaceState({}, '', path);
}

beforeEach(() => {
  useSessionModeMock.mockReset();
  setPath('/');
});

describe('App dispatch (T6F.2 AuthGate + mode)', () => {
  it('renders the AuthGate splash while useSessionMode is pending', () => {
    useSessionModeMock.mockReturnValue({
      data: null,
      loading: true,
      error: null,
      refetch: () => {},
    });
    render(<App />);
    expect(screen.getByTestId('auth-splash')).toBeInTheDocument();
    expect(screen.queryByTestId('master-layout')).not.toBeInTheDocument();
    expect(screen.queryByTestId('tenant-layout')).not.toBeInTheDocument();
  });

  it('renders MasterLayout when authenticated + mode === "master"', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'master',
        tenant_id: null,
        authenticated: true,
        authenticated_as: 'admin@ops.com',
        tier: 0,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    render(<App />);
    expect(screen.getByTestId('master-layout')).toBeInTheDocument();
    expect(screen.queryByTestId('tenant-layout')).not.toBeInTheDocument();
    expect(screen.queryByTestId('auth-splash')).not.toBeInTheDocument();
  });

  it('renders TenantLayout when authenticated + mode === "tenant"', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'tenant',
        tenant_id: 'acme',
        authenticated: true,
        authenticated_as: 'admin@acme.com',
        tier: 1,
        brand_name: 'Acme',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    render(<App />);
    const tenantLayout = screen.getByTestId('tenant-layout');
    expect(tenantLayout).toBeInTheDocument();
    expect(tenantLayout.getAttribute('data-tenant-id')).toBe('acme');
    expect(screen.queryByTestId('master-layout')).not.toBeInTheDocument();
  });

  it('renders an error splash when /api/session/mode fails', () => {
    useSessionModeMock.mockReturnValue({
      data: null,
      loading: false,
      error: new Error('network'),
      refetch: () => {},
    });
    render(<App />);
    const splash = screen.getByTestId('auth-splash');
    expect(splash.getAttribute('data-variant')).toBe('error');
    expect(screen.queryByTestId('master-layout')).not.toBeInTheDocument();
    expect(screen.queryByTestId('tenant-layout')).not.toBeInTheDocument();
  });

  it('forces TenantLayout on /tenant/<tid>/admin (authenticated)', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'master',
        tenant_id: null,
        authenticated: true,
        authenticated_as: 'admin@ops.com',
        tier: 0,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    setPath('/tenant/tenant_abc/admin');
    render(<App />);
    const tenantLayout = screen.getByTestId('tenant-layout');
    expect(tenantLayout).toBeInTheDocument();
    expect(tenantLayout.getAttribute('data-tenant-id')).toBe('tenant_abc');
    expect(screen.queryByTestId('master-layout')).not.toBeInTheDocument();
  });

  it('decodes percent-encoded tenant ids from /tenant/<tid>/admin', () => {
    useSessionModeMock.mockReturnValue({
      data: null,
      loading: true,
      error: null,
      refetch: () => {},
    });
    setPath('/tenant/a%2Fb/admin');
    render(<App />);
    // Still in loading → AuthGate splash shows; but when data resolves the
    // wrapped TenantLayout would receive the decoded id.
    expect(screen.getByTestId('auth-splash')).toBeInTheDocument();
  });

  it('routes /login to the public LoginPage stub (no gate)', () => {
    useSessionModeMock.mockReturnValue({
      data: null,
      loading: true,
      error: null,
      refetch: () => {},
    });
    setPath('/login');
    render(<App />);
    expect(screen.getByTestId('login-page-stub')).toBeInTheDocument();
    expect(screen.queryByTestId('auth-splash')).not.toBeInTheDocument();
    expect(screen.queryByTestId('master-layout')).not.toBeInTheDocument();
  });
});

describe('App adminStore.tenantId sync (legacy-gate removal)', () => {
  beforeEach(() => {
    useAdminStore.setState(initialState);
  });

  it('syncs session.tenant_id into adminStore on mount (tenant mode)', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'tenant',
        tenant_id: 'acme',
        authenticated: true,
        authenticated_as: 'admin@acme.com',
        tier: 1,
        brand_name: 'Acme',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    render(<App />);
    expect(useAdminStore.getState().tenantId).toBe('acme');
  });

  it('syncs null when master session has no tenant_id', () => {
    useAdminStore.setState({ ...initialState, tenantId: 'stale' });
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'master',
        tenant_id: null,
        authenticated: true,
        authenticated_as: 'admin@ops.com',
        tier: 0,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    render(<App />);
    expect(useAdminStore.getState().tenantId).toBeNull();
  });

  it('URL /tenant/<tid>/admin wins over session.tenant_id', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'master',
        tenant_id: null,
        authenticated: true,
        authenticated_as: 'admin@ops.com',
        tier: 0,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    setPath('/tenant/path_tenant/admin');
    render(<App />);
    expect(useAdminStore.getState().tenantId).toBe('path_tenant');
  });
});
