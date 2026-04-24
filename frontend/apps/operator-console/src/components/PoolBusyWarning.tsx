import { useTranslation } from '@autoservice/i18n';
import { useOperatorStore } from '../store/operatorStore';

/**
 * Banner that surfaces real cc_pool pressure (checked_out / max_size)
 * from the backend snapshot endpoint. Formerly `ConcurrencyWarning`,
 * which compared a per-operator conv count against a hardcoded `5` —
 * that number was never wired to anything real.
 *
 * Hidden when:
 * - `started=false` or `maxSize<=0` → no pool to compare against (tests,
 *   POOL_MODE=0, pool never booted). A 0/0 badge is noise.
 * - `checkedOut < maxSize - 1` → plenty of headroom.
 *
 * `at_capacity` (checkedOut ≥ maxSize) vs `approaching_capacity` drives
 * the CSS severity (`danger` vs `warn`).
 */
export function PoolBusyWarning() {
  const { t } = useTranslation();
  const pool = useOperatorStore((s) => s.poolStatus);

  if (!pool.started || pool.maxSize <= 0) return null;
  if (pool.checkedOut < pool.maxSize - 1) return null;

  const atCapacity = pool.checkedOut >= pool.maxSize;

  return (
    <div
      data-testid="concurrency-warning"
      className={`op-notif ${atCapacity ? 'danger' : 'warn'}`}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0ZM12 9v4M12 17h.01" />
      </svg>
      <span>
        {atCapacity
          ? t('operator.pool.at_capacity', { limit: pool.maxSize })
          : t('operator.pool.approaching_capacity', {
              count: pool.checkedOut,
              limit: pool.maxSize,
            })}
      </span>
    </div>
  );
}
