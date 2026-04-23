// src/__tests__/asr-client.test.ts
import { describe, it, expect } from 'vitest';
import { parseAsrFrame } from '../voice/asr-client';

describe('parseAsrFrame', () => {
  it('parses partial frame', () => {
    expect(parseAsrFrame('{"type":"partial","text":"hel"}')).toEqual({ type: 'partial', text: 'hel' });
  });
  it('parses final frame', () => {
    expect(parseAsrFrame('{"type":"final","text":"hello"}')).toEqual({ type: 'final', text: 'hello' });
  });
  it('parses speech_started frame', () => {
    expect(parseAsrFrame('{"type":"speech_started"}')).toEqual({ type: 'speech_started' });
  });
  it('parses error frame', () => {
    expect(parseAsrFrame('{"type":"error","message":"oops"}')).toEqual({ type: 'error', message: 'oops' });
  });
  it('returns null for invalid JSON', () => {
    expect(parseAsrFrame('not-json')).toBeNull();
  });
  it('returns null for unknown type', () => {
    expect(parseAsrFrame('{"type":"weird"}')).toBeNull();
  });
});
