import { describe, it, expect, beforeEach, vi } from 'vitest';
import { resolveWsBase } from '../lib/wsBase';

describe('resolveWsBase', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns wss:// when page is https', () => {
    vi.stubGlobal('window', { location: { protocol: 'https:', host: 'autoservice.ezagent.chat' } });
    expect(resolveWsBase()).toBe('wss://autoservice.ezagent.chat');
  });

  it('returns ws:// when page is http', () => {
    vi.stubGlobal('window', { location: { protocol: 'http:', host: 'localhost:5174' } });
    expect(resolveWsBase()).toBe('ws://localhost:5174');
  });

  it('WorkspacePage does not hardcode :8000', async () => {
    const src = await import('fs').then(fs =>
      fs.readFileSync(
        new URL('../components/WorkspacePage.tsx', import.meta.url).pathname,
        'utf8'
      )
    );
    expect(src).not.toMatch(/localhost:8000/);
    expect(src).not.toMatch(/:8000/);
  });
});
