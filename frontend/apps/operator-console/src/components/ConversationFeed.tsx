import { useMemo } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useOperatorStore, deriveCardStatus, type Conversation, type CardStatus } from '../store/operatorStore';

const STATUS_I18N_KEY: Record<CardStatus, string> = {
  idle: 'operator.feed.status.idle',
  'waiting-reply': 'operator.feed.status.waiting_reply',
  'escalation-pending': 'operator.feed.status.escalation_pending',
  'human-takeover': 'operator.feed.status.human_takeover',
  closed: 'operator.feed.status.closed',
};

const STATUS_KIND: Record<CardStatus, 'auto' | 'copilot' | 'takeover' | 'wait'> = {
  idle: 'auto',
  'waiting-reply': 'copilot',
  'escalation-pending': 'wait',
  'human-takeover': 'takeover',
  closed: 'auto',
};

function avatarKind(conv: Conversation): 'a1' | 'a2' | 'a3' | 'a4' {
  if (conv.mode === 'takeover') return 'a4';
  const c = (conv.customerId || conv.id).charCodeAt(0) % 3;
  return (['a1', 'a2', 'a3'] as const)[c];
}

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + '…' : text;
}

const CUSTOMER_ANIMALS = [
  'tiger', 'otter', 'fox', 'panda', 'owl', 'wolf', 'koala', 'lynx',
  'heron', 'dolphin', 'rabbit', 'falcon', 'badger', 'seal', 'ibex', 'stork',
  'raven', 'marten', 'gecko', 'puma',
];

const CUSTOMER_TRAITS = [
  'curious', 'bold', 'calm', 'quirky', 'wise', 'gentle', 'clever', 'witty',
  'cheerful', 'humble', 'swift', 'steady', 'keen', 'merry', 'mellow', 'bright',
  'nimble', 'earnest', 'candid', 'sunny',
];

function hash32(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h;
}

export function customerDisplayName(customerId: string | undefined): string {
  if (!customerId) return '—';
  const h = hash32(customerId);
  const animal = CUSTOMER_ANIMALS[h % CUSTOMER_ANIMALS.length];
  const trait = CUSTOMER_TRAITS[Math.floor(h / CUSTOMER_ANIMALS.length) % CUSTOMER_TRAITS.length];
  return `customer-${animal}-${trait}`;
}

function avatarInitial(conv: Conversation): string {
  const name = customerDisplayName(conv.customerId ?? conv.id);
  const animal = name.split('-')[1] || '?';
  return animal[0].toUpperCase();
}

/**
 * Render an ISO timestamp as a short, human-friendly relative time —
 * "刚刚 / 5 分钟前 / 2 小时前 / 3 天前 / 04-15"-style.
 * Falls back to the raw value if the input can't be parsed (defensive: we
 * don't want a date parse error to blank the entire card meta row).
 */
function formatRelativeTime(
  iso: string,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  if (!iso) return '—';
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return iso;
  const diff = Date.now() - ts;
  const sec = Math.round(diff / 1000);
  if (sec < 45) return t('operator.feed.time.now');
  const min = Math.round(diff / 60000);
  if (min < 60) return t('operator.feed.time.minutes_ago', { count: min });
  const hr = Math.round(diff / 3600000);
  if (hr < 24) return t('operator.feed.time.hours_ago', { count: hr });
  const day = Math.round(diff / 86400000);
  if (day < 7) return t('operator.feed.time.days_ago', { count: day });
  // Older than a week — show the date as MM-DD (locale-neutral).
  const d = new Date(ts);
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${mm}-${dd}`;
}

interface ConversationFeedProps {
  squadId: string | null;
  onCardClick?: (conversationId: string) => void;
}

export function ConversationFeed({ squadId, onCardClick }: ConversationFeedProps) {
  const { t } = useTranslation();
  const conversations = useOperatorStore((s) => s.conversations);
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);

  const sorted = useMemo(() => {
    return Object.values(conversations)
      .filter((c) => !squadId || c.squadId === squadId)
      .sort((a, b) => (b.lastActivityTs > a.lastActivityTs ? 1 : -1));
  }, [conversations, squadId]);

  const avatarHumanLabel = t('operator.feed.avatar.human');

  function avatarText(conv: Conversation): string {
    if (conv.mode === 'takeover') return avatarHumanLabel;
    return avatarInitial(conv);
  }

  if (sorted.length === 0) {
    return (
      <div className="im-feed">
        <div className="im-empty" data-testid="empty-squad">
          {t('operator.feed.empty_title')}<br />
          {t('operator.feed.empty_hint')}
        </div>
      </div>
    );
  }

  return (
    <div className="im-feed cards" data-testid="conversation-feed">
      <div className="im-sec-lbl">
        <span>{t('operator.feed.sec_label')}</span>
        <span className="im-sec-cnt">{t('operator.feed.card_count', { count: sorted.length })}</span>
      </div>
      <div className="im-card-grid">
        {sorted.map((conv) => {
          const status = deriveCardStatus(conv);
          const statusLabel = t(STATUS_I18N_KEY[status]);
          const statusKind = STATUS_KIND[status];
          const isUrgent = status === 'escalation-pending';
          const slaPct = status === 'escalation-pending' ? 42 : status === 'human-takeover' ? 58 : 88;
          const slaKind = slaPct < 50 ? 'danger' : slaPct < 75 ? 'warn' : 'ok';

          const isActive = conv.id === activeCopilotConvId;
          return (
            <div
              key={conv.id}
              className={`op-card ${isActive ? 'active' : ''} ${isUrgent ? 'urgent' : ''}`}
              data-testid={`conv-card-${conv.id}`}
              onClick={() => onCardClick?.(conv.id)}
              style={{ opacity: status === 'closed' ? 0.6 : 1 }}
            >
              <div className="op-card-hd">
                <div className={`op-av ${avatarKind(conv)}`}>{avatarText(conv)}</div>
                <div className="op-card-who">
                  <div className="op-agent-nm" data-testid="conv-customer-id">
                    <span className="op-dot" />
                    {t('operator.feed.customer_label', { handle: customerDisplayName(conv.customerId) })}
                  </div>
                  <div className="op-cust">
                    {t('operator.feed.handled_by', { squad: conv.squadId || 'agent' })}
                  </div>
                </div>
                <span className={`op-status st-${statusKind}`} data-testid="conv-status-tag">
                  {statusLabel}
                </span>
              </div>
              {conv.lastMessage && (
                <div className="op-card-summary">
                  <span className="op-quote">
                    <span data-testid="conv-last-message">{truncate(conv.lastMessage, 40)}</span>
                  </span>
                </div>
              )}
              <div className="op-card-foot">
                <div className="op-stats">
                  <span data-testid="conv-timestamp" title={conv.lastActivityTs}>
                    {formatRelativeTime(conv.lastActivityTs, t)}
                  </span>
                </div>
                <div className="op-sla">
                  <span style={{ fontSize: 10.5 }}>SLA</span>
                  <div className="op-sla-bar">
                    <div className={`op-sla-fill ${slaKind}`} style={{ width: `${slaPct}%` }} />
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
