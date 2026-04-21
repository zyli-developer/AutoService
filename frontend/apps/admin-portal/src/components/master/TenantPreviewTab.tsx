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
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from '@autoservice/i18n';

// Top bar height (px) — the iframe fills the remaining canvas height.
const TOP_BAR_HEIGHT = 60;

type PreviewView = 'chat' | 'operator' | 'admin';

// Per-view default dev ports (see each app's vite.config.ts). Used only
// when admin-portal itself is served from its dev port (5175) — in prod
// the reverse proxy routes `/t/<tid>/{chat,operator,admin}` on a single
// origin and we keep the relative path.
const DEV_PORTS: Record<PreviewView, string> = {
  chat: '5173',     // customer-chat
  operator: '5174', // operator-console
  admin: '5175',    // admin-portal (tenant mode) — same origin, no rewrite needed
};

/**
 * Resolve the iframe source URL for an embedded tenant view.
 *
 * In production the reverse proxy routes `/t/<tid>/<view>` to the
 * matching SPA bundle on one origin, so the relative path works. In dev,
 * admin-portal (default :5175) has no proxy for `/t/*` and would
 * SPA-fallback to its own index.html — causing the iframe to load
 * admin-portal recursively (the "infinite nesting" bug). We detect this
 * and point chat/operator iframes at their respective dev servers.
 *
 * Overrides:
 *   VITE_CUSTOMER_CHAT_URL
 *   VITE_OPERATOR_CONSOLE_URL
 *   VITE_ADMIN_PORTAL_URL
 */
function resolveViewSrc(tenantId: string, view: PreviewView): string {
  const path = `/t/${encodeURIComponent(tenantId)}/${view}`;
  const overrideKey = (
    {
      chat: 'VITE_CUSTOMER_CHAT_URL',
      operator: 'VITE_OPERATOR_CONSOLE_URL',
      admin: 'VITE_ADMIN_PORTAL_URL',
    } as const
  )[view];
  const override = (import.meta.env[overrideKey] as string | undefined)?.trim();
  if (override) {
    return `${override.replace(/\/$/, '')}${path}`;
  }
  // Gate on the admin-portal dev port so unit tests running under jsdom
  // (port === '') still assert the relative path.
  if (
    import.meta.env.DEV &&
    typeof window !== 'undefined' &&
    window.location.port === '5175'
  ) {
    const devBase = `${window.location.protocol}//${window.location.hostname}:${DEV_PORTS[view]}`;
    return `${devBase}${path}`;
  }
  return path;
}

const VIEW_LABELS: Record<PreviewView, { zh: string; key: string }> = {
  chat: { zh: '客户', key: 'admin.master.preview.view_chat' },
  operator: { zh: '坐席台', key: 'admin.master.preview.view_operator' },
  admin: { zh: '商户后台', key: 'admin.master.preview.view_admin' },
};

export function TenantPreviewTab() {
  const { t } = useTranslation();
  const { id: tenantId } = useParams<{ id: string }>();
  const [view, setView] = useState<PreviewView>('chat');

  if (!tenantId) {
    return (
      <div className="im-empty" data-testid="tenant-preview-missing-id">
        {t('admin.master.preview.missing_id', '缺少租户 ID')}
      </div>
    );
  }

  const iframeSrc = resolveViewSrc(tenantId, view);
  const views: PreviewView[] = ['chat', 'operator', 'admin'];

  return (
    <div data-testid="tab-tenant-preview" style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
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
          gap: 12,
        }}
        data-testid="tenant-preview-topbar"
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
          <Link
            to="/master/tenants"
            data-testid="tenant-preview-back"
            style={{ color: 'var(--ink)', textDecoration: 'none', fontSize: 14, whiteSpace: 'nowrap' }}
          >
            {t('admin.master.preview.back', '← 返回列表')}
          </Link>
          <span style={{ color: 'var(--silver)' }}>|</span>
          <span style={{ fontWeight: 600, color: 'var(--ink)', whiteSpace: 'nowrap' }}>
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
        <div
          role="tablist"
          aria-label={t('admin.master.preview.view_switcher', '预览视角')}
          style={{ display: 'flex', gap: 4, background: 'var(--m300)', borderRadius: 6, padding: 2 }}
          data-testid="tenant-preview-view-switcher"
        >
          {views.map((v) => {
            const isActive = v === view;
            return (
              <button
                key={v}
                type="button"
                role="tab"
                aria-selected={isActive}
                data-testid={`tenant-preview-view-${v}`}
                onClick={() => setView(v)}
                style={{
                  fontSize: 12,
                  padding: '4px 10px',
                  border: 0,
                  borderRadius: 4,
                  cursor: 'pointer',
                  background: isActive ? 'var(--paper)' : 'transparent',
                  color: isActive ? 'var(--ink)' : 'var(--silver)',
                  fontWeight: isActive ? 600 : 500,
                  boxShadow: isActive ? 'var(--shd)' : 'none',
                }}
              >
                {t(VIEW_LABELS[v].key, VIEW_LABELS[v].zh)}
              </button>
            );
          })}
        </div>
        <a
          href={iframeSrc}
          target="_blank"
          rel="noreferrer noopener"
          data-testid="tenant-preview-open-new"
          style={{ color: 'var(--ink)', textDecoration: 'none', fontSize: 12, whiteSpace: 'nowrap' }}
        >
          {t('admin.master.preview.open_new_tab', '在新标签页打开 ↗')}
        </a>
      </div>
      <iframe
        data-testid="tenant-preview-iframe"
        data-view={view}
        src={iframeSrc}
        title={`${t('admin.master.preview.iframe_title', 'Preview of tenant')} ${tenantId} (${view})`}
        style={{
          width: '100%',
          flex: 1,
          border: 0,
          minHeight: 0,
        }}
      />
    </div>
  );
}
