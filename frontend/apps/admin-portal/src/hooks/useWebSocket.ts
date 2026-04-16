import { useEffect, useRef, useState } from 'react';
import { WSClient, type Envelope, type ServerHelloPayload } from '@autoservice/ws-client';

type Status = 'idle' | 'connecting' | 'open' | 'closed';

export function useWebSocket(
  url: string,
  clientApp: string,
): { status: Status; lastFrame: Envelope | null; sessionId: string | null } {
  const [status, setStatus] = useState<Status>('idle');
  const [lastFrame, setLastFrame] = useState<Envelope | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const clientRef = useRef<WSClient | null>(null);

  useEffect(() => {
    setStatus('connecting');
    const client = new WSClient({
      url,
      clientApp,
      onOpen: (hello: ServerHelloPayload) => {
        setSessionId(hello.session_id);
        setStatus('open');
      },
      onClose: () => setStatus('closed'),
      onFrame: (frame) => setLastFrame(frame),
    });
    clientRef.current = client;
    client.connect();
    return () => client.close();
  }, [url, clientApp]);

  return { status, lastFrame, sessionId };
}
