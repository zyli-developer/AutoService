import { useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useOperatorStore } from '../store/operatorStore';

export function LoginPage() {
  const { t } = useTranslation();
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
        <h2>{t('operator.login.title')}</h2>
        <form onSubmit={handleSubmit}>
          <input
            data-testid="input-operator-id"
            placeholder={t('operator.login.operator_id')}
            value={operatorId}
            onChange={(e) => setOperatorId(e.target.value)}
          />
          <input
            data-testid="input-token"
            type="password"
            placeholder={t('operator.login.token')}
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
          <button
            type="submit"
            disabled={!operatorId.trim()}
            data-testid="btn-login"
          >
            {t('common.login')}
          </button>
        </form>
      </div>
    </div>
  );
}
