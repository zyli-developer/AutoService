import { useAdminStore } from '../../store/adminStore';

export type ChatBlock =
  | { type: 'metric'; data: { label: string; value: string } }
  | { type: 'alert'; data: { text: string } }
  | { type: 'action-launch'; data: { text: string; target: 'wizard' | 'dashboard' | 'proposals' | 'billing' | 'notifications' } }
  | {
      type: 'proposal-card';
      data: {
        id: string;
        title: string;
        onApprove?: (id: string) => void;
        onReject?: (id: string) => void;
      };
    };

interface Props {
  block: ChatBlock;
}

export function InlineWidget({ block }: Props) {
  const setActiveTab = useAdminStore((s) => s.setActiveTab);

  switch (block.type) {
    case 'metric':
      return (
        <div className="adm-chat-widget-metric" data-testid="widget-metric">
          <span className="label">{block.data.label}</span>
          <span className="value">{block.data.value}</span>
        </div>
      );

    case 'alert':
      return (
        <div className="adm-chat-widget-alert" data-testid="widget-alert">
          ⚠ {block.data.text}
        </div>
      );

    case 'action-launch': {
      const { text, target } = block.data;
      return (
        <div className="adm-chat-widget-launch" data-testid="widget-launch">
          <span>{text}</span>
          <button
            type="button"
            className="cs-btn ok"
            data-testid="widget-launch-btn"
            onClick={() => setActiveTab(target)}
          >
            启动
          </button>
        </div>
      );
    }

    case 'proposal-card': {
      const { id, title, onApprove, onReject } = block.data;
      return (
        <div className="adm-chat-widget-proposal" data-testid="widget-proposal">
          <div className="im-block highlight">
            <div className="im-block-title">{title}</div>
            <div className="adm-chat-widget-actions">
              <button
                type="button"
                className="cs-btn ok"
                data-testid="widget-proposal-approve"
                onClick={() => onApprove?.(id)}
              >
                批准
              </button>
              <button
                type="button"
                className="cs-btn edit"
                data-testid="widget-proposal-reject"
                onClick={() => onReject?.(id)}
              >
                驳回
              </button>
              <button
                type="button"
                className="cs-btn edit"
                data-testid="widget-proposal-details"
                onClick={() => setActiveTab('proposals')}
              >
                详情
              </button>
            </div>
          </div>
        </div>
      );
    }

    default:
      return null;
  }
}
