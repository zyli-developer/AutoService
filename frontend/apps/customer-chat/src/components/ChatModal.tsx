import { useRef, useEffect } from 'react';
import { useTranslation } from '@autoservice/i18n';
import type { ChatMessage } from '../store/chatStore';
import { useChatStore } from '../store/chatStore';
import { MessageBubble } from './MessageBubble';
import { ChatInput } from './ChatInput';
import { TypingIndicator } from './TypingIndicator';
import { ConnectionBanner } from './ConnectionBanner';
import { CSATRating } from './CSATRating';
import { useAutoScroll } from '../hooks/useAutoScroll';

interface ChatModalProps {
  messages: ChatMessage[];
  onSend: (content: string) => void;
  onClose: () => void;
  onCsatSubmit: (score: number) => void;
  disabled?: boolean;
  connectionStatus: 'idle' | 'connecting' | 'open' | 'closed';
  isReplaying?: boolean;
  replayCount?: number;
}

export function ChatModal({
  messages,
  onSend,
  onClose,
  onCsatSubmit,
  disabled,
  connectionStatus,
  isReplaying = false,
  replayCount = 0,
}: ChatModalProps) {
  const { t } = useTranslation();
  const isAgentTyping = useChatStore((s) => s.isAgentTyping);
  const csatRequest = useChatStore((s) => s.csatRequest);
  const bodyRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  useAutoScroll(bodyRef as React.RefObject<HTMLElement>, [messages.length]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, isAgentTyping]);

  return (
    <div className="web-modal" data-testid="chat-modal">
      <div className="web-modal-header">
        <div className="w-hd-av">{'店'}</div>
        <div className="w-hd-info">
          <div className="web-modal-title" data-testid="modal-title">
            {t('customer.chat.title')}
          </div>
          <div className="w-hd-sub">
            <span className="w-hd-dot" />
            {'通常 30 秒内回复 · 今天 09:00 – 24:00'}
          </div>
        </div>
        <div className="w-hd-actions">
          <button
            type="button"
            className="w-hd-btn"
            data-testid="modal-minimize"
            onClick={onClose}
            aria-label="Minimize chat"
            title="收起"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M5 12h14" />
            </svg>
          </button>
          <button
            type="button"
            className="w-hd-btn"
            onClick={onClose}
            data-testid="modal-close"
            aria-label={t('customer.chat.close')}
            title="关闭"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>
      <ConnectionBanner
        status={connectionStatus}
        isReplaying={isReplaying}
        replayCount={replayCount}
      />
      <div className="web-modal-body" ref={bodyRef} data-testid="message-list">
        <div className="w-day">{'今天 · 09:38'}</div>
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        <TypingIndicator visible={isAgentTyping} />
        <div ref={endRef} />
      </div>
      <div className="web-modal-input">
        <ChatInput onSend={onSend} disabled={disabled} />
      </div>
      {csatRequest && <CSATRating onSubmit={onCsatSubmit} />}
    </div>
  );
}
