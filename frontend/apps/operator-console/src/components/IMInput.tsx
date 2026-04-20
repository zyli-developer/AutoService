import { useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import type { Envelope } from '@autoservice/ws-client';
import { useOperatorStore } from '../store/operatorStore';

interface IMInputProps {
  send: (frame: Envelope) => void;
}

export function IMInput({ send }: IMInputProps) {
  const { t } = useTranslation();
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);
  const conversations = useOperatorStore((s) => s.conversations);
  const addCopilotMessage = useOperatorStore((s) => s.addCopilotMessage);
  const [inputText, setInputText] = useState('');

  const conv = activeCopilotConvId ? conversations[activeCopilotConvId] : null;
  const isTakeover = conv?.mode === 'takeover';

  const placeholder = activeCopilotConvId
    ? isTakeover
      ? t('operator.input.takeover.placeholder')
      : t('operator.input.copilot.placeholder')
    : t('operator.main.waiting_for_customer');

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
          {t('common.send')}
        </button>
      </div>
    </div>
  );
}
