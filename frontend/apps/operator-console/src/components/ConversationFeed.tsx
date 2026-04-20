import { useMemo } from 'react';
import { useOperatorStore, deriveCardStatus, type Conversation, type CardStatus } from '../store/operatorStore';

const STATUS_LABELS: Record<CardStatus, string> = {
  idle: '空闲',
  'waiting-reply': '待回复',
  'escalation-pending': '升级中',
  'human-takeover': '人工接管',
  closed: '已关闭',
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
  // hash to one of the three palettes for visual variety
  const c = (conv.customerId || conv.id).charCodeAt(0) % 3;
  return (['a1', 'a2', 'a3'] as const)[c];
}

function avatarText(conv: Conversation): string {
  if (conv.mode === 'takeover') return '人';
  return (conv.customerId || conv.id).slice(0, 1).toUpperCase();
}

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + '…' : text;
}

interface ConversationFeedProps {
  squadId: string | null;
  onCardClick?: (conversationId: string) => void;
}

export function ConversationFeed({ squadId, onCardClick }: ConversationFeedProps) {
  const conversations = useOperatorStore((s) => s.conversations);

  const sorted = useMemo(() => {
    return Object.values(conversations)
      .filter((c) => !squadId || c.squadId === squadId)
      .sort((a, b) => (b.lastActivityTs > a.lastActivityTs ? 1 : -1));
  }, [conversations, squadId]);

  if (sorted.length === 0) {
    return (
      <div className="im-feed">
        <div className="im-empty" data-testid="empty-squad">
          {'暂无进行中的对话'}<br />
          {'等待 Agent 接入新客户...'}
        </div>
      </div>
    );
  }

  return (
    <div className="im-feed cards" data-testid="conversation-feed">
      <div className="im-sec-lbl">
        <span>{'进行中对话'}</span>
        <span className="im-sec-cnt">{sorted.length} 张卡片</span>
      </div>
      <div className="im-card-grid">
        {sorted.map((conv) => {
          const status = deriveCardStatus(conv);
          const statusLabel = STATUS_LABELS[status];
          const statusKind = STATUS_KIND[status];
          const isUrgent = status === 'escalation-pending';
          const slaPct = status === 'escalation-pending' ? 42 : status === 'human-takeover' ? 58 : 88;
          const slaKind = slaPct < 50 ? 'danger' : slaPct < 75 ? 'warn' : 'ok';

          return (
            <div
              key={conv.id}
              className={`op-card ${isUrgent ? 'urgent' : ''}`}
              data-testid={`conv-card-${conv.id}`}
              onClick={() => onCardClick?.(conv.id)}
              style={{ opacity: status === 'closed' ? 0.6 : 1 }}
            >
              <div className="op-card-hd">
                <div className={`op-av ${avatarKind(conv)}`}>{avatarText(conv)}</div>
                <div className="op-card-who">
                  <div className="op-agent-nm">
                    <span className="op-dot" />
                    {conv.squadId || 'agent'}
                  </div>
                  <div className="op-cust" data-testid="conv-customer-id">
                    #{conv.id.slice(0, 6)} · {conv.customerId}
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
                  <span data-testid="conv-timestamp">{conv.lastActivityTs}</span>
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
