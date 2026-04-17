import { useState } from 'react';
import { useOperatorStore } from '../store/operatorStore';

export function LoginPage() {
  const login = useOperatorStore((s) => s.login);
  const [operatorId, setOperatorId] = useState('');
  const [token, setToken] = useState('');

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!operatorId.trim()) return;
    login(operatorId.trim(), token);
  };

  return (
    <div className="im-login">
      <div className="im-login-card">
        <h2>AutoService · 工作台登录</h2>
        <form onSubmit={handleSubmit}>
          <input
            data-testid="input-operator-id"
            placeholder="Operator ID"
            value={operatorId}
            onChange={(e) => setOperatorId(e.target.value)}
          />
          <input
            data-testid="input-token"
            type="password"
            placeholder="Token（可选）"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
          <button
            type="submit"
            disabled={!operatorId.trim()}
            data-testid="btn-login"
          >
            登录
          </button>
        </form>
      </div>
    </div>
  );
}
