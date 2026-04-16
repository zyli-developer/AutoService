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
        <h2>AutoService {'\u7BA1\u7406\u540E\u53F0'}</h2>
        <p>{'\u8BF7\u8F93\u5165\u79DF\u6237 ID \u767B\u5F55'}</p>
        <form onSubmit={handleLogin}>
          <input
            data-testid="input-tenant-id"
            placeholder="Tenant ID"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
          />
          <button type="submit" data-testid="btn-login">
            {'\u767B\u5F55'}
          </button>
        </form>
      </div>
    </div>
  );
}
