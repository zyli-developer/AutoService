import { useEffect, useRef } from 'react';
import { WSClient, type Envelope, type ServerHelloPayload } from '@autoservice/ws-client';
import { useOperatorStore } from '../store/operatorStore';

// 允许测试时注入 fake client
type WSClientConstructor = new (opts: ConstructorParameters<typeof WSClient>[0]) => WSClient;
let WSClientImpl: WSClientConstructor = WSClient;
export function _setWSClientImpl(impl: WSClientConstructor) {
  WSClientImpl = impl;
}

export function useOperatorWS(url: string): { send: (frame: Envelope) => void } {
  const isLoggedIn = useOperatorStore((s) => s.isLoggedIn);
  const operatorId = useOperatorStore((s) => s.operatorId);
  const squads = useOperatorStore((s) => s.squads);
  const setWsStatus = useOperatorStore((s) => s.setWsStatus);
  const setSessionId = useOperatorStore((s) => s.setSessionId);
  const addSubscription = useOperatorStore((s) => s.addSubscription);

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
        // S8 event frames → T2B.2 will handle
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
