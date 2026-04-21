import { useState } from 'react';
import { LanguageSwitcher, useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../../store/adminStore';
import { AvatarMenu } from './AvatarMenu';
import { CommandPalette } from './CommandPalette';

const TITLE_KEYS: Record<string, string> = {
  notifications: 'admin.nav.management_chat',
  dashboard: 'admin.nav.dashboard',
  wizard: 'admin.nav.wizard',
  proposals: 'admin.nav.proposals',
  billing: 'admin.nav.billing',
};

interface AdminTopbarProps {
  onToggleNav?: () => void;
  /**
   * Override the store's `tenantId` for display. Set when the topbar is
   * rendered inside a tenant-scoped iframe (/t/<tid>/admin) so the crumb
   * reflects the previewed tenant instead of the host session.
   */
  tenantIdOverride?: string;
  /**
   * T6F.4 — tenant fork brand name (spec §4.3, "B 的 brand_name").
   * When provided, replaces the tenant token in the crumb/title, so a
   * tenant-mode admin sees their fork's brand instead of the bare tenant id.
   * Empty string is treated as "not provided" (no flicker).
   */
  brandName?: string;
  /**
   * T6F.4 — `authenticated_as` email from `/api/session/mode` (spec §4.3,
   * "Avatar（显示 authenticated_as）"). Renders inline to the left of the
   * avatar. Empty string is treated as "not provided".
   */
  authenticatedAs?: string;
}

export function AdminTopbar({
  onToggleNav,
  tenantIdOverride,
  brandName,
  authenticatedAs,
}: AdminTopbarProps = {}) {
  const { t } = useTranslation();
  const storeTenantId = useAdminStore((s) => s.tenantId);
  const tenantId = tenantIdOverride ?? storeTenantId;
  const activeTab = useAdminStore((s) => s.activeTab);
  const [cmdkOpen, setCmdkOpen] = useState(false);

  // Empty string → treated as absent (spec §4.3 flicker guard)
  const brandNameResolved = brandName && brandName.length > 0 ? brandName : null;
  const authedAsResolved =
    authenticatedAs && authenticatedAs.length > 0 ? authenticatedAs : null;

  const brand = brandNameResolved ?? tenantId ?? 'Admin';
  const titleKey = TITLE_KEYS[activeTab] ?? 'admin.nav.dashboard';
  const pageTitle = t(titleKey);

  return (
    <header className="cs-topbar" data-testid="admin-topbar">
      <button
        type="button"
        className="cs-hamburger"
        data-testid="cs-hamburger"
        onClick={onToggleNav}
        aria-label={t('admin.nav.open_menu')}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 6h18M3 12h18M3 18h18" />
        </svg>
      </button>
      <div className="cs-topbar-left">
        <div className="cs-topbar-crumb">{`${brand} · ${t('admin.topbar.suffix')}`}</div>
        <div className="cs-topbar-title">
          <span className="cs-topbar-dot" aria-hidden="true" />
          <span className="cs-topbar-tenant" data-testid="topbar-tenant">{brand}</span>
          <span className="cs-topbar-sep">/</span>
          <span className="cs-topbar-page">{pageTitle}</span>
        </div>
      </div>
      <div className="cs-topbar-right">
        {authedAsResolved ? (
          <span
            className="cs-topbar-authed-as"
            data-testid="topbar-authed-as"
            style={{
              fontSize: 12,
              color: 'var(--color-text-secondary)',
              fontFamily: 'var(--font-mono)',
              marginRight: 4,
              maxWidth: 220,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
            title={authedAsResolved}
          >
            {`Signed in as ${authedAsResolved}`}
          </span>
        ) : null}
        <LanguageSwitcher
          style={{
            padding: '4px 10px',
            fontSize: 12,
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--color-bg-surface)',
            color: 'var(--color-text-secondary)',
            cursor: 'pointer',
            fontFamily: 'var(--font-mono)',
            letterSpacing: '0.1px',
          }}
        />
        <button
          type="button"
          className="cs-cmdk-btn"
          data-testid="btn-cmdk"
          aria-label={t('admin.command_palette.open')}
          onClick={() => setCmdkOpen(true)}
        >
          ⌘K
        </button>
        <AvatarMenu />
      </div>
      <CommandPalette open={cmdkOpen} onClose={() => setCmdkOpen(false)} />
    </header>
  );
}
