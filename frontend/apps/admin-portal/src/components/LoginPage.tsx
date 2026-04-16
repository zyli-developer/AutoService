import { useState } from 'react';
import { Button, Card, Input, Layout, Typography } from 'antd';
import { useAdminStore } from '../store/adminStore';

export function LoginPage() {
  const [tenantId, setTenantId] = useState('');
  const login = useAdminStore((s) => s.login);

  const handleLogin = () => {
    if (!tenantId.trim()) return;
    login(tenantId.trim());
  };

  return (
    <Layout style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Card title="AutoService 管理后台" style={{ width: 400 }} data-testid="login-card">
        <Typography.Paragraph type="secondary">请输入租户 ID 登录</Typography.Paragraph>
        <Input
          data-testid="input-tenant-id"
          placeholder="Tenant ID"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          onPressEnter={handleLogin}
          style={{ marginBottom: 16 }}
        />
        <Button
          type="primary"
          block
          data-testid="btn-login"
          onClick={handleLogin}
        >
          登录
        </Button>
      </Card>
    </Layout>
  );
}
