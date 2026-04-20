/**
 * T1F.6 · TenantPreviewTab — A "embodies" B's sandbox via iframe
 *
 * Route: `/master/tenants/:id/preview`
 *
 * Reads `tenantId` from the route, renders a slim top bar with the tenant id
 * and a back link, and embeds `/t/<tenant_id>/chat` (the customer-chat SPA's
 * tenant-scoped entry — see T1F.3 / operator-console/main.tsx for the pattern)
 * in an iframe that fills the remaining viewport height.
 *
 * Security note: the iframe uses a same-origin src (relative path) so the
 * existing cookie-based session works. Once M2 adds tenant-admin auth, we
 * should tighten this with a sandbox= attribute and a per-tenant CSP.
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-design.md §5.2
 */
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from '@autoservice/i18n';

// Top bar height (px) — the iframe fills the remaining viewport.
const TOP_BAR_HEIGHT = 60;

export function TenantPreviewTab() {
  const { t } = useTranslation();
  const { id: tenantId } = useParams<{ id: string }>();

  if (!tenantId) {
    return (
      <div className="im-empty" data-testid="tenant-preview-missing-id">
        {t('admin.master.preview.missing_id', '缺少租户 ID')}
      </div>
    );
  }

  const chatSrc = `/t/${encodeURIComponent(tenantId)}/chat`;

  return (
    <div data-testid="tab-tenant-preview" style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <div
        style={{
          height: TOP_BAR_HEIGHT,
          padding: '0 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--bg-elev)',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}
        data-testid="tenant-preview-topbar"
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Link
            to="/master/tenants"
            data-testid="tenant-preview-back"
            style={{ color: 'var(--ink)', textDecoration: 'none', fontSize: 14 }}
          >
            {t('admin.master.preview.back', '← 返回列表')}
          </Link>
          <span style={{ color: 'var(--silver)' }}>|</span>
          <span style={{ fontWeight: 600, color: 'var(--ink)' }}>
            {t('admin.master.preview.title', '代入预览')}
          </span>
          <span
            data-testid="tenant-preview-id"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              color: 'var(--silver)',
              padding: '2px 8px',
              background: 'var(--m300)',
              borderRadius: 4,
            }}
          >
            {tenantId}
          </span>
        </div>
        <a
          href={chatSrc}
          target="_blank"
          rel="noreferrer noopener"
          data-testid="tenant-preview-open-new"
          style={{ color: 'var(--ink)', textDecoration: 'none', fontSize: 12 }}
        >
          {t('admin.master.preview.open_new_tab', '在新标签页打开 ↗')}
        </a>
      </div>
      <iframe
        data-testid="tenant-preview-iframe"
        src={chatSrc}
        title={`${t('admin.master.preview.iframe_title', 'Preview of tenant')} ${tenantId}`}
        style={{
          width: '100%',
          flex: 1,
          border: 0,
          minHeight: `calc(100vh - ${TOP_BAR_HEIGHT}px)`,
        }}
      />
    </div>
  );
}
