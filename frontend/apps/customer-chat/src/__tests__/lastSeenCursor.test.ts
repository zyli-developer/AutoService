import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { saveCursor, loadCursor, updateConvCursor } from '../utils/lastSeenCursor';

describe('lastSeenCursor', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it('TC-039: saveCursor / loadCursor round-trips correctly', () => {
    saveCursor({ conv_seq: { cv1: { msg: 5, evt: 12 } } });
    const got = loadCursor();
    expect(got?.conv_seq?.cv1?.msg).toBe(5);
    expect(got?.conv_seq?.cv1?.evt).toBe(12);
  });

  it('TC-040: loadCursor returns null when empty', () => {
    expect(loadCursor()).toBeNull();
  });

  it('TC-041: updateConvCursor advances monotonically (ignores rollback)', () => {
    let c = updateConvCursor({}, 'cv1', 'msg', 10);
    c = updateConvCursor(c, 'cv1', 'msg', 8);   // rollback — ignored
    c = updateConvCursor(c, 'cv1', 'msg', 15);  // advance
    expect(c.conv_seq?.cv1?.msg).toBe(15);
  });

  it('TC-042: updateConvCursor keeps different convIds independent', () => {
    let c = updateConvCursor({}, 'cv1', 'msg', 5);
    c = updateConvCursor(c, 'cv2', 'msg', 3);
    expect(c.conv_seq?.cv1?.msg).toBe(5);
    expect(c.conv_seq?.cv2?.msg).toBe(3);
  });

  it('TC-043: saveCursor does not throw when sessionStorage unavailable', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceeded');
    });
    expect(() => saveCursor({ conv_seq: { cv1: { msg: 1, evt: 1 } } })).not.toThrow();
  });
});
