import { useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useAdminStore, type Notification } from '../store/adminStore';

const TYPE_STYLES: Record<Notification['type'], { bg: string; color: string; labelKey: string }> = {
  alert: { bg: 'var(--p)', color: '#fff', labelKey: 'admin.notifications.type.alert' },
  info: { bg: 'var(--m300)', color: 'var(--m800)', labelKey: 'admin.notifications.type.info' },
  command: { bg: 'var(--m800)', color: '#fff', labelKey: 'admin.notifications.type.command' },
};

function makeId(): string {
  return `notif-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

type CommandKind = '/rules' | '/status' | '/review';
const COMMAND_KINDS: CommandKind[] = ['/rules', '/status', '/review'];

function makeCommand(
  cmd: CommandKind,
  t: (k: string, opts?: Record<string, unknown>) => string,
): Pick<Notification, 'title' | 'description' | 'type'> {
  const slug = cmd.slice(1);
  return {
    type: 'command',
    title: t(`admin.notifications.cmd.${slug}.title`),
    description: t('admin.notifications.cmd.executed', { cmd }),
  };
}

export function NotificationsTab() {
  const { t } = useTranslation();
  const [input, setInput] = useState('');
  const notifications = useAdminStore((s) => s.notifications);
  const addNotification = useAdminStore((s) => s.addNotification);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed) return;

    if ((COMMAND_KINDS as string[]).includes(trimmed)) {
      addNotification({
        id: makeId(),
        ts: new Date().toISOString(),
        ...makeCommand(trimmed as CommandKind, t),
      });
    } else {
      addNotification({
        id: makeId(),
        type: 'info',
        title: trimmed,
        description: t('admin.notifications.user_input'),
        ts: new Date().toISOString(),
      });
    }
    setInput('');
  };

  return (
    <div data-testid="tab-notifications">
      <div data-testid="notification-list">
        {notifications.length === 0 ? (
          <div className="im-empty">{t('admin.notifications.empty')}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {notifications.map((item) => {
              const style = TYPE_STYLES[item.type];
              const label = t(style.labelKey);
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
                    {label.charAt(0)}
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
                        {label}
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
          placeholder={t('admin.notifications.input_placeholder')}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
        />
        <button data-testid="notification-send" onClick={handleSend}>
          {t('common.send')}
        </button>
      </div>
    </div>
  );
}
