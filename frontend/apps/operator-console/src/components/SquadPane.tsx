import { Typography } from 'antd';

interface SquadPaneProps {
  squadId: string;
}

export function SquadPane({ squadId }: SquadPaneProps) {
  return (
    <div data-testid={`squad-pane-${squadId}`} style={{ padding: 16 }}>
      <Typography.Text type="secondary">
        Squad: {squadId} · 卡片列表 — T2B.2 TODO
      </Typography.Text>
    </div>
  );
}
