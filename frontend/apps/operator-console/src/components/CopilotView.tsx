import { useEffect, useRef } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { MarkdownText } from '@autoservice/ui-components';
import { useOperatorStore, type CopilotMessage } from '../store/operatorStore';
import type { Envelope } from '@autoservice/ws-client';
import { TakeoverWarning } from './TakeoverWarning';
import { HijackButton } from './HijackButton';
import { TakeoverIndicator } from './TakeoverIndicator';
import { IMInput } from './IMInput';

interface CopilotViewProps {
  send: (frame: Envelope) => void;
  panelOpen?: boolean;
  onTogglePanel?: () => void;
  onOpenSheet?: () => void;
  onCloseSheet?: () => void;
  onBackToList?: () => void;
}

function ChatTop({
  convId,
  conv,
  isTakeover,
  send,
  onClose,
  panelOpen,
  onTogglePanel,
  onOpenSheet,
  onBackToList,
}: {
  convId: string;
  conv: any;
  isTakeover: boolean;
  send: (frame: Envelope) => void;
  onClose: () => void;
  panelOpen?: boolean;
  onTogglePanel?: () => void;
  onOpenSheet?: () => void;
  onBackToList?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="op-chat-top" data-testid="copilot-header">
      <button
        type="button"
        className="op-mobi-back"
        data-testid="op-mobi-back"
        onClick={onBackToList}
        aria-label={t('operator.chat.back')}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M15 18 9 12l6-6" />
        </svg>
      </button>
      <div className={`op-chat-av ${isTakeover ? 'a4' : 'a1'}`}>
        {isTakeover ? t('operator.chat.avatar.takeover') : (conv?.customerId || convId).slice(0, 1).toUpperCase()}
      </div>
      <div className="op-chat-title">
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
      <button
        type="button"
        className="op-mobi-detail-btn"
        data-testid="op-mobi-detail"
        onClick={onOpenSheet}
        aria-label={t('operator.chat.show_detail')}
      >
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 3h7v7" />
          <path d="M10 21H3v-7" />
          <path d="m21 3-7 7" />
          <path d="m3 21 7-7" />
        </svg>
        {t('operator.chat.detail')}
      </button>
      <div className="op-chat-actions">
        <button
          type="button"
          className={`op-detail-toggle ${panelOpen ? 'on' : ''}`}
          data-testid="op-detail-toggle"
          onClick={onTogglePanel}
          title={panelOpen ? t('operator.chat.collapse_detail') : t('operator.chat.expand_detail')}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            {panelOpen ? (
              <>
                <path d="M9 3v18" />
                <path d="m16 15-3-3 3-3" />
              </>
            ) : (
              <>
                <path d="M15 3v18" />
                <path d="m8 9 3 3-3 3" />
              </>
            )}
          </svg>
          {t('operator.chat.detail')}
        </button>
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
          <MarkdownText className="op-msg-text">{msg.text}</MarkdownText>
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
            <MarkdownText className="op-msg-text">{msg.text}</MarkdownText>
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
          <MarkdownText className="op-msg-text">{msg.text}</MarkdownText>
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
        <MarkdownText className="op-msg-text">{msg.text}</MarkdownText>
      </div>
    </div>
  );
}

function SidePanel({ conv, onCloseSheet }: { conv: any; onCloseSheet?: () => void }) {
  const { t } = useTranslation();
  const draftPlaceholder = conv?.lastMessage
    ? t('operator.panel.draft_placeholder_active', { snippet: (conv.lastMessage as string).slice(0, 60) })
    : t('operator.panel.draft_placeholder_idle');

  return (
    <aside className="op-side-panel">
      <button
        type="button"
        className="op-sheet-handle"
        onClick={onCloseSheet}
        aria-label={t('operator.chat.close_detail')}
        data-testid="op-sheet-handle"
      />
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

export function CopilotView({
  send,
  panelOpen,
  onTogglePanel,
  onOpenSheet,
  onCloseSheet,
  onBackToList,
}: CopilotViewProps) {
  const { t } = useTranslation();
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);
  const copilotMessages = useOperatorStore((s) => s.copilotMessages);
  const conversations = useOperatorStore((s) => s.conversations);
  const closeCopilot = useOperatorStore((s) => s.closeCopilot);

  // Sort by ts so SIDE / live / history-fetched frames interleave correctly.
  // Receive order isn't enough: history snapshots arrive after live frames
  // even when their timestamps are earlier, which causes [分流] SIDE summaries
  // to render below the placeholder reply they should precede.
  // Computed before the early-return so the hooks below run unconditionally
  // (rules of hooks — order must be stable across renders).
  const allMessages: CopilotMessage[] = activeCopilotConvId
    ? [...(copilotMessages[activeCopilotConvId] ?? [])]
        .sort((a, b) => (a.ts ?? '').localeCompare(b.ts ?? ''))
    : [];

  // Auto-scroll the stream container to the bottom whenever a new message
  // arrives OR the last message grows (progressive streaming edits). Re-runs
  // on length change and last-message text length so token-level fill-in
  // keeps the latest content visible without manual scrolling.
  const streamRef = useRef<HTMLDivElement>(null);
  const lastMessageLen = allMessages.length > 0
    ? (allMessages[allMessages.length - 1]?.text?.length ?? 0)
    : 0;
  useEffect(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [allMessages.length, lastMessageLen, activeCopilotConvId]);

  if (!activeCopilotConvId) return null;

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
        panelOpen={panelOpen}
        onTogglePanel={onTogglePanel}
        onOpenSheet={onOpenSheet}
        onBackToList={onBackToList}
      />
      <TakeoverWarning conversationId={activeCopilotConvId} send={send} />
      <div className={`op-chat-split ${panelOpen ? 'panel-open' : ''}`}>
        <div className="op-chat-col">
          <div className="op-stream-lbl">
            <span>{t('operator.stream.lbl')}</span>
            <b>{t('operator.stream.msg_count', { count: allMessages.length })}</b>
          </div>
          <div className="op-stream" ref={streamRef}>
            {allMessages.length === 0 && (
              <div className="im-empty" style={{ padding: '40px 0' }}>
                {t('operator.stream.waiting')}
              </div>
            )}
            {allMessages.map((msg) => (
              <StreamMessage key={msg.id} msg={msg} />
            ))}
          </div>
          <IMInput send={send} />
        </div>
        <SidePanel conv={conv} onCloseSheet={onCloseSheet} />
      </div>
    </div>
  );
}
