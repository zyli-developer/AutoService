interface AgentInfo {
  key: string;
  name: string;
  online: boolean;
}

const agents: AgentInfo[] = [
  { key: 'customer', name: 'Customer Agent', online: true },
  { key: 'translate', name: 'Translate Agent', online: true },
  { key: 'lead', name: 'Lead Agent', online: true },
  { key: 'triage', name: 'Triage Agent', online: true },
];

const metrics = [
  { testId: 'metric-takeover', title: '\u63A5\u7BA1\u6B21\u6570', value: '23' },
  { testId: 'metric-csat', title: 'CSAT', value: '4.6 / 5.0' },
  { testId: 'metric-resolution', title: '\u5347\u7EA7\u2192\u7ED3\u6848\u7387', value: '87%' },
];

const events = [
  { t: '09:38:02', text: 'conn.open tenant=mystore client=david', cls: '' },
  { t: '09:38:05', text: 'agent.greet TTFB=2.1s', cls: '' },
  { t: '09:42:01', text: 'human.open chat_id=#2', cls: '' },
  { t: '09:43:09', text: 'agent2.adopt suggestion', cls: '' },
  { t: '09:45:00', text: 'state \u2192 HumanRequested', cls: 'warn' },
  { t: '09:45:42', text: 'human.takeover #2', cls: '' },
  { t: '09:48:12', text: '\u5347\u7EA7\u8F6C\u7ED3\u6848\u7387 89.3% \u2713', cls: 'ok' },
];

export function DashboardTab() {
  return (
    <div data-testid="tab-dashboard">
      <div className="cs-card">
        <div className="cs-ct">{'\u25C9 \u5B9E\u65F6 SLA'}</div>
        {metrics.map((m) => (
          <div key={m.testId} className="cs-row" data-testid={m.testId}>
            <span>{m.title}</span>
            <span style={{ color: 'var(--m600)', fontWeight: 700 }}>{m.value}</span>
          </div>
        ))}
      </div>

      <div className="cs-card">
        <div className="cs-ct">{'\u2699\uFE0F Agent \u72B6\u6001'}</div>
        {agents.map((agent) => (
          <div key={agent.key} className="cs-row" data-testid={`agent-card-${agent.key}`}>
            <span>{agent.name}</span>
            <span style={{ color: agent.online ? 'var(--m600)' : 'var(--silver)', fontWeight: 700 }}>
              {agent.online ? 'online' : 'offline'}
            </span>
          </div>
        ))}
      </div>

      <div className="cs-card">
        <div className="cs-ct">{'\uD83D\uDCE1 \u4E8B\u4EF6\u6D41'}</div>
        <div style={{ lineHeight: 1.7, maxHeight: 200, overflowY: 'auto' }}>
          {events.map((ev, i) => (
            <div key={i} className={`ev ${ev.cls}`}>
              <span className="t">{ev.t}</span>
              {ev.text}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
