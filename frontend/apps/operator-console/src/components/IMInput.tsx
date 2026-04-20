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

    addCopilotMessage(activeCopilotConvId, { id, text, sender: 'operator', ts });

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
          💡 <b>输入建议</b> · 仅对 agent 可见 · 不会发给客户
        </div>
      )}
      {activeCopilotConvId && isTakeover && (
        <div className="im-comp-hint takeover">
          <b>接管模式</b> · 你现在是 driver · 消息将直接发给客户 · AI 退居副驾驶
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
