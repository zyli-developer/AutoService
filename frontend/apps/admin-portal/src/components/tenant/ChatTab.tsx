/**
 * T6F.6 · ChatTab — tenant-mode admin conversation with `_local_admin`
 *
 * Per spec §4.4, this is the tenant-side symmetric of master's
 * `ManagementChat`:
 *   - Master admin chats with `_master` via `/api/management/chat`
 *   - Tenant admin chats with `_local_admin` via `/api/admin/chat`  ← THIS
 *
 * M2 scope is stub integration — the backend endpoint `/api/admin/chat`
 * returns a canned reply (see `autoservice/api_routes.py::admin_chat`).
 * Full `_local_admin` / `run_dream` wiring is deferred to T7B.6. The wire
 * contract is stable: POST `{message: string}` → `{reply: string}`, so the
 * real routing swap is a backend-only change.
 *
 * See: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §4.4
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from '@autoservice/i18n';

interface ChatEntry {
  id: string;
  role: 'user' | 'assistant' | 'error';
  text: string;
}

interface ChatTabProps {
  /**
   * Test seam — override fetch() so unit tests can stub the network without
   * touching global state. Defaults to the real `fetch` in production.
   */
  fetcher?: typeof fetch;
  /**
   * Test seam — endpoint override. Defaults to `/api/admin/chat` (spec §4.4).
   */
  endpoint?: string;
}

let nextId = 0;
const makeId = () => {
  nextId += 1;
  return `m${nextId}`;
};

export function ChatTab({
  fetcher = typeof window !== 'undefined' ? window.fetch.bind(window) : fetch,
  endpoint = '/api/admin/chat',
}: ChatTabProps = {}) {
  const { t } = useTranslation();
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<ChatEntry[]>([]);
  const logRef = useRef<HTMLDivElement>(null);

  // Auto-scroll the log to bottom on new messages (best-effort; jsdom no-ops).
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [history.length]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    // Optimistically append the user message, then clear the input.
    setHistory((prev) => [...prev, { id: makeId(), role: 'user', text }]);
    setInput('');
    setLoading(true);

    try {
      const resp = await fetcher(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ message: text }),
      });
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const payload = (await resp.json()) as { reply?: string };
      const reply =
        typeof payload?.reply === 'string' && payload.reply.length > 0
          ? payload.reply
          : '(no reply)';
      setHistory((prev) => [...prev, { id: makeId(), role: 'assistant', text: reply }]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setHistory((prev) => [
        ...prev,
        { id: makeId(), role: 'error', text: `(error: ${msg})` },
      ]);
    } finally {
      setLoading(false);
    }
  }, [input, loading, fetcher, endpoint]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  const disabled = loading || input.trim().length === 0;

  return (
    <div
      data-testid="tenant-chat-tab"
      style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
    >
      <div
        className="im-main-header"
        style={{ flexShrink: 0, padding: '12px 20px', borderBottom: '1px solid var(--color-border, #eee)' }}
      >
        <div className="im-main-title" style={{ fontWeight: 600 }}>
          {t('admin.tenant.chat.title')}
        </div>
        <div className="im-main-subtitle" style={{ fontSize: 12, color: 'var(--color-text-secondary, #666)' }}>
          {/* Spec §4.4 — tenant admin talks to `_local_admin`. The agent
              identifier is a system handle, not a localized label. */}
          _local_admin
        </div>
      </div>

      <div
        ref={logRef}
        role="log"
        aria-live="polite"
        aria-label="chat history"
        data-testid="chat-history"
        style={{ flex: 1, overflowY: 'auto', padding: '12px 20px' }}
      >
        {history.length === 0 ? (
          <div
            data-testid="chat-empty-state"
            style={{ color: 'var(--color-text-secondary, #888)', fontSize: 13 }}
          >
            {t('admin.tenant.chat.placeholder')}
          </div>
        ) : (
          history.map((entry) => (
            <div
              key={entry.id}
              data-testid={`chat-msg-${entry.role}`}
              className={`chat-bubble chat-bubble-${entry.role}`}
              style={{
                marginBottom: 8,
                padding: '6px 10px',
                borderRadius: 8,
                background:
                  entry.role === 'user'
                    ? 'var(--color-bg-user, #e7f0ff)'
                    : entry.role === 'error'
                      ? 'var(--color-bg-error, #fde8e8)'
                      : 'var(--color-bg-bot, #f3f4f6)',
                whiteSpace: 'pre-wrap',
              }}
            >
              {entry.text}
            </div>
          ))
        )}
        {loading && (
          <div
            data-testid="chat-loading"
            style={{ color: 'var(--color-text-secondary, #888)', fontSize: 12, fontStyle: 'italic' }}
          >
            …
          </div>
        )}
      </div>

      <form
        role="form"
        aria-label="send chat message"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
        style={{
          flexShrink: 0,
          display: 'flex',
          gap: 8,
          padding: '10px 20px',
          borderTop: '1px solid var(--color-border, #eee)',
        }}
      >
        <input
          type="text"
          data-testid="chat-input"
          aria-label="chat message"
          placeholder={t('admin.tenant.chat.placeholder')}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={loading}
          style={{ flex: 1, padding: '6px 10px', border: '1px solid var(--color-border, #ddd)', borderRadius: 6 }}
        />
        <button
          type="submit"
          data-testid="chat-send"
          aria-label="send"
          disabled={disabled}
          style={{
            padding: '6px 14px',
            borderRadius: 6,
            border: '1px solid var(--color-border, #ddd)',
            background: disabled ? 'var(--color-bg-disabled, #f3f4f6)' : 'var(--color-bg-primary, #3b82f6)',
            color: disabled ? 'var(--color-text-disabled, #999)' : '#fff',
            cursor: disabled ? 'not-allowed' : 'pointer',
          }}
        >
          Send
        </button>
      </form>
    </div>
  );
}
