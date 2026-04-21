import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LoginPage } from '../components/LoginPage';
import { useOperatorStore, initialState } from '../store/operatorStore';

function mockFetchOnce(response: {
  status: number;
  body?: unknown;
}) {
  const fetchMock = vi.fn(async () => ({
    ok: response.status >= 200 && response.status < 300,
    status: response.status,
    json: async () => response.body ?? {},
  }));
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

beforeEach(() => {
  useOperatorStore.setState(initialState);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('LoginPage', () => {
  it('TC-006: renders form with email + tenant_id inputs and submit button', () => {
    render(<LoginPage />);
    expect(screen.getByTestId('input-email')).toBeInTheDocument();
    expect(screen.getByTestId('input-tenant-id')).toBeInTheDocument();
    expect(screen.getByTestId('btn-login')).toBeInTheDocument();
  });

  it('TC-007: on successful dev-login, sets isLoggedIn=true with operator_id from response', async () => {
    const fetchMock = mockFetchOnce({
      status: 200,
      body: {
        ok: true,
        redirect: '/operator',
        operator_id: 'op-abc123',
        tenant_id: 'acme',
        email: 'alice@acme.com',
      },
    });
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByTestId('input-email'), 'alice@acme.com');
    await user.type(screen.getByTestId('input-tenant-id'), 'acme');
    await user.click(screen.getByTestId('btn-login'));

    await waitFor(() => {
      expect(useOperatorStore.getState().isLoggedIn).toBe(true);
    });
    expect(useOperatorStore.getState().operatorId).toBe('op-abc123');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/auth/operator/dev-login',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({ email: 'alice@acme.com', tenant_id: 'acme' }),
      }),
    );
  });

  it('TC-008: login button is disabled while either field is empty', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    const btn = screen.getByTestId('btn-login');
    expect(btn).toBeDisabled();

    await user.type(screen.getByTestId('input-email'), 'alice@acme.com');
    expect(btn).toBeDisabled(); // tenant still empty

    await user.type(screen.getByTestId('input-tenant-id'), 'acme');
    expect(btn).toBeEnabled();
  });

  it('TC-009: 404 from dev-login surfaces dev-disabled message and stays logged out', async () => {
    mockFetchOnce({ status: 404, body: { error: 'not found' } });
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByTestId('input-email'), 'alice@acme.com');
    await user.type(screen.getByTestId('input-tenant-id'), 'acme');
    await user.click(screen.getByTestId('btn-login'));

    const err = await screen.findByTestId('login-error');
    expect(err.textContent).toMatch(/AUTH_DEV_MODE|dev_disabled|未开启/i);
    expect(useOperatorStore.getState().isLoggedIn).toBe(false);
  });

  it('TC-010: 401 disabled operator surfaces generic error with backend message', async () => {
    mockFetchOnce({
      status: 401,
      body: { error: 'operator disabled' },
    });
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByTestId('input-email'), 'ghost@acme.com');
    await user.type(screen.getByTestId('input-tenant-id'), 'acme');
    await user.click(screen.getByTestId('btn-login'));

    const err = await screen.findByTestId('login-error');
    expect(err.textContent).toMatch(/disabled/i);
    expect(useOperatorStore.getState().isLoggedIn).toBe(false);
  });
});
