export function MerchantSite() {
  return (
    <div className="web-page">
      <div className="web-nav">
        <div className="web-logo" data-testid="merchant-logo">{'◆'} {'商户独立站'}</div>
        <div className="web-nav-links">
          <span>{'首页'}</span>
          <span>{'产品'}</span>
          <span>{'关于'}</span>
        </div>
      </div>
      <div className="web-hero">
        <div className="web-hero-title">{'欢迎光临'}</div>
        <div className="web-hero-sub">{'7×24 智能客服为您服务'}</div>
      </div>
      <div className="web-features">
        <div className="web-feature-card">
          <div className="web-feature-card-title">{'套餐 A'}</div>
          {'基础版，适合个人'}
        </div>
        <div className="web-feature-card">
          <div className="web-feature-card-title">{'套餐 B'}</div>
          {'进阶版，本月特惠'}
        </div>
      </div>
    </div>
  );
}
