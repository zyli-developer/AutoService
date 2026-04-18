import { useState } from 'react';
import type { Envelope } from '@autoservice/ws-client';
import { useOperatorStore } from '../store/operatorStore';

interface IMInputProps {
  send: (frame: Envelope) => void;
}

export function IMInput({ send }: IMInputProps) {
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);
  const conversations = useOperatorStore((s) => s.conversations);
  const addCopilotMessage = useOperatorStore((s) => s.addCopilotMessage);
  const [inputText, setInputText] = useState('');

  const conv = activeCopilotConvId ? conversations[activeCopilotConvId] : null;
  const isTakeover = conv?.mode === 'takeover';

  const placeholder = activeCopilotConvId
    ? isTakeover
      ? '直接输入，会发给客户 (人工 driver 模式)'
      : '输入建议给 agent (不会发给客户)'
    : '发送消息到 Agent分队';

  const operatorId = useOperatorStore((s) => s.operatorId);

  const handleSend = () => {
    const text = inputText.trim();
    if (!text || !activeCopilotConvId) return;
    setInputText('');

    const id = crypto.randomUUID();
    const ts = new Date().toISOString();

    addCopilotMessage(activeCopilotConvId, { id, text, sender: 'operator', ts });

    // Send via WebSocket operator_message frame (unified operator write path)
    send({
      v: 1,
      type: 'operator_message',
      id,
      ts,
      payload: {
        conversation_id: activeCopilotConvId,
        operator_id: operatorId || 'operator',
        content: text,
      },
    } as Envelope);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="im-input">
      <div className="im-input-row">
        <textarea
          data-testid="copilot-input"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
        />
        <button
          data-testid="copilot-send"
          onClick={handleSend}
          disabled={!inputText.trim() || !activeCopilotConvId}
        >
          {'发送'}
        </button>
      </div>
    </div>
  );
}
