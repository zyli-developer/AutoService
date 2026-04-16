import { useState, useRef } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useChatStore } from './store/chatStore';
import { MerchantSite } from './components/MerchantSite';
import { ChatFAB } from './components/ChatFAB';
import { ChatModal } from './components/ChatModal';

export function App() {
  const wsUrl = `ws://${window.location.hostname}:8000/ws/customer`;
  const { send } = useWebSocket(wsUrl, 'customer-chat');
  const { messages, connectionStatus, isReplaying, replayCount } = useChatStore();
  const [isOpen, setIsOpen] = useState(false);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  return (
    <div className="web-canvas">
      <MerchantSite />
      {isOpen ? (
        <ChatModal
          messages={messages}
          onSend={handleSend}
          onClose={() => setIsOpen(false)}
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
