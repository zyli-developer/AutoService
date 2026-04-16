import { Badge } from 'antd';
import type { ReactNode } from 'react';
import { useOperatorStore } from '../store/operatorStore';

interface UnreadBadgeProps {
  squadId: string;
  children: ReactNode;
}

export function UnreadBadge({ squadId, children }: UnreadBadgeProps) {
  const count = useOperatorStore((s) => s.unreadCounts[squadId] ?? 0);

  return (
    <span data-testid={`unread-badge-${squadId}`}>
      <Badge count={count}>{children}</Badge>
    </span>
  );
}
