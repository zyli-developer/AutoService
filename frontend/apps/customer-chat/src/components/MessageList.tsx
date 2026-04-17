import { useRef, useMemo } from 'react';
import type { ChatMessage } from '../store/chatStore';
import { useChatStore } from '../store/chatStore';
import { groupMessages, MessageGroup } from './MessageGroup';
import type { MessageGroupData } from './MessageGroup';
import { SystemMessage } from './SystemMessage';
import { TypingIndicator } from './TypingIndicator';
import { useAutoScroll } from '../hooks/useAutoScroll';

interface MessageListProps {
  messages: ChatMessage[];
}

type ListItem =
  | { type: 'system'; id: string; content: string }
  | { type: 'group'; key: string; group: MessageGroupData };

export function MessageList({ messages }: MessageListProps) {
  const isAgentTyping = useChatStore((s) => s.isAgentTyping);
  const containerRef = useRef<HTMLDivElement>(null);
  const { isAtBottom, scrollToBottom } = useAutoScroll(
    containerRef as React.RefObject<HTMLElement>,
    [messages.length],
  );

  const items = useMemo((): ListItem[] => {
    const result: ListItem[] = [];
    let pending: ChatMessage[] = [];

    const flushPending = () => {
      if (pending.length === 0) return;
      const grouped = groupMessages(pending);
      grouped.forEach((g, i) => {
        result.push({ type: 'group', key: `${pending[0].id}-${i}`, group: g });
      });
      pending = [];
    };

    for (const msg of messages) {
      if (msg.visibility === 'system') {
        flushPending();
        result.push({ type: 'system', id: msg.id, content: msg.content });
      } else {
        pending.push(msg);
      }
    }
    flushPending();
    return result;
  }, [messages]);

  return (
    <div className="relative flex-1 overflow-hidden">
      <div
        ref={containerRef}
        className="h-full overflow-y-auto flex flex-col py-4"
        data-testid="message-list"
      >
        {items.map((item) =>
          item.type === 'system' ? (
            <SystemMessage key={item.id} content={item.content} />
          ) : (
            <MessageGroup key={item.key} group={item.group} />
          ),
        )}
        <TypingIndicator visible={isAgentTyping} />
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
