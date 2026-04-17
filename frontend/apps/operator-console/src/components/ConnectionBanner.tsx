import { Alert } from 'antd';
import { useOperatorStore } from '../store/operatorStore';

export function ConnectionBanner() {
  const wsStatus = useOperatorStore((s) => s.wsStatus);
  if (wsStatus === 'open' || wsStatus === 'idle') return null;
  return (
    <Alert
      data-testid="connection-banner"
      type={wsStatus === 'connecting' ? 'info' : 'warning'}
      message={wsStatus === 'connecting' ? '连接中...' : '连接已断开，尝试重连'}
      banner
    />
  );
}
