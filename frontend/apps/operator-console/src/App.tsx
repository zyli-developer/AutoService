import { useTranslation } from '@autoservice/i18n';
import { useOperatorStore } from './store/operatorStore';
import { LoginPage } from './components/LoginPage';
import { WorkspacePage } from './components/WorkspacePage';

function MobileBlock() {
  const { t } = useTranslation();
  return (
    <div className="op-mobile-block" data-testid="op-mobile-block">
      <div className="op-mobile-badge">{t('operator.mobile.badge')}</div>
      <h2 className="op-mobile-h2">
        {t('operator.mobile.title_l1')}
        <br />
        {t('operator.mobile.title_l2')}
      </h2>
      <p className="op-mobile-p">{t('operator.mobile.desc')}</p>
      <div className="op-mobile-minw">
        {t('operator.mobile.min_width_label')} · <b>{t('operator.mobile.min_width_value')}</b>
      </div>
    </div>
  );
}

export function App() {
  const isLoggedIn = useOperatorStore((s) => s.isLoggedIn);
  return (
    <>
      <div className="op-desktop-only">
        {isLoggedIn ? <WorkspacePage /> : <LoginPage />}
      </div>
      <MobileBlock />
    </>
  );
}
