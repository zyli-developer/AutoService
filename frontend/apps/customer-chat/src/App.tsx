import { useWebSocket } from './hooks/useWebSocket';
import { useChatStore } from './store/chatStore';
import { ChatLayout } from './components/ChatLayout';
import { ChatHeader } from './components/ChatHeader';
import { MessageList } from './components/MessageList';
import { ChatInput } from './components/ChatInput';
import { ConnectionBanner } from './components/ConnectionBanner';

export function App() {
  const { send } = useWebSocket('ws://localhost:9999/ws/customer', 'customer-chat');
  const { messages, connectionStatus } = useChatStore();

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
    try {
      await send('customer_message', { content, client_msg_id: clientMsgId });
    } catch {
      // Mark as failed on send error
      useChatStore.getState().updateMessage(clientMsgId, content);
    }
  };

  return (
    <>
      <ConnectionBanner status={connectionStatus} />
      <ChatLayout
        header={<ChatHeader status={connectionStatus} />}
        messageList={<MessageList messages={messages} />}
        input={<ChatInput onSend={handleSend} disabled={connectionStatus !== 'open'} />}
      />
    </>
  );
}
