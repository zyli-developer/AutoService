import { useEffect, useRef } from 'react';
import { WSClient, type Envelope, type ServerHelloPayload } from '@autoservice/ws-client';
import { useChatStore } from '../store/chatStore';
import type { FeToBeType } from '@autoservice/ws-client';

export function useWebSocket(
  url: string,
  clientApp: string,
): { status: ReturnType<typeof useChatStore.getState>['connectionStatus']; lastFrame: Envelope | null; sessionId: string | null; send: (type: string, payload: unknown) => Promise<void> } {
  const clientRef = useRef<WSClient | null>(null);
  const lastFrameRef = useRef<Envelope | null>(null);

  const store = useChatStore();

  useEffect(() => {
    useChatStore.getState().setConnectionStatus('connecting');

    const client = new WSClient({
      url,
      clientApp,
      heartbeatMs: 20_000,
      onOpen: (hello: ServerHelloPayload) => {
        useChatStore.getState().setSessionId(hello.session_id);
        useChatStore.getState().setConnectionStatus('open');
      },
      onClose: () => {
        useChatStore.getState().setConnectionStatus('closed');
      },
      onFrame: (frame: Envelope) => {
        lastFrameRef.current = frame;

        if (frame.type === 'message') {
          const p = frame.payload as Record<string, unknown>;
          const msg = p.message as Record<string, unknown> | undefined;
          if (msg) {
            useChatStore.getState().addMessage({
              id: msg.id as string,
              source: msg.source as string ?? '',
              sourceRole: (p.source_display as Record<string, unknown>)?.role as 'customer' | 'agent' | 'operator' | 'system' | undefined,
              content: msg.content as string ?? '',
              visibility: (msg.visibility as 'public' | 'side' | 'system') ?? 'public',
              timestamp: msg.timestamp as string ?? new Date().toISOString(),
              sequenceNumber: (msg.sequence_number as number) ?? 0,
              status: 'sent',
            });
          }
        } else if (frame.type === 'message_edited') {
          const p = frame.payload as Record<string, unknown>;
          const messageId = p.message_id as string;
          const content = p.content as string;
          if (messageId && content !== undefined) {
            useChatStore.getState().updateMessage(messageId, content);
          }
        } else if (frame.type === 'event') {
          const p = frame.payload as Record<string, unknown>;
          const eventType = p.event_type as string;
          if (
            eventType === 'conversation.created' ||
            eventType === 'conversation.activated'
          ) {
            const conversationId = p.conversation_id as string;
            if (conversationId) {
              useChatStore.getState().setConversationId(conversationId);
            }
          }
        }
      },
    });

    clientRef.current = client;
    client.connect();

    return () => {
      client.close();
    };
  }, [url, clientApp]);

  const send = async (type: string, payload: unknown): Promise<void> => {
    const client = clientRef.current;
    if (!client) throw new Error('ws_not_ready');
    return client.send(type as FeToBeType, payload);
  };

  return {
    status: store.connectionStatus,
    lastFrame: lastFrameRef.current,
    sessionId: store.sessionId,
    send,
  };
}
