import { useEffect, useRef } from 'react';
import { WSClient, type Envelope, type ServerHelloPayload } from '@autoservice/ws-client';
import type { LastSeenCursor } from '@autoservice/ws-client';
import { useChatStore } from '../store/chatStore';
import type { FeToBeType } from '@autoservice/ws-client';
import type { ChatMessage } from '../store/chatStore';
import { loadCursor, saveCursor, updateConvCursor } from '../utils/lastSeenCursor';

export function useWebSocket(url: string, clientApp: string) {
  const clientRef = useRef<WSClient | null>(null);
  const cursorRef = useRef<LastSeenCursor>(loadCursor() ?? {});
  const wasReconnectRef = useRef(false);
  const store = useChatStore();

  useEffect(() => {
    useChatStore.getState().setConnectionStatus('connecting');

    const client = new WSClient({
      url,
      clientApp,
      heartbeatMs: 20_000,
      lastSeen: Object.keys(cursorRef.current.conv_seq ?? {}).length > 0
        ? cursorRef.current
        : undefined,

      onOpen: (hello: ServerHelloPayload) => {
        useChatStore.getState().setSessionId(hello.session_id);
        // Tenant brand arrives on the handshake for the customer role only;
        // undefined means "tenant has no brand configured" → widget uses
        // i18n fallback (see ChatModal / MessageBubble).
        useChatStore.getState().setBrandName(hello.brand_name ?? null);
        useChatStore.getState().setConnectionStatus('open');
        if (wasReconnectRef.current) {
          useChatStore.getState().setReplaying(true);
          wasReconnectRef.current = false;
          // Auto-clear replay if server never sends replay_complete
          setTimeout(() => {
            if (useChatStore.getState().isReplaying) {
              useChatStore.getState().setReplaying(false);
            }
          }, 5_000);
        }
      },

      onClose: (code: number) => {
        useChatStore.getState().setConnectionStatus('closed');
        // 1000 = normal close, 4003 = permission revoked, 4409 = conflict → don't mark reconnect
        if (code !== 1000 && code !== 4003 && code !== 4409) {
          wasReconnectRef.current = true;
        }
      },

      onFrame: (frame: Envelope) => {
        const store = useChatStore.getState();

        if (frame.type === 'message_confirm') {
          const p = frame.payload as Record<string, unknown>;
          const clientMsgId = p.client_msg_id as string | undefined;
          const convId = p.conversation_id as string | undefined;
          if (clientMsgId) {
            store.confirmOptimistic(clientMsgId, {
              id: p.message_id as string,
              sequenceNumber: (p.sequence_number as number) ?? 0,
              timestamp: (p.timestamp as string) ?? new Date().toISOString(),
            });
          }
          if (convId && !store.conversationId) {
            store.setConversationId(convId);
          }

        } else if (frame.type === 'message') {
          const p = frame.payload as Record<string, unknown>;
          const msg = p.message as Record<string, unknown> | undefined;
          const sourceDisplay = p.source_display as Record<string, unknown> | undefined;
          const convId = p.conversation_id as string | undefined;
          if (msg) {
            const metadata = msg.metadata as Record<string, unknown> | undefined;
            const isPlaceholder = (metadata?.is_placeholder as boolean) === true;
            const attachmentUrl = metadata?.attachment_url as string | undefined;
            const seqNum = (msg.sequence_number as number) ?? 0;

            // Update cursor (only if convId is known)
            if (convId) {
              const newCursor = updateConvCursor(cursorRef.current, convId, 'msg', seqNum);
              cursorRef.current = newCursor;
              saveCursor(newCursor);
              store.updateCursor(newCursor);
            }

            store.addMessageDedup({
              id: msg.id as string,
              source: (msg.source as string) ?? '',
              sourceRole: sourceDisplay?.role as ChatMessage['sourceRole'],
              senderName: sourceDisplay?.name as string | undefined,
              avatarUrl: sourceDisplay?.avatar_url as string | undefined,
              content: (msg.content as string) ?? '',
              visibility: (msg.visibility as ChatMessage['visibility']) ?? 'public',
              timestamp: (msg.timestamp as string) ?? new Date().toISOString(),
              sequenceNumber: seqNum,
              status: 'sent',
              metadata: metadata,
              contentType: attachmentUrl ? 'image' : 'text',
              isStreaming: isPlaceholder,
            });

            // Update conversationId if not set
            if (!store.conversationId && convId) {
              store.setConversationId(convId);
            }
          }

        } else if (frame.type === 'message_edited') {
          const p = frame.payload as Record<string, unknown>;
          const messageId = p.message_id as string;
          const newContent = p.new_content as string;
          if (messageId && newContent !== undefined) {
            store.updateMessage(messageId, newContent);
          }

        } else if (frame.type === 'event') {
          const p = frame.payload as Record<string, unknown>;
          const event = p.event as Record<string, unknown> | undefined;
          if (event) {
            const eventId = event.id as string;
            const convId = event.conversation_id as string | undefined;
            const seqNum = (event.sequence_number as number) ?? 0;
            const eventType = event.type as string;

            // Update cursor
            if (convId && seqNum) {
              const newCursor = updateConvCursor(cursorRef.current, convId, 'evt', seqNum);
              cursorRef.current = newCursor;
              saveCursor(newCursor);
              store.updateCursor(newCursor);
            }

            // Send client_ack
            if (eventId && clientRef.current) {
              clientRef.current.send('client_ack' as FeToBeType, { event_id: eventId }).catch(() => {});
            }

            // Handle conversation events
            if (eventType === 'conversation.created' || eventType === 'conversation.activated') {
              const convIdFromEvent = event.conversation_id as string | undefined
                ?? (event.data as Record<string, unknown>)?.conversation_id as string | undefined;
              if (convIdFromEvent) store.setConversationId(convIdFromEvent);
            }
          }

        } else if (frame.type === 'replay_complete') {
          const p = frame.payload as Record<string, unknown>;
          const count = (p.count as number) ?? 0;
          store.setReplaying(false);
          store.setReplayCount(count);

        } else if (frame.type === 'history_snapshot') {
          const p = frame.payload as Record<string, unknown>;
          const msgs = (p.messages as Record<string, unknown>[]) ?? [];
          for (const msg of msgs) {
            const metadata = msg.metadata as Record<string, unknown> | undefined;
            store.addMessageDedup({
              id: msg.id as string,
              source: (msg.source as string) ?? '',
              sourceRole: undefined,
              content: (msg.content as string) ?? '',
              visibility: (msg.visibility as ChatMessage['visibility']) ?? 'public',
              timestamp: (msg.timestamp as string) ?? new Date().toISOString(),
              sequenceNumber: (msg.sequence_number as number) ?? 0,
              status: 'sent',
              metadata,
            });
          }

        } else if (frame.type === 'csat_request') {
          const p = frame.payload as Record<string, unknown>;
          const convId = p.conversation_id as string;
          const prompt = p.prompt as string | undefined;
          const options = (p.options as number[]) ?? [1, 2, 3, 4, 5];
          store.setCsatRequest({ conversationId: convId, prompt, options });

        } else if (frame.type === 'error') {
          const p = frame.payload as Record<string, unknown>;
          if (p.code === '4041_REPLAY_GAP') {
            store.setReplaying(false);
            // Fallback: full history request
            const convId = store.conversationId;
            if (clientRef.current) {
              clientRef.current.send('history_request' as FeToBeType, {
                conversation_id: convId,
                since_sequence: 0,
                limit: 50,
              }).catch(() => {});
            }
          }
        }
      },
    });

    clientRef.current = client;
    client.connect();
    return () => { client.close(); };
  }, [url, clientApp]);

  const send = async (type: string, payload: unknown): Promise<void> => {
    const client = clientRef.current;
    if (!client) throw new Error('ws_not_ready');
    return client.send(type as FeToBeType, payload);
  };

  return {
    status: store.connectionStatus,
    lastFrame: null,
    sessionId: store.sessionId,
    send,
  };
}
