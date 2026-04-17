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

  const operatorId = useOperatorStore((s) => s.operatorId);
  const updateConversation = useOperatorStore((s) => s.updateConversation);

  const handleHijack = async () => {
    try {
      const API = `http://${window.location.hostname}:8000`;
      const resp = await fetch(
        `${API}/api/command/hijack?conversation_id=${encodeURIComponent(activeCopilotConvId!)}&operator_id=${encodeURIComponent(operatorId || 'operator')}`,
        { method: 'POST' },
      );
      const result = await resp.json();
      console.log('[Hijack] result:', result);
      if (result.ok) {
        updateConversation(activeCopilotConvId!, { mode: result.mode });
      }
    } catch (err) {
      console.error('[Hijack] failed:', err);
    }
  };

  return (
    <>
      <div className="im-main-header" data-testid="copilot-header">
        <div className="im-main-title">
          {'聊天窗'} {activeCopilotConvId.slice(0, 8)}
          {isTakeover && (
            <span data-testid="takeover-indicator" style={{ color: 'var(--p)', fontSize: 11, marginLeft: 8, fontWeight: 700 }}>
              TAKEOVER
            </span>
          )}
        </div>
        <div className="im-main-subtitle">
          {isTakeover
            ? '⚡ 人工已接管 · agent 副驾驶'
            : '默认 copilot 模式 · agent driver'}
        </div>
      </div>
      <div className="im-feed" data-testid="copilot-sidebar">
        {messages.map((msg) => {
          if (msg.sender === 'customer') {
            return (
              <div key={msg.id} className="im-relay-line" data-testid={`copilot-message-${msg.id}`}>
                {'客户说'}: <span className="quote">{msg.text}</span>
              </div>
            );
          }
          if (msg.sender === 'operator') {
            if (isTakeover) {
              return (
                <div key={msg.id} className="im-driver" data-testid={`copilot-message-${msg.id}`}>
                  {'\uD83D\uDC64'} <b>{'客服'}</b>: {msg.text}
                </div>
              );
            }
            return (
              <div key={msg.id} className="im-suggest" data-testid={`copilot-message-${msg.id}`}>
                {'\uD83D\uDCA1'} <b>{'客服'}</b>: {msg.text}
              </div>
            );
          }
          // agent
          if (isTakeover) {
            return (
              <div key={msg.id} className="im-sidebar-msg" data-testid={`copilot-message-${msg.id}`}>
                [{'侧栏'}] agent: {msg.text}
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
                  {'拟回复'}: <span className="quote">{msg.text}</span>
                </div>
              </div>
            </div>
          );
        })}
        {messages.length === 0 && (
          <div className="im-empty">{'暂无消息'}</div>
        )}
        <div className="im-system">
          {isTakeover
            ? '↻ 人工 driver · agent 副驾驶'
            : '↻ 实时刷新中'}
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
            <span className="im-cmd">/hijack</span> {'抢单'}
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
          {'返回列表'}
        </button>
      </div>
    </>
  );
}
