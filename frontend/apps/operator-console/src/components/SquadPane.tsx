import { useMemo } from 'react';
import { Typography } from 'antd';
import { useOperatorStore } from '../store/operatorStore';
import { ConversationCard } from './ConversationCard';

interface SquadPaneProps {
  squadId: string;
  onCardClick?: (conversationId: string) => void;
}

export function SquadPane({ squadId, onCardClick }: SquadPaneProps) {
  const conversations = useOperatorStore((s) => s.conversations);

  const sorted = useMemo(() => {
    return Object.values(conversations)
      .filter((c) => c.squadId === squadId)
      .sort((a, b) => (b.lastActivityTs > a.lastActivityTs ? 1 : -1));
  }, [conversations, squadId]);

  return (
    <div data-testid={`squad-pane-${squadId}`} style={{ padding: 16 }}>
      {sorted.length === 0 ? (
        <Typography.Text type="secondary" data-testid="empty-squad">
          暂无会话
        </Typography.Text>
      ) : (
        sorted.map((conv) => (
          <ConversationCard key={conv.id} conversation={conv} onClick={onCardClick} />
        ))
      )}
    </div>
  );
}
