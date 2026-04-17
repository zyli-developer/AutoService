import { useOperatorStore } from '../store/operatorStore';

export function ConcurrencyWarning() {
  const conversations = useOperatorStore((s) => s.conversations);
  const concurrencyLimit = useOperatorStore((s) => s.concurrencyLimit);

  const count = Object.values(conversations).filter(
    (c) => c.state !== 'closed',
  ).length;

  if (count < concurrencyLimit) return null;

  return (
    <div
      data-testid="concurrency-warning"
      className="im-handoff"
      style={{ margin: '8px 20px' }}
    >
      {`并发会话已达上限 (${count}/${concurrencyLimit})`}
    </div>
  );
}
