import { useState } from 'react';
import { LanguageSwitcher, useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../../store/adminStore';
import { AvatarMenu } from './AvatarMenu';
import { CommandPalette } from './CommandPalette';

export function AdminTopbar() {
  const { t } = useTranslation();
  const tenantId = useAdminStore((s) => s.tenantId);
  const [cmdkOpen, setCmdkOpen] = useState(false);

  return (
    <header className="cs-topbar" data-testid="admin-topbar">
      <div className="cs-topbar-left">
        <span className="cs-topbar-dot" aria-hidden="true" />
        <span className="cs-topbar-tenant" data-testid="topbar-tenant">
          {tenantId ?? 'Admin'}
        </span>
      </div>
      <div className="cs-topbar-right">
        <LanguageSwitcher
          style={{
            marginRight: 12,
            padding: '2px 6px',
            fontSize: 12,
            border: '1px solid var(--glass-border, #ccc)',
            borderRadius: 4,
            background: 'transparent',
            color: 'inherit',
            cursor: 'pointer',
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
