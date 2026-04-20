import { useTranslation } from '@autoservice/i18n';
import { useOperatorStore, type CopilotMessage } from '../store/operatorStore';
import type { Envelope } from '@autoservice/ws-client';
import { TakeoverWarning } from './TakeoverWarning';
import { HijackButton } from './HijackButton';
import { TakeoverIndicator } from './TakeoverIndicator';

interface CopilotViewProps {
  send: (frame: Envelope) => void;
}

function ChatTop({
  convId,
  conv,
  isTakeover,
  send,
  onClose,
}: {
  convId: string;
  conv: any;
  isTakeover: boolean;
  send: (frame: Envelope) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="op-chat-top" data-testid="copilot-header">
      <div className={`op-chat-av ${isTakeover ? 'a4' : 'a1'}`}>
        {isTakeover ? '人' : (conv?.customerId || convId).slice(0, 1).toUpperCase()}
      </div>
      <div className="op-chat-info">
        <h3 className="op-chat-h3">
          {t('operator.copilot.chat_window')} #{convId.slice(0, 6)}
          {conv?.customerId && <span className="op-chat-cust"> · {conv.customerId}</span>}
        </h3>
        <div className="op-chat-sub">
          <span className={`op-mode-pill ${isTakeover ? 'takeover' : ''}`}>
            mode: {isTakeover ? 'takeover' : 'copilot'}
          </span>
          <span>· driver: {isTakeover ? t('operator.copilot.operator') : conv?.squadId || 'agent'}</span>
          <TakeoverIndicator conversationId={convId} />
        </div>
      </div>
      <div className="op-chat-actions">
        <HijackButton conversationId={convId} send={send} />
        <button
          type="button"
          data-testid="copilot-close"
          onClick={onClose}
          className="op-chat-act-btn"
        >
          关闭
        </button>
      </div>
    </div>
  );
}

function StreamMessage({ msg, isTakeover }: { msg: CopilotMessage; isTakeover: boolean }) {
  const { t } = useTranslation();

  if (msg.sender === 'customer') {
    return (
      <div className="op-msg" data-testid={`copilot-message-${msg.id}`}>
        <div className="op-msg-av cust">客</div>
        <div className="op-msg-body">
          <div className="op-msg-meta">
            <b>{t('operator.copilot.customer_says')}</b>
            <span className="op-msg-tag">cust</span>
            <span className="op-msg-time">{msg.ts}</span>
          </div>
          <div className="op-msg-text">{msg.text}</div>
        </div>
      </div>
    );
  }
  if (msg.sender === 'operator') {
    if (isTakeover) {
      return (
        <div className="op-msg" data-testid={`copilot-message-${msg.id}`}>
          <div className="op-msg-av op">李</div>
          <div className="op-msg-body">
            <div className="op-msg-meta">
              <b>{t('operator.copilot.operator')}</b>
              <span className="op-msg-tag op">driver</span>
              <span className="op-msg-time">{msg.ts}</span>
            </div>
            <div className="op-msg-text">{msg.text}</div>
          </div>
        </div>
      );
    }
    return (
      <div className="op-msg side" data-testid={`copilot-message-${msg.id}`}>
        <div className="op-msg-av op">李</div>
        <div className="op-msg-body">
          <div className="op-msg-meta">
            <b>{t('operator.copilot.operator')}</b>
            <span className="op-msg-tag side">建议</span>
            <span className="op-msg-time">{msg.ts}</span>
          </div>
          <div className="op-msg-text">{msg.text}</div>
        </div>
      </div>
    );
  }
  // agent
  return (
    <div className="op-msg" data-testid={`copilot-message-${msg.id}`}>
      <div className="op-msg-av ai">店</div>
      <div className="op-msg-body">
        <div className="op-msg-meta">
          <b>agent</b>
          <span className="op-msg-tag">{isTakeover ? 'side' : 'auto'}</span>
          <span className="op-msg-time">{msg.ts}</span>
        </div>
        <div className="op-msg-text">{msg.text}</div>
      </div>
    </div>
  );
}

function SidePanel({ conv }: { conv: any }) {
  return (
    <aside className="op-side-panel">
      <div className="op-sp-sec">
        <div className="op-sp-lbl">
          <span>客户快照</span>
          <span className="op-sp-meta">crm</span>
        </div>
        <div className="op-kv">
          <span className="op-k">客户</span>
          <span className="op-v">{conv?.customerId ?? '—'}</span>
        </div>
        <div className="op-kv">
          <span className="op-k">分队</span>
          <span className="op-v">{conv?.squadId ?? '—'}</span>
        </div>
        <div className="op-kv">
          <span className="op-k">模式</span>
          <span className="op-v">{conv?.mode ?? '—'}</span>
        </div>
        <div className="op-kv">
          <span className="op-k">状态</span>
          <span className="op-v">{conv?.state ?? '—'}</span>
        </div>
        <div className="op-kv">
          <span className="op-k">情绪</span>
          <span className="op-v" style={{ color: 'var(--spring-700)' }}>● 中性</span>
        </div>
      </div>

      <div className="op-sp-sec">
        <div className="op-sp-lbl">
          <span>Agent 拟回复</span>
          <span className="op-sp-live">
            <span className="op-sp-live-dot" />
            streaming
          </span>
        </div>
        <div className="op-draft">
          {conv?.lastMessage
            ? `回应「${(conv.lastMessage as string).slice(0, 60)}」的拟回复将出现在这里…`
            : '等待 agent 起草回复…'}
        </div>
        <div className="op-draft-actions">
          <button type="button" className="op-btn-mini pri">发送</button>
          <button type="button" className="op-btn-mini">改写</button>
          <button type="button" className="op-btn-mini">保留</button>
        </div>
      </div>

      <div className="op-sp-sec">
        <div className="op-sp-lbl">
          <span>知识库参考</span>
          <span className="op-sp-meta">— hits</span>
        </div>
        <div className="op-kb-empty">
          知识库命中将在 agent 检索后出现
        </div>
      </div>
    </aside>
  );
}

export function CopilotView({ send }: CopilotViewProps) {
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);
  const copilotMessages = useOperatorStore((s) => s.copilotMessages);
  const conversations = useOperatorStore((s) => s.conversations);
  const closeCopilot = useOperatorStore((s) => s.closeCopilot);

  if (!activeCopilotConvId) return null;

  const allMessages: CopilotMessage[] = copilotMessages[activeCopilotConvId] ?? [];
  const conv = conversations[activeCopilotConvId];
  const isTakeover = conv?.mode === 'takeover';

  return (
    <div className="op-chat-pane" data-testid="copilot-sidebar">
      <ChatTop
        convId={activeCopilotConvId}
        conv={conv}
        isTakeover={isTakeover}
        send={send}
        onClose={closeCopilot}
      />
      <TakeoverWarning conversationId={activeCopilotConvId} send={send} />
      <div className="op-chat-split">
        <div className="op-chat-col">
          <div className="op-stream-lbl">
            <span>客户 ⇄ Agent · public 可见</span>
            <b>{allMessages.length} 条消息</b>
          </div>
          <div className="op-stream">
            {allMessages.length === 0 && (
              <div className="im-empty" style={{ padding: '40px 0' }}>
                等待消息接入…
              </div>
            )}
            {allMessages.map((msg) => (
              <StreamMessage key={msg.id} msg={msg} isTakeover={isTakeover} />
            ))}
          </div>
        </div>
        <SidePanel conv={conv} />
      </div>
    </div>
  );
}
