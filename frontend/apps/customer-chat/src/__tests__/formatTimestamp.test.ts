import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { formatTimestamp } from '../utils/formatTimestamp';

describe('formatTimestamp', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('TC-001: timestamp from today returns HH:MM', () => {
    // Fix "now" to 2026-04-16T15:00:00 local
    vi.setSystemTime(new Date('2026-04-16T15:00:00Z'));
    // A timestamp earlier today (in UTC which is same date for this test)
    const result = formatTimestamp('2026-04-16T14:32:00Z');
    // Should return just time portion
    expect(result).toMatch(/^\d{2}:\d{2}$/);
  });

  it('TC-002: timestamp from yesterday returns 昨天 HH:MM', () => {
    // Fix "now" to noon on 2026-04-16
    vi.setSystemTime(new Date('2026-04-16T12:00:00Z'));
    // Use a local-date-safe approach: create date at local midnight yesterday
    // We test with a UTC timestamp that lands on 2026-04-15 in local time
    // Since jsdom runs in UTC, 2026-04-15T09:15:00Z is yesterday
    const result = formatTimestamp('2026-04-15T09:15:00Z');
    expect(result).toMatch(/^昨天 \d{2}:\d{2}$/);
  });

  it('TC-003: timestamp from older date returns M/D HH:MM', () => {
    vi.setSystemTime(new Date('2026-04-16T12:00:00Z'));
    // 2026-04-10 is neither today nor yesterday
    const result = formatTimestamp('2026-04-10T08:00:00Z');
    expect(result).toMatch(/^\d+\/\d+ \d{2}:\d{2}$/);
    expect(result).toContain('4/10');
  });

  it('TC-004: empty string returns empty string', () => {
    vi.setSystemTime(new Date('2026-04-16T12:00:00Z'));
    const result = formatTimestamp('');
    expect(result).toBe('');
  });

  it('TC-005: invalid date string returns empty string', () => {
    vi.setSystemTime(new Date('2026-04-16T12:00:00Z'));
    const result = formatTimestamp('not-a-date');
    expect(result).toBe('');
  });
});
