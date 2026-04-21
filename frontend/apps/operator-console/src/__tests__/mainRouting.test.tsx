/**
 * T7F.3 · operator-console main.tsx mode-routing tests
 *
 * Covers:
 *  1. deriveBasename — master + tenant id
 *  2. deriveBasename — master + null tenant id
 *  3. deriveBasename — tenant mode (URL-flat, basename="")
 *  4. RouteBootstrap — loading state renders Splash
 *  5. RouteBootstrap — error state renders Splash+retry
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const useSessionModeMock = vi.fn();
vi.mock('@autoservice/shared', () => ({
  useSessionMode: () => useSessionModeMock(),
  useTenantId: () => null,
}));

import { deriveBasename, RouteBootstrap } from '../main';

beforeEach(() => {
  useSessionModeMock.mockReset();
});

describe('deriveBasename', () => {
  it('master mode + tenant id → /tenant/<tid>', () => {
    expect(deriveBasename('master', 'acme')).toBe('/tenant/acme');
  });

  it('master mode + null tenant id → empty (URL-flat fall-back)', () => {
    expect(deriveBasename('master', null)).toBe('');
  });

  it('tenant mode → empty (URL-flat; backend middleware rewrote)', () => {
    expect(deriveBasename('tenant', 'acme')).toBe('');
    expect(deriveBasename('tenant', null)).toBe('');
  });
});

describe('RouteBootstrap', () => {
  it('loading → operator-splash rendered, no router content', () => {
    useSessionModeMock.mockReturnValue({
      data: null,
      loading: true,
      error: null,
      refetch: () => {},
    });
    render(<RouteBootstrap />);
    const splash = screen.getByTestId('operator-splash');
    expect(splash).toBeInTheDocument();
    expect(splash.getAttribute('data-variant')).toBe('loading');
    // No router-rendered content should appear during loading.
    expect(screen.queryByTestId('no-tenant-fallback')).not.toBeInTheDocument();
  });

  it('error → operator-splash error variant with retry button calling refetch', async () => {
    const refetch = vi.fn();
    useSessionModeMock.mockReturnValue({
      data: null,
      loading: false,
      error: new Error('network'),
      refetch,
    });
    const user = userEvent.setup();
    render(<RouteBootstrap />);
    const splash = screen.getByTestId('operator-splash');
    expect(splash.getAttribute('data-variant')).toBe('error');
    const retryBtn = screen.getByTestId('operator-splash-retry');
    await user.click(retryBtn);
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
