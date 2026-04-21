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
 * Additionally (2026-04-21-dev-auto-login):
 *  5. Dev-mode probe disabled → no dev panel rendered.
 *  6. Dev-mode probe enabled → dev panel rendered with personas + tenants.
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

function devModeOff() {
  return {
    ok: true,
    status: 200,
    json: async () => ({ enabled: false }),
  } as unknown as Response;
}

function devModeOn(
  personas: string[] = ['admin@dev.local'],
  tenants: string[] = ['_master', '_local_admin', 'acme']
) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ enabled: true, personas, tenants }),
  } as unknown as Response;
}

/**
 * Install a fetch mock where the dev-mode probe resolves to {enabled:false}
 * (so the dev panel stays hidden for magic-link tests) and the given
 * `response` is returned for `/api/auth/request-login`.
 */
function mockRequestLogin(response: Response) {
  fetchMock.mockImplementation((url: string) => {
    if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
      return Promise.resolve(devModeOff());
    }
    if (typeof url === 'string' && url.includes('/api/auth/request-login')) {
      return Promise.resolve(response);
    }
    return Promise.reject(new Error('no mock configured for ' + url));
  });
}

beforeEach(() => {
  originalFetch = globalThis.fetch;
  fetchMock = vi.fn().mockImplementation((url: string) => {
    // Default: dev-mode probe resolves to {enabled:false} so it doesn't
    // interfere with the magic-link tests. Individual tests override via
    // mockImplementation for dev-panel scenarios.
    if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
      return Promise.resolve(devModeOff());
    }
    return Promise.reject(new Error('no mock configured for ' + url));
  });
  globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  localStorage.clear();
});

describe('components/auth/LoginPage', () => {
  it('happy path — POSTs email + null tenant_id and shows success', async () => {
    mockRequestLogin(okResponse());
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
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/auth/request-login',
      expect.any(Object)
    );
    const requestLoginCall = fetchMock.mock.calls.find(
      ([url]) => typeof url === 'string' && url.includes('/api/auth/request-login')
    );
    expect(requestLoginCall).toBeDefined();
    const [, init] = requestLoginCall!;
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
    mockRequestLogin(errResponse(500));
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
    fetchMock.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
        return Promise.resolve(devModeOff());
      }
      return new Promise<Response>((res) => (resolveFetch = res));
    });
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

  it('blocks submit on empty email (no request-login call, inline error)', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    // click without typing anything
    await user.click(screen.getByTestId('login-submit'));

    // The dev-mode probe may have fired, but request-login must NOT have been called.
    const requestLoginCalled = fetchMock.mock.calls.some(
      ([url]) => typeof url === 'string' && url.includes('/api/auth/request-login')
    );
    expect(requestLoginCalled).toBe(false);
    expect(screen.getByTestId('login-error')).toBeInTheDocument();
  });
});

describe('components/auth/LoginPage — dev panel', () => {
  it('does not render the dev panel when dev-mode is off', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
        return Promise.resolve(devModeOff());
      }
      return Promise.resolve(okResponse());
    });
    render(<LoginPage />);
    // Give the probe a tick to resolve.
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/auth/dev-mode')
    );
    expect(screen.queryByTestId('dev-login-panel')).not.toBeInTheDocument();
  });

  it('renders the dev panel with personas + tenants when enabled', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
        return Promise.resolve(
          devModeOn(['alice@dev.local'], ['_master', 'acme'])
        );
      }
      return Promise.resolve(okResponse());
    });
    render(<LoginPage />);
    await waitFor(() =>
      expect(screen.getByTestId('dev-login-panel')).toBeInTheDocument()
    );
    // Email datalist populated.
    const datalist = document.getElementById('dev-login-personas');
    expect(datalist).not.toBeNull();
    expect(datalist?.querySelectorAll('option').length).toBe(1);
    // Tenant select includes "None" + _master + acme + Custom…
    const select = screen.getByTestId(
      'dev-login-tenant-select'
    ) as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toEqual(['', '_master', 'acme', '__custom__']);
  });

  it('POSTs to /auth/dev-login with tier-0 body and navigates on success', async () => {
    const assignSpy = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, assign: assignSpy, origin: 'http://localhost:5175' },
    });

    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
        return Promise.resolve(
          devModeOn(['admin@dev.local'], ['_master', 'acme'])
        );
      }
      if (typeof url === 'string' && url.includes('/api/auth/dev-login')) {
        const body = JSON.parse(String(init?.body ?? '{}'));
        expect(body).toEqual({ email: 'admin@dev.local', tenant_id: null });
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ ok: true, redirect: '/admin' }),
        } as unknown as Response);
      }
      return Promise.reject(new Error('unexpected url ' + url));
    });

    const user = userEvent.setup();
    render(<LoginPage />);

    await waitFor(() =>
      expect(screen.getByTestId('dev-login-panel')).toBeInTheDocument()
    );
    await user.type(screen.getByTestId('dev-login-email'), 'admin@dev.local');
    await user.click(screen.getByTestId('dev-login-submit'));

    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith('/admin'));
  });

  it('sends custom tenant_id when "Custom…" is picked', async () => {
    const assignSpy = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, assign: assignSpy, origin: 'http://localhost:5175' },
    });

    let capturedBody: Record<string, unknown> | null = null;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
        return Promise.resolve(devModeOn(['admin@dev.local'], ['_master']));
      }
      if (typeof url === 'string' && url.includes('/api/auth/dev-login')) {
        capturedBody = JSON.parse(String(init?.body ?? '{}'));
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ ok: true, redirect: '/t/ghost/admin' }),
        } as unknown as Response);
      }
      return Promise.reject(new Error('unexpected url ' + url));
    });

    const user = userEvent.setup();
    render(<LoginPage />);
    await waitFor(() =>
      expect(screen.getByTestId('dev-login-panel')).toBeInTheDocument()
    );
    await user.type(screen.getByTestId('dev-login-email'), 'admin@dev.local');
    await user.selectOptions(
      screen.getByTestId('dev-login-tenant-select'),
      '__custom__'
    );
    await user.type(screen.getByTestId('dev-login-tenant-custom'), 'ghost');
    await user.click(screen.getByTestId('dev-login-submit'));

    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith('/t/ghost/admin'));
    expect(capturedBody).toEqual({ email: 'admin@dev.local', tenant_id: 'ghost' });
  });

  it('shows an env-off hint when the backend returns 404', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
        return Promise.resolve(devModeOn());
      }
      if (typeof url === 'string' && url.includes('/api/auth/dev-login')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({ error: 'not found' }),
        } as unknown as Response);
      }
      return Promise.reject(new Error('unexpected url ' + url));
    });

    const user = userEvent.setup();
    render(<LoginPage />);
    await waitFor(() =>
      expect(screen.getByTestId('dev-login-panel')).toBeInTheDocument()
    );
    await user.type(screen.getByTestId('dev-login-email'), 'admin@dev.local');
    await user.click(screen.getByTestId('dev-login-submit'));

    await waitFor(() =>
      expect(screen.getByTestId('dev-login-error')).toBeInTheDocument()
    );
    expect(screen.getByTestId('dev-login-error').textContent).toMatch(
      /AUTH_DEV_MODE/i
    );
  });

  it('pushes successful email to localStorage.recentPersonas (dedup, cap 5)', async () => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, assign: vi.fn(), origin: 'http://localhost:5175' },
    });
    // Seed prior history with 5 entries — oldest should be evicted.
    localStorage.setItem(
      'autoservice.dev.recentPersonas',
      JSON.stringify(['a@x', 'b@x', 'c@x', 'd@x', 'e@x'])
    );
    fetchMock.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
        return Promise.resolve(devModeOn());
      }
      if (typeof url === 'string' && url.includes('/api/auth/dev-login')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ ok: true, redirect: '/admin' }),
        } as unknown as Response);
      }
      return Promise.reject(new Error('unexpected url ' + url));
    });

    const user = userEvent.setup();
    render(<LoginPage />);
    await waitFor(() =>
      expect(screen.getByTestId('dev-login-panel')).toBeInTheDocument()
    );
    await user.type(screen.getByTestId('dev-login-email'), 'new@x');
    await user.click(screen.getByTestId('dev-login-submit'));

    await waitFor(() => {
      const stored = JSON.parse(
        localStorage.getItem('autoservice.dev.recentPersonas') ?? '[]'
      );
      expect(stored).toEqual(['new@x', 'a@x', 'b@x', 'c@x', 'd@x']);
    });
  });
});
