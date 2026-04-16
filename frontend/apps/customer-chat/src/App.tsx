import { useRef } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useChatStore } from './store/chatStore';
import { ChatLayout } from './components/ChatLayout';
import { ChatHeader } from './components/ChatHeader';
import { MessageList } from './components/MessageList';
import { ChatInput } from './components/ChatInput';
import { ConnectionBanner } from './components/ConnectionBanner';

export function App() {
  const wsUrl = `ws://${window.location.hostname}:8000/ws/customer`;
  const { send } = useWebSocket(wsUrl, 'customer-chat');
  const { messages, connectionStatus, isReplaying, replayCount } = useChatStore();
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSend = async (content: string) => {
    const clientMsgId = crypto.randomUUID();
    // Optimistic add
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

    // Show typing indicator while waiting for agent response
    useChatStore.getState().setAgentTyping(true);

    // Auto-clear after 30s in case no response
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
      // Mark as failed on send error
      if (typingTimerRef.current) {
        clearTimeout(typingTimerRef.current);
        typingTimerRef.current = null;
      }
      useChatStore.getState().setAgentTyping(false);
      useChatStore.getState().updateMessage(clientMsgId, content);
    }
  };

  return (
    <>
      <ConnectionBanner status={connectionStatus} isReplaying={isReplaying} replayCount={replayCount} />
      <ChatLayout
        header={<ChatHeader status={connectionStatus} />}
        messageList={<MessageList messages={messages} />}
        input={<ChatInput onSend={handleSend} disabled={connectionStatus !== 'open'} />}
      />
    </>
  );
}
