export function MerchantSite() {
  return (
    <div className="web-page">
      <div className="web-nav">
        <div className="web-logo" data-testid="merchant-logo">{'\u25C6'} {'\u5546\u6237\u72EC\u7ACB\u7AD9'}</div>
        <div className="web-nav-links">
          <span>{'\u9996\u9875'}</span>
          <span>{'\u4EA7\u54C1'}</span>
          <span>{'\u5173\u4E8E'}</span>
        </div>
      </div>
      <div className="web-hero">
        <div className="web-hero-title">{'\u6B22\u8FCE\u5149\u4E34'}</div>
        <div className="web-hero-sub">{'7\u00D724 \u667A\u80FD\u5BA2\u670D\u4E3A\u60A8\u670D\u52A1'}</div>
      </div>
      <div className="web-features">
        <div className="web-feature-card">
          <div className="web-feature-card-title">{'\u5957\u9910 A'}</div>
          {'\u57FA\u7840\u7248\uFF0C\u9002\u5408\u4E2A\u4EBA'}
        </div>
        <div className="web-feature-card">
          <div className="web-feature-card-title">{'\u5957\u9910 B'}</div>
          {'\u8FDB\u9636\u7248\uFF0C\u672C\u6708\u7279\u60E0'}
        </div>
      </div>
    </div>
  );
}
