import { describe, it, expect, beforeEach } from 'vitest';
import { createIframe, showIframe, hideIframe } from '../iframe';

beforeEach(() => {
  document.body.innerHTML = '';
});

describe('iframe', () => {
  it('TC-078: createIframe appends container and is initially hidden', () => {
    createIframe({ domain: 'm-001', chatUrl: '/chat', lang: 'zh-CN' });
    const container = document.getElementById('as-embed-container');
    expect(container).not.toBeNull();
    expect(container!.style.display).toBe('none');
  });

  it('TC-079: showIframe / hideIframe toggles display', () => {
    const container = createIframe({ domain: 'm-001', chatUrl: '/chat' });
    showIframe(container);
    expect(container.style.display).not.toBe('none');
    hideIframe(container);
    expect(container.style.display).toBe('none');
  });

  it('TC-080: iframe src contains correct URL params', () => {
    const container = createIframe({
      domain: 'm-abc',
      chatUrl: 'https://chat.example.com',
      lang: 'en',
    });
    const iframe = container.querySelector('iframe')!;
    expect(iframe.src).toContain('domain=m-abc');
    expect(iframe.src).toContain('lang=en');
    expect(iframe.src).toContain('embed=1');
  });
});
