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

  // Force scroll to bottom on new messages
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, isAgentTyping]);

  return (
    <div className="web-modal" data-testid="chat-modal">
      <div className="web-modal-header">
        <div className="web-modal-title" data-testid="modal-title">
          {t('customer.chat.title')}
        </div>
        <div
          className="web-modal-close"
          onClick={onClose}
          data-testid="modal-close"
          role="button"
          aria-label={t('customer.chat.close')}
        >
          {'×'}
        </div>
      </div>
      <ConnectionBanner
        status={connectionStatus}
        isReplaying={isReplaying}
        replayCount={replayCount}
      />
      <div className="web-modal-body" ref={bodyRef} data-testid="message-list">
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
