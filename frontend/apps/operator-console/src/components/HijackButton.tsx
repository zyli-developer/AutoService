import { Button } from 'antd';
import type { Envelope } from '@autoservice/ws-client';
import { useOperatorStore } from '../store/operatorStore';

interface HijackButtonProps {
  conversationId: string;
  send: (frame: Envelope) => void;
  disabled?: boolean;
}

export function HijackButton({ conversationId, send, disabled }: HijackButtonProps) {
  const mode = useOperatorStore(
    (s) => s.conversations[conversationId]?.mode,
  );

  const isTakeover = mode === 'takeover';
  const command = isTakeover ? '/release' : '/hijack';
  const text = isTakeover ? '释放回 AI' : '抢单';
  const testId = isTakeover
    ? `btn-release-${conversationId}`
    : `btn-hijack-${conversationId}`;

  const handleClick = () => {
    send({
      v: 1,
      type: 'operator_command',
      id: crypto.randomUUID(),
      ts: new Date().toISOString(),
      payload: { conversation_id: conversationId, command },
    } as Envelope);
  };

  return (
    <Button
      type="primary"
      danger={!isTakeover}
      disabled={disabled}
      data-testid={testId}
      onClick={handleClick}
    >
      {text}
    </Button>
  );
}
