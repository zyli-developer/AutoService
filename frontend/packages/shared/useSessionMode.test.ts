/**
 * T1F.2 · useSessionMode tests
 *
 * Covers:
 *  1. Returns master-mode payload when endpoint responds with
 *     {mode: "master", role: "platform_admin"} (M1 shape)
 *  2. Returns tenant-mode payload when endpoint responds with
 *     {mode: "tenant", role: "tenant_admin", tenant_id: "B"} (M2 shape)
 *  3. `loading` is true initially and flips to false once the fetcher resolves
 *  4. `error` is populated when the endpoint returns a non-2xx status
 *
 * Uses an injected mock fetcher so tests never hit the real network.
 */
import { describe, it, expect } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

import { useSessionMode, type SessionMode } from './useSessionMode';

function mockFetcher(body: unknown, init: { ok?: boolean; status?: number } = {}) {
  const ok = init.ok ?? true;
  const status = init.status ?? (ok ? 200 : 500);
  return async (_input: RequestInfo | URL, _opts?: RequestInit) => {
    return {
      ok,
      status,
      json: async () => body,
    } as Response;
  };
}

describe('useSessionMode', () => {
  it('returns master-mode payload from /api/session/mode (M1)', async () => {
    const payload: SessionMode = { mode: 'master', role: 'platform_admin' };
    const fetcher = mockFetcher(payload);

    const { result } = renderHook(() =>
      useSessionMode(fetcher as unknown as typeof fetch)
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data).toEqual(payload);
    expect(result.current.error).toBeNull();
  });

  it('returns tenant-mode payload including tenant_id (M2)', async () => {
    const payload: SessionMode = {
      mode: 'tenant',
      role: 'tenant_admin',
      tenant_id: 'B',
    };
    const fetcher = mockFetcher(payload);

    const { result } = renderHook(() =>
      useSessionMode(fetcher as unknown as typeof fetch)
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data).toEqual(payload);
    expect(result.current.data?.tenant_id).toBe('B');
    expect(result.current.error).toBeNull();
  });

  it('starts in loading=true and flips to false after resolve', async () => {
    const fetcher = mockFetcher({ mode: 'master', role: 'platform_admin' });

    const { result } = renderHook(() =>
      useSessionMode(fetcher as unknown as typeof fetch)
    );

    // Initially loading — data not yet resolved.
    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).not.toBeNull();
  });

  it('surfaces an Error when the endpoint returns 500', async () => {
    const fetcher = mockFetcher({}, { ok: false, status: 500 });

    const { result } = renderHook(() =>
      useSessionMode(fetcher as unknown as typeof fetch)
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toContain('500');
  });
});
