import { describe, it, expect } from 'vitest';
import { buildVoiceIframeUrl, isVoiceMessage } from '../lib/voice-iframe';

describe('buildVoiceIframeUrl', () => {
  const BASE = 'https://voice.ezagent.chat/';

  it('TC-022-011: omits tenant_id / customer_id when not provided; always sets embed=1 + call_id', () => {
    const url = new URL(
      buildVoiceIframeUrl({ baseUrl: BASE, call_id: 'abc-123' }),
    );
    expect(url.searchParams.get('embed')).toBe('1');
    expect(url.searchParams.get('call_id')).toBe('abc-123');
    expect(url.searchParams.has('tenant_id')).toBe(false);
    expect(url.searchParams.has('customer_id')).toBe(false);
    expect(url.searchParams.has('systemRole')).toBe(false);
  });

  it('TC-022-011: includes all provided fields', () => {
    const url = new URL(
      buildVoiceIframeUrl({
        baseUrl: BASE,
        call_id: 'cid-1',
        tenant_id: 't1',
        customer_id: 'c1',
        mode: 'e2e',
        lang: 'zh-CN',
      }),
    );
    expect(url.searchParams.get('tenant_id')).toBe('t1');
    expect(url.searchParams.get('customer_id')).toBe('c1');
    expect(url.searchParams.get('mode')).toBe('e2e');
    expect(url.searchParams.get('lang')).toBe('zh-CN');
  });

  it('TC-022-011-b: non-ASCII greeting is URL-encoded and round-trips cleanly', () => {
    const greeting = '你好，请问有什么可以帮你？';
    const raw = buildVoiceIframeUrl({
      baseUrl: BASE,
      call_id: 'cid-2',
      greeting,
    });
    // Encoded form does not contain raw CJK bytes
    expect(raw).not.toContain(greeting);
    // But the URL parser decodes it back to the original string
    const parsed = new URL(raw);
    expect(parsed.searchParams.get('greeting')).toBe(greeting);
  });

  it('TC-022-011: empty-string options are treated as absent', () => {
    const url = new URL(
      buildVoiceIframeUrl({
        baseUrl: BASE,
        call_id: 'cid-3',
        tenant_id: '',
        greeting: '',
      }),
    );
    expect(url.searchParams.has('tenant_id')).toBe(false);
    expect(url.searchParams.has('greeting')).toBe(false);
  });
});

describe('isVoiceMessage', () => {
  it('accepts known voice message types', () => {
    expect(isVoiceMessage({ type: 'as:voice:ready' })).toBe(true);
    expect(isVoiceMessage({ type: 'as:voice:state', state: 'greeting' })).toBe(true);
    expect(isVoiceMessage({ type: 'as:voice:error', code: 'X', message: 'Y' })).toBe(true);
    expect(isVoiceMessage({ type: 'as:voice:close' })).toBe(true);
  });

  it('rejects unrelated messages', () => {
    expect(isVoiceMessage(null)).toBe(false);
    expect(isVoiceMessage(undefined)).toBe(false);
    expect(isVoiceMessage('as:voice:ready')).toBe(false);
    expect(isVoiceMessage({})).toBe(false);
    expect(isVoiceMessage({ type: 'random' })).toBe(false);
    expect(isVoiceMessage({ type: 'as:chat:open' })).toBe(false);
  });
});
