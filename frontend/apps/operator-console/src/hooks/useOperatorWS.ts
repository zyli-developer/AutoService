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
      const to = event.data.to as Conversation['mode'];
      updateConversation(convId, { mode: to, lastActivityTs: ts });
      break;
    }
    case 'conversation.closed':
    case 'conversation.resolved':
      updateConversation(convId, { state: 'closed', lastActivityTs: ts });
      break;
    case 'message.sent': {
      const sender = event.data.sender_role === 'customer' ? 'customer' as const : 'agent' as const;
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

  const clientRef = useRef<WSClient | null>(null);

  useEffect(() => {
    if (!isLoggedIn || !operatorId) return;

    setWsStatus('connecting');

    const client = new WSClientImpl({
      url,
      clientApp: 'operator-console',
      heartbeatMs: 20_000,
      onOpen: (hello: ServerHelloPayload) => {
        setSessionId(hello.session_id);
        setWsStatus('open');

        // F6: subscribe for each squad
        const currentSquads = useOperatorStore.getState().squads;
        currentSquads.forEach((squadId) => {
          client.send({
            v: 1,
            type: 'subscribe',
            id: crypto.randomUUID(),
            ts: new Date().toISOString(),
            payload: { scope: { squad_id: squadId } },
          } as Envelope);
        });
      },
      onClose: () => {
        setWsStatus('closed');
      },
      onFrame: (frame: Envelope) => {
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
            // Auto-create conversation if not exists
            const state = useOperatorStore.getState();
            if (!state.conversations[convId]) {
              addConversation({
                id: convId,
                customerId: role === 'customer' ? (srcDisplay?.id as string ?? 'customer') : 'customer',
                squadId: state.activeSquadId ?? 'default',
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

        if (frame.type === 'event') {
          handleEventFrame(frame, addConversation, updateConversation);

          const evtPayload = frame.payload as EventPayload;
          const evt = evtPayload?.event;
          if (evt?.type === 'message.sent' && evt.conversation_id) {
            const state = useOperatorStore.getState();
            if (state.activeCopilotConvId === evt.conversation_id) {
              const sender = evt.data.sender_role === 'customer' ? 'customer' as const
                : evt.data.sender_role === 'operator' ? 'operator' as const
                : 'agent' as const;
              addCopilotMessage(evt.conversation_id, {
                id: evt.id,
                text: (evt.data.text ?? evt.data.content ?? '') as string,
                sender,
                ts: evt.timestamp || new Date().toISOString(),
              });
            }
          }
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
    clientRef.current?.send(frame);
  };

  return { send };
}
