/**
 * T6F.1 · useSessionMode tests (M2 real impl)
 *
 * Covers:
 *  1. Returns master-mode payload with full M2 shape (6 fields)
 *  2. Returns tenant-mode payload including tenant_id and authenticated_as
 *  3. `loading` starts true then flips false once the fetcher resolves
 *  4. `error` is populated on non-2xx status
 *  5. `error` is populated on network failure (fetch rejects)
 *  6. `refetch` re-runs the query and returns fresh data
 *
 * Uses an injected mock fetcher so tests never hit the real network.
 */
import { describe, it, expect } from 'vitest';
import { act } from 'react';
import { renderHook, waitFor } from '@testing-library/react';

import { useSessionMode, type SessionMode } from './useSessionMode';

function mockFetcher(
  body: unknown,
  init: { ok?: boolean; status?: number } = {}
) {
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

function rejectingFetcher(err: unknown) {
  return async (_input: RequestInfo | URL, _opts?: RequestInit) => {
    throw err instanceof Error ? err : new Error(String(err));
  };
}

describe('useSessionMode (M2 real impl)', () => {
  it('returns master-mode payload with all 6 fields', async () => {
    const payload: SessionMode = {
      mode: 'master',
      tenant_id: null,
      authenticated: true,
      authenticated_as: 'platform@ops.com',
      tier: 0,
      brand_name: 'AutoService',
    };
    const fetcher = mockFetcher(payload);

    const { result } = renderHook(() =>
      useSessionMode(fetcher as unknown as typeof fetch)
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data).toEqual(payload);
    expect(result.current.error).toBeNull();
    expect(typeof result.current.refetch).toBe('function');
  });

  it('returns tenant-mode payload including tenant_id', async () => {
    const payload: SessionMode = {
      mode: 'tenant',
      tenant_id: 'acme',
      authenticated: true,
      authenticated_as: 'admin@acme.com',
      tier: 1,
      brand_name: 'Acme Corp',
    };
    const fetcher = mockFetcher(payload);

    const { result } = renderHook(() =>
      useSessionMode(fetcher as unknown as typeof fetch)
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data?.tenant_id).toBe('acme');
    expect(result.current.data?.authenticated_as).toBe('admin@acme.com');
    expect(result.current.data?.tier).toBe(1);
    expect(result.current.data?.brand_name).toBe('Acme Corp');
  });

  it('starts in loading=true then flips false after resolve', async () => {
    const fetcher = mockFetcher({
      mode: 'master',
      tenant_id: null,
      authenticated: false,
      authenticated_as: null,
      tier: null,
      brand_name: 'AutoService',
    });

    const { result } = renderHook(() =>
      useSessionMode(fetcher as unknown as typeof fetch)
    );

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

  it('surfaces an Error on network failure (fetch rejects)', async () => {
    const fetcher = rejectingFetcher(new Error('network down'));

    const { result } = renderHook(() =>
      useSessionMode(fetcher as unknown as typeof fetch)
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toContain('network down');
  });

  it('refetch re-runs the query and returns fresh data', async () => {
    let callCount = 0;
    const bodies: SessionMode[] = [
      {
        mode: 'master',
        tenant_id: null,
        authenticated: false,
        authenticated_as: null,
        tier: null,
        brand_name: 'AutoService',
      },
      {
        mode: 'master',
        tenant_id: null,
        authenticated: true,
        authenticated_as: 'admin@ops.com',
        tier: 0,
        brand_name: 'AutoService',
      },
    ];
    const fetcher: typeof fetch = async () => {
      const body = bodies[Math.min(callCount, bodies.length - 1)];
      callCount += 1;
      return {
        ok: true,
        status: 200,
        json: async () => body,
      } as Response;
    };

    const { result } = renderHook(() => useSessionMode(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data?.authenticated).toBe(false);

    // Kick a refetch and wait for the second response to land.
    act(() => {
      result.current.refetch();
    });

    await waitFor(() =>
      expect(result.current.data?.authenticated).toBe(true)
    );
    expect(result.current.data?.authenticated_as).toBe('admin@ops.com');
    expect(callCount).toBe(2);
  });
});
