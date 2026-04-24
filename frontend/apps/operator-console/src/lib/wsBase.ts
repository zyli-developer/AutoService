/**
 * Resolve the WebSocket base URL.
 *
 * Priority:
 *   1. VITE_WS_BASE env var (full URL, e.g. wss://ops.example.com)
 *   2. Same-origin derived from window.location.
 *
 * Mirrors customer-chat/src/App.tsx::resolveWsBase() so both apps behave
 * identically under subpath deployment (B scheme).
 */
export function resolveWsBase(): string {
  const envBase = (import.meta as unknown as { env?: Record<string, string | undefined> })
    .env?.VITE_WS_BASE;
  if (envBase) return envBase.replace(/\/$/, '');
  if (typeof window !== 'undefined' && window.location) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}`;
  }
  return 'ws://invalid.local';
}
