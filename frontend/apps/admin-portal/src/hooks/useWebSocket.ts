import { useEffect, useRef, useState } from 'react';
import { WSClient, type Envelope } from '@autoservice/ws-client';

type Status = 'idle' | 'connecting' | 'open' | 'closed';

export function useWebSocket(url: string): { status: Status; lastFrame: Envelope | null } {
  const [status, setStatus] = useState<Status>('idle');
  const [lastFrame, setLastFrame] = useState<Envelope | null>(null);
  const clientRef = useRef<WSClient | null>(null);

  useEffect(() => {
    setStatus('connecting');
    const client = new WSClient({
      url,
      onOpen: () => setStatus('open'),
      onClose: () => setStatus('closed'),
      onFrame: (frame) => setLastFrame(frame),
    });
    clientRef.current = client;
    client.connect();
    return () => client.close();
  }, [url]);

  return { status, lastFrame };
}
