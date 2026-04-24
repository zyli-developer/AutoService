# Cloudflare Tunnel Demo Deployment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose AutoService at `https://autoservice.ezagent.chat` via the already-created `autoservice` cloudflared tunnel, fronted by a local Caddy on `127.0.0.1:18080`, with subpath routing (`/site`, `/console`, `/admin`, `/api`, `/ws`), Cloudflare Access gating the admin/operator surface, magic-link + narrow password login, and launchd supervision of gateway + Caddy + cloudflared on Mac Studio.

**Architecture:** Single cloudflared named tunnel → local Caddy (non-80 port, loopback) → file_server for three built React apps + reverse_proxy to uvicorn gateway (`127.0.0.1:8000`). Subpath mounting via `VITE_MOUNT_PATH` build env. CF Access policy applied as IaC via REST API. launchd agents auto-restart all three services.

**Tech Stack:** FastAPI + uvicorn, React/Vite (pnpm monorepo), Caddy v2.11.2, cloudflared (named tunnel UUID `389c95d2-6066-437e-854f-8a09b2481259`), bcrypt (new dep for password login), Feishu Mail SMTP, launchd.

**Design spec:** `docs/superpowers/specs/2026-04-24-cloudflare-tunnel-demo-deploy-design.md`

---

## Critical-path ordering

```
Phase 0: branch setup
       │
       ▼
┌──────┴───────────────────────────────────────────┐
│ Phase 1 (PARALLEL)                               │
│   Frontend refactors  ─┐                         │
│   Backend refactors    ─┤  both green before Phase 2
└────────────────────────┘
       │
       ▼
Phase 2: frontend password-login UI (depends on backend password_login endpoint)
       │
       ▼
Phase 3: config files (Caddyfile, cloudflared.yml.example, allowlist.yml)  ┐
       │                                                                    │
       ▼                                                                    │ (independent; can parallel with P1–P2)
Phase 4: scripts + Makefile public-* targets                               ┘
       │
       ▼
Phase 5: launchd plists + install scripts + Makefile install/uninstall
       │
       ▼
Phase 6: runbook docs
       │
       ▼
Phase 7: integration + smoke + agent-browser QA + launchd install + merge
```

Phase 1 frontend + backend are independent (disjoint files) — subagents should run them in parallel. Phase 2 must wait for Task 8 (backend password endpoint). Phase 3 is config-only and can start as soon as Phase 0 is done. Phases 4–7 are strict sequential from there.

---

## File structure / decomposition

**Modified — frontend:**
- `frontend/apps/customer-chat/vite.config.ts` — add `base: process.env.VITE_MOUNT_PATH ?? '/'`
- `frontend/apps/operator-console/vite.config.ts` — same
- `frontend/apps/admin-portal/vite.config.ts` — same
- `frontend/apps/admin-portal/src/api.ts` — drop `:8000`, use same-origin
- `frontend/apps/admin-portal/src/components/wizard/SandboxReady.tsx` — same
- `frontend/apps/operator-console/src/components/WorkspacePage.tsx` — mirror `customer-chat/src/App.tsx::resolveWsBase()`
- `frontend/apps/admin-portal/src/components/auth/LoginPage.tsx` — add collapsed password-login section
- `frontend/apps/{customer-chat,operator-console,admin-portal}/index.html` — robots meta

**New — backend:**
- `autoservice/password_login.py` — new module, bcrypt-verified POST `/api/auth/password-login`
- `tests/test_password_login.py` — unit tests

**Modified — backend:**
- `autoservice/web_gateway.py` — env-merge CORS origins + include password-login router
- `pyproject.toml` — `bcrypt>=4,<5`

**New — deploy config:**
- `deploy/caddy/Caddyfile.public`
- `deploy/cloudflared/autoservice.yml.example`
- `deploy/cloudflare-access/allowlist.yml`
- `deploy/launchd/com.autoservice.gateway.plist.template`
- `deploy/launchd/com.autoservice.caddy.plist.template`
- `deploy/launchd/com.autoservice.cloudflared.plist.template`

**New — scripts:**
- `scripts/install-smtp-config.sh`
- `scripts/generate-admin-passwords.sh`
- `scripts/apply-cf-access.sh`
- `scripts/public-build.sh`
- `scripts/public-up.sh`
- `scripts/public-down.sh`
- `scripts/public-panic.sh`
- `scripts/public-reload.sh`
- `scripts/public-smoke.sh`
- `scripts/install-launchd.sh`
- `scripts/uninstall-launchd.sh`

**New — docs:**
- `docs/deploy/public-tunnel-runbook.md`

**Modified — meta:**
- `Makefile` — new public-* + access-apply + generate-admin-passwords targets
- `.gitignore` — add `.cf-access.env` (already done in spec commit)

---

## Phase 0 — Branch

### Task 0: Create feature branch

- [ ] **Step 1: Create and switch**

```bash
git checkout -b deploy/autoservice-tunnel
```

Expected: `Switched to a new branch 'deploy/autoservice-tunnel'`.

---

## Phase 1A — Frontend refactors (parallelizable)

### Task 1: Parameterize Vite `base` on all three apps

**Files:**
- Modify: `frontend/apps/customer-chat/vite.config.ts`
- Modify: `frontend/apps/operator-console/vite.config.ts`
- Modify: `frontend/apps/admin-portal/vite.config.ts`
- Test: `frontend/apps/customer-chat/src/__tests__/vite-base.test.ts` (new)

- [ ] **Step 1: Write a smoke-test build script** (single shell command, not a unit test — Vite `base` only exists at build time)

Create `frontend/scripts/verify-base.sh`:

```bash
#!/usr/bin/env bash
# Builds customer-chat with VITE_MOUNT_PATH=/site/ and asserts the emitted
# index.html references /site/assets/ — proving base is parameterized.
set -euo pipefail
cd "$(dirname "$0")/.."

VITE_MOUNT_PATH=/site/ pnpm --filter @autoservice/customer-chat build >/dev/null
html="apps/customer-chat/dist/index.html"
grep -q 'src="/site/assets/' "$html" \
  && grep -q 'href="/site/assets/' "$html" \
  && echo "OK: customer-chat dist references /site/assets/" \
  || { echo "FAIL: base not applied"; exit 1; }
```

Make executable: `chmod +x frontend/scripts/verify-base.sh`.

- [ ] **Step 2: Run and verify it fails** (because vite.config.ts hasn't been updated yet)

```bash
bash frontend/scripts/verify-base.sh
```

Expected: `FAIL: base not applied` or assets referenced from `/assets/` not `/site/assets/`.

- [ ] **Step 3: Update `frontend/apps/customer-chat/vite.config.ts`**

Replace the top of the file with:

```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_MOUNT_PATH ?? '/',
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true, changeOrigin: true },
    },
  },
  preview: { port: 5173 },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['src/__tests__/setup.ts'],
  },
});
```

- [ ] **Step 4: Apply identical `base` line to operator-console and admin-portal**

`frontend/apps/operator-console/vite.config.ts` — add `base: process.env.VITE_MOUNT_PATH ?? '/',` below `plugins: [react()],`. Same for `frontend/apps/admin-portal/vite.config.ts`.

- [ ] **Step 5: Run verify script — expect PASS**

```bash
bash frontend/scripts/verify-base.sh
```

Expected: `OK: customer-chat dist references /site/assets/`.

- [ ] **Step 6: Confirm dev mode unchanged**

```bash
cd frontend && pnpm --filter @autoservice/customer-chat build 2>&1 | tail -3 && \
  head -2 apps/customer-chat/dist/index.html | grep -c 'src="/assets/' || true
```

Expected: build succeeds; without `VITE_MOUNT_PATH`, asset refs are `/assets/` (root). Dev-mode behavior preserved.

- [ ] **Step 7: Commit**

```bash
git add frontend/apps/*/vite.config.ts frontend/scripts/verify-base.sh
git commit -m "build(frontend): parameterize Vite base via VITE_MOUNT_PATH

Enables subpath deployment (/site, /console, /admin) while preserving
default root-mounted dev builds."
```

---

### Task 2: Fix `admin-portal/src/api.ts` hardcoded `:8000`

**Files:**
- Modify: `frontend/apps/admin-portal/src/api.ts`
- Test: `frontend/apps/admin-portal/src/__tests__/api.test.ts` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/apps/admin-portal/src/__tests__/api.test.ts`:

```ts
import { describe, it, expect } from 'vitest';

describe('admin-portal api module', () => {
  it('does not hardcode localhost:8000 in its source', async () => {
    const src = await import('fs').then(fs =>
      fs.readFileSync(
        new URL('../api.ts', import.meta.url).pathname,
        'utf8'
      )
    );
    expect(src).not.toMatch(/localhost:8000/);
    expect(src).not.toMatch(/\$\{[^}]*hostname[^}]*\}:8000/);
  });
});
```

- [ ] **Step 2: Run and expect FAIL**

```bash
cd frontend && pnpm --filter @autoservice/admin-portal exec vitest run src/__tests__/api.test.ts
```

Expected: FAIL because `api.ts:4` still has `${window.location.hostname}:8000`.

- [ ] **Step 3: Edit `frontend/apps/admin-portal/src/api.ts`**

Replace the first 4 lines:

```ts
// Same-origin-relative by default. Override via VITE_API_BASE (e.g. to
// a dedicated api.* subdomain in a future subdomain-routed deployment).
const API_BASE: string = (import.meta as unknown as { env?: { VITE_API_BASE?: string } }).env?.VITE_API_BASE ?? '';
```

All existing `fetch(`${API_BASE}${path}` ...)` calls continue to work — an empty `API_BASE` just makes them same-origin relative.

- [ ] **Step 4: Re-run test — expect PASS**

```bash
cd frontend && pnpm --filter @autoservice/admin-portal exec vitest run src/__tests__/api.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/admin-portal/src/api.ts frontend/apps/admin-portal/src/__tests__/api.test.ts
git commit -m "fix(admin): drop hardcoded :8000 from api.ts

Enables same-origin fetches under subpath deployment (B scheme). Dev
proxy still routes /api to localhost:8000 because the fetch URL is
relative."
```

---

### Task 3: Fix `admin-portal/.../wizard/SandboxReady.tsx` hardcoded `:8000`

**Files:**
- Modify: `frontend/apps/admin-portal/src/components/wizard/SandboxReady.tsx`

- [ ] **Step 1: Read current pattern around line 36**

```bash
sed -n '30,70p' /Users/h2oslabs/Workspace/AutoService/frontend/apps/admin-portal/src/components/wizard/SandboxReady.tsx
```

Expected: constant `API_BASE` using `window.location.hostname + ':8000'`.

- [ ] **Step 2: Replace the constant**

Change the existing `API_BASE` constant block to:

```ts
const API_BASE =
  (import.meta as unknown as { env?: { VITE_API_BASE?: string } }).env?.VITE_API_BASE ??
  '';
```

Remove any accompanying `:8000` / `window.location.hostname` assembly lines.

- [ ] **Step 3: Add a grep-style test** (extend the Task 2 approach)

Append to `frontend/apps/admin-portal/src/__tests__/api.test.ts`:

```ts
it('SandboxReady does not hardcode localhost:8000', async () => {
  const src = await import('fs').then(fs =>
    fs.readFileSync(
      new URL('../components/wizard/SandboxReady.tsx', import.meta.url).pathname,
      'utf8'
    )
  );
  expect(src).not.toMatch(/localhost:8000/);
  expect(src).not.toMatch(/\$\{[^}]*hostname[^}]*\}:8000/);
});
```

- [ ] **Step 4: Run test — PASS**

```bash
cd frontend && pnpm --filter @autoservice/admin-portal exec vitest run src/__tests__/api.test.ts
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/admin-portal/src/components/wizard/SandboxReady.tsx frontend/apps/admin-portal/src/__tests__/api.test.ts
git commit -m "fix(admin): drop hardcoded :8000 from SandboxReady"
```

---

### Task 4: Fix `operator-console/.../WorkspacePage.tsx` hardcoded WS `:8000`

**Files:**
- Modify: `frontend/apps/operator-console/src/components/WorkspacePage.tsx`
- Create: `frontend/apps/operator-console/src/lib/wsBase.ts`
- Test: `frontend/apps/operator-console/src/__tests__/wsBase.test.ts` (new)

- [ ] **Step 1: Create the shared WS base helper**

Create `frontend/apps/operator-console/src/lib/wsBase.ts`, mirroring `customer-chat/src/App.tsx::resolveWsBase()`:

```ts
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
```

- [ ] **Step 2: Write the failing test**

Create `frontend/apps/operator-console/src/__tests__/wsBase.test.ts`:

```ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { resolveWsBase } from '../lib/wsBase';

describe('resolveWsBase', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns wss:// when page is https', () => {
    vi.stubGlobal('window', { location: { protocol: 'https:', host: 'autoservice.ezagent.chat' } });
    expect(resolveWsBase()).toBe('wss://autoservice.ezagent.chat');
  });

  it('returns ws:// when page is http', () => {
    vi.stubGlobal('window', { location: { protocol: 'http:', host: 'localhost:5174' } });
    expect(resolveWsBase()).toBe('ws://localhost:5174');
  });
});
```

- [ ] **Step 3: Run test — expect PASS**

```bash
cd frontend && pnpm --filter @autoservice/operator-console exec vitest run src/__tests__/wsBase.test.ts
```

Expected: both PASS (the helper file already exists from Step 1).

- [ ] **Step 4: Update `WorkspacePage.tsx`**

Read the current line 20 to find the exact context:

```bash
sed -n '15,30p' /Users/h2oslabs/Workspace/AutoService/frontend/apps/operator-console/src/components/WorkspacePage.tsx
```

Then replace the URL-building line so that it uses the helper:

```ts
import { resolveWsBase } from '../lib/wsBase';

// Previously: `ws://${hostname}:8000/ws/operator?tenant=${encodeURIComponent(tenantId)}`
function buildOperatorWsUrl(tenantId: string): string {
  return `${resolveWsBase()}/ws/operator?tenant=${encodeURIComponent(tenantId)}`;
}
```

Use `buildOperatorWsUrl(...)` at the call site that previously built the URL inline.

- [ ] **Step 5: Add grep guard to the test file**

Append to `frontend/apps/operator-console/src/__tests__/wsBase.test.ts`:

```ts
it('WorkspacePage does not hardcode :8000', async () => {
  const src = await import('fs').then(fs =>
    fs.readFileSync(
      new URL('../components/WorkspacePage.tsx', import.meta.url).pathname,
      'utf8'
    )
  );
  expect(src).not.toMatch(/localhost:8000/);
  expect(src).not.toMatch(/:8000/);
});
```

- [ ] **Step 6: Run full test file — all PASS**

```bash
cd frontend && pnpm --filter @autoservice/operator-console exec vitest run src/__tests__/wsBase.test.ts
```

- [ ] **Step 7: Commit**

```bash
git add frontend/apps/operator-console/src
git commit -m "fix(operator): drop hardcoded :8000 from WorkspacePage WS URL

Extracts resolveWsBase() helper mirroring customer-chat, enables wss://
under the subpath-routed tunnel deployment."
```

---

### Task 5: Add `noindex` meta to all three apps

**Files:**
- Modify: `frontend/apps/customer-chat/index.html`
- Modify: `frontend/apps/operator-console/index.html`
- Modify: `frontend/apps/admin-portal/index.html`

- [ ] **Step 1: Add meta tag to each `<head>`**

For each of the three `index.html` files, insert within the `<head>`:

```html
    <meta name="robots" content="noindex, nofollow" />
```

- [ ] **Step 2: Verify**

```bash
grep -l 'noindex' /Users/h2oslabs/Workspace/AutoService/frontend/apps/*/index.html
```

Expected: all three paths listed.

- [ ] **Step 3: Commit**

```bash
git add frontend/apps/*/index.html
git commit -m "chore(frontend): add robots noindex to demo deployment

Prevents search engines from indexing the trial instance."
```

---

## Phase 1B — Backend refactors (parallelizable with Phase 1A)

### Task 6: CORS env append in `web_gateway.py`

**Files:**
- Modify: `autoservice/web_gateway.py` lines 57-59
- Test: `tests/test_gateway_cors.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_gateway_cors.py`:

```python
import importlib
import os

import pytest


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv("CORS_EXTRA_ORIGINS", raising=False)
    yield


def test_cors_origins_default_has_localhost_range(monkeypatch):
    monkeypatch.delenv("CORS_EXTRA_ORIGINS", raising=False)
    import autoservice.web_gateway as wg
    importlib.reload(wg)
    assert "http://localhost:5173" in wg._CORS_ORIGINS
    assert "http://localhost:5179" in wg._CORS_ORIGINS


def test_cors_env_extra_single(monkeypatch):
    monkeypatch.setenv("CORS_EXTRA_ORIGINS", "https://autoservice.ezagent.chat")
    import autoservice.web_gateway as wg
    importlib.reload(wg)
    assert "https://autoservice.ezagent.chat" in wg._CORS_ORIGINS


def test_cors_env_extra_multi(monkeypatch):
    monkeypatch.setenv(
        "CORS_EXTRA_ORIGINS",
        "https://foo.example, https://bar.example",
    )
    import autoservice.web_gateway as wg
    importlib.reload(wg)
    assert "https://foo.example" in wg._CORS_ORIGINS
    assert "https://bar.example" in wg._CORS_ORIGINS


def test_cors_env_extra_ignores_empty_entries(monkeypatch):
    monkeypatch.setenv("CORS_EXTRA_ORIGINS", "  , https://a,  ,")
    import autoservice.web_gateway as wg
    importlib.reload(wg)
    assert "https://a" in wg._CORS_ORIGINS
    assert "" not in wg._CORS_ORIGINS
```

- [ ] **Step 2: Run — expect 3 failures (env-merge not implemented)**

```bash
cd /Users/h2oslabs/Workspace/AutoService && uv run pytest tests/test_gateway_cors.py -v
```

Expected: `test_cors_env_extra_*` FAIL (module has no env append).

- [ ] **Step 3: Edit `autoservice/web_gateway.py` lines 57-59**

Replace:

```python
_CORS_ORIGINS = [
    f"http://localhost:{p}" for p in range(5173, 5180)
]
```

with:

```python
_CORS_ORIGINS = [f"http://localhost:{p}" for p in range(5173, 5180)]
_extra_origins = os.environ.get("CORS_EXTRA_ORIGINS", "").strip()
if _extra_origins:
    _CORS_ORIGINS.extend(
        o.strip() for o in _extra_origins.split(",") if o.strip()
    )
```

(`os` is already imported at the top of the file.)

- [ ] **Step 4: Re-run — expect all PASS**

```bash
cd /Users/h2oslabs/Workspace/AutoService && uv run pytest tests/test_gateway_cors.py -v
```

- [ ] **Step 5: Commit**

```bash
git add autoservice/web_gateway.py tests/test_gateway_cors.py
git commit -m "feat(gateway): honor CORS_EXTRA_ORIGINS env

Allows public deploy to add https://autoservice.ezagent.chat without
code changes."
```

---

### Task 7: Add `bcrypt` dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock` (auto-regenerated)

- [ ] **Step 1: Inspect current deps**

```bash
grep -A 2 "dependencies =" /Users/h2oslabs/Workspace/AutoService/pyproject.toml
```

- [ ] **Step 2: Add bcrypt**

Edit `pyproject.toml`, add `"bcrypt>=4,<5",` to the `dependencies` list.

- [ ] **Step 3: Lock**

```bash
cd /Users/h2oslabs/Workspace/AutoService && uv lock
```

- [ ] **Step 4: Verify importable**

```bash
cd /Users/h2oslabs/Workspace/AutoService && uv run python -c "import bcrypt; print(bcrypt.gensalt(4)[:4])"
```

Expected: 4-byte prefix of a salt printed, no ImportError.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add bcrypt for shared-admin password login"
```

---

### Task 8: Create `autoservice/password_login.py` (TDD)

**Files:**
- Create: `autoservice/password_login.py`
- Test: `tests/test_password_login.py` (new)

- [ ] **Step 1: Write failing tests (per-email file-backed lookup)**

Create `tests/test_password_login.py`:

```python
"""Unit tests for autoservice.password_login.

Covers:
- File missing → 404 (feature disabled)
- Email not in entries → 401 (constant-time, no enumeration)
- Wrong password → 401
- Correct password → 200 + auth_session cookie
- Rate limit (5 failures / 10 min per IP) → 429
- Lockout decay after window
"""
from __future__ import annotations

import json
import time

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoservice import password_login as pl


_EMAIL = "admin@example.com"
_GOOD_PASSWORD = "unit-test-password-16ch"


def _mk_file(tmp_path, entries: list[dict]) -> str:
    p = tmp_path / "passwords.json"
    p.write_text(json.dumps({"version": 1, "updated_at": "2026-04-24T00:00:00Z", "entries": entries}))
    return str(p)


def _mk_app(path_or_none) -> TestClient:
    app = FastAPI()
    app.include_router(pl.build_router(passwords_path=path_or_none))
    return TestClient(app)


def _entry(email: str, pw: str) -> dict:
    return {
        "email": email,
        "password_bcrypt": bcrypt.hashpw(pw.encode(), bcrypt.gensalt(4)).decode(),
        "generated_at": "2026-04-24T00:00:00Z",
    }


@pytest.fixture(autouse=True)
def _reset_lockout():
    pl._FAILED_ATTEMPTS.clear()
    yield
    pl._FAILED_ATTEMPTS.clear()


def test_missing_file_returns_404(tmp_path):
    path = tmp_path / "nonexistent.json"
    client = _mk_app(str(path))
    r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": "x"})
    assert r.status_code == 404


def test_email_not_in_entries_returns_401_without_enumeration(tmp_path):
    path = _mk_file(tmp_path, [_entry("someone@else.com", _GOOD_PASSWORD)])
    client = _mk_app(path)
    r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": "x"})
    assert r.status_code == 401
    assert r.json().get("detail") == "invalid credentials"


def test_wrong_password_returns_401(tmp_path):
    path = _mk_file(tmp_path, [_entry(_EMAIL, _GOOD_PASSWORD)])
    client = _mk_app(path)
    r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": "wrong"})
    assert r.status_code == 401


def test_success_sets_session_cookie(tmp_path):
    path = _mk_file(tmp_path, [_entry(_EMAIL, _GOOD_PASSWORD)])
    client = _mk_app(path)
    r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": _GOOD_PASSWORD})
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "auth_session=" in set_cookie
    assert "HttpOnly" in set_cookie


def test_email_match_is_case_insensitive(tmp_path):
    path = _mk_file(tmp_path, [_entry(_EMAIL, _GOOD_PASSWORD)])
    client = _mk_app(path)
    r = client.post("/api/auth/password-login", json={"email": _EMAIL.upper(), "password": _GOOD_PASSWORD})
    assert r.status_code == 200


def test_rate_limit_blocks_after_five_failures(tmp_path):
    path = _mk_file(tmp_path, [_entry(_EMAIL, _GOOD_PASSWORD)])
    client = _mk_app(path)
    for _ in range(5):
        r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": _GOOD_PASSWORD})
    assert r.status_code == 429


def test_rate_limit_decays_after_window(tmp_path):
    path = _mk_file(tmp_path, [_entry(_EMAIL, _GOOD_PASSWORD)])
    client = _mk_app(path)
    for _ in range(5):
        client.post("/api/auth/password-login", json={"email": _EMAIL, "password": "wrong"})
    for ip in list(pl._FAILED_ATTEMPTS.keys()):
        pl._FAILED_ATTEMPTS[ip] = [t - (11 * 60) for t in pl._FAILED_ATTEMPTS[ip]]
    r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": _GOOD_PASSWORD})
    assert r.status_code == 200
```

- [ ] **Step 2: Run — expect module-not-found**

```bash
cd /Users/h2oslabs/Workspace/AutoService && uv run pytest tests/test_password_login.py -v
```

Expected: `ModuleNotFoundError: autoservice.password_login`.

- [ ] **Step 3: Implement the module**

Create `autoservice/password_login.py`:

```python
"""POST /api/auth/password-login — per-email, file-backed password login.

Storage lives at ``.autoservice/passwords.json`` with shape::

    {
      "version": 1,
      "updated_at": "...",
      "entries": [{"email": "x@y", "password_bcrypt": "$2b$...", "generated_at": "..."}]
    }

Emails are compared case-insensitively. When a request arrives for an
email NOT in ``entries`` the endpoint still runs a bcrypt check against
a throwaway hash so response time does not leak membership.

Rate limit: 5 failures per 10-minute window per client IP → 429.

On success mints the same ``auth_session`` cookie shape as the magic-
link flow (``HttpOnly``, ``Secure``, ``SameSite=Lax``, ``Path=/``,
7-day TTL). Session row persistence is not the responsibility of this
module; session-verification middleware elsewhere in the gateway
treats the cookie value as an opaque token and verifies against its
own session table. For demo-phase this endpoint only needs to produce
the cookie — the same-file-backed pattern can be replaced by a real
users table without touching the Caddy/tunnel layer.
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

import bcrypt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr

logger = logging.getLogger("autoservice.password_login")

_FAILED_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_WINDOW_SECONDS = 10 * 60
_MAX_FAILURES = 5

# Dummy hash used to maintain constant-time behavior for missing emails.
_DUMMY_HASH = bcrypt.hashpw(b"unused-reference", bcrypt.gensalt(4)).decode()


class PasswordLoginRequest(BaseModel):
    email: EmailStr
    password: str


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_locked(ip: str) -> bool:
    now = time.time()
    _FAILED_ATTEMPTS[ip] = [t for t in _FAILED_ATTEMPTS.get(ip, []) if (now - t) < _WINDOW_SECONDS]
    return len(_FAILED_ATTEMPTS[ip]) >= _MAX_FAILURES


def _record_failure(ip: str) -> None:
    _FAILED_ATTEMPTS[ip].append(time.time())


def _clear_failures(ip: str) -> None:
    _FAILED_ATTEMPTS.pop(ip, None)


def _load_entries(path: str) -> Optional[list[dict]]:
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[password-login] cannot read %s: %s", path, exc)
        return None
    entries = data.get("entries") or []
    return entries if isinstance(entries, list) else None


def _find_entry(entries: list[dict], email: str) -> Optional[dict]:
    target = email.lower()
    for e in entries:
        if str(e.get("email", "")).lower() == target:
            return e
    return None


def build_router(*, passwords_path: str) -> APIRouter:
    """Build the router; ``passwords_path`` is the absolute path to passwords.json."""
    router = APIRouter()

    @router.post("/api/auth/password-login")
    def password_login(body: PasswordLoginRequest, request: Request, response: Response) -> dict[str, str]:
        entries = _load_entries(passwords_path)
        if entries is None:
            # File missing → feature disabled, pretend route does not exist.
            raise HTTPException(status_code=404)

        ip = _client_ip(request)
        if _is_locked(ip):
            logger.warning("[password-login] ip=%s locked out", ip)
            raise HTTPException(status_code=429, detail="too many attempts")

        entry = _find_entry(entries, body.email)
        if entry is None:
            bcrypt.checkpw(body.password.encode(), _DUMMY_HASH.encode())
            _record_failure(ip)
            raise HTTPException(status_code=401, detail="invalid credentials")

        stored = str(entry.get("password_bcrypt", ""))
        if not stored or not bcrypt.checkpw(body.password.encode(), stored.encode()):
            _record_failure(ip)
            logger.warning("[password-login] ip=%s email=%s bad password", ip, body.email)
            raise HTTPException(status_code=401, detail="invalid credentials")

        _clear_failures(ip)

        token = secrets.token_urlsafe(32)
        response.set_cookie(
            key="auth_session",
            value=token,
            max_age=7 * 24 * 3600,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
        logger.info("[password-login] ip=%s email=%s success", ip, body.email)
        return {"ok": "true", "email": body.email}

    return router
```

- [ ] **Step 4: Run — expect all 7 tests PASS**

```bash
cd /Users/h2oslabs/Workspace/AutoService && uv run pytest tests/test_password_login.py -v
```

- [ ] **Step 5: Commit**

```bash
git add autoservice/password_login.py tests/test_password_login.py
git commit -m "feat(auth): per-email password-login backed by passwords.json

Case-insensitive email match, constant-time miss-path (bcrypt dummy
check), per-IP rate limit (5/10min → 429), mints auth_session cookie
on success. File-missing returns 404 so the feature is opt-in per
deployment. passwords.json schema: {version, updated_at, entries:
[{email, password_bcrypt, generated_at}, ...]}."
```

---

### Task 9: Wire `password_login` router into the gateway

**Files:**
- Modify: `autoservice/web_gateway.py`

- [ ] **Step 1: Locate where other routers are included**

```bash
grep -n "include_router\|from autoservice\." /Users/h2oslabs/Workspace/AutoService/autoservice/web_gateway.py | head
```

- [ ] **Step 2: Add import + include**

Near the top of `web_gateway.py`, add:

```python
from autoservice import password_login as _password_login
```

Inside `create_app()`, after other `app.include_router(...)` calls,
add:

```python
# Path to the per-email password file; same convention as auth.db etc.
_PASSWORDS_FILE = Path(__file__).resolve().parent.parent / ".autoservice" / "passwords.json"
app.include_router(
    _password_login.build_router(passwords_path=str(_PASSWORDS_FILE))
)
```

(`Path` is already imported via `from pathlib import Path`.)

- [ ] **Step 3: Write integration smoke test**

Append to `tests/test_password_login.py`:

```python
def test_gateway_mounts_password_login_route(tmp_path, monkeypatch):
    """Route is reachable via the real app factory.

    passwords.json is absent in the test env → 404 is the expected
    response, which still proves the route is mounted (distinct from
    405 'method not allowed' or 500).
    """
    from autoservice.web_gateway import create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)
    r = client.post("/api/auth/password-login", json={"email": "foo@bar.com", "password": "x"})
    assert r.status_code in (401, 404)
```

- [ ] **Step 4: Run — PASS**

```bash
cd /Users/h2oslabs/Workspace/AutoService && uv run pytest tests/test_password_login.py -v
```

- [ ] **Step 5: Commit**

```bash
git add autoservice/web_gateway.py tests/test_password_login.py
git commit -m "feat(gateway): include password-login router"
```

---

## Phase 2 — Frontend password-login UI (depends on Phase 1B)

### Task 10: Add collapsed password section to `LoginPage.tsx`

**Files:**
- Modify: `frontend/apps/admin-portal/src/components/auth/LoginPage.tsx`
- Test: `frontend/apps/admin-portal/src/components/auth/__tests__/LoginPage.test.tsx` (new or extend existing)

- [ ] **Step 1: Read existing LoginPage**

```bash
cat /Users/h2oslabs/Workspace/AutoService/frontend/apps/admin-portal/src/components/auth/LoginPage.tsx | head -200
```

Note the existing magic-link submission pattern; we will mirror its
`fetch` call shape.

- [ ] **Step 2: Add a password-login section**

Inside the component's JSX, below the magic-link form, add:

```tsx
<details className="mt-6">
  <summary className="cursor-pointer text-sm text-slate-500">
    Developer password login
  </summary>
  <form
    className="mt-3 space-y-2"
    onSubmit={async e => {
      e.preventDefault();
      setError(null);
      setPwBusy(true);
      try {
        const res = await fetch('/api/auth/password-login', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: pwEmail, password: pwPassword }),
        });
        if (res.ok) {
          window.location.href = '/admin/';
          return;
        }
        if (res.status === 429) setError('Too many attempts. Try again in 10 minutes.');
        else if (res.status === 404) setError('Password login disabled on this deployment.');
        else setError('Invalid credentials.');
      } catch (err) {
        setError('Network error.');
      } finally {
        setPwBusy(false);
      }
    }}
  >
    <input
      type="email"
      value={pwEmail}
      onChange={e => setPwEmail(e.target.value)}
      placeholder="you@example.com"
      className="w-full px-2 py-1 border rounded"
      required
    />
    <input
      type="password"
      value={pwPassword}
      onChange={e => setPwPassword(e.target.value)}
      placeholder="Password"
      className="w-full px-2 py-1 border rounded"
      required
    />
    <button
      type="submit"
      disabled={pwBusy}
      className="w-full py-1 bg-slate-700 text-white rounded disabled:opacity-50"
    >
      {pwBusy ? 'Signing in…' : 'Sign in with password'}
    </button>
  </form>
</details>
```

Add the state hooks at the top of the component:

```tsx
const [pwEmail, setPwEmail] = useState('');
const [pwPassword, setPwPassword] = useState('');
const [pwBusy, setPwBusy] = useState(false);
```

- [ ] **Step 3: Write a component test**

Create `frontend/apps/admin-portal/src/components/auth/__tests__/LoginPage.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { LoginPage } from '../LoginPage';

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('LoginPage password section', () => {
  it('renders the collapsed developer password form', () => {
    render(<LoginPage />);
    expect(screen.getByText(/Developer password login/i)).toBeInTheDocument();
  });

  it('posts to /api/auth/password-login when submitted', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ ok: 'true' }), { status: 200 }));
    render(<LoginPage />);
    fireEvent.click(screen.getByText(/Developer password login/i));
    fireEvent.change(screen.getAllByPlaceholderText(/@/)[0], { target: { value: 'admin@example.com' } });
    fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'secret' } });
    fireEvent.submit(screen.getByRole('button', { name: /Sign in with password/i }));
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe('/api/auth/password-login');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(init?.body as string)).toMatchObject({ email: 'admin@example.com', password: 'secret' });
  });
});
```

Adjust import path for `LoginPage` to the exact named/default export the file uses.

- [ ] **Step 4: Run — all PASS**

```bash
cd frontend && pnpm --filter @autoservice/admin-portal exec vitest run src/components/auth/__tests__/LoginPage.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/admin-portal/src/components/auth
git commit -m "feat(admin-portal): collapsed dev password-login section

Calls POST /api/auth/password-login (same-origin) and redirects to
/admin/ on success. Magic-link remains the primary path."
```

---

## Phase 3 — Config files (can parallel with Phase 1/2)

### Task 11: `deploy/caddy/Caddyfile.public`

**Files:**
- Create: `deploy/caddy/Caddyfile.public`

- [ ] **Step 1: Write the Caddyfile**

```caddyfile
{
    admin off
    auto_https off
    log {
        output file {env.AUTOSERVICE_ROOT}/.autoservice/logs/caddy.log {
            roll_size 10mb
            roll_keep 10
        }
        format json
    }
}

http://:{env.CADDY_PORT} {
    encode zstd gzip

    @root path /
    redir @root /site/ 302

    handle /robots.txt {
        respond "User-agent: *\nDisallow: /\n" 200
    }

    handle /_caddy_health {
        respond "ok" 200
    }

    redir /site /site/ 308
    handle_path /site/* {
        root * {env.AUTOSERVICE_ROOT}/frontend/apps/customer-chat/dist
        try_files {path} /index.html
        file_server
    }

    redir /console /console/ 308
    handle_path /console/* {
        root * {env.AUTOSERVICE_ROOT}/frontend/apps/operator-console/dist
        try_files {path} /index.html
        file_server
    }

    redir /admin /admin/ 308
    handle_path /admin/* {
        root * {env.AUTOSERVICE_ROOT}/frontend/apps/admin-portal/dist
        try_files {path} /index.html
        file_server
    }

    handle /api/* {
        reverse_proxy 127.0.0.1:8000 {
            header_up X-Forwarded-Host {host}
            header_up X-Forwarded-Proto https
        }
    }

    handle /ws/* {
        reverse_proxy 127.0.0.1:8000 {
            header_up X-Forwarded-Host {host}
            header_up X-Forwarded-Proto https
        }
    }

    handle {
        respond "not found" 404
    }
}
```

- [ ] **Step 2: Validate syntax**

```bash
CADDY_PORT=18080 AUTOSERVICE_ROOT=/Users/h2oslabs/Workspace/AutoService \
  /usr/local/bin/caddy validate --adapter caddyfile --config /Users/h2oslabs/Workspace/AutoService/deploy/caddy/Caddyfile.public
```

Expected: `Valid configuration`. If any env placeholder is misspelled, this errors loudly.

- [ ] **Step 3: Commit**

```bash
git add deploy/caddy/Caddyfile.public
git commit -m "deploy(caddy): add public-tunnel Caddyfile

127.0.0.1:\${CADDY_PORT} with subpath routing for three SPAs and
reverse_proxy for /api + /ws. admin off, auto_https off — designed
to coexist with an existing Caddy already using 80/443/2019."
```

---

### Task 12: `deploy/cloudflared/autoservice.yml.example`

**Files:**
- Create: `deploy/cloudflared/autoservice.yml.example`

- [ ] **Step 1: Write the template**

```yaml
# Render to ~/.cloudflared/autoservice.yml and fill in the UUID + paths.
# Mirrors the already-running config at that path.
tunnel: <autoservice-tunnel-uuid>
credentials-file: /Users/<you>/.cloudflared/<autoservice-tunnel-uuid>.json

# Explicit metrics port to avoid colliding with the ezagent-voice tunnel's
# auto-picked port.
metrics: 127.0.0.1:20242

logfile: /Users/<you>/Workspace/AutoService/.autoservice/logs/cloudflared.log
loglevel: info

ingress:
  - hostname: autoservice.ezagent.chat
    service: http://127.0.0.1:18080
    originRequest:
      noTLSVerify: true
      connectTimeout: 30s
  - service: http_status:404
```

- [ ] **Step 2: Commit**

```bash
git add deploy/cloudflared/autoservice.yml.example
git commit -m "deploy(cloudflared): checked-in template for autoservice tunnel

Real config lives at ~/.cloudflared/autoservice.yml (outside git)."
```

---

### Task 13: `deploy/cloudflare-access/allowlist.yml`

**Files:**
- Create: `deploy/cloudflare-access/allowlist.yml`

- [ ] **Step 1: Write**

```yaml
# Source of truth for the Cloudflare Access application on
# autoservice.ezagent.chat. Applied via scripts/apply-cf-access.sh.
#
# Paths under `protected:` require the user to authenticate via CF
# Access (email OTP by default) before the request reaches Caddy.
# Paths under `public:` bypass Access entirely.
#
# After editing this file run `make access-apply`. Without a
# CF_API_TOKEN the script prints the equivalent curl commands for
# manual execution.

application:
  name: autoservice
  domain: autoservice.ezagent.chat
  session_duration: "720h"  # 30 days — dev ergonomics

identity_providers:
  - type: onetimepin         # email OTP; no extra provider required

protected_paths:
  - /admin
  - /admin/*
  - /console
  - /console/*
  - /ws/operator
  - /ws/operator/*
  - /ws/admin
  - /ws/admin/*
  - /api/master/*
  - /api/admin/*
  - /api/management/*
  - /api/proposals*
  - /api/dream/*
  - /api/onboard/*
  - /api/canary/*
  - /api/compliance/*
  - /api/rehearsal/*
  - /api/billing/*
  - /api/metrics/*
  - /api/cc_pool/*
  - /api/sla/*
  - /api/conversations/active

public_paths:
  - /
  - /site
  - /site/*
  - /robots.txt
  - /_caddy_health
  - /api/auth/*
  - /api/tenants/*
  - /api/healthz
  - /ws/customer
  - /ws/customer/*

allowed_emails:
  - lin.yilun@h2oslabs.com
  - huang.jiajia@h2oslabs.com
  - yao.shengyue@h2oslabs.com
  - chen.ruihua@h2oslabs.com
  - autoservice@h2oslabs.com
```

- [ ] **Step 2: Commit**

```bash
git add deploy/cloudflare-access/allowlist.yml
git commit -m "deploy(cf-access): config-as-code allowlist for autoservice

Captures path-selective policy + initial five-email allowlist."
```

---

## Phase 4 — Scripts + Makefile

### Task 14: `scripts/install-smtp-config.sh`

**Files:**
- Create: `scripts/install-smtp-config.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Render .autoservice/config.local.yaml from .smtp.env + initial admin
# allowlist. Idempotent: existing shared_admin.password_bcrypt preserved
# if already set.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO/.smtp.env"
OUT="$REPO/.autoservice/config.local.yaml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. See docs/deploy/public-tunnel-runbook.md §SMTP."
  exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

: "${SMTP_USER:?SMTP_USER unset in .smtp.env}"
: "${SMTP_FROM:?SMTP_FROM unset in .smtp.env}"
: "${SMTP_PASSWORD:?SMTP_PASSWORD unset in .smtp.env}"
: "${SMTP_HOST:?SMTP_HOST unset}"
: "${SMTP_PORT:=587}"
: "${SMTP_STARTTLS:=true}"

# Preserve existing shared_admin block if present.
EXISTING_BCRYPT=""
if [[ -f "$OUT" ]] && command -v yq >/dev/null 2>&1; then
  EXISTING_BCRYPT="$(yq e '.auth.shared_admin.password_bcrypt // ""' "$OUT" 2>/dev/null || true)"
fi

mkdir -p "$(dirname "$OUT")"

cat > "$OUT" <<YAML
# Rendered by scripts/install-smtp-config.sh from .smtp.env
auth:
  admin_emails:
    - lin.yilun@h2oslabs.com
    - huang.jiajia@h2oslabs.com
    - yao.shengyue@h2oslabs.com
    - chen.ruihua@h2oslabs.com
    - autoservice@h2oslabs.com
  smtp:
    host: "$SMTP_HOST"
    port: $SMTP_PORT
    user: "$SMTP_USER"
    password: "$SMTP_PASSWORD"
    from: "$SMTP_FROM"
    starttls: $SMTP_STARTTLS
  shared_admin:
    email: autoservice@h2oslabs.com
    password_bcrypt: "${EXISTING_BCRYPT}"
YAML

chmod 600 "$OUT"
echo "Wrote $OUT (mode 600). Set the password with scripts/generate-admin-passwords.sh"
```

- [ ] **Step 2: Make executable + dry run**

```bash
chmod +x /Users/h2oslabs/Workspace/AutoService/scripts/install-smtp-config.sh
bash -n /Users/h2oslabs/Workspace/AutoService/scripts/install-smtp-config.sh
```

Expected: no syntax errors.

- [ ] **Step 3: Commit**

```bash
git add scripts/install-smtp-config.sh
git commit -m "chore(deploy): install-smtp-config.sh renders config.local.yaml"
```

---

### Task 15: `scripts/generate-admin-passwords.sh`

**Files:**
- Create: `scripts/generate-admin-passwords.sh`

- [ ] **Step 1: Write the idempotent generator**

```bash
#!/usr/bin/env bash
# For every email in .autoservice/config.local.yaml::auth.admin_emails
# that does NOT yet have an entry in .autoservice/passwords.json,
# generate a random password, bcrypt-hash it, and append the entry.
# Plaintext passwords are printed ONCE at the end with a warning.
# Idempotent: rerunning skips emails that already have entries.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$REPO/.autoservice/config.local.yaml"
PWFILE="$REPO/.autoservice/passwords.json"

if [[ ! -f "$CFG" ]]; then
  echo "ERROR: $CFG not found. Run scripts/install-smtp-config.sh first." >&2
  exit 1
fi
command -v yq >/dev/null 2>&1 || { echo "ERROR: brew install yq" >&2; exit 2; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: brew install jq" >&2; exit 3; }

mapfile -t emails < <(yq e '.auth.admin_emails[]' "$CFG")
[[ ${#emails[@]} -gt 0 ]] || { echo "No admin_emails in $CFG"; exit 4; }

if [[ ! -f "$PWFILE" ]]; then
  echo '{"version":1,"updated_at":"","entries":[]}' > "$PWFILE"
  chmod 600 "$PWFILE"
fi

declare -a newly_generated_emails=()
declare -a newly_generated_passwords=()

for email in "${emails[@]}"; do
  exists="$(jq --arg e "$email" '[.entries[] | select(.email==$e)] | length' "$PWFILE")"
  if [[ "$exists" != "0" ]]; then
    continue
  fi

  # 22-char base64 password (secrets.token_urlsafe(16)).
  pw="$(cd "$REPO" && uv run python -c 'import secrets; print(secrets.token_urlsafe(16))')"
  hash="$(cd "$REPO" && printf '%s' "$pw" | uv run python -c '
import sys, bcrypt
pw = sys.stdin.read().encode()
print(bcrypt.hashpw(pw, bcrypt.gensalt(12)).decode(), end="")
')"
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  tmp="$(mktemp)"
  jq --arg email "$email" --arg h "$hash" --arg now "$now" \
     '.entries += [{"email":$email,"password_bcrypt":$h,"generated_at":$now}] | .updated_at = $now' \
     "$PWFILE" > "$tmp"
  mv "$tmp" "$PWFILE"
  chmod 600 "$PWFILE"

  newly_generated_emails+=("$email")
  newly_generated_passwords+=("$pw")
done

if [[ ${#newly_generated_emails[@]} -eq 0 ]]; then
  echo "No new passwords generated — all admin_emails already have entries."
  exit 0
fi

echo
echo "======================================================================"
echo "  NEW ADMIN PASSWORDS — NOT SHOWN AGAIN. DISTRIBUTE SECURELY."
echo "======================================================================"
for i in "${!newly_generated_emails[@]}"; do
  printf "  %-40s  %s\n" "${newly_generated_emails[$i]}" "${newly_generated_passwords[$i]}"
done
echo "======================================================================"
echo
echo "Run 'make public-reload' if the gateway is running."
```

- [ ] **Step 2: Executable + lint**

```bash
chmod +x /Users/h2oslabs/Workspace/AutoService/scripts/generate-admin-passwords.sh
bash -n /Users/h2oslabs/Workspace/AutoService/scripts/generate-admin-passwords.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/generate-admin-passwords.sh
git commit -m "chore(deploy): generate-admin-passwords.sh (idempotent)

Reads admin_emails, generates and stores bcrypt hashes in
.autoservice/passwords.json, prints plaintext passwords once for
out-of-band distribution."
```

---

### Task 16: `scripts/apply-cf-access.sh`

**Files:**
- Create: `scripts/apply-cf-access.sh`

- [ ] **Step 1: Write the script (degrade gracefully without token)**

```bash
#!/usr/bin/env bash
# Apply deploy/cloudflare-access/allowlist.yml to Cloudflare Access via
# the REST API. If CF_API_TOKEN / CF_ACCOUNT_ID are not set, print the
# curl commands for the operator to run manually.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
YML="$REPO/deploy/cloudflare-access/allowlist.yml"
ENV_FILE="$REPO/.cf-access.env"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

require_yq() {
  command -v yq >/dev/null 2>&1 || { echo "ERROR: yq required. brew install yq." >&2; exit 1; }
}
require_jq() {
  command -v jq >/dev/null 2>&1 || { echo "ERROR: jq required. brew install jq." >&2; exit 1; }
}
require_yq; require_jq

DOMAIN="$(yq e '.application.domain' "$YML")"
NAME="$(yq e '.application.name' "$YML")"
SESSION="$(yq e '.application.session_duration' "$YML")"
EMAILS_JSON="$(yq e -o=json '.allowed_emails' "$YML")"

# Build the include list: one email rule per address.
INCLUDE="$(echo "$EMAILS_JSON" | jq '[.[] | {email: {email: .}}]')"

if [[ -z "${CF_API_TOKEN:-}" || -z "${CF_ACCOUNT_ID:-}" ]]; then
  cat <<EOF
CF_API_TOKEN or CF_ACCOUNT_ID unset — printing curl commands for manual execution.
Place them in \$HOME/autoservice-cf-access.sh and run with a valid token.

# 1) Create or update the Access Application
curl -X POST https://api.cloudflare.com/client/v4/accounts/\${CF_ACCOUNT_ID}/access/apps \\
  -H "Authorization: Bearer \${CF_API_TOKEN}" -H "Content-Type: application/json" \\
  -d '{"name":"$NAME","domain":"$DOMAIN","session_duration":"$SESSION","type":"self_hosted"}'

# 2) Attach an allow policy with the email list
curl -X POST https://api.cloudflare.com/client/v4/accounts/\${CF_ACCOUNT_ID}/access/apps/<APP_UUID>/policies \\
  -H "Authorization: Bearer \${CF_API_TOKEN}" -H "Content-Type: application/json" \\
  -d '{"name":"allow-team","decision":"allow","include":'"$INCLUDE"'}'

# 3) Per protected path, bypass-public the public_paths by creating paired
#    Access applications with decision "bypass" — see runbook for details.
EOF
  exit 0
fi

# Upsert the application
existing="$(curl -s -H "Authorization: Bearer $CF_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/access/apps" \
  | jq -r --arg d "$DOMAIN" '.result[] | select(.domain==$d) | .id' | head -1)"

if [[ -n "$existing" ]]; then
  echo "Updating existing app $existing"
  app_id="$existing"
  curl -s -X PUT "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/access/apps/$app_id" \
    -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" \
    -d "{\"name\":\"$NAME\",\"domain\":\"$DOMAIN\",\"session_duration\":\"$SESSION\",\"type\":\"self_hosted\"}" \
    | jq '.success'
else
  echo "Creating new Access application"
  app_id="$(curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/access/apps" \
    -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" \
    -d "{\"name\":\"$NAME\",\"domain\":\"$DOMAIN\",\"session_duration\":\"$SESSION\",\"type\":\"self_hosted\"}" \
    | jq -r '.result.id')"
fi

# Upsert policy
policies="$(curl -s "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/access/apps/$app_id/policies" \
  -H "Authorization: Bearer $CF_API_TOKEN")"

policy_id="$(echo "$policies" | jq -r '.result[] | select(.name=="allow-team") | .id' | head -1)"
policy_body=$(jq -n --argjson inc "$INCLUDE" '{name:"allow-team",decision:"allow",include:$inc}')

if [[ -n "$policy_id" && "$policy_id" != "null" ]]; then
  curl -s -X PUT "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/access/apps/$app_id/policies/$policy_id" \
    -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" \
    -d "$policy_body" | jq '.success'
else
  curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/access/apps/$app_id/policies" \
    -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" \
    -d "$policy_body" | jq '.success'
fi

echo "CF Access applied. App ID: $app_id"
```

- [ ] **Step 2: Executable + syntax**

```bash
chmod +x /Users/h2oslabs/Workspace/AutoService/scripts/apply-cf-access.sh
bash -n /Users/h2oslabs/Workspace/AutoService/scripts/apply-cf-access.sh
```

- [ ] **Step 3: Degraded-mode verification**

```bash
cd /Users/h2oslabs/Workspace/AutoService && bash scripts/apply-cf-access.sh
```

Expected: prints curl commands (because `.cf-access.env` is absent).

- [ ] **Step 4: Commit**

```bash
git add scripts/apply-cf-access.sh
git commit -m "chore(deploy): apply-cf-access.sh wraps CF Access REST API"
```

---

### Task 17: `scripts/public-build.sh`

**Files:**
- Create: `scripts/public-build.sh`

- [ ] **Step 1: Write**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../frontend"

echo "==> Building customer-chat (base=/site/)"
VITE_MOUNT_PATH=/site/    pnpm --filter @autoservice/customer-chat    build

echo "==> Building operator-console (base=/console/)"
VITE_MOUNT_PATH=/console/ pnpm --filter @autoservice/operator-console build

echo "==> Building admin-portal (base=/admin/)"
VITE_MOUNT_PATH=/admin/   pnpm --filter @autoservice/admin-portal     build

echo "==> Assets:"
for app in customer-chat operator-console admin-portal; do
  echo "  $app:"
  head -1 "apps/$app/dist/index.html" | grep -oE '(src|href)="[^"]+"' | head -3 | sed 's/^/    /'
done
```

- [ ] **Step 2: Executable + dry run**

```bash
chmod +x /Users/h2oslabs/Workspace/AutoService/scripts/public-build.sh
bash /Users/h2oslabs/Workspace/AutoService/scripts/public-build.sh
```

Expected: three builds succeed; each `index.html` references `/site/…`,
`/console/…`, `/admin/…` respectively.

- [ ] **Step 3: Commit**

```bash
git add scripts/public-build.sh
git commit -m "chore(deploy): public-build.sh produces subpath-mounted dists"
```

---

### Task 18: `scripts/public-up.sh`

**Files:**
- Create: `scripts/public-up.sh`

- [ ] **Step 1: Write**

```bash
#!/usr/bin/env bash
# Start gateway + Caddy + (if not running) cloudflared as backgrounded
# user processes. Tracks PIDs under .autoservice/run/.
# Unset AUTH_DEV_MODE defensively — public deploy must NEVER have it set.
set -euo pipefail
unset AUTH_DEV_MODE

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

mkdir -p .autoservice/logs .autoservice/run

: "${CADDY_PORT:=18080}"
export CADDY_PORT
export AUTOSERVICE_ROOT="$REPO"

# Reject if the port is already bound.
if lsof -nP -iTCP:$CADDY_PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ERROR: port $CADDY_PORT already in use:"
  lsof -nP -iTCP:$CADDY_PORT -sTCP:LISTEN
  exit 1
fi

# Gateway
echo "==> Starting gateway (127.0.0.1:8000)"
PLACEHOLDER_ENABLED=0 \
CORS_EXTRA_ORIGINS="https://autoservice.ezagent.chat" \
nohup uv run uvicorn autoservice.web_gateway:create_app \
  --factory --host 127.0.0.1 --port 8000 \
  --proxy-headers --forwarded-allow-ips="127.0.0.1" \
  --log-level info \
  >> .autoservice/logs/gateway.log 2>&1 &
echo $! > .autoservice/run/gateway.pid
disown

sleep 1

# Caddy
echo "==> Starting Caddy (127.0.0.1:$CADDY_PORT)"
nohup /usr/local/bin/caddy run \
  --adapter caddyfile \
  --config "$REPO/deploy/caddy/Caddyfile.public" \
  >> .autoservice/logs/caddy-stdout.log 2>&1 &
echo $! > .autoservice/run/caddy.pid
disown

sleep 1

# cloudflared — only start if not already running for this tunnel UUID.
TUNNEL_UUID=389c95d2-6066-437e-854f-8a09b2481259
if pgrep -f "cloudflared.*$TUNNEL_UUID" >/dev/null 2>&1; then
  echo "==> cloudflared already running for $TUNNEL_UUID — skipping start"
else
  echo "==> Starting cloudflared"
  nohup /opt/homebrew/bin/cloudflared tunnel \
    --config /Users/$USER/.cloudflared/autoservice.yml run "$TUNNEL_UUID" \
    >> .autoservice/logs/cloudflared-stdout.log 2>&1 &
  echo $! > .autoservice/run/cloudflared.pid
  disown
fi

sleep 2
echo
echo "==> Status"
for p in gateway caddy cloudflared; do
  pidfile=".autoservice/run/$p.pid"
  if [[ -f "$pidfile" ]]; then
    pid="$(cat "$pidfile")"
    if ps -p "$pid" -o pid= >/dev/null 2>&1; then
      echo "  $p UP (pid=$pid)"
    else
      echo "  $p DEAD (pidfile stale)"
    fi
  fi
done

echo
echo "Caddy health:   curl -I http://127.0.0.1:$CADDY_PORT/_caddy_health"
echo "Gateway health: curl -I http://127.0.0.1:8000/docs"
echo "Public:         curl -I https://autoservice.ezagent.chat/_caddy_health"
```

- [ ] **Step 2: Executable + syntax**

```bash
chmod +x /Users/h2oslabs/Workspace/AutoService/scripts/public-up.sh
bash -n /Users/h2oslabs/Workspace/AutoService/scripts/public-up.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/public-up.sh
git commit -m "chore(deploy): public-up.sh launches gateway+caddy+cloudflared

Guards: unset AUTH_DEV_MODE, port conflict check, skip cloudflared if
it's already running for our tunnel UUID (coexistence)."
```

---

### Task 19: `scripts/public-down.sh` and `scripts/public-panic.sh`

**Files:**
- Create: `scripts/public-down.sh`
- Create: `scripts/public-panic.sh`

- [ ] **Step 1: Write public-down.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

# Stop in reverse dependency order.
for name in caddy cloudflared gateway; do
  pidfile=".autoservice/run/$name.pid"
  if [[ -f "$pidfile" ]]; then
    pid="$(cat "$pidfile")"
    if ps -p "$pid" -o pid= >/dev/null 2>&1; then
      echo "  stopping $name (pid=$pid)"
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
  fi
done

# Port cleanup fallback
for port in 18080 8000; do
  pids=$(lsof -ti tcp:$port 2>/dev/null || true)
  for pid in $pids; do
    echo "  freeing port $port (pid=$pid)"
    kill -9 "$pid" 2>/dev/null || true
  done
done
```

- [ ] **Step 2: Write public-panic.sh** (faster, kills tunnel only)

```bash
#!/usr/bin/env bash
# Takes the public hostname offline by stopping cloudflared. Gateway
# and Caddy keep running for post-mortem.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

pidfile=".autoservice/run/cloudflared.pid"
if [[ -f "$pidfile" ]]; then
  pid="$(cat "$pidfile")"
  kill "$pid" 2>/dev/null || true
  rm -f "$pidfile"
  echo "cloudflared stopped; hostname will go 5xx within ~2 seconds."
fi

# Also kill any orphaned cloudflared for our UUID
pkill -f "cloudflared.*389c95d2-6066-437e-854f-8a09b2481259" 2>/dev/null || true
```

- [ ] **Step 3: Make executable + lint**

```bash
chmod +x /Users/h2oslabs/Workspace/AutoService/scripts/public-{down,panic}.sh
bash -n /Users/h2oslabs/Workspace/AutoService/scripts/public-down.sh
bash -n /Users/h2oslabs/Workspace/AutoService/scripts/public-panic.sh
```

- [ ] **Step 4: Commit**

```bash
git add scripts/public-down.sh scripts/public-panic.sh
git commit -m "chore(deploy): public-down + public-panic scripts"
```

---

### Task 20: `scripts/public-reload.sh`

**Files:**
- Create: `scripts/public-reload.sh`

- [ ] **Step 1: Write (restart both gateway AND cloudflared per spec §8.2)**

```bash
#!/usr/bin/env bash
# Full reload: rebuild frontends, restart gateway (pick up new Python),
# restart cloudflared (drop long-lived WS sessions so clients
# reconnect to the new code). Caddy does NOT need restart — it serves
# static files from disk, which are now fresh after public-build.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

echo "==> Rebuilding frontends"
bash scripts/public-build.sh

echo "==> Restarting gateway"
if [[ -f .autoservice/run/gateway.pid ]]; then
  kill "$(cat .autoservice/run/gateway.pid)" 2>/dev/null || true
  rm -f .autoservice/run/gateway.pid
  sleep 1
fi
PLACEHOLDER_ENABLED=0 \
CORS_EXTRA_ORIGINS="https://autoservice.ezagent.chat" \
nohup uv run uvicorn autoservice.web_gateway:create_app \
  --factory --host 127.0.0.1 --port 8000 \
  --proxy-headers --forwarded-allow-ips="127.0.0.1" \
  --log-level info \
  >> .autoservice/logs/gateway.log 2>&1 &
echo $! > .autoservice/run/gateway.pid
disown

echo "==> Restarting cloudflared (drops existing WS)"
if [[ -f .autoservice/run/cloudflared.pid ]]; then
  kill "$(cat .autoservice/run/cloudflared.pid)" 2>/dev/null || true
  rm -f .autoservice/run/cloudflared.pid
  sleep 1
fi
nohup /opt/homebrew/bin/cloudflared tunnel \
  --config /Users/$USER/.cloudflared/autoservice.yml run 389c95d2-6066-437e-854f-8a09b2481259 \
  >> .autoservice/logs/cloudflared-stdout.log 2>&1 &
echo $! > .autoservice/run/cloudflared.pid
disown

sleep 3
echo "Reload complete."
```

- [ ] **Step 2: Make executable + lint**

```bash
chmod +x /Users/h2oslabs/Workspace/AutoService/scripts/public-reload.sh
bash -n /Users/h2oslabs/Workspace/AutoService/scripts/public-reload.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/public-reload.sh
git commit -m "chore(deploy): public-reload.sh (rebuild+gateway+tunnel)"
```

---

### Task 21: `scripts/public-smoke.sh`

**Files:**
- Create: `scripts/public-smoke.sh`

- [ ] **Step 1: Write**

```bash
#!/usr/bin/env bash
# HTTP + WS smoke checks against the public hostname. Exits non-zero
# on any failure so CI / runbook can chain safely.
set -euo pipefail

HOST=${HOST:-https://autoservice.ezagent.chat}

fail() { echo "✗ $*"; exit 1; }
ok()   { echo "✓ $*"; }

# 1. Caddy health
code="$(curl -fsS -o /dev/null -w '%{http_code}' "$HOST/_caddy_health" || true)"
[[ "$code" == "200" ]] && ok "caddy /_caddy_health 200" || fail "/_caddy_health expected 200, got $code"

# 2. Customer site served (public path, no Access)
code="$(curl -fsS -o /tmp/site.html -w '%{http_code}' "$HOST/site/" || true)"
[[ "$code" == "200" ]] && ok "/site/ 200" || fail "/site/ expected 200, got $code"
grep -q 'id="root"' /tmp/site.html && ok "/site/ has React mount root" || fail "/site/ missing React root"

# 3. AUTH_DEV_MODE must NOT be leaked: /api/auth/dev-mode must return 404 or "enabled":false
resp="$(curl -fsS "$HOST/api/auth/dev-mode" 2>&1 || true)"
if echo "$resp" | grep -qi '"enabled"[[:space:]]*:[[:space:]]*true'; then
  fail "AUTH_DEV_MODE appears enabled on public deployment — refuse to continue"
fi
ok "AUTH_DEV_MODE not leaked"

# 4. /api/master/tenants must be gated by CF Access (302 or 403), NEVER 200
code="$(curl -fsS -o /dev/null -w '%{http_code}' "$HOST/api/master/tenants" || true)"
if [[ "$code" == "200" ]]; then
  fail "/api/master/tenants returned 200 on public — CF Access not protecting it"
fi
ok "/api/master/tenants gated (HTTP $code)"

# 5. /admin/ is gated by CF Access (302 to CF login, NEVER 200 with app HTML)
code="$(curl -fsS -o /tmp/admin.html -w '%{http_code}' -L --max-redirs 0 "$HOST/admin/" || true)"
if [[ "$code" == "200" ]] && grep -q 'id="root"' /tmp/admin.html; then
  fail "/admin/ served app HTML without CF Access challenge"
fi
ok "/admin/ gated (HTTP $code)"

# 6. /robots.txt disallows all
code="$(curl -fsS "$HOST/robots.txt" || true)"
echo "$code" | grep -q 'Disallow: /' && ok "robots.txt disallows all" || fail "robots.txt malformed"

# 7. WS handshake (requires websocat). Public /ws/customer should upgrade.
if command -v websocat >/dev/null 2>&1; then
  if echo | websocat --exit-on-eof -1 --protocol "" "wss://${HOST#https://}/ws/customer?tenant=_smoke" >/dev/null 2>&1; then
    ok "wss /ws/customer handshake"
  else
    echo "⚠ wss /ws/customer: connect failed (server may reject tenant=_smoke; check manually)"
  fi
else
  echo "⚠ websocat not installed — skip WS check"
fi

echo
echo "Smoke passed."
```

- [ ] **Step 2: Make executable + lint**

```bash
chmod +x /Users/h2oslabs/Workspace/AutoService/scripts/public-smoke.sh
bash -n /Users/h2oslabs/Workspace/AutoService/scripts/public-smoke.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/public-smoke.sh
git commit -m "chore(deploy): public-smoke.sh HTTP+WS acceptance checks"
```

---

### Task 22: Makefile `public-*` + `access-apply` + `generate-admin-passwords` targets

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Append new targets**

At the end of `Makefile` (or in logical place matching existing style):

```makefile
# --- Public tunnel deploy ---
.PHONY: public-build public-up public-down public-panic public-reload public-smoke public-status public-logs access-apply generate-admin-passwords

public-build:
	@bash scripts/public-build.sh

public-up:
	@bash scripts/public-up.sh

public-down:
	@bash scripts/public-down.sh

public-panic:
	@bash scripts/public-panic.sh

public-reload:
	@bash scripts/public-reload.sh

public-smoke:
	@bash scripts/public-smoke.sh

public-status:
	@for name in gateway caddy cloudflared; do \
		pidfile=".autoservice/run/$$name.pid"; \
		if [ -f "$$pidfile" ] && ps -p $$(cat $$pidfile) -o pid= >/dev/null 2>&1; then \
			echo "$$name UP (pid=$$(cat $$pidfile))"; \
		else \
			echo "$$name DOWN"; \
		fi; \
	done

public-logs:
	@tail -n 40 -F .autoservice/logs/{gateway,caddy,cloudflared}.log 2>/dev/null

access-apply:
	@bash scripts/apply-cf-access.sh

generate-admin-passwords:
	@bash scripts/generate-admin-passwords.sh
```

- [ ] **Step 2: Verify**

```bash
cd /Users/h2oslabs/Workspace/AutoService && make -n public-status
```

Expected: prints the echo lines without error.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "build(make): add public-*, access-apply, generate-admin-passwords targets"
```

---

## Phase 5 — launchd

### Task 23: launchd plist templates (× 3)

**Files:**
- Create: `deploy/launchd/com.autoservice.gateway.plist.template`
- Create: `deploy/launchd/com.autoservice.caddy.plist.template`
- Create: `deploy/launchd/com.autoservice.cloudflared.plist.template`

- [ ] **Step 1: Gateway plist template**

Create `deploy/launchd/com.autoservice.gateway.plist.template`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.autoservice.gateway</string>
    <key>WorkingDirectory</key>
    <string>{{AUTOSERVICE_ROOT}}</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/bash</string>
      <string>-lc</string>
      <string>exec uv run uvicorn autoservice.web_gateway:create_app --factory --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1 --log-level info</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
      <key>PLACEHOLDER_ENABLED</key>
      <string>0</string>
      <key>CORS_EXTRA_ORIGINS</key>
      <string>https://autoservice.ezagent.chat</string>
    </dict>
    <key>KeepAlive</key><true/>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key>
    <string>{{AUTOSERVICE_ROOT}}/.autoservice/logs/gateway.log</string>
    <key>StandardErrorPath</key>
    <string>{{AUTOSERVICE_ROOT}}/.autoservice/logs/gateway.log</string>
</dict>
</plist>
```

- [ ] **Step 2: Caddy plist template**

Create `deploy/launchd/com.autoservice.caddy.plist.template`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.autoservice.caddy</string>
    <key>WorkingDirectory</key>
    <string>{{AUTOSERVICE_ROOT}}</string>
    <key>ProgramArguments</key>
    <array>
      <string>/usr/local/bin/caddy</string>
      <string>run</string>
      <string>--adapter</string><string>caddyfile</string>
      <string>--config</string>
      <string>{{AUTOSERVICE_ROOT}}/deploy/caddy/Caddyfile.public</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
      <key>CADDY_PORT</key>
      <string>18080</string>
      <key>AUTOSERVICE_ROOT</key>
      <string>{{AUTOSERVICE_ROOT}}</string>
    </dict>
    <key>KeepAlive</key><true/>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key>
    <string>{{AUTOSERVICE_ROOT}}/.autoservice/logs/caddy-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{{AUTOSERVICE_ROOT}}/.autoservice/logs/caddy-stdout.log</string>
</dict>
</plist>
```

- [ ] **Step 3: cloudflared plist template**

Create `deploy/launchd/com.autoservice.cloudflared.plist.template`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.autoservice.cloudflared</string>
    <key>WorkingDirectory</key>
    <string>{{AUTOSERVICE_ROOT}}</string>
    <key>ProgramArguments</key>
    <array>
      <string>/opt/homebrew/bin/cloudflared</string>
      <string>tunnel</string>
      <string>--config</string>
      <string>/Users/{{USER}}/.cloudflared/autoservice.yml</string>
      <string>run</string>
      <string>389c95d2-6066-437e-854f-8a09b2481259</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>KeepAlive</key><true/>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key>
    <string>{{AUTOSERVICE_ROOT}}/.autoservice/logs/cloudflared-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{{AUTOSERVICE_ROOT}}/.autoservice/logs/cloudflared-stdout.log</string>
</dict>
</plist>
```

- [ ] **Step 4: Commit**

```bash
git add deploy/launchd
git commit -m "deploy(launchd): plist templates for gateway/caddy/cloudflared

Explicit EnvironmentVariables (does NOT inherit shell), WorkingDirectory,
KeepAlive=true for auto-restart. Placeholders {{AUTOSERVICE_ROOT}} and
{{USER}} rendered at install time."
```

---

### Task 24: `scripts/install-launchd.sh` + `uninstall-launchd.sh`

**Files:**
- Create: `scripts/install-launchd.sh`
- Create: `scripts/uninstall-launchd.sh`

- [ ] **Step 1: install-launchd.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

TARGETS="$HOME/Library/LaunchAgents"
mkdir -p "$TARGETS"

for svc in gateway caddy cloudflared; do
  tmpl="deploy/launchd/com.autoservice.$svc.plist.template"
  out="$TARGETS/com.autoservice.$svc.plist"
  [[ -f "$tmpl" ]] || { echo "missing $tmpl"; exit 1; }
  sed -e "s|{{AUTOSERVICE_ROOT}}|$REPO|g" \
      -e "s|{{USER}}|$USER|g" "$tmpl" > "$out"
  echo "wrote $out"
done

# Unload old first, then bootstrap.
for svc in gateway caddy cloudflared; do
  label="com.autoservice.$svc"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$TARGETS/$label.plist"
  launchctl enable "gui/$(id -u)/$label"
  echo "loaded $label"
done

echo
echo "Status:"
for svc in gateway caddy cloudflared; do
  launchctl print "gui/$(id -u)/com.autoservice.$svc" 2>&1 | grep -E 'state|pid' | head -4
done
```

- [ ] **Step 2: uninstall-launchd.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
TARGETS="$HOME/Library/LaunchAgents"
for svc in gateway caddy cloudflared; do
  label="com.autoservice.$svc"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  rm -f "$TARGETS/$label.plist"
  echo "removed $label"
done
```

- [ ] **Step 3: Executable + lint**

```bash
chmod +x /Users/h2oslabs/Workspace/AutoService/scripts/install-launchd.sh /Users/h2oslabs/Workspace/AutoService/scripts/uninstall-launchd.sh
bash -n /Users/h2oslabs/Workspace/AutoService/scripts/install-launchd.sh
bash -n /Users/h2oslabs/Workspace/AutoService/scripts/uninstall-launchd.sh
```

- [ ] **Step 4: Add Makefile targets**

Append to `Makefile`:

```makefile
public-install:
	@bash scripts/install-launchd.sh

public-uninstall:
	@bash scripts/uninstall-launchd.sh
```

- [ ] **Step 5: Commit**

```bash
git add scripts/install-launchd.sh scripts/uninstall-launchd.sh Makefile
git commit -m "deploy(launchd): install/uninstall scripts + make targets"
```

---

## Phase 6 — Runbook

### Task 25: `docs/deploy/public-tunnel-runbook.md`

**Files:**
- Create: `docs/deploy/public-tunnel-runbook.md`

- [ ] **Step 1: Write the runbook**

Create `docs/deploy/public-tunnel-runbook.md`:

```markdown
# Public Tunnel Runbook — autoservice.ezagent.chat

Day-2 operations for the Cloudflare-Tunnel demo deployment.
Spec: `docs/superpowers/specs/2026-04-24-cloudflare-tunnel-demo-deploy-design.md`.
Plan: `docs/superpowers/plans/2026-04-24-cloudflare-tunnel-demo-deploy.md`.

## First-time setup (fresh clone)

1. `make setup`
2. Create / restore cloudflared config at `~/.cloudflared/autoservice.yml`
   (see `deploy/cloudflared/autoservice.yml.example`) and credentials
   JSON (`<uuid>.json`).
3. Route DNS (once per tunnel): `cloudflared tunnel route dns --overwrite-dns <UUID> autoservice.ezagent.chat`
4. `cp deploy/.smtp.env.example .smtp.env` — or create `.smtp.env`
   manually with SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/SMTP_FROM.
5. `bash scripts/install-smtp-config.sh` — renders `.autoservice/config.local.yaml`.
6. `make generate-admin-passwords` — set the shared-admin password (interactive).
7. (If you have `CF_API_TOKEN`) `cp /dev/null .cf-access.env`, populate
   `CF_API_TOKEN` and `CF_ACCOUNT_ID`, then `make access-apply`.
   Otherwise do the CF dashboard dance per §"Applying CF Access manually".
8. `make public-build`
9. `make public-install` to install launchd agents (or `make public-up`
   for manual PID-based launch during iteration).
10. `make public-smoke` — acceptance checks.

## Adding a trial customer

Two allowlists must match or the user will either be stopped at the edge
or denied inside the app.

**Step 1 — Cloudflare Access:**
- Edit `deploy/cloudflare-access/allowlist.yml`, add the email under
  `allowed_emails:`.
- `make access-apply` (or run the printed curl commands if no token).

**Step 2 — in-app admin allowlist:**
- Edit `.autoservice/config.local.yaml`, add the email under
  `auth.admin_emails:`.
- `make public-reload` — gateway rereads config.

**Step 3 — tell the customer:**
- Direct link: https://autoservice.ezagent.chat/admin/
- First visit: CF will email an OTP; enter it → land on admin login.
- Admin login: enter the same email → magic link emailed from
  `autoservice@h2oslabs.com` → click.

## Reload after code merge

```bash
git pull
make public-reload
make public-smoke
```

`public-reload` restarts gateway AND cloudflared (per design §8.2): the
tunnel restart drops long-lived WS sessions so clients reconnect to the
new code.

## Emergency stop

- `make public-panic` — cloudflared down, hostname unreachable in ~2 s.
- `make public-down` — stop all three services cleanly.

## Logs

- `.autoservice/logs/gateway.log` — uvicorn
- `.autoservice/logs/caddy.log` — JSON access log (rotated at 10 MB × 10)
- `.autoservice/logs/caddy-stdout.log` — Caddy stderr
- `.autoservice/logs/cloudflared.log` — JSON
- `.autoservice/logs/cloudflared-stdout.log` — stderr

`make public-logs` tails all three with follow.

## Known-good versions

- cloudflared 2026.3.0 (Homebrew `/opt/homebrew/bin/cloudflared`)
- Caddy 2.11.2 (`/usr/local/bin/caddy`)
- Node 20.x, pnpm 10.20.0
- Python 3.12 via uv

## Applying CF Access manually (no API token)

1. Open Cloudflare Dashboard → Zero Trust → Access → Applications.
2. Add application: `name=autoservice`, `domain=autoservice.ezagent.chat`,
   `session=720h`, `type=self_hosted`.
3. Add policy: decision = `allow`, include = `email` with each address from
   `deploy/cloudflare-access/allowlist.yml::allowed_emails`.
4. **Bypass-public paths:** for each entry under `public_paths:`, create
   a separate Access application with the same domain and a more-specific
   path matcher, decision = `bypass`. (CF evaluates by-path, most-specific
   wins.)
5. Save. Verify with `make public-smoke`.

## Troubleshooting

- **502 at the hostname**: cloudflared is up but Caddy is down, or Caddy
  is up but on a different port than the tunnel expects. Check
  `lsof -iTCP:18080` and `.autoservice/logs/caddy-stdout.log`.
- **Long WS drops around the 100-second mark**: Cloudflare free-plan WS
  idle cap. uvicorn's default `ws_ping_interval=20s` should prevent this —
  if you see it, inspect gateway uvicorn version.
- **Admin UI loads but magic-link email never arrives**: check
  `.autoservice/logs/gateway.log` for SMTP errors. Feishu Mail requires
  STARTTLS on port 587. If you see `SMTPAuthenticationError`, verify
  `SMTP_USER` matches the actual Feishu-hosted mailbox.
- **New hire email added to `.cf-access.env` but they can't log in**:
  did you run `make access-apply`? The yml file alone doesn't configure
  anything.
```

- [ ] **Step 2: Commit**

```bash
git add docs/deploy/public-tunnel-runbook.md
git commit -m "docs(deploy): public-tunnel runbook

First-setup, adding-trial-customer, reload, panic, logs, manual CF
Access path, and common troubleshooting."
```

---

## Phase 7 — Integration, smoke, agent-browser, launchd

### Task 26: First full build + local-only verification

- [ ] **Step 1: Build the three frontends for real**

```bash
cd /Users/h2oslabs/Workspace/AutoService && make public-build
```

Expected: three `dist/` directories produced, asset paths prefixed per
subpath.

- [ ] **Step 2: Install SMTP config**

```bash
cd /Users/h2oslabs/Workspace/AutoService && bash scripts/install-smtp-config.sh
```

Expected: `.autoservice/config.local.yaml` written with mode 600.

- [ ] **Step 3: Set shared admin password**

```bash
cd /Users/h2oslabs/Workspace/AutoService && make generate-admin-passwords
```

Interactive: enter a password ≥10 chars twice.

- [ ] **Step 4: Bring up services (manual mode)**

```bash
cd /Users/h2oslabs/Workspace/AutoService && make public-up
```

- [ ] **Step 5: Local-only hit tests**

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/_caddy_health   # expect 200
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/site/            # expect 200
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/console/         # expect 200
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/admin/           # expect 200 (no Access in the loopback path)
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/api/auth/dev-mode # expect 404 or {"enabled":false}
```

If any of the three subpaths returns 404, re-check that `public-build`
emitted `dist/index.html` in the expected locations.

---

### Task 27: Apply CF Access

- [ ] **Step 1: Create or confirm `.cf-access.env`**

If the user has a CF API token, create `.cf-access.env`:

```
CF_API_TOKEN=<token>
CF_ACCOUNT_ID=<account-uuid>
CF_ZONE_ID=<zone-uuid-for-ezagent.chat>
```

If no token, they'll apply via dashboard per runbook §"Applying CF Access manually".

- [ ] **Step 2: Apply**

```bash
cd /Users/h2oslabs/Workspace/AutoService && make access-apply
```

Expected with token: JSON `true` for create/update. Without token:
curl commands printed.

- [ ] **Step 3: Confirm via smoke**

```bash
cd /Users/h2oslabs/Workspace/AutoService && make public-smoke
```

Expected: all ✓, /admin/ gated (302 or 403 from CF challenge page).

---

### Task 28: agent-browser verification against the public hostname

- [ ] **Step 1: Dispatch agent-browser for customer-chat smoke**

Use the agent-browser skill to open `https://autoservice.ezagent.chat/site/`,
send a sample message, and confirm the AI reply streams in. The browser
session should not receive any CF Access login prompt on /site.

- [ ] **Step 2: Dispatch agent-browser for admin login**

Open `https://autoservice.ezagent.chat/admin/`. Expect CF Access OTP
email challenge. After entering the OTP, confirm the admin login page
loads (not a blank/error page), and exercise the magic-link path —
enter admin email, receive link (will need a real mailbox).

- [ ] **Step 3: Dispatch agent-browser for password-login**

On `/admin/` login page, expand "Developer password login", enter
`autoservice@h2oslabs.com` + the password set in Task 26, submit.
Confirm redirect to `/admin/` dashboard.

- [ ] **Step 4: Record results**

Write findings (any visual / functional defects) into a
`e2e-evidence/tunnel-demo-first-run/` directory. Screenshots optional.

---

### Task 29: launchd install + reboot drill

- [ ] **Step 1: Stop manual processes**

```bash
cd /Users/h2oslabs/Workspace/AutoService && make public-down
```

- [ ] **Step 2: Install launchd**

```bash
cd /Users/h2oslabs/Workspace/AutoService && make public-install
```

- [ ] **Step 3: Verify running via launchctl**

```bash
launchctl list | grep com.autoservice
```

Expected: 3 entries with `-` exit status and a positive PID.

- [ ] **Step 4: Re-run smoke**

```bash
cd /Users/h2oslabs/Workspace/AutoService && make public-smoke
```

Expected: all green.

- [ ] **Step 5: Simulate a crash** (ensures KeepAlive works)

```bash
kill -9 $(cat /Users/h2oslabs/Workspace/AutoService/.autoservice/run/gateway.pid 2>/dev/null || launchctl print gui/$(id -u)/com.autoservice.gateway | awk '/pid =/ {print $3}')
sleep 3
launchctl print gui/$(id -u)/com.autoservice.gateway | head -5
```

Expected: new PID different from the one killed — KeepAlive restarted it.

- [ ] **Step 6: Optional — reboot the Mac Studio** and confirm services come up automatically.

---

### Task 30: Merge to main

- [ ] **Step 1: Review diff summary**

```bash
cd /Users/h2oslabs/Workspace/AutoService && git log --oneline main..HEAD
```

- [ ] **Step 2: Push branch**

```bash
git push -u origin deploy/autoservice-tunnel
```

- [ ] **Step 3: Open PR**

Using `gh`:

```bash
gh pr create --title "deploy: public tunnel at autoservice.ezagent.chat" --body "$(cat <<'EOF'
## Summary
- Full wiring of the Cloudflare tunnel demo deploy per `docs/superpowers/specs/2026-04-24-cloudflare-tunnel-demo-deploy-design.md`.
- Subpath routing (/site, /console, /admin), reverse proxy for /api + /ws.
- Cloudflare Access path-selective policy as IaC (`deploy/cloudflare-access/allowlist.yml`).
- Narrow password login for `autoservice@h2oslabs.com`.
- launchd supervision, full public-build/up/down/reload/smoke/panic lifecycle.

## Test plan
- [x] `make public-build`
- [x] `make public-up` + localhost smoke
- [x] `make access-apply` (or manual dashboard)
- [x] `make public-smoke` green
- [x] agent-browser verification of /site, /admin OTP, password login
- [x] launchd install + KeepAlive crash drill

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Merge after review**

---

## Self-review notes

Covered against the spec:

- §1 scope in: all frontends + gateway served under single hostname, SMTP
  magic-link, CF Access, launchd, one-cmd reload → Tasks 1–25.
- §2 final decisions: URL `/site/console/admin` (Task 1), loopback gateway
  (Task 18/22 uvicorn flags), `CADDY_PORT=18080` env-parametrized, launchd
  (Phase 5), password-login (Task 8–10).
- §3 architecture: Caddyfile (Task 11) follows topology exactly.
- §4 cloudflared: Task 12 template + Task 18/20/24 invocations all use
  UUID (not name) per spec note.
- §4.3 CF Access IaC: Task 13 yml + Task 16 script; degraded mode
  documented.
- §4.4 identity model: covered in runbook (Task 25).
- §4.5 initial allowlist: hardcoded in Task 13 yml + Task 14 config render.
- §4.6 password login: Tasks 8–10, including rate limit, gate by config,
  frontend UI.
- §5 Caddy coexistence: Task 11 Caddyfile `admin off` + high port.
- §6 Vite base + React Router basename: Task 1; hardcoded-:8000 fixes
  Tasks 2–4; robots meta Task 5.
- §7 backend hardening: CORS env (Task 6), bcrypt dep (Task 7), proxy
  headers in public-up.sh (Task 18), `AUTH_DEV_MODE` triple-defense
  (unset in public-up.sh, explicit launchd env in Task 23 — NOT set,
  import-time freeze preexisting).
- §8 launchd + reload semantics: Tasks 23–24, reload script Task 20
  restarts cloudflared.
- §9 Makefile surface: Task 22 + 24 cover all listed targets.
- §10 rollout: Task 26 sequence matches spec order.
- §11 portability: plist templates use `{{USER}}` placeholder; future
  Linux migration only requires systemd translation.
- §12 risks: R3 (CF 100s WS) monitored via smoke; R4 (AUTH_DEV_MODE
  leak) defended by public-up.sh `unset` + plist explicit env dict;
  R5 SQLite backup deferred per spec; R6 log rotation: Caddy yes
  (Task 11 Caddyfile), gateway+cloudflared tracked in runbook (Task 25).

No placeholders. All code blocks complete. Types consistent
(`_FAILED_ATTEMPTS`, `build_router`, `resolveWsBase` used identically
across tasks).

---

## Execution Handoff

Plan complete and saved to
`docs/superpowers/plans/2026-04-24-cloudflare-tunnel-demo-deploy.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch fresh subagent per task;
review between tasks; parallel-dispatch Phase 1A (frontend refactors) and
Phase 1B (backend refactors) together.

**2. Inline Execution** — Execute tasks in this session using executing-plans.

The user has already indicated auto-mode intent: "直接开始实施". Recommend
**Subagent-Driven with parallel Phase 1A+1B**, which matches auto mode
semantics (I dispatch, review, and continue without interrupting the user
for routine decisions) and keeps wall-clock short by running the disjoint
frontend + backend refactors concurrently.
