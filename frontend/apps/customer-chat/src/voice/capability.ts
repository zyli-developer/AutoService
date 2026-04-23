// src/voice/capability.ts
export type CapabilityReason = 'insecure_context' | 'no_get_user_media';

export interface CapabilityResult {
  supported: boolean;
  reason?: CapabilityReason;
}

export function checkVoiceCapability(): CapabilityResult {
  const secure = typeof isSecureContext !== 'undefined' ? isSecureContext : false;
  if (!secure) return { supported: false, reason: 'insecure_context' };
  if (!navigator?.mediaDevices?.getUserMedia) return { supported: false, reason: 'no_get_user_media' };
  return { supported: true };
}
