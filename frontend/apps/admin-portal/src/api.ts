/**
 * API client for admin-portal — calls backend REST endpoints.
 */
const API_BASE = `http://${window.location.hostname}:8000`;

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
