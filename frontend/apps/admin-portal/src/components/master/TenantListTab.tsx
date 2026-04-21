/**
 * T1F.6 · TenantListTab — list all tenants known to Master
 *
 * Route: `/master/tenants`
 *
 * Fetches `GET /api/master/tenants` (see autoservice.api_routes.list_master_tenants)
 * which scans `.autoservice/sandbox/` and `.autoservice/archived/` for per-tenant
 * `config.json` files. Each row links to `/master/tenants/:id/preview` so that
 * platform-operator A can "代入" (embody) tenant B's sandbox via iframe.
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.2
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from '@autoservice/i18n';
import { fetchJSON } from '../../api';

export interface TenantListEntry {
  tenant_id: string;
  brand_name: string | null;
  industry: string | null;
  status: string;
  created_at: string | null;
}

// Status badge palette reuses the existing cs-* token system (see
// ProposalsTab for the pattern).
const STATUS_COLORS: Record<string, { bg: string; color: string }> = {
  sandbox: { bg: 'var(--m300)', color: 'var(--m800)' },
  published_pending_fork: { bg: 'var(--l500)', color: 'var(--l800)' },
  archived: { bg: 'var(--silver)', color: '#fff' },
};

function statusStyle(status: string) {
  return STATUS_COLORS[status] ?? { bg: 'var(--m300)', color: 'var(--ink)' };
}

export function TenantListTab() {
  const { t } = useTranslation();
  const [tenants, setTenants] = useState<TenantListEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchJSON<TenantListEntry[]>('/api/master/tenants')
      .then((data) => {
        if (cancelled) return;
        setTenants(data ?? []);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div data-testid="tab-tenant-list" style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0, color: 'var(--ink)' }}>
          {t('admin.master.tenants.title', '租户列表')}
        </h2>
        <Link
          to="/master/tenants/new"
          className="cs-btn ok"
          data-testid="tenant-new-link"
        >
          {t('admin.master.tenants.new_tenant', '新建租户')}
        </Link>
      </div>

      {loading && (
        <div className="im-empty" data-testid="tenant-list-loading">
          {t('common.loading', '加载中…')}
        </div>
      )}

      {!loading && error && (
        <div className="im-empty" data-testid="tenant-list-error" style={{ color: 'var(--p)' }}>
          {t('admin.master.tenants.load_error', '加载失败')}: {error}
        </div>
      )}

      {!loading && !error && tenants.length === 0 && (
        <div className="im-empty" data-testid="tenant-list-empty">
          {t('admin.master.tenants.empty', '暂无租户。点击"新建租户"开始配置。')}
        </div>
      )}

      {!loading && !error && tenants.length > 0 && (
        <div className="cs-split-list" data-testid="tenant-list">
          {tenants.map((tn) => {
            const badge = statusStyle(tn.status);
            const previewHref = `/master/tenants/${tn.tenant_id}/preview`;
            return (
              <Link
                key={tn.tenant_id}
                to={previewHref}
                className="cs-list-row"
                data-testid={`tenant-row-${tn.tenant_id}`}
                style={{ display: 'block', textDecoration: 'none', color: 'inherit' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span
                    style={{
                      fontSize: 10,
                      padding: '1px 6px',
                      borderRadius: 4,
                      background: badge.bg,
                      color: badge.color,
                      fontWeight: 600,
                    }}
                    data-testid={`tenant-status-${tn.tenant_id}`}
                  >
                    {tn.status}
                  </span>
                  {tn.industry && (
                    <span style={{ fontSize: 11, color: 'var(--silver)' }}>{tn.industry}</span>
                  )}
                </div>
                <div style={{ fontWeight: 600, color: 'var(--ink)' }}>
                  {tn.brand_name || tn.tenant_id}
                </div>
                <div style={{ fontSize: 11, color: 'var(--silver)', marginTop: 2, fontFamily: 'var(--font-mono)' }}>
                  {tn.tenant_id}
                </div>
                {tn.created_at && (
                  <div style={{ fontSize: 10, color: 'var(--silver)', marginTop: 2 }}>
                    {t('admin.master.tenants.created_at', '创建于')}: {tn.created_at}
                  </div>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
