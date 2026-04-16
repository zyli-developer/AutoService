import { useState } from 'react';
import { Button, Card, Form, Input, Typography } from 'antd';
import { useOperatorStore } from '../store/operatorStore';

export function LoginPage() {
  const login = useOperatorStore((s) => s.login);
  const [operatorId, setOperatorId] = useState('');
  const [token, setToken] = useState('');

  const handleSubmit = () => {
    if (!operatorId.trim()) return;
    login(operatorId.trim(), token);
  };

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        background: '#f0f2f5',
      }}
    >
      <Card style={{ width: 360 }}>
        <Typography.Title level={4} style={{ textAlign: 'center', marginBottom: 24 }}>
          AutoService · 工作台登录
        </Typography.Title>
        <Form layout="vertical" onFinish={handleSubmit}>
          <Form.Item label="Operator ID">
            <Input
              data-testid="input-operator-id"
              placeholder="Operator ID"
              value={operatorId}
              onChange={(e) => setOperatorId(e.target.value)}
            />
          </Form.Item>
          <Form.Item label="Token">
            <Input.Password
              data-testid="input-token"
              placeholder="Token（可选）"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              block
              disabled={!operatorId.trim()}
              data-testid="btn-login"
            >
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
