# Dev Auto-Login — Design Spec

**Date:** 2026-04-21
**Status:** Draft (awaiting review)
**Owner:** dev-a
**Related:** `docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md` §5 (magic-link auth)

## 1 · Problem

The current admin login flow is magic-link only:

1. Admin enters email on `/admin` → POST `/api/auth/request-login`
2. Backend issues a 10-min token; in dev it's written to `.autoservice/logs/auth-devmail.jsonl`
3. Admin tails the JSONL, copies the link, opens in browser, hits `/api/auth/verify`
4. Session cookie set → redirected to admin UI

For daily development and testing this is friction-heavy:

- Every login requires tail + copy-paste
- 10-min TTL means tokens expire mid-session, re-loop
- Switching between `_master` / `_local_admin` / tier-1 tenants multiplies the cost
- Reset DB / new browser / Incognito → full loop again

Goal: **one-click dev login** that mints a session directly, bypassing the token
flow, scoped to any persona + tenant we want to test. The magic-link path stays
untouched as the production code path.

## 2 · Non-goals

- Does **not** replace magic-link flow — that remains the only production path.
- Does **not** change session semantics (same `sessions` table, same 30-day TTL,
  same cookie name `auth_session`).
- Does **not** add multi-session or "switch user" UI — logout + re-login is fine.
- Does **not** ship in production images — `AUTH_DEV_MODE` env gate is off by
  default; production deployments must never set it.

## 3 · Architecture

### 3.1 Gate: `AUTH_DEV_MODE` environment variable

A single boolean env var controls both new endpoints:

- Read once at module import: `DEV_MODE_ENABLED = os.environ.get("AUTH_DEV_MODE") == "1"`
- Production images do not set this variable; both endpoints behave as if absent.
- `make run-web` adds `AUTH_DEV_MODE=1` to its invocation. `make run-channel`
  (Feishu MCP) does not serve the admin portal and is left unchanged.

Rationale: env-only gate is simpler than localhost-sniffing (which breaks inside
containers or ssh tunnels) and auditable — "did we set it?" is a shell question,
not a runtime-check question. Chosen over `localhost`-detection and combined
`env + localhost` variants during brainstorming.

### 3.2 Endpoints (additions to `autoservice/api_routes.py`)

#### `GET /api/auth/dev-mode`

Public, unauthenticated. Used by the frontend to decide whether to render the
dev-login panel and to populate its dropdowns.

- When `DEV_MODE_ENABLED` is false → `200 {"enabled": false}`. No other fields.
- When true:
  ```json
  {
    "enabled": true,
    "personas": ["admin@dev.local", "master@dev.local", ...],
    "tenants":  ["_master", "_local_admin", "acme", ...]
  }
  ```
- `personas` comes from `config.local.yaml auth.dev.personas`; falls back to
  `["admin@dev.local"]` if missing.
- `tenants` is assembled by:
  1. Starting with `["_master"]` (the tier-0 built-in, not a plugin directory).
  2. Scanning `plugins/*/plugin.yaml` and extracting each plugin's `tenant_id`
     (or the directory name if absent).
  3. Filtering out `_example` unless `auth.dev.tenant_include_examples: true`.
- The response does **not** include `"tier-0 / None"` — the frontend adds that
  as a literal dropdown option (it's UI state, not a tenant).

#### `POST /api/auth/dev-login`

Dev-only session minter. Bypasses `login_tokens` entirely.

- When `DEV_MODE_ENABLED` is false → **`404 Not Found`** (deliberately not 403, to
  avoid revealing the endpoint's existence in production).
- Request body: `{"email": str (required), "tenant_id": str | null}`
  - Empty-string `tenant_id` is treated as `null` (tier-0).
- Handler logic:
  1. Validate `email` is non-empty; otherwise 400.
  2. Open the auth DB via `api_routes._get_auth_db()`.
  3. Call `auth.create_session(conn, email, tenant_id)` — no changes to `auth.py`.
  4. Set the `auth_session` cookie with the same attributes the magic-link flow
     uses (HttpOnly, SameSite=Lax, Secure based on request scheme, Path=/,
     Max-Age tied to session TTL).
  5. Log `WARNING [dev-login] minted session for %s tenant=%s sid=%s…`
     (session id prefix only — never log the full id).
  6. Append one JSONL line to `.autoservice/logs/auth-devmail.jsonl`:
     `{"kind": "dev_login", "ts": "...", "email": "...", "tenant_id": "...",
     "session_id_prefix": "abc12345"}`
  7. Respond `200 {"ok": true, "redirect": "/admin" | "/t/{tid}/admin"}`.
- The frontend navigates using the `redirect` field rather than computing it,
  so a future change to the post-login landing page is a single-site edit.

### 3.3 Session reuse

The endpoint deliberately calls the **same** `auth.create_session` the
magic-link verify path uses. Implications:

- Dev-minted sessions are indistinguishable from real ones at the DB level —
  middleware, tier enforcement, logout, expiry all work unchanged.
- Turning off `AUTH_DEV_MODE` after the fact does **not** revoke already-minted
  sessions. This is accepted (dev data is disposable; for paranoia, delete
  `.autoservice/database/auth.db`).

## 4 · Config schema

Additions to `.autoservice/config.local.yaml` (gitignored):

```yaml
auth:
  smtp: { ... }                 # existing
  dev:                          # new, all optional
    personas:
      - admin@dev.local
      - master@dev.local
    tenant_include_examples: false
```

All fields optional. Server reads via the existing config-loader helper (same
used for `auth.smtp`); missing keys yield the defaults described in §3.2.

## 5 · Frontend (`LoginPage.tsx`)

### 5.1 Probe

On mount, fetch `GET /api/auth/dev-mode`. Treat any non-200 or `{enabled:false}`
response as "dev mode off, do nothing extra" — the existing magic-link form
remains the sole UI.

### 5.2 Dev panel layout

When enabled, render a second section **below** the magic-link form, separated
by a labeled horizontal rule ("Developer"):

```
Persona email    [combobox: datalist from personas + localStorage history]
Tenant scope     [select: None (tier-0 master) / _master / _local_admin / … / Custom…]
                 [text input — visible only when "Custom…" is selected]
[ Dev login → ]
```

- Combobox = `<input list="...">` + `<datalist>`. No third-party lib.
- Datalist options = server `personas` ∪ localStorage `autoservice.dev.recentPersonas`
  (dedup, most-recent-first; cap at 5 stored).
- Tenant `<select>` options, in order:
  1. `None (tier-0 master)` — value `""` → sent as `tenant_id: null`
  2. Each tenant from `/dev-mode` `tenants`
  3. `Custom…` — value `__custom__` → reveals the text input; its value is sent
     as `tenant_id`.

### 5.3 Submit

On click:

1. POST `/api/auth/dev-login` with `{email, tenant_id}` (credentials: include).
2. On 200 → push email to localStorage (front of list, dedup, cap 5); then
   `window.location.assign(response.redirect)`.
3. On 404 → show inline error: `"Dev mode is off on the server. Set
   AUTH_DEV_MODE=1 and restart."`
4. On any other non-2xx → show the HTTP status in an error banner.

### 5.4 Test-id hooks

Add data-testid attributes so the existing Vitest suite can target the panel:

- `dev-login-panel` (wrapper, present only when enabled)
- `dev-login-email`
- `dev-login-tenant-select`
- `dev-login-tenant-custom`
- `dev-login-submit`
- `dev-login-error`

## 6 · Security considerations

- `AUTH_DEV_MODE` must never be set in production builds. Enforced by:
  - Dockerfile / compose files for prod do not set it.
  - Makefile's `run-web` sets it explicitly (dev-only target).
  - `CLAUDE.md` gains a short warning paragraph cross-linking this spec.
- `GET /dev-mode` returns `{enabled: false}` when off — no `personas`, no
  `tenants` leaked.
- `POST /dev-login` returns **404** when off (not 403) — matches the principle
  of not advertising dev endpoints' existence.
- Every dev-login call emits a `WARNING` log **and** a JSONL audit line so
  operators who accidentally run with the flag on in a shared environment can
  see it in the logs.
- Session id is only logged by **prefix** (first 8 chars), never in full.
- The endpoint has no rate limit. Justification: local dev only; production
  returns 404 so there's nothing to rate-limit.

## 7 · Testing

### 7.1 Backend unit — `tests/auth/test_dev_login.py` (new)

| Case | Assertion |
|------|-----------|
| `AUTH_DEV_MODE` unset + POST `/dev-login` | 404, no DB write |
| `AUTH_DEV_MODE` unset + GET `/dev-mode` | 200 `{enabled:false}`, no other keys |
| Env on + POST with valid email | 200, `auth_session` cookie set, `sessions` row exists |
| Env on + empty tenant_id | session row has `tenant_id IS NULL` (tier-0) |
| Env on + specific tenant_id | session row has matching `tenant_id` |
| Env on + empty email | 400 |
| `/dev-mode` personas fallback | when yaml missing, returns `["admin@dev.local"]` |
| `/dev-mode` tenant scan | includes `_master` + scanned plugin tenants; excludes `_example` by default |
| JSONL audit line written on dev-login | file contains one `{"kind":"dev_login",...}` row |

Env toggling in tests: `monkeypatch.setenv("AUTH_DEV_MODE", ...)` combined with
an `importlib.reload(api_routes)` (or an explicit `_refresh_dev_mode_flag()`
helper if reload proves ugly). Module-level env read stays — tests adapt.

### 7.2 Frontend unit — `AuthLoginPage.test.tsx` (extend)

| Case | Assertion |
|------|-----------|
| `/dev-mode` returns `{enabled:false}` | `dev-login-panel` not in DOM |
| `/dev-mode` returns enabled + personas + tenants | panel renders, email datalist + tenant select populated |
| Select "Custom…" | `dev-login-tenant-custom` becomes visible |
| Click "Dev login" with valid inputs | POST called with correct body; `window.location.assign` spy receives `response.redirect` |
| POST returns 404 | error banner shows env-off hint |
| Successful login | localStorage `autoservice.dev.recentPersonas` updated |

### 7.3 E2E

No new e2e case. Existing magic-link e2e remains, asserting the production
path is untouched.

## 8 · File inventory

| File | Change |
|------|--------|
| `autoservice/api_routes.py` | +2 endpoints, +plugin-scan helper, +JSONL audit helper (or reuse existing) |
| `autoservice/auth.py` | No changes |
| `frontend/apps/admin-portal/src/components/auth/LoginPage.tsx` | +dev panel, +probe fetch, +localStorage handling |
| `Makefile` | `run-web` target sets `AUTH_DEV_MODE=1` |
| `tests/auth/test_dev_login.py` | New |
| `frontend/apps/admin-portal/src/__tests__/AuthLoginPage.test.tsx` | +dev-mode cases |
| `CLAUDE.md` | +one-paragraph warning on `AUTH_DEV_MODE` |
| `docs/superpowers/specs/2026-04-21-dev-auto-login-design.md` | This file |

## 9 · YAGNI — explicitly not doing

- Persisting "last used persona" on the server — localStorage suffices.
- Rate-limiting `/dev-login` — dev-only endpoint, 404 in prod.
- A "switch identity" button in the admin header — logout + re-login is fine.
- Custom TTL for dev-minted sessions — reuse the 30-day default.
- A `DELETE /api/auth/dev-sessions` bulk-revoke — `rm
  .autoservice/database/auth.db` is the escape hatch.

## 10 · Open questions

None at time of writing. All three brainstorming decisions (env gate, persona
source, tenant source) are locked in §3.1, §4, §3.2 respectively.
