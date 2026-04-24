import { useState, useRef, useMemo, useEffect } from 'react';
import { useTenantId } from '@autoservice/shared';
import { useTranslation } from '@autoservice/i18n';
import { useWebSocket } from './hooks/useWebSocket';
import { useChatStore } from './store/chatStore';
import { MerchantSite } from './components/MerchantSite';
import { ChatFAB } from './components/ChatFAB';
import { ChatModal } from './components/ChatModal';
import { useVoiceCall } from './voice/useVoiceCall';

// Unique customer ID per browser tab (persisted in sessionStorage)
function getCustomerId(): string {
  let id = sessionStorage.getItem('customer_id');
  if (!id) {
    id = `cust_${crypto.randomUUID().slice(0, 8)}`;
    sessionStorage.setItem('customer_id', id);
  }
  return id;
}

/**
 * Resolve the WebSocket base URL.
 *
 * Priority:
 *   1. `VITE_WS_BASE` env var (full URL, e.g. `wss://chat.example.com`)
 *   2. Same-origin derived from `window.location` (secure protocol auto-upgrade).
 *
 * We deliberately avoid hardcoding `localhost:8000` — the dev server proxy
 * (or reverse proxy in prod) forwards `/ws/customer` to the gateway.
 */
function resolveWsBase(): string {
  const envBase = (import.meta as unknown as { env?: Record<string, string | undefined> }).env?.VITE_WS_BASE;
  if (envBase) return envBase.replace(/\/$/, '');
  if (typeof window !== 'undefined' && window.location) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}`;
  }
  // Last-resort fallback for non-DOM contexts (tests without jsdom). Tenant
  // presence is already gated by useTenantId(), so this is only ever reached
  // if a caller renders <App/> outside jsdom — we return an obviously-fake
  // origin so any accidental connect fails loudly.
  return 'ws://invalid.local';
}

/** Resolve voice gateway WS URL.
 *
 * Priority:
 *   1. `VITE_VOICE_GATEWAY_URL` env var (e.g. `http://localhost:8089`)
 *   2. Same-origin fallback (`wss://` on HTTPS, `ws://` on HTTP)
 *
 * Returns the URL with the given path appended (e.g. `/asr` or `/tts`).
 */
function resolveVoiceWsUrl(path: '/asr' | '/tts'): string {
  const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env;
  const base = env?.VITE_VOICE_GATEWAY_URL;
  if (base) {
    // Convert http(s):// to ws(s):// if needed
    const wsBase = base.replace(/^https:\/\//, 'wss://').replace(/^http:\/\//, 'ws://');
    return `${wsBase.replace(/\/$/, '')}${path}`;
  }
  if (typeof window !== 'undefined' && window.location) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}${path}`;
  }
  return `ws://invalid.local${path}`;
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

/**
 * Chat application. Requires a tenant in the URL:
 *   - `/tenant/<tenant>/chat` (canonical)
 *   - `/chat?tenant=<tenant>` (fork-side fallback, see spec §5.4)
 *
 * When no tenant is resolvable, renders a friendly "select tenant" message
 * instead of crashing or silently connecting to the wrong backend.
 */
export function App() {
  const tenantId = useTenantId();

  if (!tenantId) {
    return <TenantFallback />;
  }

  return <ChatApp tenantId={tenantId} />;
}

function TenantFallback() {
  return (
    <div
      className="web-canvas"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        padding: '2rem',
        textAlign: 'center',
      }}
      data-testid="tenant-fallback"
    >
      <div style={{ maxWidth: 480 }}>
        <h1 style={{ fontSize: '1.25rem', marginBottom: '0.75rem' }}>
          Select a tenant to start chatting
        </h1>
        <p style={{ opacity: 0.75, lineHeight: 1.5 }}>
          Open this page via <code>/tenant/&lt;your-tenant&gt;/chat</code> or append{' '}
          <code>?tenant=&lt;your-tenant&gt;</code> to the URL.
        </p>
      </div>
    </div>
  );
}

function ChatApp({ tenantId }: { tenantId: string }) {
  const wsUrl = useMemo(
    () => `${resolveWsBase()}/ws/customer?tenant=${encodeURIComponent(tenantId)}`,
    [tenantId],
  );
  const { send } = useWebSocket(wsUrl, 'customer-chat');
  const { messages, connectionStatus, isReplaying, replayCount } = useChatStore();
  const { t } = useTranslation();
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

  // ---------------- Voice wiring ----------------
  const asrUrl = useMemo(() => resolveVoiceWsUrl('/asr'), []);
  const ttsUrl = useMemo(() => resolveVoiceWsUrl('/tts'), []);
  const comfortPool = useMemo(
    () => [
      t('voice.comfort.1'),
      t('voice.comfort.2'),
      t('voice.comfort.3'),
      t('voice.comfort.4'),
    ],
    [t],
  );

  // Shared id between the optimistic-bubble insert (onUserMessage) and the
  // WS send (onSendTextToChat) so message_confirm can dedupe correctly.
  const pendingAsrClientMsgIdRef = useRef<string | null>(null);

  const voice = useVoiceCall({
    asrUrl,
    ttsUrl,
    comfortPool,
    onUserMessage: (text: string) => {
      const clientMsgId = crypto.randomUUID();
      pendingAsrClientMsgIdRef.current = clientMsgId;
      useChatStore.getState().addMessage({
        id: clientMsgId,
        clientMsgId,
        source: 'customer',
        sourceRole: 'customer',
        content: text,
        visibility: 'public',
        timestamp: new Date().toISOString(),
        sequenceNumber: 0,
        status: 'sending',
      });
    },
    onSendTextToChat: (text: string) => {
      const clientMsgId = pendingAsrClientMsgIdRef.current ?? crypto.randomUUID();
      pendingAsrClientMsgIdRef.current = null;
      const convId = useChatStore.getState().conversationId;
      void send('customer_message', {
        content: text,
        source: customerId,
        client_msg_id: clientMsgId,
        ...(convId ? { conversation_id: convId } : {}),
      });
    },
  });

  // When a new agent/bot message lands in the store AND voice is active,
  // forward the content to the voice controller so it can TTS the reply.
  const lastBotSignature = useRef<string | null>(null);
  useEffect(() => {
    if (voice.state === 'idle' || voice.state === 'error') return;
    // Find the most recent agent/operator message in the message list
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.sourceRole === 'agent' || m.sourceRole === 'operator') {
        const signature = `${m.id}:${m.content}`;
        if (signature !== lastBotSignature.current && m.content && !m.isStreaming) {
          lastBotSignature.current = signature;
          voice.onCcReply(m.content);
        }
        break; // only care about the latest bot message
      }
    }
  }, [messages, voice]);

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

  // Mirror modal open/closed to body.sheet-open so CSS can dim merchant only
  // when the sheet is actually visible (and show FAB again when it's not)
  useEffect(() => {
    document.body.classList.toggle('sheet-open', isOpen);
    return () => document.body.classList.remove('sheet-open');
  }, [isOpen]);

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
          disabled={connectionStatus !== 'open' || voice.state !== 'idle'}
          connectionStatus={connectionStatus}
          isReplaying={isReplaying}
          replayCount={replayCount}
          sheet={sheet}
          onToggleSheet={toggleSheet}
          voiceState={voice.state}
          voiceErrorReason={voice.errorReason}
          onVoiceStart={voice.start}
          onVoiceHangup={voice.hangup}
          onVoiceRetry={voice.retry}
        />
      ) : null}
      <ChatFAB
        onClick={() => setIsOpen(true)}
        highlight={!isOpen}
      />
    </div>
  );
}
