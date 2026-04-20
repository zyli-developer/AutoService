import { useEffect, useRef } from 'react';
import { WSClient, type Envelope, type ServerHelloPayload } from '@autoservice/ws-client';
import { useOperatorStore, type Conversation } from '../store/operatorStore';

// 允许测试时注入 fake client
type WSClientConstructor = new (opts: ConstructorParameters<typeof WSClient>[0]) => WSClient;
let WSClientImpl: WSClientConstructor = WSClient;
export function _setWSClientImpl(impl: WSClientConstructor) {
  WSClientImpl = impl;
}

interface EventPayload {
  event: {
    id: string;
    type: string;
    conversation_id: string;
    data: Record<string, any>;
    timestamp: string;
  };
}

export function handleEventFrame(
  frame: Envelope,
  addConversation: (conv: Conversation) => void,
  updateConversation: (id: string, patch: Partial<Conversation>) => void,
) {
  const { event } = frame.payload as EventPayload;
  if (!event?.conversation_id) return;
  const convId = event.conversation_id;
  const ts = event.timestamp || new Date().toISOString();

  switch (event.type) {
    case 'conversation.created': {
      const d = event.data;
      addConversation({
        id: convId,
        squadId: d.squad_id ?? '',
        customerId: d.customer_id ?? '',
        mode: 'auto',
        state: 'created',
        lastMessage: '',
        lastMessageSender: '',
        lastActivityTs: ts,
      });
      break;
    }
    case 'mode.changed': {
      const to = (event.data.to as Conversation['mode'] | undefined)
        ?? (event.data.new_mode as Conversation['mode']);
      const takeoverId = event.data.takeover_operator_id as string | null | undefined;
      const patch: Partial<Conversation> = {
        mode: to,
        takeoverOperatorId: takeoverId ?? null,
        lastActivityTs: ts,
      };
      if (to !== 'takeover') {
        // Clear armed timer fields when leaving takeover mode
        (patch as any).takeoverArmedAt = undefined;
        (patch as any).takeoverIdleMs = undefined;
        (patch as any).takeoverWarningMs = undefined;
      }
      updateConversation(convId, patch);
      break;
    }
    case 'conversation.closed':
    case 'conversation.resolved':
      updateConversation(convId, { state: 'closed', lastActivityTs: ts });
      break;
    case 'message.sent': {
      const _src = (event.data.source as string) ?? '';
      const sender = (_src.startsWith('cust') || _src === 'customer') ? 'customer' as const : 'agent' as const;
      const text = (event.data.text ?? event.data.content ?? '') as string;
      updateConversation(convId, {
        lastMessage: text,
        lastMessageSender: sender,
        lastActivityTs: ts,
        state: 'active',
      });
      break;
    }
  }
}

export function useOperatorWS(url: string): { send: (frame: Envelope) => void } {
  const isLoggedIn = useOperatorStore((s) => s.isLoggedIn);
  const operatorId = useOperatorStore((s) => s.operatorId);
  const squads = useOperatorStore((s) => s.squads);
  const setWsStatus = useOperatorStore((s) => s.setWsStatus);
  const setSessionId = useOperatorStore((s) => s.setSessionId);
  const addSubscription = useOperatorStore((s) => s.addSubscription);
  const addConversation = useOperatorStore((s) => s.addConversation);
  const updateConversation = useOperatorStore((s) => s.updateConversation);
  const addCopilotMessage = useOperatorStore((s) => s.addCopilotMessage);
  const updateCopilotMessage = useOperatorStore((s) => s.updateCopilotMessage);

  const clientRef = useRef<WSClient | null>(null);

  useEffect(() => {
    if (!isLoggedIn || !operatorId) return;

    setWsStatus('connecting');

    const client = new WSClientImpl({
      url,
      clientApp: 'operator-console',
      operatorId: operatorId || undefined,
      heartbeatMs: 20_000,
      onOpen: (hello: ServerHelloPayload) => {
        setSessionId(hello.session_id);
        setWsStatus('open');

        // F6: subscribe for each squad
        const currentSquads = useOperatorStore.getState().squads;
        currentSquads.forEach((squadId) => {
          client.send('subscribe' as any, { scope: { squad_id: squadId } }).catch(() => {});
        });

        // Seed active conversation list so the operator sees existing
        // conversations on (re)login without waiting for live events.
        // Uses Vite proxy (/api -> localhost:8000) so the fetch is same-origin.
        currentSquads.forEach((squadId) => {
          const url = `/api/conversations/active?squad_id=${encodeURIComponent(squadId)}`;
          fetch(url)
            .then((r) => (r.ok ? r.json() : { conversations: [] }))
            .then((data: { conversations?: Array<Record<string, unknown>> }) => {
              const items = data.conversations ?? [];
              const store = useOperatorStore.getState();
              for (const c of items) {
                const id = c.id as string;
                if (!id || store.conversations[id]) continue;
                store.addSquad(String(c.squad_id || squadId));
                store.addConversation({
                  id,
                  squadId: String(c.squad_id || squadId),
                  customerId: String(c.customer_id || 'customer'),
                  mode: (c.mode as Conversation['mode']) ?? 'auto',
                  state: (c.state as Conversation['state']) ?? 'active',
                  lastMessage: String(c.last_message || ''),
                  lastMessageSender: (c.last_sender as Conversation['lastMessageSender']) ?? '',
                  lastActivityTs: String(c.last_activity_ts || new Date().toISOString()),
                  takeoverOperatorId: (c.takeover_operator_id as string | null) ?? null,
                });
              }
            })
            .catch(() => {
              /* ignore — live events will backfill */
            });
        });
      },
      onClose: () => {
        setWsStatus('closed');
      },
      onFrame: (frame: Envelope) => {
        // Handle history_snapshot — load messages into copilot
        if (frame.type === 'history_snapshot') {
          const p = frame.payload as Record<string, unknown>;
          const convId = p.conversation_id as string;
          const msgs = (p.messages as Record<string, unknown>[]) ?? [];
          if (convId && msgs.length > 0) {
            for (const msg of msgs) {
              const src = (msg.source as string) ?? '';
              const sender = (src.includes('customer') || src.startsWith('cust')) ? 'customer' as const
                : src.includes('operator') ? 'operator' as const
                : 'agent' as const;
              addCopilotMessage(convId, {
                id: (msg.id as string) ?? crypto.randomUUID(),
                text: (msg.content as string) ?? '',
                sender,
                ts: (msg.timestamp as string) ?? new Date().toISOString(),
              });
            }
          }
        }

        if (frame.type === 'subscription_added') {
          const p = frame.payload as { subscription_id: string; scope: { squad_id?: string } };
          if (p.scope?.squad_id) {
            addSubscription(p.scope.squad_id, p.subscription_id);
          }
        }

        // Handle broadcast message frames (customer/agent messages from other connections)
        if (frame.type === 'message') {
          const p = frame.payload as Record<string, unknown>;
          const convId = p.conversation_id as string;
          const msg = p.message as Record<string, unknown>;
          const srcDisplay = p.source_display as Record<string, unknown> | undefined;
          const role = (srcDisplay?.role as string) ?? 'agent';
          const content = (msg?.content as string) ?? '';
          const ts = (msg?.timestamp as string) ?? new Date().toISOString();

          if (convId) {
            const squadId = (p.squad_id as string) ?? 'web-support';
            // Auto-create conversation if not exists
            const state = useOperatorStore.getState();
            // Auto-add squad to sidebar if not present
            if (!state.squads.includes(squadId)) {
              useOperatorStore.getState().addSquad(squadId);
            }
            if (!state.conversations[convId]) {
              addConversation({
                id: convId,
                customerId: role === 'customer' ? (srcDisplay?.id as string ?? 'customer') : 'customer',
                squadId,
                mode: 'auto',
                lastMessage: content,
                lastActivityTs: ts,
                unreadCount: 1,
              });
            } else {
              updateConversation(convId, {
                lastMessage: content,
                lastActivityTs: ts,
                unreadCount: (state.conversations[convId].unreadCount ?? 0) + 1,
              });
            }

            // Add to copilot if this conversation is open
            if (state.activeCopilotConvId === convId) {
              const sender = role === 'customer' ? 'customer' as const
                : role === 'operator' ? 'operator' as const
                : 'agent' as const;
              addCopilotMessage(convId, {
                id: (msg?.id as string) ?? crypto.randomUUID(),
                text: content,
                sender,
                ts,
              });
            }
          }
        }

        if (frame.type === 'message_edited') {
          const p = frame.payload as Record<string, unknown>;
          const convId = p.conversation_id as string | undefined;
          const msg = p.message as Record<string, unknown> | undefined;
          const messageId = (msg?.id as string) ?? (p.message_id as string);
          const newContent = (msg?.content as string) ?? (p.new_content as string);
          if (convId && messageId && newContent !== undefined) {
            updateCopilotMessage(convId, messageId, { text: newContent });
          }
        }

        if (frame.type === 'takeover_timer_armed') {
          const p = frame.payload as {
            conversation_id: string;
            armed_at: string;
            idle_timeout_ms: number;
            warning_ms: number;
          };
          useOperatorStore.getState().setTakeoverArmed(p.conversation_id, {
            armedAt: p.armed_at,
            idleMs: p.idle_timeout_ms,
            warningMs: p.warning_ms,
          });
          return;
        }

        if (frame.type === 'takeover_warning') {
          const p = frame.payload as {
            conversation_id: string; remaining_ms: number; reason: 'idle';
          };
          useOperatorStore.getState().setTakeoverWarning(p.conversation_id, {
            remainingMs: p.remaining_ms,
            reason: p.reason,
            warningFrameId: frame.id,
            armedAt: new Date().toISOString(),
          });
          return;
        }

        if (frame.type === 'takeover_warning_cancelled') {
          const p = frame.payload as { conversation_id: string };
          useOperatorStore.getState().clearTakeoverWarning(p.conversation_id);
          return;
        }

        if (frame.type === 'event') {
          // event frames update conversation metadata only (mode, state, etc.)
          // copilot messages are handled exclusively via broadcast `message` frames
          handleEventFrame(frame, addConversation, updateConversation);
        }
      },
    });

    clientRef.current = client;
    client.connect();

    return () => {
      client.close();
      clientRef.current = null;
    };
  }, [isLoggedIn, operatorId, url]);

  const send = (frame: Envelope) => {
    if (!clientRef.current) {
      console.warn('[OperatorWS] send: no client');
      return;
    }
    console.log('[OperatorWS] send:', frame.type, frame.payload);
    clientRef.current.send(frame.type as any, frame.payload).catch((err) => {
      console.error('[OperatorWS] send error:', err);
    });
  };

  const fetchHistory = (conversationId: string) => {
    if (!clientRef.current) return;
    clientRef.current.send(
      'history_request' as any,
      { conversation_id: conversationId, limit: 50 },
    ).catch(() => {});
  };

  return { send, fetchHistory };
}
