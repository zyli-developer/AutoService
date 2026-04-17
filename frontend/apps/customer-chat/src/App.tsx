import { useState, useRef, useMemo } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useChatStore } from './store/chatStore';
import { MerchantSite } from './components/MerchantSite';
import { ChatFAB } from './components/ChatFAB';
import { ChatModal } from './components/ChatModal';

// Unique customer ID per browser tab (persisted in sessionStorage)
function getCustomerId(): string {
  let id = sessionStorage.getItem('customer_id');
  if (!id) {
    id = `cust_${crypto.randomUUID().slice(0, 8)}`;
    sessionStorage.setItem('customer_id', id);
  }
  return id;
}

export function App() {
  const wsUrl = `ws://${window.location.hostname}:8000/ws/customer`;
  const { send } = useWebSocket(wsUrl, 'customer-chat');
  const { messages, connectionStatus, isReplaying, replayCount } = useChatStore();
  const [isOpen, setIsOpen] = useState(false);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const customerId = useMemo(getCustomerId, []);

  const handleSend = async (content: string) => {
    const clientMsgId = crypto.randomUUID();
    useChatStore.getState().addMessage({
      id: clientMsgId,
      clientMsgId,
      source: 'customer',
      sourceRole: 'customer',
      content,
      visibility: 'public',
      timestamp: new Date().toISOString(),
      sequenceNumber: 0,
      status: 'sending',
    });

    useChatStore.getState().setAgentTyping(true);

    if (typingTimerRef.current) {
      clearTimeout(typingTimerRef.current);
    }
    typingTimerRef.current = setTimeout(() => {
      useChatStore.getState().setAgentTyping(false);
      typingTimerRef.current = null;
    }, 30_000);

    try {
      const convId = useChatStore.getState().conversationId;
      await send('customer_message', {
        content,
        source: customerId,
        client_msg_id: clientMsgId,
        ...(convId ? { conversation_id: convId } : {}),
      });
    } catch {
      if (typingTimerRef.current) {
        clearTimeout(typingTimerRef.current);
        typingTimerRef.current = null;
      }
      useChatStore.getState().setAgentTyping(false);
      useChatStore.getState().updateMessage(clientMsgId, content);
    }
  };

  const handleCsatSubmit = async (score: number) => {
    const convId = useChatStore.getState().conversationId;
    if (!convId) return;
    try {
      await send('csat_response', {
        conversation_id: convId,
        score,
      });
      useChatStore.getState().setCsatSubmitted();
    } catch {
      // Silently fail — user already sees the score they selected
    }
  };

  return (
    <div className="web-canvas">
      <MerchantSite />
      {isOpen ? (
        <ChatModal
          messages={messages}
          onSend={handleSend}
          onClose={() => setIsOpen(false)}
          onCsatSubmit={handleCsatSubmit}
          disabled={connectionStatus !== 'open'}
          connectionStatus={connectionStatus}
          isReplaying={isReplaying}
          replayCount={replayCount}
        />
      ) : null}
      <ChatFAB onClick={() => setIsOpen(true)} highlight={!isOpen} />
    </div>
  );
}
