import { useState, useRef, useEffect } from 'react';
import { postJSON } from '../api';

interface ChatMsg {
  id: string;
  role: 'user' | 'dream_engine' | 'system';
  content: string;
  ts: string;
}

const WELCOME: ChatMsg = {
  id: 'welcome',
  role: 'dream_engine',
  content: '早上好！我是 Dream Engine，负责夜间学习和优化。\n\n可用命令:\n  /rules — 查看/配置规则\n  /status — 系统状态概览\n  /approve #N — 批准提案\n  /reject #N — 拒绝提案\n  /rollback — 回滚灰度发布',
  ts: new Date().toISOString(),
};

export function ManagementChat() {
  const [messages, setMessages] = useState<ChatMsg[]>([WELCOME]);
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
        { id: crypto.randomUUID(), role: 'system', content: '发送失败，请重试', ts: new Date().toISOString() },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div data-testid="tab-notifications" style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 140px)' }}>
      {/* Header */}
      <div className="im-main-header" style={{ flexShrink: 0 }}>
        <div className="im-main-title">管理群</div>
        <div className="im-main-subtitle">Dream Engine · 对话式管理</div>
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
                    <span className="im-msg-author">老陈</span>
                    <span className="im-msg-time">{new Date(msg.ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
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
                    <span className="im-msg-author">Dream Engine</span>
                    <span className="im-msg-bot-tag">DREAM</span>
                    <span className="im-msg-time">{new Date(msg.ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                  <div className="im-msg-text" style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
                </div>
              </div>
            );
          }

          return (
            <div key={msg.id} className="im-system">{msg.content}</div>
          );
        })}
        {loading && (
          <div className="im-system">Dream Engine 正在处理...</div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div className="cs-notification-input" style={{ flexShrink: 0 }}>
        <input
          data-testid="notification-input"
          placeholder="/rules, /status, /approve, /reject, /rollback"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          disabled={loading}
        />
        <button data-testid="notification-send" onClick={handleSend} disabled={loading || !input.trim()}>
          发送
        </button>
      </div>
    </div>
  );
}
