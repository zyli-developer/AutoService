import { useOperatorStore, type CopilotMessage } from '../store/operatorStore';
import type { Envelope } from '@autoservice/ws-client';

interface CopilotViewProps {
  send: (frame: Envelope) => void;
}

export function CopilotView({ send }: CopilotViewProps) {
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);
  const copilotMessages = useOperatorStore((s) => s.copilotMessages);
  const conversations = useOperatorStore((s) => s.conversations);
  const closeCopilot = useOperatorStore((s) => s.closeCopilot);

  if (!activeCopilotConvId) return null;

  const messages: CopilotMessage[] = copilotMessages[activeCopilotConvId] ?? [];
  const conv = conversations[activeCopilotConvId];
  const isTakeover = conv?.mode === 'takeover';

  const handleHijack = () => {
    send({
      v: 1,
      type: 'operator_command',
      id: crypto.randomUUID(),
      ts: new Date().toISOString(),
      payload: { conversation_id: activeCopilotConvId, command: '/hijack' },
    } as Envelope);
  };

  return (
    <>
      <div className="im-main-header" data-testid="copilot-header">
        <div className="im-main-title">
          {'\u804A\u5929\u7A97'} {activeCopilotConvId.slice(0, 8)}
          {isTakeover && (
            <span data-testid="takeover-indicator" style={{ color: 'var(--p)', fontSize: 11, marginLeft: 8, fontWeight: 700 }}>
              TAKEOVER
            </span>
          )}
        </div>
        <div className="im-main-subtitle">
          {isTakeover
            ? '\u26A1 \u4EBA\u5DE5\u5DF2\u63A5\u7BA1 \u00B7 agent \u526F\u9A7E\u9A76'
            : '\u9ED8\u8BA4 copilot \u6A21\u5F0F \u00B7 agent driver'}
        </div>
      </div>
      <div className="im-feed" data-testid="copilot-sidebar">
        {messages.map((msg) => {
          if (msg.sender === 'customer') {
            return (
              <div key={msg.id} className="im-relay-line" data-testid={`copilot-message-${msg.id}`}>
                {'\u5BA2\u6237\u8BF4'}: <span className="quote">{msg.text}</span>
              </div>
            );
          }
          if (msg.sender === 'operator') {
            if (isTakeover) {
              return (
                <div key={msg.id} className="im-driver" data-testid={`copilot-message-${msg.id}`}>
                  {'\uD83D\uDC64'} <b>{'\u5BA2\u670D'}</b>: {msg.text}
                </div>
              );
            }
            return (
              <div key={msg.id} className="im-suggest" data-testid={`copilot-message-${msg.id}`}>
                {'\uD83D\uDCA1'} <b>{'\u5BA2\u670D'}</b>: {msg.text}
              </div>
            );
          }
          // agent
          if (isTakeover) {
            return (
              <div key={msg.id} className="im-sidebar-msg" data-testid={`copilot-message-${msg.id}`}>
                [{'\u4FA7\u680F'}] agent: {msg.text}
              </div>
            );
          }
          return (
            <div key={msg.id} className="im-card" data-testid={`copilot-message-${msg.id}`}>
              <div className="im-avatar a1">a</div>
              <div className="im-msg-body">
                <div className="im-msg-meta">
                  <span className="im-msg-author">agent</span>
                  <span className="im-msg-bot-tag">APP</span>
                  <span className="im-msg-time">{msg.ts}</span>
                </div>
                <div className="im-relay-line">
                  {'\u62DF\u56DE\u590D'}: <span className="quote">{msg.text}</span>
                </div>
              </div>
            </div>
          );
        })}
        {messages.length === 0 && (
          <div className="im-empty">{'\u6682\u65E0\u6D88\u606F'}</div>
        )}
        <div className="im-system">
          {isTakeover
            ? '\u21BB \u4EBA\u5DE5 driver \u00B7 agent \u526F\u9A7E\u9A76'
            : '\u21BB \u5B9E\u65F6\u5237\u65B0\u4E2D'}
        </div>
      </div>
      <div style={{ padding: '8px 20px', display: 'flex', gap: 8 }}>
        {!isTakeover && (
          <button
            data-testid={`btn-hijack-${activeCopilotConvId}`}
            onClick={handleHijack}
            style={{
              background: 'var(--p)',
              color: '#fff',
              border: 'none',
              borderRadius: 9,
              padding: '6px 14px',
              fontSize: 12,
              fontWeight: 700,
              cursor: 'pointer',
              fontFamily: 'var(--font-sans)',
            }}
          >
            <span className="im-cmd">/hijack</span> {'\u62A2\u5355'}
          </button>
        )}
        <button
          data-testid="copilot-close"
          onClick={closeCopilot}
          style={{
            background: 'transparent',
            border: '1px solid var(--oat)',
            borderRadius: 9,
            padding: '6px 14px',
            fontSize: 12,
            color: 'var(--charcoal)',
            cursor: 'pointer',
            fontFamily: 'var(--font-sans)',
          }}
        >
          {'\u8FD4\u56DE\u5217\u8868'}
        </button>
      </div>
    </>
  );
}
