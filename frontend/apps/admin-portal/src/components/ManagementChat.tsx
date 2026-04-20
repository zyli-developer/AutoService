import { useState, useRef, useEffect, useMemo } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { postJSON } from '../api';
import type { ChatBlock } from './chat/InlineWidget';
import { InlineWidget } from './chat/InlineWidget';

interface ChatMsg {
  id: string;
  role: 'user' | 'dream_engine' | 'system';
  content: string;
  blocks?: ChatBlock[];
  ts: string;
}

export function ManagementChat() {
  const { t, i18n } = useTranslation();
  const welcome = useMemo<ChatMsg>(
    () => ({
      id: 'welcome',
      role: 'dream_engine',
      content: t('admin.dream.welcome'),
      ts: new Date().toISOString(),
    }),
    // Rebuild welcome when the active language changes so a live user who
    // switches mid-session still sees a consistent greeting.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [i18n.language],
  );
  const [messages, setMessages] = useState<ChatMsg[]>([welcome]);
  // Keep the first message in sync with language switch (re-seed if only welcome present).
  useEffect(() => {
    setMessages((prev) => (prev.length <= 1 ? [welcome] : prev));
  }, [welcome]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');

    const userMsg: ChatMsg = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      ts: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const resp = await postJSON<{ role: string; content: string }>(
        `/api/management/chat?message=${encodeURIComponent(text)}`,
      );
      const botMsg: ChatMsg = {
        id: crypto.randomUUID(),
        role: (resp.role as ChatMsg['role']) || 'dream_engine',
        content: resp.content,
        ts: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, botMsg]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: 'system', content: t('message.status.failed'), ts: new Date().toISOString() },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div data-testid="tab-notifications" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <div className="im-main-header" style={{ flexShrink: 0 }}>
        <div className="im-main-title">{t('admin.nav.management_chat')}</div>
        <div className="im-main-subtitle">{t('admin.dream.title')}</div>
      </div>

      {/* Messages */}
      <div className="im-feed" style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
        {messages.map((msg) => {
          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="im-card" style={{ marginBottom: 10 }}>
                <div className="im-avatar human" style={{ background: 'var(--m600)' }}>陈</div>
                <div className="im-msg-body">
                  <div className="im-msg-meta">
                    <span className="im-msg-author">{t('admin.dream.user_label')}</span>
                    <span className="im-msg-time">{new Date(msg.ts).toLocaleTimeString(i18n.language === 'zh-CN' ? 'zh-CN' : 'en-US', { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                  <div className="im-msg-text">
                    {msg.content.startsWith('/') ? (
                      <span className="im-cmd">{msg.content}</span>
                    ) : (
                      msg.content
                    )}
                  </div>
                </div>
              </div>
            );
          }

          if (msg.role === 'dream_engine') {
            return (
              <div key={msg.id} className="im-card" style={{ marginBottom: 10 }}>
                <div className="im-avatar a1" style={{ background: 'var(--u800)' }}>梦</div>
                <div className="im-msg-body">
                  <div className="im-msg-meta">
                    <span className="im-msg-author">{t('admin.dream.name')}</span>
                    <span className="im-msg-bot-tag">DREAM</span>
                    <span className="im-msg-time">{new Date(msg.ts).toLocaleTimeString(i18n.language === 'zh-CN' ? 'zh-CN' : 'en-US', { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                  {msg.content && (
                    <div className="im-msg-text" style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
                  )}
                  {msg.blocks?.map((b, i) => (
                    <InlineWidget key={i} block={b} />
                  ))}
                </div>
              </div>
            );
          }

          return (
            <div key={msg.id} className="im-system">{msg.content}</div>
          );
        })}
        {loading && (
          <div className="im-system">{t('admin.dream.processing')}</div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div className="cs-notification-input" style={{ flexShrink: 0 }}>
        <input
          data-testid="notification-input"
          placeholder={t('admin.dream.input.placeholder')}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          disabled={loading}
        />
        <button data-testid="notification-send" onClick={handleSend} disabled={loading || !input.trim()}>
          {t('common.send')}
        </button>
      </div>
    </div>
  );
}
