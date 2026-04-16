import { useRef } from 'react';
import type { ChatMessage } from '../store/chatStore';
import { MessageBubble } from './MessageBubble';
import { SystemMessage } from './SystemMessage';
import { useAutoScroll } from '../hooks/useAutoScroll';

interface MessageListProps {
  messages: ChatMessage[];
}

export function MessageList({ messages }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { isAtBottom, scrollToBottom } = useAutoScroll(
    containerRef as React.RefObject<HTMLElement>,
    [messages.length],
  );

  return (
    <div className="relative flex-1 overflow-hidden">
      <div
        ref={containerRef}
        className="h-full overflow-y-auto flex flex-col py-4"
        data-testid="message-list"
      >
        {messages.map((message) => {
          if (message.visibility === 'system') {
            return <SystemMessage key={message.id} content={message.content} />;
          }
          return <MessageBubble key={message.id} message={message} />;
        })}
        <div data-testid="typing-indicator-placeholder" />
      </div>

      {!isAtBottom && (
        <button
          data-testid="new-msg-btn"
          onClick={scrollToBottom}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-blue-500 text-white text-xs px-3 py-1.5 rounded-full shadow-lg hover:bg-blue-600 transition-colors"
        >
          New message ↓
        </button>
      )}
    </div>
  );
}
