/**
 * T6F.2 · AuthGate tests
 *
 * Covers:
 *  1. loading → Splash rendered, children NOT rendered
 *  2. anon (authenticated=false) → redirector called with /login?redirect=<path>
 *  3. authenticated → children rendered, splash absent
 *  4. error → error-variant splash with a retry button that calls refetch
 *  5. loading → authenticated transition never flashes anon content
 *
 * Uses a mocked useSessionMode + an injected `redirector` prop to observe
 * the navigation target without unloading jsdom.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const useSessionModeMock = vi.fn();
vi.mock('@autoservice/shared', () => ({
  useSessionMode: () => useSessionModeMock(),
}));

import { AuthGate } from '../components/auth/AuthGate';

function setPath(path: string) {
  window.history.replaceState({}, '', path);
}

const CHILD = <div data-testid="gated-child">protected</div>;

beforeEach(() => {
  useSessionModeMock.mockReset();
  setPath('/admin');
});

describe('AuthGate', () => {
  it('loading → Splash rendered, children hidden', () => {
    useSessionModeMock.mockReturnValue({
      data: null,
      loading: true,
      error: null,
      refetch: () => {},
    });
    render(<AuthGate>{CHILD}</AuthGate>);
    const splash = screen.getByTestId('auth-splash');
    expect(splash).toBeInTheDocument();
    expect(splash.getAttribute('data-variant')).toBe('loading');
    expect(screen.queryByTestId('gated-child')).not.toBeInTheDocument();
  });

  it('anon → redirector called with /login?redirect=<current path>', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'master',
        tenant_id: null,
        authenticated: false,
        authenticated_as: null,
        tier: null,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    setPath('/admin/dashboard?foo=bar');
    const redirector = vi.fn();
    render(<AuthGate redirector={redirector}>{CHILD}</AuthGate>);
    expect(redirector).toHaveBeenCalledTimes(1);
    const target = redirector.mock.calls[0][0] as string;
    expect(target.startsWith('/login?redirect=')).toBe(true);
    // encoded form of "/admin/dashboard?foo=bar"
    expect(decodeURIComponent(target.split('=', 2)[1])).toBe(
      '/admin/dashboard?foo=bar'
    );
    // Even during the redirect, children MUST NOT render.
    expect(screen.queryByTestId('gated-child')).not.toBeInTheDocument();
    expect(screen.getByTestId('auth-splash')).toBeInTheDocument();
  });

  it('authenticated → children rendered, splash absent', () => {
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'master',
        tenant_id: null,
        authenticated: true,
        authenticated_as: 'ops@autoservice.com',
        tier: 0,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    const redirector = vi.fn();
    render(<AuthGate redirector={redirector}>{CHILD}</AuthGate>);
    expect(screen.getByTestId('gated-child')).toBeInTheDocument();
    expect(screen.queryByTestId('auth-splash')).not.toBeInTheDocument();
    expect(redirector).not.toHaveBeenCalled();
  });

  it('error → error-variant splash with retry button calling refetch', async () => {
    const refetch = vi.fn();
    useSessionModeMock.mockReturnValue({
      data: null,
      loading: false,
      error: new Error('network'),
      refetch,
    });
    const user = userEvent.setup();
    render(<AuthGate>{CHILD}</AuthGate>);
    const splash = screen.getByTestId('auth-splash');
    expect(splash.getAttribute('data-variant')).toBe('error');
    expect(screen.queryByTestId('gated-child')).not.toBeInTheDocument();
    const retryBtn = screen.getByTestId('auth-splash-retry');
    await user.click(retryBtn);
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it('loading → authenticated transition never flashes anon content', () => {
    // Start with loading
    useSessionModeMock.mockReturnValue({
      data: null,
      loading: true,
      error: null,
      refetch: () => {},
    });
    const redirector = vi.fn();
    const { rerender } = render(
      <AuthGate redirector={redirector}>{CHILD}</AuthGate>
    );
    expect(screen.getByTestId('auth-splash')).toBeInTheDocument();
    expect(redirector).not.toHaveBeenCalled();

    // Transition directly to authenticated — skipping any anon state.
    useSessionModeMock.mockReturnValue({
      data: {
        mode: 'master',
        tenant_id: null,
        authenticated: true,
        authenticated_as: 'ops@autoservice.com',
        tier: 0,
        brand_name: 'AutoService',
      },
      loading: false,
      error: null,
      refetch: () => {},
    });
    act(() => {
      rerender(<AuthGate redirector={redirector}>{CHILD}</AuthGate>);
    });
    expect(screen.getByTestId('gated-child')).toBeInTheDocument();
    // No redirect should have been scheduled during the transition.
    expect(redirector).not.toHaveBeenCalled();
  });
});
