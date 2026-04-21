import { useState } from 'react';
import { LanguageSwitcher, useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../store/adminStore';

export function LoginPage() {
  const { t } = useTranslation();
  const [tenantId, setTenantId] = useState('');
  const login = useAdminStore((s) => s.login);

  const handleLogin = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!tenantId.trim()) return;
    login(tenantId.trim());
  };

  return (
    <div className="cs-login">
      <div className="cs-login-card" data-testid="login-card">
        <h2>{t('admin.login.title')}</h2>
        <p>{t('admin.login.subtitle')}</p>
        <form onSubmit={handleLogin}>
          <input
            data-testid="input-tenant-id"
            placeholder={t('admin.login.tenant_id')}
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
          />
          <button type="submit" data-testid="btn-login">
            {t('common.login')}
          </button>
        </form>
        <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end' }}>
          <LanguageSwitcher
            style={{
              padding: '2px 6px',
              fontSize: 12,
              border: '1px solid var(--color-border)',
              borderRadius: 4,
              background: 'transparent',
              color: 'inherit',
              cursor: 'pointer',
            }}
          />
        </div>
      </div>
    </div>
  );
}
