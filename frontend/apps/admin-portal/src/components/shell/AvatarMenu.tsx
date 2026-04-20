import { useState, useEffect, useRef } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../../store/adminStore';

export function AvatarMenu() {
  const { t } = useTranslation();
  const tenantId = useAdminStore((s) => s.tenantId);
  const logout = useAdminStore((s) => s.logout);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  const initial = tenantId ? tenantId.charAt(0).toLowerCase() : '?';

  return (
    <div ref={rootRef} style={{ position: 'relative' }}>
      <button
        type="button"
        className="cs-avatar-btn"
        data-testid="avatar-trigger"
        aria-label={t('admin.user_menu.open')}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {initial}
      </button>
      {open && (
        <div className="cs-avatar-menu" data-testid="avatar-menu" role="menu">
          <div className="cs-avatar-menu-row label">{t('admin.user_menu.tenant_id')}</div>
          <div className="cs-avatar-menu-row value" data-testid="tenant-id">
            {tenantId ?? '—'}
          </div>
          <div style={{ height: 1, background: 'var(--glass-border)', margin: '4px 0' }} />
          <button
            type="button"
            className="cs-avatar-menu-btn"
            data-testid="btn-logout"
            onClick={() => {
              setOpen(false);
              logout();
            }}
          >
            {t('common.logout')}
          </button>
          <div className="cs-avatar-menu-row label" style={{ marginTop: 4 }}>{t('admin.user_menu.version')}</div>
          <div className="cs-avatar-menu-row value">v0.0.1</div>
        </div>
      )}
    </div>
  );
}
