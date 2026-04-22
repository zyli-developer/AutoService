import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '../App';
import { useAdminStore, initialState } from '../store/adminStore';

const useSessionModeMock = vi.fn();
vi.mock('@autoservice/shared', () => ({
  useSessionMode: () => useSessionModeMock(),
}));

// Stub out /api/auth/logout so AvatarMenu's logout button doesn't make a
// real network call in jsdom.
const originalFetch = globalThis.fetch;

beforeEach(() => {
  useAdminStore.setState(initialState);
  useSessionModeMock.mockReset();
  globalThis.fetch = vi.fn().mockResolvedValue(
    new Response('{}', { status: 200 })
  ) as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe('integration (admin-portal App flows)', () => {
  it('TC-13: anon session → AuthGate splash, no AdminWorkspace', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        authenticated: false,
        mode: 'master',
        tenant_id: null,
        authenticated_as: null,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    render(<App />);
    expect(screen.getByTestId('auth-splash')).toBeInTheDocument();
    expect(screen.queryByTestId('admin-workspace')).toBeNull();
  });

  it('TC-14: authenticated master session → AdminWorkspace renders', async () => {
    useSessionModeMock.mockReturnValue({
      data: {
        authenticated: true,
        mode: 'master',
        tenant_id: 'tenant-001',
        authenticated_as: 'admin@ops.com',
        tier: 0,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    render(<App />);
    expect(await screen.findByTestId('admin-workspace')).toBeInTheDocument();
    // Sync effect should have mirrored tenant_id into adminStore.
    await waitFor(() => {
      expect(useAdminStore.getState().tenantId).toBe('tenant-001');
    });
  });

  it('TC-15: clicking Logout resets adminStore and calls /api/auth/logout', async () => {
    useSessionModeMock.mockReturnValue({
      data: {
        authenticated: true,
        mode: 'master',
        tenant_id: 'tenant-001',
        authenticated_as: 'admin@ops.com',
        tier: 0,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByTestId('admin-workspace');
    await user.click(screen.getByTestId('avatar-trigger'));
    await user.click(screen.getByTestId('btn-logout'));
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/auth/logout',
        expect.objectContaining({ method: 'POST' }),
      );
    });
    // logout() resets adminStore to initialState — tenantId cleared.
    expect(useAdminStore.getState().tenantId).toBeNull();
  });
});
