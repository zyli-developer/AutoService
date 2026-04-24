// src/__tests__/tts-client.test.ts
import { describe, it, expect } from 'vitest';
import { parseTtsFrame } from '../voice/tts-client';

describe('parseTtsFrame', () => {
  it('parses done', () => {
    expect(parseTtsFrame('{"type":"done"}')).toEqual({ type: 'done' });
  });
  it('parses error', () => {
    expect(parseTtsFrame('{"type":"error","message":"x"}')).toEqual({ type: 'error', message: 'x' });
  });
  it('returns null for invalid', () => {
    expect(parseTtsFrame('{}')).toBeNull();
    expect(parseTtsFrame('bad')).toBeNull();
  });
});
