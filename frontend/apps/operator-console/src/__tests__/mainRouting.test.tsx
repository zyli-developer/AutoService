import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const useSessionModeMock = vi.fn();
vi.mock('@autoservice/shared', () => ({
  useSessionMode: () => useSessionModeMock(),
  useTenantId: () => null,
}));

import { RouteBootstrap } from '../main';

beforeEach(() => {
  useSessionModeMock.mockReset();
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
