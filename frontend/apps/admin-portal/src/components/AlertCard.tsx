/**
 * AlertCard — renders incoming SLA alert events pushed via WebSocket.
 *
 * T6E.7 | Displays severity badge, metric info, threshold details,
 * and a /dispatch button for operator escalation.
 */

import { useState } from 'react';
import { useTranslation } from '@autoservice/i18n';

export interface SLAAlert {
  rule_id: string;
  rule_name_zh: string;
  severity: 'critical' | 'high' | 'medium';
  metric: string;
  window: string;
  value: number;
  threshold: number;
  message: string;
  timestamp: number;
}

const SEVERITY_STYLES: Record<SLAAlert['severity'], { bg: string; color: string; labelKey: string }> = {
  critical: { bg: 'var(--vermillion-500)', color: '#fff', labelKey: 'admin.alert.severity.critical' },
  high:     { bg: 'var(--goose-500)',      color: '#fff', labelKey: 'admin.alert.severity.high' },
  medium:   { bg: 'var(--gold-500)',       color: '#fff', labelKey: 'admin.alert.severity.medium' },
};

interface AlertCardProps {
  alert: SLAAlert;
  onDispatch?: (alert: SLAAlert) => void;
}

export function AlertCard({ alert, onDispatch }: AlertCardProps) {
  const { t } = useTranslation();
  const [dispatched, setDispatched] = useState(false);
  const style = SEVERITY_STYLES[alert.severity] || SEVERITY_STYLES.medium;
  const label = t(style.labelKey);

  const handleDispatch = () => {
    setDispatched(true);
    onDispatch?.(alert);
  };

  const ts = new Date(alert.timestamp * 1000).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  return (
    <div
      className="im-card"
      data-testid={`alert-card-${alert.rule_id}`}
      style={{ borderLeft: `3px solid ${style.bg}` }}
    >
      <div
        className="im-avatar a1"
        style={{ background: style.bg, color: style.color, fontSize: 10 }}
      >
        {label.charAt(0)}
      </div>
      <div className="im-msg-body" style={{ flex: 1 }}>
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
          <span className="im-msg-author">{alert.rule_name_zh}</span>
          <span className="im-msg-time">{ts}</span>
        </div>
        <div className="im-msg-text" style={{ color: 'var(--charcoal)' }}>
          {alert.message}
        </div>
        <div style={{ fontSize: 11, color: 'var(--m500)', marginTop: 2 }}>
          {alert.metric} / {alert.window} &mdash; {alert.value.toFixed(1)} (阈值 {alert.threshold})
        </div>
      </div>
      <button
        data-testid={`alert-dispatch-${alert.rule_id}`}
        onClick={handleDispatch}
        disabled={dispatched}
        style={{
          alignSelf: 'center',
          padding: '4px 10px',
          fontSize: 12,
          borderRadius: 4,
          border: 'none',
          cursor: dispatched ? 'default' : 'pointer',
          background: dispatched ? 'var(--m300)' : 'var(--p)',
          color: dispatched ? 'var(--m600)' : '#fff',
        }}
      >
        {dispatched ? t('admin.alert.dispatched') : t('admin.alert.dispatch_action')}
      </button>
    </div>
  );
}
