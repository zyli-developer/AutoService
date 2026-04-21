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
        {isTakeover ? t('operator.chat.avatar.takeover') : (conv?.customerId || convId).slice(0, 1).toUpperCase()}
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
          {t('operator.chat.close')}
        </button>
      </div>
    </div>
  );
}

function StreamMessage({ msg }: { msg: CopilotMessage }) {
  const { t } = useTranslation();

  if (msg.sender === 'customer') {
    return (
      <div className="op-msg" data-testid={`copilot-message-${msg.id}`}>
        <div className="op-msg-av cust">{t('operator.chat.avatar.customer')}</div>
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
  // Tag is driven by the message's own visibility, not the current conv.mode.
  // Otherwise historical messages flip labels when the operator hijacks/releases:
  // a real SIDE suggestion would show as "driver" in takeover, and a PUBLIC
  // hijack reply would show as "建议" after release.
  const isSide = msg.visibility === 'side';
  if (msg.sender === 'operator') {
    if (!isSide) {
      return (
        <div className="op-msg" data-testid={`copilot-message-${msg.id}`}>
          <div className="op-msg-av op">{t('operator.chat.avatar.operator')}</div>
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
        <div className="op-msg-av op">{t('operator.chat.avatar.operator')}</div>
        <div className="op-msg-body">
          <div className="op-msg-meta">
            <b>{t('operator.copilot.operator')}</b>
            <span className="op-msg-tag side">{t('operator.chat.tag.suggestion')}</span>
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
      <div className="op-msg-av ai">{t('operator.chat.avatar.agent')}</div>
      <div className="op-msg-body">
        <div className="op-msg-meta">
          <b>agent</b>
          <span className="op-msg-tag">{isSide ? 'side' : 'auto'}</span>
          <span className="op-msg-time">{msg.ts}</span>
        </div>
        <div className="op-msg-text">{msg.text}</div>
      </div>
    </div>
  );
}

function SidePanel({ conv }: { conv: any }) {
  const { t } = useTranslation();
  const draftPlaceholder = conv?.lastMessage
    ? t('operator.panel.draft_placeholder_active', { snippet: (conv.lastMessage as string).slice(0, 60) })
    : t('operator.panel.draft_placeholder_idle');

  return (
    <aside className="op-side-panel">
      <div className="op-sp-sec">
        <div className="op-sp-lbl">
          <span>{t('operator.panel.snapshot_title')}</span>
          <span className="op-sp-meta">{t('operator.panel.crm_tag')}</span>
        </div>
        <div className="op-kv">
          <span className="op-k">{t('operator.panel.customer')}</span>
          <span className="op-v">{conv?.customerId ?? '—'}</span>
        </div>
        <div className="op-kv">
          <span className="op-k">{t('operator.panel.squad')}</span>
          <span className="op-v">{conv?.squadId ?? '—'}</span>
        </div>
        <div className="op-kv">
          <span className="op-k">{t('operator.panel.mode')}</span>
          <span className="op-v">{conv?.mode ?? '—'}</span>
        </div>
        <div className="op-kv">
          <span className="op-k">{t('operator.panel.state')}</span>
          <span className="op-v">{conv?.state ?? '—'}</span>
        </div>
        <div className="op-kv">
          <span className="op-k">{t('operator.panel.emotion')}</span>
          <span className="op-v" style={{ color: 'var(--spring-700)' }}>{t('operator.panel.emotion_neutral')}</span>
        </div>
      </div>

      <div className="op-sp-sec">
        <div className="op-sp-lbl">
          <span>{t('operator.panel.draft_title')}</span>
          <span className="op-sp-live">
            <span className="op-sp-live-dot" />
            {t('operator.panel.draft_live')}
          </span>
        </div>
        <div className="op-draft">{draftPlaceholder}</div>
        <div className="op-draft-actions">
          <button type="button" className="op-btn-mini pri">{t('operator.panel.draft.send')}</button>
          <button type="button" className="op-btn-mini">{t('operator.panel.draft.rewrite')}</button>
          <button type="button" className="op-btn-mini">{t('operator.panel.draft.keep')}</button>
        </div>
      </div>

      <div className="op-sp-sec">
        <div className="op-sp-lbl">
          <span>{t('operator.panel.kb_title')}</span>
          <span className="op-sp-meta">— hits</span>
        </div>
        <div className="op-kb-empty">
          {t('operator.panel.kb_empty')}
        </div>
      </div>
    </aside>
  );
}

export function CopilotView({ send }: CopilotViewProps) {
  const { t } = useTranslation();
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
            <span>{t('operator.stream.lbl')}</span>
            <b>{t('operator.stream.msg_count', { count: allMessages.length })}</b>
          </div>
          <div className="op-stream">
            {allMessages.length === 0 && (
              <div className="im-empty" style={{ padding: '40px 0' }}>
                {t('operator.stream.waiting')}
              </div>
            )}
            {allMessages.map((msg) => (
              <StreamMessage key={msg.id} msg={msg} />
            ))}
          </div>
        </div>
        <SidePanel conv={conv} />
      </div>
    </div>
  );
}
