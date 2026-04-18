import { describe, it, expect } from 'vitest';
import type { BeToFeType } from '../types';

describe('takeover frame types', () => {
  it('BeToFeType includes takeover_warning', () => {
    const t: BeToFeType = 'takeover_warning';
    expect(t).toBe('takeover_warning');
  });
  it('BeToFeType includes takeover_warning_cancelled', () => {
    const t: BeToFeType = 'takeover_warning_cancelled';
    expect(t).toBe('takeover_warning_cancelled');
  });
});
