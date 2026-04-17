import { describe, it, expect, beforeEach } from 'vitest';
import { parseScriptConfig, buildIframeSrc } from '../config';

beforeEach(() => {
  document.body.innerHTML = '';
});

describe('config', () => {
  it('TC-071: parseScriptConfig parses all data-* attributes', () => {
    const script = document.createElement('script');
    script.setAttribute('data-domain', 'm-001');
    script.setAttribute('data-lang', 'en');
    script.setAttribute('data-theme-color', '#ff0000');
    script.setAttribute('data-position', 'bottom-left');
    const config = parseScriptConfig(script);
    expect(config).toMatchObject({
      domain: 'm-001',
      lang: 'en',
      theme: { color: '#ff0000', position: 'bottom-left' },
    });
  });

  it('TC-072: parseScriptConfig uses defaults when data-* omitted', () => {
    const script = document.createElement('script');
    script.setAttribute('data-domain', 'm-002');
    const config = parseScriptConfig(script);
    expect(config).toMatchObject({
      domain: 'm-002',
      lang: 'zh-CN',
      theme: { color: '#0ea5e9', position: 'bottom-right' },
    });
  });

  it('TC-073: parseScriptConfig returns null when domain missing', () => {
    const script = document.createElement('script');
    expect(parseScriptConfig(script)).toBeNull();
  });

  it('TC-074: buildIframeSrc includes domain, lang, embed=1', () => {
    const src = buildIframeSrc({ domain: 'm-003', lang: 'en', chatUrl: '/chat' });
    expect(src).toContain('domain=m-003');
    expect(src).toContain('lang=en');
    expect(src).toContain('embed=1');
  });
});
