import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useAdminStore, initialState } from '../store/adminStore';
import { AvatarMenu } from '../components/shell/AvatarMenu';

beforeEach(() => {
  useAdminStore.setState({ ...initialState, tenantId: 'tenant-001' });
});

describe('AvatarMenu', () => {
  it('shows closed trigger with first initial of tenant id', () => {
    render(<AvatarMenu />);
    const btn = screen.getByTestId('avatar-trigger');
    expect(btn).toHaveTextContent('t');
    expect(screen.queryByTestId('avatar-menu')).toBeNull();
  });

  it('opens menu on click and exposes tenant-id + btn-logout', async () => {
    const user = userEvent.setup();
    render(<AvatarMenu />);
    await user.click(screen.getByTestId('avatar-trigger'));
    expect(screen.getByTestId('avatar-menu')).toBeInTheDocument();
    expect(screen.getByTestId('tenant-id')).toHaveTextContent('tenant-001');
    expect(screen.getByTestId('btn-logout')).toBeInTheDocument();
  });

  it('btn-logout resets adminStore (tenantId cleared)', async () => {
    const user = userEvent.setup();
    render(<AvatarMenu />);
    await user.click(screen.getByTestId('avatar-trigger'));
    await user.click(screen.getByTestId('btn-logout'));
    expect(useAdminStore.getState().tenantId).toBeNull();
  });

  it('falls back to "?" when tenantId is null', () => {
    useAdminStore.setState({ ...initialState, tenantId: null });
    render(<AvatarMenu />);
    expect(screen.getByTestId('avatar-trigger')).toHaveTextContent('?');
  });

  // T6F.4 — new logout flow (spec §4.3 + §5)
  describe('logout integration', () => {
    let fetchMock: ReturnType<typeof vi.fn>;
    let redirector: ReturnType<typeof vi.fn>;

    beforeEach(() => {
      fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
      vi.stubGlobal('fetch', fetchMock);
      redirector = vi.fn();
    });

    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it('btn-logout POSTs /api/auth/logout with credentials', async () => {
      const user = userEvent.setup();
      render(<AvatarMenu redirector={redirector} />);
      await user.click(screen.getByTestId('avatar-trigger'));
      await user.click(screen.getByTestId('btn-logout'));
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/auth/logout',
        expect.objectContaining({ method: 'POST', credentials: 'include' }),
      );
    });

    it('redirects to /login after logout', async () => {
      const user = userEvent.setup();
      render(<AvatarMenu redirector={redirector} />);
      await user.click(screen.getByTestId('avatar-trigger'));
      await user.click(screen.getByTestId('btn-logout'));
      expect(redirector).toHaveBeenCalledWith('/login');
    });

    it('network error still triggers redirect (best-effort)', async () => {
      fetchMock.mockRejectedValueOnce(new Error('offline'));
      const user = userEvent.setup();
      render(<AvatarMenu redirector={redirector} />);
      await user.click(screen.getByTestId('avatar-trigger'));
      await user.click(screen.getByTestId('btn-logout'));
      expect(redirector).toHaveBeenCalledWith('/login');
    });
  });
});
