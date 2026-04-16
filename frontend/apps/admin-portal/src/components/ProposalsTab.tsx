export function ProposalsTab() {
  return (
    <div data-testid="tab-proposals">
      <div className="cs-card hl">
        <div className="cs-ct">{'\uD83D\uDCDD \u63D0\u6848\u5BA1\u6838'}</div>
        <div className="im-block highlight">
          <div className="im-block-title">
            {'\u63D0\u6848 #1 \u00B7 \u5957\u9910 B \u8BDD\u672F\u4F18\u5316'}
            <span className="im-block-status">{'\u4F4E\u98CE\u9669'}</span>
          </div>
          <div className="im-block-meta">
            {'\u6765\u6E90 23 \u6BB5\u5BF9\u8BDD \u00B7 \u5EFA\u8BAE\u5F3A\u8C03\u9996\u6708\u514D\u8D39'}
          </div>
        </div>
        <div className="im-block">
          <div className="im-block-title">
            {'\u63D0\u6848 #2 \u00B7 \u897F\u8BED FAQ \u8865\u5145'}
            <span className="im-block-status">{'\u4F4E\u98CE\u9669'}</span>
          </div>
          <div className="im-block-meta">
            {'\u58A8\u897F\u54E5\u5BA2\u6237\u9AD8\u9891\u95EE\u201C\u8FD0\u8D39\u201D'}
          </div>
        </div>
      </div>

      <div className="cs-card">
        <div className="cs-ct">{'\u26A1 \u5FEB\u901F\u64CD\u4F5C'}</div>
        <div className="cs-row">
          <span>/approve #1</span>
          <span className="ck">{'\u2713 \u901A\u8FC7'}</span>
        </div>
        <div className="cs-row">
          <span>/edit #2</span>
          <span style={{ color: 'var(--l700)', fontWeight: 700 }}>{'\u270E \u4FEE\u6539'}</span>
        </div>
        <div className="cs-row">
          <span>/reject #3</span>
          <span style={{ color: 'var(--p)', fontWeight: 700 }}>{'\u2717 \u62D2\u7EDD'}</span>
        </div>
      </div>
    </div>
  );
}
