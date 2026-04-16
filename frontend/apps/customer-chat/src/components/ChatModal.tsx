import { useRef } from 'react';
import type { ChatMessage } from '../store/chatStore';
import { useChatStore } from '../store/chatStore';
import { MessageBubble } from './MessageBubble';
import { ChatInput } from './ChatInput';
import { TypingIndicator } from './TypingIndicator';
import { ConnectionBanner } from './ConnectionBanner';
import { useAutoScroll } from '../hooks/useAutoScroll';

interface ChatModalProps {
  messages: ChatMessage[];
  onSend: (content: string) => void;
  onClose: () => void;
  disabled?: boolean;
  connectionStatus: 'idle' | 'connecting' | 'open' | 'closed';
  isReplaying?: boolean;
  replayCount?: number;
}

export function ChatModal({
  messages,
  onSend,
  onClose,
  disabled,
  connectionStatus,
  isReplaying = false,
  replayCount = 0,
}: ChatModalProps) {
  const isAgentTyping = useChatStore((s) => s.isAgentTyping);
  const bodyRef = useRef<HTMLDivElement>(null);
  useAutoScroll(bodyRef as React.RefObject<HTMLElement>, [messages.length]);

  return (
    <div className="web-modal" data-testid="chat-modal">
      <div className="web-modal-header">
        <div className="web-modal-title" data-testid="modal-title">
          {'\u667A\u80FD\u5BA2\u670D \u00B7 \u5728\u7EBF'}
        </div>
        <div
          className="web-modal-close"
          onClick={onClose}
          data-testid="modal-close"
          role="button"
          aria-label="Close chat"
        >
          {'\u00D7'}
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
      </div>
      <div className="web-modal-input">
        <ChatInput onSend={onSend} disabled={disabled} />
      </div>
    </div>
  );
}
