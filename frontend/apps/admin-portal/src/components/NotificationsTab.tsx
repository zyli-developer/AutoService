import { useState } from 'react';
import { useAdminStore, type Notification } from '../store/adminStore';

const TYPE_STYLES: Record<Notification['type'], { bg: string; color: string; label: string }> = {
  alert: { bg: 'var(--p)', color: '#fff', label: '告警' },
  info: { bg: 'var(--m300)', color: 'var(--m800)', label: '信息' },
  command: { bg: 'var(--m800)', color: '#fff', label: '命令' },
};

function makeId(): string {
  return `notif-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const commandHandlers: Record<string, () => Pick<Notification, 'title' | 'description' | 'type'>> = {
  '/rules': () => ({ type: 'command', title: '规则配置已更新', description: '已执行 /rules 命令' }),
  '/status': () => ({ type: 'command', title: '系统状态：正常', description: '已执行 /status 命令' }),
  '/review': () => ({ type: 'command', title: '审查已启动', description: '已执行 /review 命令' }),
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
        description: '用户输入',
        ts: new Date().toISOString(),
      });
    }
    setInput('');
  };

  return (
    <div data-testid="tab-notifications">
      <div data-testid="notification-list">
        {notifications.length === 0 ? (
          <div className="im-empty">{'暂无通知'}</div>
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
          placeholder="输入命令：/rules, /status, /review"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
        />
        <button data-testid="notification-send" onClick={handleSend}>
          {'发送'}
        </button>
      </div>
    </div>
  );
}
