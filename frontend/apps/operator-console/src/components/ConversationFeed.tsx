import { useMemo } from 'react';
import { useOperatorStore, deriveCardStatus, type Conversation, type CardStatus } from '../store/operatorStore';

const STATUS_LABELS: Record<CardStatus, string> = {
  idle: '空闲',
  'waiting-reply': '待回复',
  'escalation-pending': '升级中',
  'human-takeover': '人工接管',
  closed: '已关闭',
};

function avatarClass(conv: Conversation): string {
  if (conv.mode === 'takeover') return 'im-avatar human';
  return 'im-avatar a1';
}

function avatarText(conv: Conversation): string {
  if (conv.mode === 'takeover') return '人';
  return 'a';
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
    <div className="im-feed" data-testid="conversation-feed">
      {sorted.map((conv) => {
        const status = deriveCardStatus(conv);
        const statusLabel = STATUS_LABELS[status];
        const isHighlight = status === 'escalation-pending' || status === 'human-takeover';

        return (
          <div
            key={conv.id}
            className="im-card"
            data-testid={`conv-card-${conv.id}`}
            onClick={() => onCardClick?.(conv.id)}
            style={{ cursor: 'pointer', opacity: status === 'closed' ? 0.6 : 1 }}
          >
            <div className={avatarClass(conv)}>{avatarText(conv)}</div>
            <div className="im-msg-body">
              <div className="im-msg-meta">
                <span className="im-msg-author" data-testid="conv-customer-id">
                  {conv.customerId}
                </span>
                <span className="im-msg-bot-tag">
                  {conv.mode === 'takeover' ? 'HUMAN' : 'APP'}
                </span>
                <span className="im-msg-time">{conv.lastActivityTs}</span>
              </div>
              <div className={`im-block ${isHighlight ? 'highlight' : ''}`}>
                <div className="im-block-title">
                  {'卡片'} {conv.id.slice(0, 8)}
                  <span className="im-block-status" data-testid="conv-status-tag">
                    {statusLabel}
                  </span>
                </div>
                {conv.lastMessage && (
                  <div className="im-block-meta" data-testid="conv-last-message">
                    {conv.lastMessage.length > 40
                      ? conv.lastMessage.slice(0, 40) + '…'
                      : conv.lastMessage}
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
