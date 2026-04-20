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

export function AdminTopbar() {
  const { t } = useTranslation();
  const tenantId = useAdminStore((s) => s.tenantId);
  const activeTab = useAdminStore((s) => s.activeTab);
  const [cmdkOpen, setCmdkOpen] = useState(false);

  const tenant = tenantId ?? 'Admin';
  const titleKey = TITLE_KEYS[activeTab] ?? 'admin.nav.dashboard';
  const pageTitle = t(titleKey);

  return (
    <header className="cs-topbar" data-testid="admin-topbar">
      <div className="cs-topbar-left">
        <div className="cs-topbar-crumb">{`${tenant} · ${t('admin.topbar.suffix')}`}</div>
        <div className="cs-topbar-title">
          <span className="cs-topbar-dot" aria-hidden="true" />
          <span className="cs-topbar-tenant" data-testid="topbar-tenant">{tenant}</span>
          <span className="cs-topbar-sep">/</span>
          <span className="cs-topbar-page">{pageTitle}</span>
        </div>
      </div>
      <div className="cs-topbar-right">
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
