import { useTranslation } from '@autoservice/i18n';

export function IMTitlebar() {
  const { i18n } = useTranslation();

  const handleLanguageChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    i18n.changeLanguage(e.target.value);
  };

  return (
    <div className="im-titlebar" data-testid="im-titlebar">
      <div className="im-titlebar-dots"><span /><span /><span /></div>
      <div className="im-workspace-name">{'商户客服工作区'}</div>
      <select
        data-testid="language-switch"
        value={i18n.language}
        onChange={handleLanguageChange}
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
      >
        <option value="zh-CN">中文</option>
        <option value="en">EN</option>
      </select>
    </div>
  );
}
