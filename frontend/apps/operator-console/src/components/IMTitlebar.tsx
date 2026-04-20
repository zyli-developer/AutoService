import { LanguageSwitcher, useTranslation } from '@autoservice/i18n';

export function IMTitlebar() {
  const { t } = useTranslation();
  return (
    <div className="im-titlebar" data-testid="im-titlebar">
      <div className="im-titlebar-dots"><span /><span /><span /></div>
      <div className="im-workspace-name">{t('operator.titlebar.title')}</div>
      <LanguageSwitcher
        style={{
          marginLeft: 'auto',
          marginRight: 12,
          padding: '2px 6px',
          fontSize: 12,
          border: '1px solid var(--l400, #ccc)',
          borderRadius: 4,
          background: 'transparent',
          color: 'inherit',
          cursor: 'pointer',
        }}
      />
    </div>
  );
}
