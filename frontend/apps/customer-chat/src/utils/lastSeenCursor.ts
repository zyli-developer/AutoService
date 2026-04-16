import type { LastSeenCursor } from '@autoservice/ws-client';

const STORAGE_KEY = 'as_last_seen';

export function saveCursor(cursor: LastSeenCursor): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(cursor));
  } catch {
    // QuotaExceededError or SecurityError in private mode — ignore
  }
}

export function loadCursor(): LastSeenCursor | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as LastSeenCursor) : null;
  } catch {
    return null;
  }
}

export function updateConvCursor(
  cursor: LastSeenCursor,
  convId: string,
  field: 'msg' | 'evt',
  seq: number,
): LastSeenCursor {
  const prev = cursor.conv_seq?.[convId]?.[field] ?? 0;
  if (seq <= prev) return cursor;  // monotonic only
  return {
    ...cursor,
    conv_seq: {
      ...cursor.conv_seq,
      [convId]: {
        ...(cursor.conv_seq?.[convId] ?? { msg: 0, evt: 0 }),
        [field]: seq,
      },
    },
  };
}
