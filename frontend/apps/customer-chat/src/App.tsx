import { useState, useRef, useMemo, useEffect } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useChatStore } from './store/chatStore';
import { MerchantSite } from './components/MerchantSite';
import { ChatFAB } from './components/ChatFAB';
import { ChatModal } from './components/ChatModal';

// Unique customer ID per browser tab (persisted in sessionStorage)
function getCustomerId(): string {
  let id = sessionStorage.getItem('customer_id');
  if (!id) {
    id = `cust_${crypto.randomUUID().slice(0, 8)}`;
    sessionStorage.setItem('customer_id', id);
  }
  return id;
}

type SheetState = 'peek' | 'full';

function getInitialSheet(): SheetState {
  try {
    const s = localStorage.getItem('as-cust-sheet');
    if (s === 'full' || s === 'peek') return s;
  } catch {
    // localStorage may be unavailable
  }
  return 'peek';
}

export function App() {
  const wsUrl = `ws://${window.location.hostname}:8000/ws/customer`;
  const { send } = useWebSocket(wsUrl, 'customer-chat');
  const { messages, connectionStatus, isReplaying, replayCount } = useChatStore();
  const [isOpen, setIsOpen] = useState(() => {
    // Auto-open on mobile viewports so the bottom sheet is always visible
    if (typeof window !== 'undefined' && window.matchMedia) {
      return window.matchMedia('(max-width: 640px)').matches;
    }
    return false;
  });
  const [sheet, setSheet] = useState<SheetState>(getInitialSheet);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const customerId = useMemo(getCustomerId, []);

  // Auto-open/close when viewport crosses the mobile breakpoint
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mql = window.matchMedia('(max-width: 640px)');
    const onChange = (e: MediaQueryListEvent) => {
      if (e.matches) setIsOpen(true);
    };
    mql.addEventListener?.('change', onChange);
    return () => mql.removeEventListener?.('change', onChange);
  }, []);

  // Persist sheet state + mirror to body class so CSS can target before modal mounts
  useEffect(() => {
    try { localStorage.setItem('as-cust-sheet', sheet); } catch { /* noop */ }
    const b = document.body;
    b.classList.remove('sheet-peek', 'sheet-full');
    b.classList.add('sheet-' + sheet);
  }, [sheet]);

  const toggleSheet = () => setSheet((s) => (s === 'peek' ? 'full' : 'peek'));

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
        source: customerId,
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

  const handleCsatSubmit = async (score: number) => {
    const convId = useChatStore.getState().conversationId;
    if (!convId) return;
    try {
      await send('csat_response', {
        conversation_id: convId,
        score,
      });
      useChatStore.getState().setCsatSubmitted();
    } catch {
      // Silently fail — user already sees the score they selected
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
          onCsatSubmit={handleCsatSubmit}
          disabled={connectionStatus !== 'open'}
          connectionStatus={connectionStatus}
          isReplaying={isReplaying}
          replayCount={replayCount}
          sheet={sheet}
          onToggleSheet={toggleSheet}
        />
      ) : null}
      <ChatFAB onClick={() => setIsOpen(true)} highlight={!isOpen} />
    </div>
  );
}
