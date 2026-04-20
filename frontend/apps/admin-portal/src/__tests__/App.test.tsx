/**
 * T1F.5 · App dual-mode dispatch tests
 *
 * Covers:
 *  - Loading state renders while useSessionMode is pending
 *  - MasterLayout renders when mode === "master"
 *  - TenantLayout stub renders when mode === "tenant"
 *  - Master fallback renders on error (M1 safety behaviour)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

// Stub the shared hook before App is imported.
const useSessionModeMock = vi.fn();
vi.mock('@autoservice/shared', () => ({
  useSessionMode: () => useSessionModeMock(),
}));

// Stub both layouts — we only care about which one App selects, not their internals.
vi.mock('../layouts/MasterLayout', () => ({
  MasterLayout: () => <div data-testid="master-layout">master layout</div>,
}));
vi.mock('../layouts/TenantLayout', () => ({
  TenantLayout: () => <div data-testid="tenant-layout">tenant layout</div>,
}));

import { App } from '../App';

beforeEach(() => {
  useSessionModeMock.mockReset();
});

describe('App dual-mode dispatch', () => {
  it('renders loading state while useSessionMode is pending', () => {
    useSessionModeMock.mockReturnValue({ data: null, loading: true, error: null });
    render(<App />);
    expect(screen.getByTestId('session-mode-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('master-layout')).not.toBeInTheDocument();
    expect(screen.queryByTestId('tenant-layout')).not.toBeInTheDocument();
  });

  it('renders MasterLayout when mode === "master"', () => {
    useSessionModeMock.mockReturnValue({
      data: { mode: 'master', role: 'platform_admin' },
      loading: false,
      error: null,
    });
    render(<App />);
    expect(screen.getByTestId('master-layout')).toBeInTheDocument();
    expect(screen.queryByTestId('tenant-layout')).not.toBeInTheDocument();
  });

  it('renders TenantLayout stub when mode === "tenant"', () => {
    useSessionModeMock.mockReturnValue({
      data: { mode: 'tenant', role: 'tenant_admin', tenant_id: 'B' },
      loading: false,
      error: null,
    });
    render(<App />);
    expect(screen.getByTestId('tenant-layout')).toBeInTheDocument();
    expect(screen.queryByTestId('master-layout')).not.toBeInTheDocument();
  });

  it('falls back to MasterLayout on error (M1 safe default)', () => {
    useSessionModeMock.mockReturnValue({
      data: null,
      loading: false,
      error: new Error('network'),
    });
    render(<App />);
    expect(screen.getByTestId('master-layout')).toBeInTheDocument();
    expect(screen.queryByTestId('tenant-layout')).not.toBeInTheDocument();
  });
});
