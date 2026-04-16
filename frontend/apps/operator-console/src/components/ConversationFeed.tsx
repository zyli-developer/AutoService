import { useMemo } from 'react';
import { useOperatorStore, deriveCardStatus, type Conversation, type CardStatus } from '../store/operatorStore';

const STATUS_LABELS: Record<CardStatus, string> = {
  idle: '\u7A7A\u95F2',
  'waiting-reply': '\u5F85\u56DE\u590D',
  'escalation-pending': '\u5347\u7EA7\u4E2D',
  'human-takeover': '\u4EBA\u5DE5\u63A5\u7BA1',
  closed: '\u5DF2\u5173\u95ED',
};

function avatarClass(conv: Conversation): string {
  if (conv.mode === 'takeover') return 'im-avatar human';
  return 'im-avatar a1';
}

function avatarText(conv: Conversation): string {
  if (conv.mode === 'takeover') return '\u4EBA';
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
          {'\u6682\u65E0\u8FDB\u884C\u4E2D\u7684\u5BF9\u8BDD'}<br />
          {'\u7B49\u5F85 Agent \u63A5\u5165\u65B0\u5BA2\u6237...'}
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
                  {'\u5361\u7247'} {conv.id.slice(0, 8)}
                  <span className="im-block-status" data-testid="conv-status-tag">
                    {statusLabel}
                  </span>
                </div>
                {conv.lastMessage && (
                  <div className="im-block-meta" data-testid="conv-last-message">
                    {conv.lastMessage.length > 40
                      ? conv.lastMessage.slice(0, 40) + '\u2026'
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
