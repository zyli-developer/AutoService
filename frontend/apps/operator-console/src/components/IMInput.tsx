import { useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import type { Envelope } from '@autoservice/ws-client';
import { useOperatorStore } from '../store/operatorStore';

interface IMInputProps {
  send: (frame: Envelope) => void;
}

const CMD_HINTS = ['/hijack', '/release', '/resolve', '/assign'];

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

    // Mirror the backend gate: copilot/auto → SIDE suggestion, takeover → PUBLIC.
    // Without this, a hijack reply shows "建议" optimistically until the backend
    // echoes, and a copilot suggestion would briefly show as "driver".
    const visibility: 'public' | 'side' = isTakeover ? 'public' : 'side';
    addCopilotMessage(activeCopilotConvId, { id, text, sender: 'operator', ts, visibility });

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

  const insertCmd = (cmd: string) => {
    setInputText((prev) => {
      if (!prev) return cmd + ' ';
      return prev.endsWith(' ') ? prev + cmd + ' ' : prev + ' ' + cmd + ' ';
    });
  };

  return (
    <div className="im-input">
      {activeCopilotConvId && !isTakeover && (
        <div className="im-comp-hint side">
          💡 <b>{t('operator.input.hint.copilot_label')}</b> · {t('operator.input.hint.copilot_detail')}
        </div>
      )}
      {activeCopilotConvId && isTakeover && (
        <div className="im-comp-hint takeover">
          <b>{t('operator.input.hint.takeover_label')}</b> · {t('operator.input.hint.takeover_detail')}
        </div>
      )}
      <div className={`im-input-row ${isTakeover ? 'takeover' : ''}`}>
        <textarea
          data-testid="copilot-input"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={2}
        />
        <button
          type="button"
          data-testid="copilot-send"
          onClick={handleSend}
          disabled={!inputText.trim() || !activeCopilotConvId}
          className={isTakeover ? 'jade' : ''}
        >
          {t('common.send')}
        </button>
      </div>
      {activeCopilotConvId && (
        <div className="im-cmd-hint">
          {CMD_HINTS.map((cmd) => (
            <button
              key={cmd}
              type="button"
              className="im-cmd-hint-btn"
              onClick={() => insertCmd(cmd)}
            >
              {cmd}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
