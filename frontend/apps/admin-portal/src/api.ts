/**
 * API client for admin-portal — calls backend REST endpoints.
 */
// Same-origin-relative by default. Override via VITE_API_BASE (e.g. to
// a dedicated api.* subdomain in a future subdomain-routed deployment).
const API_BASE: string = (import.meta as unknown as { env?: { VITE_API_BASE?: string } }).env?.VITE_API_BASE ?? '';

export async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  });
  if (!resp.ok) throw new Error(`API ${path}: ${resp.status}`);
  return resp.json();
}

export async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  return fetchJSON<T>(path, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function postForm<T>(path: string, formData: FormData): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    body: formData,
  });
  if (!resp.ok) throw new Error(`API ${path}: ${resp.status}`);
  return resp.json();
}
