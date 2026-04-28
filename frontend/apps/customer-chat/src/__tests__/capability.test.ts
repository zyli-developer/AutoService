// src/__tests__/capability.test.ts
import { describe, it, expect, vi } from 'vitest';
import { checkVoiceCapability } from '../voice/capability';

describe('checkVoiceCapability', () => {
  it('returns supported=false when not secure context', () => {
    vi.stubGlobal('isSecureContext', false);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn() } });
    const result = checkVoiceCapability();
    expect(result.supported).toBe(false);
    expect(result.reason).toBe('insecure_context');
  });

  it('returns supported=false when getUserMedia missing', () => {
    vi.stubGlobal('isSecureContext', true);
    vi.stubGlobal('navigator', { mediaDevices: undefined });
    const result = checkVoiceCapability();
    expect(result.supported).toBe(false);
    expect(result.reason).toBe('no_get_user_media');
  });

  it('returns supported=true when secure + mediaDevices present', () => {
    vi.stubGlobal('isSecureContext', true);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn() } });
    const result = checkVoiceCapability();
    expect(result.supported).toBe(true);
    expect(result.reason).toBeUndefined();
  });
});
