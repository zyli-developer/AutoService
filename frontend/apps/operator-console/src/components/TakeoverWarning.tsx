import { useEffect, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import type { Envelope } from '@autoservice/ws-client';
import { useOperatorStore } from '../store/operatorStore';

interface TakeoverWarningProps {
  conversationId: string;
  send: (frame: Envelope) => void;
}

export function TakeoverWarning({ conversationId, send }: TakeoverWarningProps) {
  const { t } = useTranslation();
  const currentOperatorId = useOperatorStore((s) => s.operatorId);
  const conv = useOperatorStore((s) => s.conversations[conversationId]);
  const warning = conv?.takeoverWarning;

  const [remaining, setRemaining] = useState<number>(warning?.remainingMs ?? 0);

  useEffect(() => {
    if (!warning) return;
    setRemaining(warning.remainingMs);
    const start = Date.now();
    const id = setInterval(() => {
      const elapsed = Date.now() - start;
      setRemaining(Math.max(0, warning.remainingMs - elapsed));
    }, 100);
    return () => clearInterval(id);
  }, [warning?.warningFrameId, warning?.remainingMs]);

  if (!warning) return null;
  if (!conv) return null;
  if (conv.takeoverOperatorId !== currentOperatorId) return null;

  const handleContinue = () => {
    send({
      v: 1,
      type: 'client_ack' as any,
      id: crypto.randomUUID(),
      ts: new Date().toISOString(),
      payload: {
        action: 'continue',
        conversation_id: conversationId,
        ref_frame_id: warning.warningFrameId,
      },
    } as Envelope);
  };

  const handleRelease = () => {
    send({
      v: 1,
      type: 'operator_command',
      id: crypto.randomUUID(),
      ts: new Date().toISOString(),
      payload: {
        conversation_id: conversationId,
        command: '/release',
        operator_id: currentOperatorId ?? 'operator',
      },
    } as Envelope);
  };

  return (
    <div
      data-testid={`takeover-warning-${conversationId}`}
      style={{
        background: 'var(--gold-50)',
        color: 'var(--gold-700)',
        padding: '8px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        borderBottom: '1px solid var(--gold-200)',
      }}
    >
      <span style={{ flex: 1 }}>
        {t('operator.warning.auto_release_in', { seconds: Math.ceil(remaining / 1000) })}
      </span>
      <button
        data-testid="takeover-warning-continue"
        onClick={handleContinue}
        style={{ padding: '4px 12px' }}
      >
        {t('operator.warning.continue_takeover')}
      </button>
      <button
        data-testid="takeover-warning-release"
        onClick={handleRelease}
        style={{ padding: '4px 12px' }}
      >
        {t('operator.warning.release')}
      </button>
    </div>
  );
}
