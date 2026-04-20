import { LanguageSwitcher, useTranslation } from '@autoservice/i18n';

export function MerchantSite() {
  const { t } = useTranslation();

  return (
    <div className="m-page">
      <div className="m-nav">
        <div className="m-brand" data-testid="merchant-logo">{t('customer.merchant.title') || 'mystore'}</div>
        <a className="m-link active">{t('customer.merchant.nav.home')}</a>
        <a className="m-link">{t('customer.merchant.nav.products')}</a>
        <a className="m-link">{'定价'}</a>
        <a className="m-link">{t('customer.merchant.nav.about')}</a>
        <a className="m-link">{'联系我们'}</a>
        <div className="m-nav-right">
          <span className="m-cart">{'购物车 · 0'}</span>
          <a className="m-login">{'登录'}</a>
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
        <div className="m-kicker">{'本月限定 · 首月 8 折'}</div>
        <h1 className="m-h1">{t('customer.merchant.welcome')}</h1>
        <p className="m-lead">
          {t('customer.merchant.subtitle')}
          {' — 不耗人，不漏客。'}
        </p>
      </div>

      <div className="m-tiles">
        <div className="m-tile">
          <div className="m-tile-ph" />
          <h4 className="m-tile-name">{t('customer.merchant.plan_a')}</h4>
          <div className="m-tile-desc">{t('customer.merchant.plan_a.desc')}</div>
          <div className="m-tile-price">¥99 / 月</div>
        </div>
        <div className="m-tile featured">
          <div className="m-tile-ph featured" />
          <h4 className="m-tile-name">
            {t('customer.merchant.plan_b')}
            <span className="m-tile-badge">{'热门'}</span>
          </h4>
          <div className="m-tile-desc">{t('customer.merchant.plan_b.desc')}</div>
          <div className="m-tile-price">¥299 / 月</div>
        </div>
        <div className="m-tile">
          <div className="m-tile-ph" />
          <h4 className="m-tile-name">{'企业定制'}</h4>
          <div className="m-tile-desc">{'50 人以上团队 · 私有化部署'}</div>
          <div className="m-tile-price">{'联系我们'}</div>
        </div>
      </div>

      <div className="m-note">
        <span className="m-note-arr" />
        <span>{'右下角是 AutoService 嵌入式客服 widget — 客户点开就开始对话'}</span>
      </div>
    </div>
  );
}
