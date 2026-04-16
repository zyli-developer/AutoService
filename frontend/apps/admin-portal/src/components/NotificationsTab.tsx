import { useState } from 'react';
import { useAdminStore, type Notification } from '../store/adminStore';

const TYPE_STYLES: Record<Notification['type'], { bg: string; color: string; label: string }> = {
  alert: { bg: 'var(--p)', color: '#fff', label: '\u544A\u8B66' },
  info: { bg: 'var(--m300)', color: 'var(--m800)', label: '\u4FE1\u606F' },
  command: { bg: 'var(--m800)', color: '#fff', label: '\u547D\u4EE4' },
};

function makeId(): string {
  return `notif-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const commandHandlers: Record<string, () => Pick<Notification, 'title' | 'description' | 'type'>> = {
  '/rules': () => ({ type: 'command', title: '\u89C4\u5219\u914D\u7F6E\u5DF2\u66F4\u65B0', description: '\u5DF2\u6267\u884C /rules \u547D\u4EE4' }),
  '/status': () => ({ type: 'command', title: '\u7CFB\u7EDF\u72B6\u6001\uFF1A\u6B63\u5E38', description: '\u5DF2\u6267\u884C /status \u547D\u4EE4' }),
  '/review': () => ({ type: 'command', title: '\u5BA1\u67E5\u5DF2\u542F\u52A8', description: '\u5DF2\u6267\u884C /review \u547D\u4EE4' }),
};

export function NotificationsTab() {
  const [input, setInput] = useState('');
  const notifications = useAdminStore((s) => s.notifications);
  const addNotification = useAdminStore((s) => s.addNotification);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed) return;

    const handler = commandHandlers[trimmed];
    if (handler) {
      const result = handler();
      addNotification({
        id: makeId(),
        ts: new Date().toISOString(),
        ...result,
      });
    } else {
      addNotification({
        id: makeId(),
        type: 'info',
        title: trimmed,
        description: '\u7528\u6237\u8F93\u5165',
        ts: new Date().toISOString(),
      });
    }
    setInput('');
  };

  return (
    <div data-testid="tab-notifications">
      <div data-testid="notification-list">
        {notifications.length === 0 ? (
          <div className="im-empty">{'\u6682\u65E0\u901A\u77E5'}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {notifications.map((item) => {
              const style = TYPE_STYLES[item.type];
              return (
                <div
                  key={item.id}
                  className="im-card"
                  data-testid={`notification-item-${item.id}`}
                >
                  <div
                    className="im-avatar a1"
                    style={{ background: style.bg, color: style.color, fontSize: 10 }}
                  >
                    {style.label.charAt(0)}
                  </div>
                  <div className="im-msg-body">
                    <div className="im-msg-meta">
                      <span
                        style={{
                          fontSize: 10,
                          padding: '1px 6px',
                          borderRadius: 4,
                          background: style.bg,
                          color: style.color,
                          fontWeight: 600,
                        }}
                      >
                        {style.label}
                      </span>
                      <span className="im-msg-author">{item.title}</span>
                      <span className="im-msg-time">{item.ts}</span>
                    </div>
                    <div className="im-msg-text" style={{ color: 'var(--charcoal)' }}>
                      {item.description}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="cs-notification-input">
        <input
          data-testid="notification-input"
          placeholder="\u8F93\u5165\u547D\u4EE4\uFF1A/rules, /status, /review"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
        />
        <button data-testid="notification-send" onClick={handleSend}>
          {'\u53D1\u9001'}
        </button>
      </div>
    </div>
  );
}
