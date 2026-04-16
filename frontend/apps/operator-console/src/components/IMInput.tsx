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
      ? '\u76F4\u63A5\u8F93\u5165\uFF0C\u4F1A\u53D1\u7ED9\u5BA2\u6237 (\u4EBA\u5DE5 driver \u6A21\u5F0F)'
      : '\u8F93\u5165\u5EFA\u8BAE\u7ED9 agent (\u4E0D\u4F1A\u53D1\u7ED9\u5BA2\u6237)'
    : '\u53D1\u9001\u6D88\u606F\u5230 Agent\u5206\u961F';

  const handleSend = () => {
    const text = inputText.trim();
    if (!text || !activeCopilotConvId) return;

    const id = crypto.randomUUID();
    const ts = new Date().toISOString();

    addCopilotMessage(activeCopilotConvId, {
      id,
      text,
      sender: 'operator',
      ts,
    });

    send({
      v: 1,
      type: isTakeover ? 'send_message' : 'operator_message',
      id,
      ts,
      payload: {
        conversation_id: activeCopilotConvId,
        text,
        ...(isTakeover ? { visible_to_customer: true } : {}),
      },
    } as Envelope);

    setInputText('');
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
          {'\u53D1\u9001'}
        </button>
      </div>
    </div>
  );
}
