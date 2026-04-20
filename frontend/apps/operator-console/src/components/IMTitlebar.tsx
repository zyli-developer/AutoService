import { LanguageSwitcher, useTranslation } from '@autoservice/i18n';
import { useOperatorStore } from '../store/operatorStore';

const SearchIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" />
    <path d="m21 21-4.35-4.35" />
  </svg>
);

const FilterIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3Z" />
  </svg>
);

export function IMTitlebar() {
  const { t } = useTranslation();
  const activeSquadId = useOperatorStore((s) => s.activeSquadId);
  const conversations = useOperatorStore((s) => s.conversations);
  const wsStatus = useOperatorStore((s) => s.wsStatus);

  const filtered = activeSquadId
    ? Object.values(conversations).filter((c) => c.squadId === activeSquadId)
    : Object.values(conversations);
  const slaOk = wsStatus === 'open';

  return (
    <header className="im-topbar" data-testid="im-titlebar">
      <div className="im-topbar-left">
        <div className="im-crumb">{t('operator.titlebar.title')}</div>
        <div className="im-page-title">
          {activeSquadId ? `# ${activeSquadId}` : t('operator.topbar.my_squad')}
          <span className="im-page-cnt">{t('operator.topbar.in_progress', { count: filtered.length })}</span>
        </div>
      </div>
      <div className="im-topbar-right">
        <span className={`im-pill ${slaOk ? 'ok' : 'warn'}`}>
          <span className="im-pill-dot" />
          {slaOk ? t('operator.topbar.sla_ok') : t('operator.topbar.sla_reconnecting')}
        </span>
        <button type="button" className="im-iconbtn" title={t('operator.topbar.search')} aria-label={t('operator.topbar.search')}>
          <SearchIcon />
        </button>
        <button type="button" className="im-iconbtn" title={t('operator.topbar.filter')} aria-label={t('operator.topbar.filter')}>
          <FilterIcon />
        </button>
        <LanguageSwitcher
          style={{
            padding: '4px 10px',
            fontSize: 12,
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--color-bg-surface)',
            color: 'var(--color-text-secondary)',
            cursor: 'pointer',
            fontFamily: 'var(--font-mono)',
            letterSpacing: '0.1px',
          }}
        />
      </div>
    </header>
  );
}
