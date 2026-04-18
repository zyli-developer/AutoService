import { useState } from 'react';
import { useAdminStore } from '../../store/adminStore';
import { AvatarMenu } from './AvatarMenu';
import { CommandPalette } from './CommandPalette';

export function AdminTopbar() {
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
        <button
          type="button"
          className="cs-cmdk-btn"
          data-testid="btn-cmdk"
          aria-label="打开命令面板"
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
