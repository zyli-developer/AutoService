import { LanguageSwitcher, useTranslation } from '@autoservice/i18n';

export function MerchantSite() {
  const { t } = useTranslation();

  return (
    <div className="m-page">
      <div className="m-nav">
        <div className="m-brand" data-testid="merchant-logo">{t('customer.merchant.title')}</div>
        <a className="m-link active">{t('customer.merchant.nav.home')}</a>
        <a className="m-link">{t('customer.merchant.nav.products')}</a>
        <a className="m-link">{t('customer.merchant.nav.pricing')}</a>
        <a className="m-link">{t('customer.merchant.nav.about')}</a>
        <a className="m-link">{t('customer.merchant.nav.contact')}</a>
        <div className="m-nav-right">
          <span className="m-cart">{t('customer.merchant.cart')}</span>
          <LanguageSwitcher
            style={{
              padding: '2px 8px',
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
      </div>

      <div className="m-hero">
        <div className="m-kicker">{t('customer.merchant.kicker')}</div>
        <h1 className="m-h1">{t('customer.merchant.welcome')}</h1>
        <p className="m-lead">
          {t('customer.merchant.subtitle')}
          {t('customer.merchant.subtitle_suffix')}
        </p>
      </div>

      <div className="m-tiles">
        <div className="m-tile">
          <div className="m-tile-ph" />
          <h4 className="m-tile-name">{t('customer.merchant.plan_a')}</h4>
          <div className="m-tile-desc">{t('customer.merchant.plan_a.desc')}</div>
          <div className="m-tile-price">{t('customer.merchant.tile.basic_price')}</div>
        </div>
        <div className="m-tile featured">
          <div className="m-tile-ph featured" />
          <h4 className="m-tile-name">
            {t('customer.merchant.plan_b')}
            <span className="m-tile-badge">{t('customer.merchant.tile.badge_hot')}</span>
          </h4>
          <div className="m-tile-desc">{t('customer.merchant.plan_b.desc')}</div>
          <div className="m-tile-price">{t('customer.merchant.tile.pro_price')}</div>
        </div>
        <div className="m-tile">
          <div className="m-tile-ph" />
          <h4 className="m-tile-name">{t('customer.merchant.tile.enterprise_name')}</h4>
          <div className="m-tile-desc">{t('customer.merchant.tile.enterprise_desc')}</div>
          <div className="m-tile-price">{t('customer.merchant.tile.enterprise_price')}</div>
        </div>
      </div>

      <div className="m-note">
        <span className="m-note-arr" />
        <span>{t('customer.merchant.note')}</span>
      </div>
    </div>
  );
}
