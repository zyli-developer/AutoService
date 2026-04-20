import { LanguageSwitcher, useTranslation } from '@autoservice/i18n';

export function MerchantSite() {
  const { t } = useTranslation();
  return (
    <div className="web-page">
      <div className="web-nav">
        <div className="web-logo" data-testid="merchant-logo">◆ {t('customer.merchant.title')}</div>
        <div className="web-nav-links" style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span>{t('customer.merchant.nav.home')}</span>
          <span>{t('customer.merchant.nav.products')}</span>
          <span>{t('customer.merchant.nav.about')}</span>
          <LanguageSwitcher
            style={{
              padding: '2px 6px',
              fontSize: 12,
              border: '1px solid rgba(255,255,255,0.4)',
              borderRadius: 4,
              background: 'transparent',
              color: 'inherit',
              cursor: 'pointer',
            }}
          />
        </div>
      </div>
      <div className="web-hero">
        <div className="web-hero-title">{t('customer.merchant.welcome')}</div>
        <div className="web-hero-sub">{t('customer.merchant.subtitle')}</div>
      </div>
      <div className="web-features">
        <div className="web-feature-card">
          <div className="web-feature-card-title">{t('customer.merchant.plan_a')}</div>
          {t('customer.merchant.plan_a.desc')}
        </div>
        <div className="web-feature-card">
          <div className="web-feature-card-title">{t('customer.merchant.plan_b')}</div>
          {t('customer.merchant.plan_b.desc')}
        </div>
      </div>
    </div>
  );
}
