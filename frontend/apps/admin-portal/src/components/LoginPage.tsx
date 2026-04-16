import { useState } from 'react';
import { useAdminStore } from '../store/adminStore';

export function LoginPage() {
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
        <h2>AutoService {'管理后台'}</h2>
        <p>{'请输入租户 ID 登录'}</p>
        <form onSubmit={handleLogin}>
          <input
            data-testid="input-tenant-id"
            placeholder="Tenant ID"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
          />
          <button type="submit" data-testid="btn-login">
            {'登录'}
          </button>
        </form>
      </div>
    </div>
  );
}
