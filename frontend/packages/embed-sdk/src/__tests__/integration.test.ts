import { describe, it, expect, beforeEach } from 'vitest';
import { init } from '../index';

beforeEach(() => {
  document.body.innerHTML = '';
});

describe('integration', () => {
  it('TC-081: init() creates button and iframe container', () => {
    init({ domain: 'm-001', chatUrl: '/chat' });
    expect(document.getElementById('as-embed-btn')).not.toBeNull();
    expect(document.getElementById('as-embed-container')).not.toBeNull();
  });

  it('TC-082: clicking button shows iframe', () => {
    init({ domain: 'm-001', chatUrl: '/chat' });
    const btn = document.getElementById('as-embed-btn')!;
    btn.click();
    const container = document.getElementById('as-embed-container')!;
    expect(container.style.display).not.toBe('none');
  });

  it('TC-083: clicking button again hides iframe (toggle)', () => {
    init({ domain: 'm-001', chatUrl: '/chat' });
    const btn = document.getElementById('as-embed-btn')!;
    btn.click(); // open
    btn.click(); // close
    const container = document.getElementById('as-embed-container')!;
    expect(container.style.display).toBe('none');
  });

  it('TC-084: postMessage as:close hides iframe', () => {
    init({ domain: 'm-001', chatUrl: '/chat' });
    const btn = document.getElementById('as-embed-btn')!;
    btn.click(); // open first
    window.dispatchEvent(
      new MessageEvent('message', { data: { type: 'as:close' } }),
    );
    const container = document.getElementById('as-embed-container')!;
    expect(container.style.display).toBe('none');
  });
});
