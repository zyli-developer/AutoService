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
      {`\u5E76\u53D1\u4F1A\u8BDD\u5DF2\u8FBE\u4E0A\u9650 (${count}/${concurrencyLimit})`}
    </div>
  );
}
