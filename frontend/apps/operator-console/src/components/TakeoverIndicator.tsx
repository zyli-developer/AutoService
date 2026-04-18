import { useEffect, useState } from 'react';
import { useOperatorStore } from '../store/operatorStore';

interface Props {
  conversationId: string;
}

export function TakeoverIndicator({ conversationId }: Props) {
  const conv = useOperatorStore((s) => s.conversations[conversationId]);
  const isTakeover = conv?.mode === 'takeover';
  const armedAt = conv?.takeoverArmedAt;
  const idleMs = conv?.takeoverIdleMs;
  const warningMs = conv?.takeoverWarningMs;

  const [remaining, setRemaining] = useState<number>(() => {
    if (!armedAt || !idleMs) return 0;
    const elapsed = Date.now() - new Date(armedAt).getTime();
    return Math.max(0, idleMs - elapsed);
  });

  useEffect(() => {
    if (!isTakeover || !armedAt || !idleMs) return;
    const start = new Date(armedAt).getTime();
    const tick = () => {
      const elapsed = Date.now() - start;
      setRemaining(Math.max(0, idleMs - elapsed));
    };
    tick();
    const id = setInterval(tick, 250);
    return () => clearInterval(id);
  }, [isTakeover, armedAt, idleMs]);

  if (!isTakeover) return null;

  const hasCountdown = !!armedAt && !!idleMs;
  const inWarningPhase = hasCountdown && !!warningMs && remaining > 0 && remaining <= warningMs;
  const seconds = Math.max(1, Math.ceil(remaining / 1000));

  return (
    <span
      data-testid="takeover-indicator"
      style={{ display: 'inline-flex', alignItems: 'center', marginLeft: 8 }}
    >
      <span className="takeover-pill" title="operator 已接管，agent 静默">
        ⚡ TAKEOVER
      </span>
      {hasCountdown && (
        <span
          data-testid="takeover-countdown"
          className={`takeover-pill-countdown${inWarningPhase ? ' warning' : ''}`}
          title={`还剩 ${seconds}s 自动回到 AI`}
        >
          {seconds}s
        </span>
      )}
    </span>
  );
}
