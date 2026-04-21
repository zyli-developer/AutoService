/**
 * T6F.2 · components/auth/LoginPage tests (magic-link request form)
 *
 * Covers:
 *  1. Submit happy path → POST /api/auth/request-login with {email, tenant_id: null}
 *     + success message rendered.
 *  2. Submit error (5xx) → error display, form stays usable for retry.
 *  3. Submit button is disabled (busy) while the request is in flight.
 *  4. Blocks submit on empty email (sets error message, does NOT call fetch).
 *
 * Note: filename `AuthLoginPage.test.tsx` distinguishes from the legacy
 * `LoginPage.test.tsx` which covers the tenant-id zustand flow.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { LoginPage } from '../components/auth/LoginPage';

let fetchMock: ReturnType<typeof vi.fn>;
let originalFetch: typeof globalThis.fetch;

function okResponse() {
  return {
    ok: true,
    status: 200,
    json: async () => ({ status: 'sent', delivered: 'log' }),
  } as unknown as Response;
}

function errResponse(status = 500) {
  return {
    ok: false,
    status,
    json: async () => ({ error: 'server' }),
  } as unknown as Response;
}

beforeEach(() => {
  originalFetch = globalThis.fetch;
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe('components/auth/LoginPage', () => {
  it('happy path — POSTs email + null tenant_id and shows success', async () => {
    fetchMock.mockResolvedValueOnce(okResponse());
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.type(
      screen.getByTestId('login-email-input'),
      'ops@autoservice.com'
    );
    await user.click(screen.getByTestId('login-submit'));

    await waitFor(() =>
      expect(screen.queryByTestId('login-sent')).toBeInTheDocument()
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/auth/request-login');
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('include');
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({
      email: 'ops@autoservice.com',
      tenant_id: null,
      redirect: `${window.location.origin}/admin`,
    });
  });

  it('error path — shows the error inline and keeps the form submittable', async () => {
    fetchMock.mockResolvedValueOnce(errResponse(500));
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.type(
      screen.getByTestId('login-email-input'),
      'ops@autoservice.com'
    );
    await user.click(screen.getByTestId('login-submit'));

    await waitFor(() =>
      expect(screen.getByTestId('login-error')).toBeInTheDocument()
    );
    // form still there (no success flip)
    expect(screen.queryByTestId('login-sent')).not.toBeInTheDocument();
    expect(screen.getByTestId('login-submit')).not.toBeDisabled();
  });

  it('disables the submit button while the request is in flight', async () => {
    let resolveFetch!: (r: Response) => void;
    fetchMock.mockImplementationOnce(
      () => new Promise<Response>((res) => (resolveFetch = res))
    );
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.type(
      screen.getByTestId('login-email-input'),
      'ops@autoservice.com'
    );
    await user.click(screen.getByTestId('login-submit'));

    const submit = screen.getByTestId('login-submit') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(screen.getByTestId('login-email-input')).toBeDisabled();

    // resolve and let it flip back
    resolveFetch(okResponse());
    await waitFor(() =>
      expect(screen.queryByTestId('login-sent')).toBeInTheDocument()
    );
  });

  it('blocks submit on empty email (no fetch call, inline error)', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    // click without typing anything
    await user.click(screen.getByTestId('login-submit'));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByTestId('login-error')).toBeInTheDocument();
  });
});
