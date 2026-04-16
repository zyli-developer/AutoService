import { Button } from 'antd';
import type { Envelope } from '@autoservice/ws-client';

interface HijackButtonProps {
  conversationId: string;
  send: (frame: Envelope) => void;
  disabled?: boolean;
}

export function HijackButton({ conversationId, send, disabled }: HijackButtonProps) {
  const handleClick = () => {
    send({
      v: 1,
      type: 'operator_command',
      id: crypto.randomUUID(),
      ts: new Date().toISOString(),
      payload: { conversation_id: conversationId, command: '/hijack' },
    } as Envelope);
  };

  return (
    <Button
      type="primary"
      danger
      disabled={disabled}
      data-testid={`btn-hijack-${conversationId}`}
      onClick={handleClick}
    >
      抢单
    </Button>
  );
}
