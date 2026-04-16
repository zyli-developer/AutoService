const AGENTS = [
  { key: 'customer', name: 'Customer Agent', online: true },
  { key: 'translate', name: 'Translate Agent', online: true },
  { key: 'lead', name: 'Lead Agent', online: true },
  { key: 'triage', name: 'Triage Agent', online: true },
];

const SLA_METRICS = [
  { key: 'onboard', label: 'onboard 首屏', value: '2.1s', status: 'ok' as const },
  { key: 'fast-model', label: '快模型问候', value: '<1s', status: 'ok' as const },
  { key: 'copilot', label: 'Copilot 通道', value: '已建', status: 'ok' as const },
  { key: 'takeover', label: '★ 接管次数', value: '+23', status: 'ok' as const },
  { key: 'csat', label: 'CSAT', value: '4.6/5', status: 'ok' as const },
  { key: 'resolution', label: '结案率', value: '87.3%', status: 'ok' as const },
  { key: 'wait', label: '接单等待', value: '42s/180s', status: 'warn' as const },
];

const EVENTS = [
  { ts: '09:38:02', text: 'conn.open tenant=mystore client=david' },
  { ts: '09:38:04', text: 'ctx.load history found ✓', cls: '' },
  { ts: '09:38:05', text: 'agent.greet TTFB=2.1s' },
  { ts: '09:42:01', text: 'human.open chat_id=#2' },
  { ts: '09:42:02', text: 'mode=copilot driver=agent2' },
  { ts: '09:45:42', text: 'human.takeover #2', cls: 'ok' },
  { ts: '09:48:12', text: 'conv.close CSAT=5', cls: 'ok' },
];

export function DashboardTab() {
  return (
    <div data-testid="tab-dashboard">
      {/* Agent Status */}
      <div className="cs-card">
        <div className="cs-ct">🤖 Agent 状态</div>
        {AGENTS.map((a) => (
          <div className="cs-row" key={a.key} data-testid={`agent-card-${a.key}`}>
            <span>{a.name}</span>
            <span style={{ color: a.online ? 'var(--m600)' : 'var(--silver)', fontWeight: 700 }}>
              {a.online ? 'online' : 'offline'}
            </span>
          </div>
        ))}
      </div>

      {/* SLA Metrics */}
      <div className="cs-card" style={{ marginTop: 14 }}>
        <div className="cs-ct">◉ 实时 SLA</div>
        {SLA_METRICS.map((m) => (
          <div className="cs-row" key={m.key} data-testid={`metric-${m.key}`}>
            <span>{m.label}</span>
            <span style={{
              color: m.status === 'ok' ? 'var(--m600)' : 'var(--l700)',
              fontWeight: 700,
            }}>
              {m.value}
            </span>
          </div>
        ))}
      </div>

      {/* Event Stream */}
      <div className="cs-card" style={{ marginTop: 14 }}>
        <div className="cs-ct">📡 事件流</div>
        <div style={{ lineHeight: 1.7, maxHeight: 180, overflowY: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
          {EVENTS.map((e, i) => (
            <div key={i} className={`ev ${e.cls ?? ''}`}>
              <span className="t">{e.ts}</span> {e.text}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
