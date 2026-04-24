import { useEffect } from 'react';
import { useOperatorStore, INITIAL_POOL_STATUS, type PoolStatus } from '../store/operatorStore';

/**
 * Poll /api/cc_pool/runtime every 3 s and mirror into the operator store.
 *
 * Drives the "system busy" banner (see `ConcurrencyWarning`). 3 s matches
 * the pool's own status-writer cadence (5 s worst-case staleness) without
 * hammering the endpoint. Fetch failures reset to an `INITIAL_POOL_STATUS`
 * so a crashed backend hides the banner rather than freezing the last
 * number on screen — stale capacity readouts are worse than none.
 *
 * Call once from the top-level layout. Do NOT mount in multiple places or
 * the polls will stack.
 */
const POLL_MS = 3000;

type ApiShape = {
  started?: boolean;
  max_size?: number;
  checked_out?: number;
  sticky?: number;
  available?: number;
  total?: number;
};

function toPoolStatus(raw: ApiShape): PoolStatus {
  return {
    started: !!raw.started,
    maxSize: Number(raw.max_size ?? 0) || 0,
    checkedOut: Number(raw.checked_out ?? 0) || 0,
    sticky: Number(raw.sticky ?? 0) || 0,
    available: Number(raw.available ?? 0) || 0,
    total: Number(raw.total ?? 0) || 0,
  };
}

export function useCCPoolStatus(): void {
  const setPoolStatus = useOperatorStore((s) => s.setPoolStatus);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch('/api/cc_pool/runtime');
        if (!r.ok) throw new Error(`status ${r.status}`);
        const body: ApiShape = await r.json();
        if (!cancelled) setPoolStatus(toPoolStatus(body));
      } catch {
        // Network blip / backend restart — hide the banner rather than
        // leaving a stale number up. A subsequent successful poll restores it.
        if (!cancelled) setPoolStatus(INITIAL_POOL_STATUS);
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [setPoolStatus]);
}

// Exposed for tests — they monkey-patch the poll interval to avoid
// ticking real time.
export const __POLL_MS_FOR_TESTS = POLL_MS;
