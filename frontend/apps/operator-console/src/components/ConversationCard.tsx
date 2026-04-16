import { Card, Tag, Typography } from 'antd';
import { type Conversation, type CardStatus, deriveCardStatus } from '../store/operatorStore';

const STATUS_CONFIG: Record<CardStatus, { color: string; label: string }> = {
  idle: { color: 'default', label: '空闲' },
  'waiting-reply': { color: 'blue', label: '待回复' },
  'escalation-pending': { color: 'orange', label: '升级中' },
  'human-takeover': { color: 'red', label: '人工接管' },
  closed: { color: 'default', label: '已关闭' },
};

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + '…' : text;
}

function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) + '…' : id;
}

interface ConversationCardProps {
  conversation: Conversation;
  onClick?: (conversationId: string) => void;
}

export function ConversationCard({ conversation, onClick }: ConversationCardProps) {
  const status = deriveCardStatus(conversation);
  const cfg = STATUS_CONFIG[status];

  return (
    <Card
      size="small"
      hoverable
      data-testid={`conv-card-${conversation.id}`}
      style={{ marginBottom: 8, opacity: status === 'closed' ? 0.6 : 1 }}
      onClick={() => onClick?.(conversation.id)}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Text strong data-testid="conv-customer-id">
          {conversation.customerId}
        </Typography.Text>
        <Tag color={cfg.color} data-testid="conv-status-tag">{cfg.label}</Tag>
      </div>
      <Typography.Text type="secondary" style={{ fontSize: 12 }} data-testid="conv-id">
        {shortId(conversation.id)}
      </Typography.Text>
      {conversation.lastMessage && (
        <div style={{ marginTop: 4 }}>
          <Typography.Text
            type="secondary"
            style={{ fontSize: 12 }}
            data-testid="conv-last-message"
          >
            {truncate(conversation.lastMessage, 40)}
          </Typography.Text>
        </div>
      )}
      <div style={{ marginTop: 4, textAlign: 'right' }}>
        <Typography.Text type="secondary" style={{ fontSize: 11 }} data-testid="conv-timestamp">
          {conversation.lastActivityTs}
        </Typography.Text>
      </div>
    </Card>
  );
}
