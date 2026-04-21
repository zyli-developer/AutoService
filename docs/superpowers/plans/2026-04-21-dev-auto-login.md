# Dev Auto-Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an env-gated dev-only quick login to the admin portal so developers can mint a session cookie (any persona + tenant) with one click, bypassing the 10-minute magic-link loop.

**Architecture:** Two new FastAPI endpoints (`GET /api/auth/dev-mode`, `POST /api/auth/dev-login`) live next to the existing magic-link routes in `autoservice/api_routes.py`. Both gate on a module-level `DEV_MODE_ENABLED` flag read from `AUTH_DEV_MODE=1`. When disabled, dev-mode returns `{enabled:false}` and dev-login returns 404. The frontend `LoginPage.tsx` probes dev-mode on mount and renders a second "Developer quick login" panel when enabled. Session creation reuses `auth.create_session` — no changes to session semantics or the production magic-link flow.

**Tech Stack:** FastAPI + starlette TestClient, sqlite3, pytest (backend). React 18 + Vitest + Testing Library + userEvent (frontend). PyYAML for config. Plain HTML `<datalist>` (no third-party combobox lib).

**Spec:** `docs/superpowers/specs/2026-04-21-dev-auto-login-design.md`

---

## File Structure

**Backend — single file, `autoservice/api_routes.py`:**
- New module-level constant `DEV_MODE_ENABLED` (read once from env).
- New helper `_load_dev_personas()` — reads `auth.dev.personas` from `config.local.yaml`.
- New helper `_scan_dev_tenants()` — scans `plugins/*/config.json`, returns sorted list.
- New endpoint `GET /api/auth/dev-mode`.
- New endpoint `POST /api/auth/dev-login`.
- Reuse existing `_get_auth_db`, `_reset_auth_db_for_tests`, `AUTH_SESSION_COOKIE`, `_DEV_MAIL_LOG`.

**Backend tests — single file, `tests/auth/test_dev_login.py`** (new):
- Reuses the `auth_conn`, `app_client`, `write_config` fixtures from `tests/auth/test_request_login.py` via local copies (tests already duplicate fixtures per-file in this repo).

**Infra:**
- `Makefile` — prepend `AUTH_DEV_MODE=1` to `run-web`.
- `CLAUDE.md` — one-paragraph warning added next to the existing auth section.

**Frontend:**
- `frontend/apps/admin-portal/src/components/auth/LoginPage.tsx` — add probe, dev panel JSX, submit handler, localStorage helpers.
- `frontend/apps/admin-portal/src/__tests__/AuthLoginPage.test.tsx` — add a `describe('dev login', ...)` block.

No new frontend files.

---

## Task 1: Backend — `DEV_MODE_ENABLED` flag + `GET /api/auth/dev-mode` (disabled path)

**Files:**
- Modify: `autoservice/api_routes.py` (add module-level flag + first endpoint)
- Test: `tests/auth/test_dev_login.py` (new)

- [ ] **Step 1.1: Create the failing test file**

Create `tests/auth/test_dev_login.py` with two test cases covering the disabled path:

```python
"""POST /api/auth/dev-login + GET /api/auth/dev-mode tests.

Spec: docs/superpowers/specs/2026-04-21-dev-auto-login-design.md
"""
from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autoservice import api_routes, auth


# ── Fixtures (mirror tests/auth/test_request_login.py) ────────────────────


@pytest.fixture()
def auth_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    auth.apply_schema(conn)
    api_routes._reset_auth_db_for_tests(conn)
    yield conn
    api_routes._reset_auth_db_for_tests(None)
    conn.close()


@pytest.fixture()
def app_client(auth_conn, monkeypatch, tmp_path) -> TestClient:
    monkeypatch.chdir(tmp_path)
    app = FastAPI()
    app.include_router(api_routes.api_router)
    return TestClient(app)


@pytest.fixture()
def dev_mode_off(monkeypatch):
    """Ensure AUTH_DEV_MODE is unset and api_routes reflects that."""
    monkeypatch.delenv("AUTH_DEV_MODE", raising=False)
    importlib.reload(api_routes)


@pytest.fixture()
def dev_mode_on(monkeypatch):
    """Set AUTH_DEV_MODE=1 and reload api_routes so the flag takes effect."""
    monkeypatch.setenv("AUTH_DEV_MODE", "1")
    importlib.reload(api_routes)


@pytest.fixture()
def write_config(tmp_path):
    def _write(yaml_text: str) -> Path:
        cfg_dir = tmp_path / ".autoservice"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        path = cfg_dir / "config.local.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        return path
    return _write


# ── /auth/dev-mode — disabled path ────────────────────────────────────────


def test_dev_mode_endpoint_returns_disabled_when_env_unset(
    dev_mode_off, app_client
):
    r = app_client.get("/api/auth/dev-mode")
    assert r.status_code == 200
    assert r.json() == {"enabled": False}


def test_dev_mode_endpoint_does_not_leak_personas_when_disabled(
    dev_mode_off, app_client, write_config
):
    write_config(
        """\
auth:
  dev:
    personas:
      - secret@dev.local
"""
    )
    r = app_client.get("/api/auth/dev-mode")
    body = r.json()
    assert body == {"enabled": False}
    assert "personas" not in body
    assert "tenants" not in body
```

**Note on fixture ordering:** `dev_mode_off` must run **before** `app_client` (app_client imports api_routes fresh state). pytest resolves fixtures left-to-right in the parameter list, so always list `dev_mode_off` (or `dev_mode_on`) **first**. The `app_client` fixture above does not reload api_routes itself; the env fixtures do.

- [ ] **Step 1.2: Run the tests — they should fail with 404 (endpoint missing)**

```bash
uv run pytest tests/auth/test_dev_login.py -v
```
Expected: both tests FAIL, likely with `assert 404 == 200` because no `/api/auth/dev-mode` route exists.

- [ ] **Step 1.3: Add the module-level flag to `autoservice/api_routes.py`**

Open `autoservice/api_routes.py`. Find the block starting at line 1640 (the `AUTH_SESSION_COOKIE = "auth_session"` line). **Immediately after** the `_DEV_MAIL_LOG` declaration (around line 1643), add:

```python
# Dev auto-login gate (spec docs/superpowers/specs/2026-04-21-dev-auto-login-design.md).
# Read ONCE at import — changing AUTH_DEV_MODE at runtime requires a process restart
# (or importlib.reload in tests). Production images must never set this variable.
DEV_MODE_ENABLED = os.environ.get("AUTH_DEV_MODE") == "1"
```

Verify `os` is already imported at the top of `api_routes.py`; if not, add `import os` to the imports.

- [ ] **Step 1.4: Add the `/auth/dev-mode` endpoint (disabled path only)**

Append the following to `autoservice/api_routes.py` **after** the existing `auth_logout` handler (end of file, after line 1944):

```python
# ---------------------------------------------------------------------------
# Dev auto-login endpoints (spec 2026-04-21-dev-auto-login-design.md)
# ---------------------------------------------------------------------------
#
# Both endpoints are gated by DEV_MODE_ENABLED (env AUTH_DEV_MODE=1).
# When disabled:
#   • GET /auth/dev-mode  → {"enabled": false}   (200)
#   • POST /auth/dev-login → 404 Not Found
# When enabled, see tasks 2 and 3 for the full behaviour.


@api_router.get("/auth/dev-mode")
async def auth_dev_mode() -> Any:
    """Public probe: tells the frontend whether dev-login is available.

    When disabled, the response is intentionally minimal — no personas or
    tenants are leaked. When enabled, returns personas (from config.local.yaml)
    and tenants (scanned from plugins/).
    """
    if not DEV_MODE_ENABLED:
        return {"enabled": False}

    # Enabled path implemented in Task 2.
    return {"enabled": True, "personas": [], "tenants": []}
```

- [ ] **Step 1.5: Run the tests — they should pass**

```bash
uv run pytest tests/auth/test_dev_login.py -v
```
Expected: 2 passed.

- [ ] **Step 1.6: Commit**

```bash
git add autoservice/api_routes.py tests/auth/test_dev_login.py
git commit -m "feat(auth): add DEV_MODE_ENABLED flag + /auth/dev-mode disabled path

Spec: docs/superpowers/specs/2026-04-21-dev-auto-login-design.md §3.1-3.2.
Tests: disabled endpoint returns {enabled:false}; no persona leak."
```

---

## Task 2: Backend — `/auth/dev-mode` enabled path (personas + tenants)

**Files:**
- Modify: `autoservice/api_routes.py` (flesh out endpoint + helpers)
- Test: `tests/auth/test_dev_login.py` (add 4 tests)

- [ ] **Step 2.1: Add failing tests for the enabled path**

Append to `tests/auth/test_dev_login.py`:

```python
# ── /auth/dev-mode — enabled path ─────────────────────────────────────────


def test_dev_mode_personas_fallback_when_config_missing(
    dev_mode_on, app_client
):
    """No config.local.yaml → single-element fallback persona list."""
    r = app_client.get("/api/auth/dev-mode")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["personas"] == ["admin@dev.local"]


def test_dev_mode_personas_from_config(
    dev_mode_on, app_client, write_config
):
    write_config(
        """\
auth:
  dev:
    personas:
      - alice@dev.local
      - bob@dev.local
"""
    )
    r = app_client.get("/api/auth/dev-mode")
    body = r.json()
    assert body["personas"] == ["alice@dev.local", "bob@dev.local"]


def test_dev_mode_tenants_include_master_and_scanned_plugins(
    dev_mode_on, app_client, tmp_path, write_config
):
    """Scans plugins/*/config.json for tenant_id; prepends _master; excludes
    _example by default."""
    write_config("auth:\n  dev: {}\n")

    plugins = tmp_path / "plugins"
    (plugins / "_local_admin").mkdir(parents=True)
    (plugins / "_local_admin" / "config.json").write_text(
        json.dumps({"tenant_id": "_local_admin"}), encoding="utf-8"
    )
    (plugins / "acme").mkdir(parents=True)
    (plugins / "acme" / "config.json").write_text(
        json.dumps({"tenant_id": "acme"}), encoding="utf-8"
    )
    (plugins / "_example").mkdir(parents=True)
    (plugins / "_example" / "config.json").write_text(
        json.dumps({"tenant_id": "_example"}), encoding="utf-8"
    )

    r = app_client.get("/api/auth/dev-mode")
    tenants = r.json()["tenants"]
    assert tenants[0] == "_master"  # always first
    assert "_local_admin" in tenants
    assert "acme" in tenants
    assert "_example" not in tenants  # excluded by default


def test_dev_mode_tenants_include_examples_when_flag_set(
    dev_mode_on, app_client, tmp_path, write_config
):
    write_config(
        """\
auth:
  dev:
    tenant_include_examples: true
"""
    )
    plugins = tmp_path / "plugins"
    (plugins / "_example").mkdir(parents=True)
    (plugins / "_example" / "config.json").write_text(
        json.dumps({"tenant_id": "_example"}), encoding="utf-8"
    )

    r = app_client.get("/api/auth/dev-mode")
    assert "_example" in r.json()["tenants"]
```

- [ ] **Step 2.2: Run the tests — they should fail**

```bash
uv run pytest tests/auth/test_dev_login.py -v
```
Expected: the 4 new tests fail (all see `{"personas": [], "tenants": []}` from the stub).

- [ ] **Step 2.3: Implement the `_load_dev_personas` and `_scan_dev_tenants` helpers**

In `autoservice/api_routes.py`, **immediately after** the existing `_smtp_host()` function (around line 1706), add:

```python
def _load_dev_personas() -> list[str]:
    """Read ``auth.dev.personas`` from config.local.yaml.

    Returns ``["admin@dev.local"]`` when the file, the section, or the list is
    missing so the frontend combobox always has at least one suggestion.
    """
    try:
        from autoservice import bootstrap
        cfg = bootstrap._load_local_config()
    except Exception:
        return ["admin@dev.local"]

    dev_cfg = ((cfg.get("auth") or {}).get("dev") or {})
    personas = dev_cfg.get("personas")
    if not isinstance(personas, list) or not personas:
        return ["admin@dev.local"]
    return [str(p).strip() for p in personas if str(p).strip()]


def _scan_dev_tenants() -> list[str]:
    """Enumerate tenants for the dev-login dropdown.

    Always starts with ``_master`` (the tier-0 built-in, not a plugin
    directory). Then scans ``plugins/*/config.json`` and collects each
    plugin's ``tenant_id`` (falling back to the directory name when
    ``tenant_id`` is absent or not a string).

    ``_example`` is filtered out unless ``auth.dev.tenant_include_examples``
    is truthy in config.local.yaml.
    """
    try:
        from autoservice import bootstrap
        cfg = bootstrap._load_local_config()
    except Exception:
        cfg = {}
    dev_cfg = ((cfg.get("auth") or {}).get("dev") or {})
    include_examples = bool(dev_cfg.get("tenant_include_examples"))

    tenants: list[str] = ["_master"]
    plugins_dir = Path("plugins")
    if plugins_dir.is_dir():
        for child in sorted(plugins_dir.iterdir()):
            if not child.is_dir():
                continue
            cfg_path = child / "config.json"
            tid: str | None = None
            if cfg_path.is_file():
                try:
                    data = json.loads(cfg_path.read_text(encoding="utf-8"))
                    raw = data.get("tenant_id")
                    if isinstance(raw, str) and raw.strip():
                        tid = raw.strip()
                except (json.JSONDecodeError, OSError):
                    tid = None
            if tid is None:
                tid = child.name
            if tid == "_example" and not include_examples:
                continue
            if tid not in tenants:
                tenants.append(tid)
    return tenants
```

- [ ] **Step 2.4: Replace the stub endpoint with the real implementation**

Still in `autoservice/api_routes.py`, **replace** the `auth_dev_mode` handler body added in Task 1.4 (the `return {"enabled": True, "personas": [], "tenants": []}` line) with:

```python
@api_router.get("/auth/dev-mode")
async def auth_dev_mode() -> Any:
    """Public probe: tells the frontend whether dev-login is available.

    When disabled, the response is intentionally minimal — no personas or
    tenants are leaked. When enabled, returns personas (from config.local.yaml)
    and tenants (scanned from plugins/).
    """
    if not DEV_MODE_ENABLED:
        return {"enabled": False}
    return {
        "enabled": True,
        "personas": _load_dev_personas(),
        "tenants": _scan_dev_tenants(),
    }
```

- [ ] **Step 2.5: Run the tests — they should pass**

```bash
uv run pytest tests/auth/test_dev_login.py -v
```
Expected: 6 passed.

- [ ] **Step 2.6: Commit**

```bash
git add autoservice/api_routes.py tests/auth/test_dev_login.py
git commit -m "feat(auth): /auth/dev-mode returns personas + scanned tenants

- personas from auth.dev.personas in config.local.yaml (fallback: admin@dev.local)
- tenants: _master + plugins/*/config.json tenant_id (filters _example by default)"
```

---

## Task 3: Backend — `POST /auth/dev-login` (disabled path → 404)

**Files:**
- Modify: `autoservice/api_routes.py`
- Test: `tests/auth/test_dev_login.py`

- [ ] **Step 3.1: Add the failing test**

Append to `tests/auth/test_dev_login.py`:

```python
# ── /auth/dev-login — disabled path ───────────────────────────────────────


def test_dev_login_returns_404_when_env_unset(
    dev_mode_off, app_client, auth_conn
):
    r = app_client.post(
        "/api/auth/dev-login",
        json={"email": "admin@dev.local"},
    )
    assert r.status_code == 404
    # No session row created.
    rows = auth_conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()
    assert rows["c"] == 0
    # No cookie set.
    assert "auth_session" not in r.cookies
```

- [ ] **Step 3.2: Run the test — it should fail**

```bash
uv run pytest tests/auth/test_dev_login.py::test_dev_login_returns_404_when_env_unset -v
```
Expected: FAIL with `405 Method Not Allowed` or `404` from "route not registered" — but the assertion on sessions/cookie may also fail depending on starlette default. Either way the endpoint doesn't exist yet.

- [ ] **Step 3.3: Add the `/auth/dev-login` endpoint**

Append to `autoservice/api_routes.py`, **immediately after** the `auth_dev_mode` handler:

```python
@api_router.post("/auth/dev-login")
async def auth_dev_login(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> Any:
    """Dev-only: mint a session cookie directly, bypassing magic-link.

    Gated by AUTH_DEV_MODE=1. When disabled, returns 404 to avoid advertising
    the endpoint's existence in production.

    Request body::

        {"email": "<admin@dev.local>", "tenant_id": "<tid>" | null}

    Response (200)::

        {"ok": true, "redirect": "/admin" | "/t/<tid>/admin"}

    Side effects on success:
      • Row inserted into the ``sessions`` table.
      • ``auth_session`` cookie set (HttpOnly, SameSite=Lax, Max-Age = session TTL).
      • WARNING log line + JSONL audit entry.
    """
    if not DEV_MODE_ENABLED:
        return JSONResponse(status_code=404, content={"error": "not found"})

    # Enabled-path implementation in Task 4.
    return JSONResponse(status_code=501, content={"error": "not implemented"})
```

- [ ] **Step 3.4: Run the test — it should pass**

```bash
uv run pytest tests/auth/test_dev_login.py::test_dev_login_returns_404_when_env_unset -v
```
Expected: PASS.

- [ ] **Step 3.5: Commit**

```bash
git add autoservice/api_routes.py tests/auth/test_dev_login.py
git commit -m "feat(auth): /auth/dev-login returns 404 when AUTH_DEV_MODE unset"
```

---

## Task 4: Backend — `POST /auth/dev-login` enabled path (mint session + audit)

**Files:**
- Modify: `autoservice/api_routes.py`
- Test: `tests/auth/test_dev_login.py`

- [ ] **Step 4.1: Add failing tests**

Append to `tests/auth/test_dev_login.py`:

```python
# ── /auth/dev-login — enabled path ────────────────────────────────────────


def test_dev_login_mints_tier0_session_when_tenant_null(
    dev_mode_on, app_client, auth_conn, tmp_path
):
    r = app_client.post(
        "/api/auth/dev-login",
        json={"email": "admin@dev.local", "tenant_id": None},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "redirect": "/admin"}

    rows = auth_conn.execute(
        "SELECT admin_email, tenant_id, revoked_at FROM sessions"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["admin_email"] == "admin@dev.local"
    assert rows[0]["tenant_id"] is None
    assert rows[0]["revoked_at"] is None

    # Cookie set with expected attributes.
    cookie_header = r.headers.get("set-cookie", "")
    assert "auth_session=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=Lax" in cookie_header.replace("samesite=lax", "SameSite=Lax")


def test_dev_login_mints_tier1_session_and_redirects_to_tenant_admin(
    dev_mode_on, app_client, auth_conn
):
    r = app_client.post(
        "/api/auth/dev-login",
        json={"email": "admin@dev.local", "tenant_id": "acme"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "redirect": "/t/acme/admin"}

    row = auth_conn.execute(
        "SELECT tenant_id FROM sessions"
    ).fetchone()
    assert row["tenant_id"] == "acme"


def test_dev_login_empty_tenant_id_treated_as_null(
    dev_mode_on, app_client, auth_conn
):
    r = app_client.post(
        "/api/auth/dev-login",
        json={"email": "admin@dev.local", "tenant_id": "   "},
    )
    assert r.status_code == 200
    assert r.json()["redirect"] == "/admin"
    row = auth_conn.execute("SELECT tenant_id FROM sessions").fetchone()
    assert row["tenant_id"] is None


def test_dev_login_empty_email_returns_400(dev_mode_on, app_client):
    r = app_client.post(
        "/api/auth/dev-login",
        json={"email": "   ", "tenant_id": None},
    )
    assert r.status_code == 400
    assert "email" in r.json()["error"]


def test_dev_login_missing_email_returns_400(dev_mode_on, app_client):
    r = app_client.post("/api/auth/dev-login", json={})
    assert r.status_code == 400


def test_dev_login_writes_audit_jsonl_entry(
    dev_mode_on, app_client, tmp_path
):
    r = app_client.post(
        "/api/auth/dev-login",
        json={"email": "admin@dev.local", "tenant_id": "acme"},
    )
    assert r.status_code == 200

    log_path = tmp_path / ".autoservice" / "logs" / "auth-devmail.jsonl"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == "dev_login"
    assert record["email"] == "admin@dev.local"
    assert record["tenant_id"] == "acme"
    assert "session_id_prefix" in record
    assert len(record["session_id_prefix"]) == 8
    # Full session id must NOT be in the log.
    assert "session_id" not in record
```

- [ ] **Step 4.2: Run the tests — they should fail**

```bash
uv run pytest tests/auth/test_dev_login.py -v
```
Expected: the 6 new tests fail with 501 (stub still in place).

- [ ] **Step 4.3: Replace the stub handler body**

Open `autoservice/api_routes.py`. Replace the `auth_dev_login` handler (the one ending `return JSONResponse(status_code=501, ...)`) with:

```python
@api_router.post("/auth/dev-login")
async def auth_dev_login(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> Any:
    """Dev-only: mint a session cookie directly, bypassing magic-link.

    Gated by AUTH_DEV_MODE=1. When disabled, returns 404 to avoid advertising
    the endpoint's existence in production.

    Request body::

        {"email": "<admin@dev.local>", "tenant_id": "<tid>" | null}

    Response (200)::

        {"ok": true, "redirect": "/admin" | "/t/<tid>/admin"}

    Side effects on success:
      • Row inserted into the ``sessions`` table.
      • ``auth_session`` cookie set (HttpOnly, SameSite=Lax, Max-Age = session TTL).
      • WARNING log line + JSONL audit entry.
    """
    if not DEV_MODE_ENABLED:
        return JSONResponse(status_code=404, content={"error": "not found"})

    email_raw = payload.get("email") if isinstance(payload, dict) else None
    if not isinstance(email_raw, str) or not email_raw.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "email is required"},
        )
    email = email_raw.strip().lower()

    tenant_raw = payload.get("tenant_id") if isinstance(payload, dict) else None
    if isinstance(tenant_raw, str):
        tenant_id = tenant_raw.strip() or None
    else:
        tenant_id = None

    conn = _get_auth_db()
    session_id = auth.create_session(conn, email, tenant_id=tenant_id)

    # Audit: WARNING log + JSONL entry (session id prefix only).
    sid_prefix = session_id[:8]
    logger.warning(
        "[dev-login] minted session for %s (tenant=%s, sid=%s…)",
        email, tenant_id or "_master", sid_prefix,
    )
    _DEV_MAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    audit_record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "dev_login",
        "email": email,
        "tenant_id": tenant_id,
        "session_id_prefix": sid_prefix,
    }
    with _DEV_MAIL_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(audit_record, ensure_ascii=False) + "\n")

    redirect_target = f"/t/{tenant_id}/admin" if tenant_id else "/admin"

    response = JSONResponse(content={"ok": True, "redirect": redirect_target})
    secure_flag = request.url.scheme == "https"
    response.set_cookie(
        key=AUTH_SESSION_COOKIE,
        value=session_id,
        max_age=auth.DEFAULT_SESSION_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=secure_flag,
        path="/",
    )
    return response
```

- [ ] **Step 4.4: Run the full test file — everything should pass**

```bash
uv run pytest tests/auth/test_dev_login.py -v
```
Expected: 13 passed (2 from Task 1, 4 from Task 2, 1 from Task 3, 6 from Task 4).

- [ ] **Step 4.5: Run the pre-existing auth tests to confirm no regression**

```bash
uv run pytest tests/auth/ -v
```
Expected: all prior magic-link tests still green.

- [ ] **Step 4.6: Commit**

```bash
git add autoservice/api_routes.py tests/auth/test_dev_login.py
git commit -m "feat(auth): /auth/dev-login mints session + cookie + audit log

- Reuses auth.create_session (no changes to session semantics).
- WARNING log + JSONL audit entry per mint (session id prefix only).
- Empty/missing email → 400; tier-0 when tenant_id null or blank."
```

---

## Task 5: Infra — Makefile + CLAUDE.md warning

**Files:**
- Modify: `Makefile` (line 16 `run-web` target)
- Modify: `CLAUDE.md` (add warning paragraph near Credentials section)

This task has no tests — it's pure config. Commit once after both edits.

- [ ] **Step 5.1: Update the `run-web` target in `Makefile`**

Current (line 16-18):

```makefile
run-web:
	@mkdir -p .autoservice/logs
	uv run uvicorn channels.web.app:app --host 0.0.0.0 --port $${DEMO_PORT:-8000} --log-level info 2>&1 | tee -a .autoservice/logs/web.log
```

Replace with:

```makefile
run-web:
	@mkdir -p .autoservice/logs
	AUTH_DEV_MODE=1 uv run uvicorn channels.web.app:app --host 0.0.0.0 --port $${DEMO_PORT:-8000} --log-level info 2>&1 | tee -a .autoservice/logs/web.log
```

(Only the `uv run` line changes — `AUTH_DEV_MODE=1` is prepended so the env var is set only for this process.)

- [ ] **Step 5.2: Add a warning to `CLAUDE.md`**

Find the `## Credentials` section in `CLAUDE.md` (search for `## Credentials`). Insert the following **immediately before** it:

```markdown
## Dev Auth Bypass

`AUTH_DEV_MODE=1` enables two dev-only endpoints (`GET /api/auth/dev-mode`,
`POST /api/auth/dev-login`) that let developers mint an admin session without
going through the magic-link flow. **This variable MUST NOT be set in
production, staging, or any shared/networked environment** — it turns the
admin portal into a no-password console for anyone who can reach it.

- `make run-web` sets it automatically for local dev.
- Production Docker/compose/k8s configs must leave it unset.
- Spec: `docs/superpowers/specs/2026-04-21-dev-auto-login-design.md`.

```

(Trailing blank line kept so the existing `## Credentials` header stays separated.)

- [ ] **Step 5.3: Verify the Makefile change with a sanity run (optional — skip if `uvicorn` not available locally)**

```bash
make run-web &
sleep 2
curl -s http://localhost:8000/api/auth/dev-mode
# Expected: {"enabled":true,"personas":[...],"tenants":[...]}
kill %1
```

(If the machine can't bind to port 8000 or `uv` isn't installed, skip — Task 4 tests already cover the code path.)

- [ ] **Step 5.4: Commit**

```bash
git add Makefile CLAUDE.md
git commit -m "chore: wire AUTH_DEV_MODE=1 into make run-web + CLAUDE.md warning"
```

---

## Task 6: Frontend — dev-mode probe + conditional panel rendering

**Files:**
- Modify: `frontend/apps/admin-portal/src/components/auth/LoginPage.tsx`
- Test: `frontend/apps/admin-portal/src/__tests__/AuthLoginPage.test.tsx`

- [ ] **Step 6.1: Add failing tests for the probe behaviour**

Append to `frontend/apps/admin-portal/src/__tests__/AuthLoginPage.test.tsx` (inside a new `describe` block, after the existing one's closing `});`):

```tsx
function devModeOff() {
  return {
    ok: true,
    status: 200,
    json: async () => ({ enabled: false }),
  } as unknown as Response;
}

function devModeOn(
  personas: string[] = ['admin@dev.local'],
  tenants: string[] = ['_master', '_local_admin', 'acme']
) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ enabled: true, personas, tenants }),
  } as unknown as Response;
}

describe('components/auth/LoginPage — dev panel', () => {
  it('does not render the dev panel when dev-mode is off', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
        return Promise.resolve(devModeOff());
      }
      return Promise.resolve(okResponse());
    });
    render(<LoginPage />);
    // Give the probe a tick to resolve.
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/auth/dev-mode')
    );
    expect(screen.queryByTestId('dev-login-panel')).not.toBeInTheDocument();
  });

  it('renders the dev panel with personas + tenants when enabled', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
        return Promise.resolve(
          devModeOn(['alice@dev.local'], ['_master', 'acme'])
        );
      }
      return Promise.resolve(okResponse());
    });
    render(<LoginPage />);
    await waitFor(() =>
      expect(screen.getByTestId('dev-login-panel')).toBeInTheDocument()
    );
    // Email datalist populated.
    const datalist = document.getElementById('dev-login-personas');
    expect(datalist).not.toBeNull();
    expect(datalist?.querySelectorAll('option').length).toBe(1);
    // Tenant select includes "None" + _master + acme + Custom…
    const select = screen.getByTestId(
      'dev-login-tenant-select'
    ) as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toEqual(['', '_master', 'acme', '__custom__']);
  });
});
```

- [ ] **Step 6.2: Run the tests — they should fail**

```bash
cd frontend && pnpm --filter admin-portal test AuthLoginPage
```
Expected: the 2 new tests fail (panel not rendered / `getByTestId('dev-login-panel')` throws).

- [ ] **Step 6.3: Add the probe + conditional panel to `LoginPage.tsx`**

In `frontend/apps/admin-portal/src/components/auth/LoginPage.tsx`:

Replace the imports block (line 19) and the component declaration down to `const busy = status === 'submitting';` (line 78) with the following. Everything from `return (` downward stays untouched **except** for one insertion described in Step 7.2 — for Task 6 we only add the probe + the panel shell.

```tsx
import { useEffect, useState } from 'react';

interface LoginPageProps {
  /**
   * Optional tenant id; when present, the request-login payload carries it
   * so the backend can mint a tier-1 session scoped to the tenant.
   * Admin-portal defaults to null (tier-0 master admin); a fork-deployed
   * tenant-portal will pass its own tid.
   */
  tenantId?: string | null;
}

type Status = 'idle' | 'submitting' | 'sent' | 'error';

interface DevMode {
  enabled: boolean;
  personas: string[];
  tenants: string[];
}

export function LoginPage({ tenantId = null }: LoginPageProps = {}) {
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [devMode, setDevMode] = useState<DevMode>({
    enabled: false,
    personas: [],
    tenants: [],
  });
  const [devEmail, setDevEmail] = useState('');
  const [devTenantChoice, setDevTenantChoice] = useState<string>('');
  const [devTenantCustom, setDevTenantCustom] = useState('');
  const [devStatus, setDevStatus] = useState<
    'idle' | 'submitting' | 'error'
  >('idle');
  const [devError, setDevError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/auth/dev-mode')
      .then((r) => (r.ok ? r.json() : { enabled: false }))
      .then((data) => {
        if (cancelled) return;
        if (data && data.enabled) {
          setDevMode({
            enabled: true,
            personas: Array.isArray(data.personas) ? data.personas : [],
            tenants: Array.isArray(data.tenants) ? data.tenants : [],
          });
        }
      })
      .catch(() => {
        // Probe failure is non-fatal — just keep the dev panel hidden.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const isLocalhost =
    typeof window !== 'undefined' &&
    /^(localhost|127\.0\.0\.1|\[::1\])$/i.test(window.location.hostname);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) {
      setErrorMsg('Please enter your admin email address.');
      setStatus('error');
      return;
    }
    setStatus('submitting');
    setErrorMsg(null);
    const redirect =
      typeof window !== 'undefined'
        ? `${window.location.origin}${tenantId ? `/t/${tenantId}/admin` : '/admin'}`
        : undefined;
    try {
      const resp = await fetch('/api/auth/request-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: trimmed, tenant_id: tenantId, redirect }),
      });
      if (!resp.ok) {
        throw new Error(`request-login ${resp.status}`);
      }
      setStatus('sent');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(msg);
      setStatus('error');
    }
  };

  const busy = status === 'submitting';
```

Now, in the JSX return block, **immediately before** the closing `</div></div>` at the end (i.e., after the existing form-or-sent conditional, still inside the inner white card `<div>`), insert the dev panel shell:

```tsx
        {devMode.enabled ? (
          <div
            data-testid="dev-login-panel"
            style={{
              marginTop: 24,
              paddingTop: 16,
              borderTop: '1px dashed #d0d7de',
            }}
          >
            <div
              style={{
                fontSize: 11,
                color: '#8c959f',
                textTransform: 'uppercase',
                letterSpacing: 0.6,
                marginBottom: 10,
              }}
            >
              Developer quick login
            </div>

            <label
              htmlFor="dev-login-email"
              style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}
            >
              Persona email
            </label>
            <input
              id="dev-login-email"
              list="dev-login-personas"
              type="email"
              data-testid="dev-login-email"
              value={devEmail}
              onChange={(e) => setDevEmail(e.target.value)}
              disabled={devStatus === 'submitting'}
              style={{
                width: '100%',
                padding: '6px 8px',
                fontSize: 13,
                border: '1px solid #d0d7de',
                borderRadius: 6,
                boxSizing: 'border-box',
              }}
            />
            <datalist id="dev-login-personas">
              {devMode.personas.map((p) => (
                <option key={p} value={p} />
              ))}
            </datalist>

            <label
              htmlFor="dev-login-tenant-select"
              style={{ display: 'block', fontSize: 12, fontWeight: 600, marginTop: 10, marginBottom: 4 }}
            >
              Tenant scope
            </label>
            <select
              id="dev-login-tenant-select"
              data-testid="dev-login-tenant-select"
              value={devTenantChoice}
              onChange={(e) => setDevTenantChoice(e.target.value)}
              disabled={devStatus === 'submitting'}
              style={{
                width: '100%',
                padding: '6px 8px',
                fontSize: 13,
                border: '1px solid #d0d7de',
                borderRadius: 6,
                boxSizing: 'border-box',
                background: '#ffffff',
              }}
            >
              <option value="">None (tier-0 master)</option>
              {devMode.tenants.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
              <option value="__custom__">Custom…</option>
            </select>

            {devTenantChoice === '__custom__' ? (
              <input
                data-testid="dev-login-tenant-custom"
                type="text"
                placeholder="tenant_id"
                value={devTenantCustom}
                onChange={(e) => setDevTenantCustom(e.target.value)}
                disabled={devStatus === 'submitting'}
                style={{
                  width: '100%',
                  padding: '6px 8px',
                  fontSize: 13,
                  border: '1px solid #d0d7de',
                  borderRadius: 6,
                  boxSizing: 'border-box',
                  marginTop: 6,
                }}
              />
            ) : null}

            {devError ? (
              <div
                data-testid="dev-login-error"
                role="alert"
                style={{ marginTop: 10, color: '#cf222e', fontSize: 12 }}
              >
                {devError}
              </div>
            ) : null}

            <button
              type="button"
              data-testid="dev-login-submit"
              disabled={devStatus === 'submitting'}
              onClick={() => {
                // Submit logic arrives in Task 7.
              }}
              style={{
                marginTop: 12,
                width: '100%',
                padding: '8px 12px',
                border: '1px solid #6639ba',
                borderRadius: 6,
                background: devStatus === 'submitting' ? '#c5b0e5' : '#6639ba',
                color: '#ffffff',
                fontSize: 13,
                fontWeight: 600,
                cursor: devStatus === 'submitting' ? 'wait' : 'pointer',
              }}
            >
              {devStatus === 'submitting' ? 'Signing in…' : 'Dev login →'}
            </button>
          </div>
        ) : null}
```

- [ ] **Step 6.4: Run the tests — they should pass**

```bash
cd frontend && pnpm --filter admin-portal test AuthLoginPage
```
Expected: 6 tests pass (4 existing + 2 new). The existing 4 may need a small tweak because they don't mock `/api/auth/dev-mode` — see Step 6.5.

- [ ] **Step 6.5: Fix existing tests' mock to tolerate the dev-mode probe**

The 4 existing tests in `AuthLoginPage.test.tsx` use `mockResolvedValueOnce` and expect exactly one call. The probe now fires on mount, so those tests will break. Update the `beforeEach` at the top of the file:

Find this block (around line 39):

```tsx
beforeEach(() => {
  originalFetch = globalThis.fetch;
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
});
```

Replace with:

```tsx
beforeEach(() => {
  originalFetch = globalThis.fetch;
  fetchMock = vi.fn().mockImplementation((url: string) => {
    // Default: dev-mode probe resolves to {enabled:false} so it doesn't
    // interfere with the existing magic-link tests. Individual tests can
    // override via mockImplementation for dev-panel scenarios.
    if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ enabled: false }),
      } as unknown as Response);
    }
    return Promise.reject(new Error('no mock configured for ' + url));
  });
  globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
});
```

Then update the 4 existing tests: swap `fetchMock.mockResolvedValueOnce(okResponse())` for a conditional mock that returns `okResponse()` only for `/api/auth/request-login`. The cleanest rewrite — put this helper near the top of the file (before the `describe` blocks):

```tsx
function mockRequestLogin(response: Response) {
  fetchMock.mockImplementation((url: string) => {
    if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ enabled: false }),
      } as unknown as Response);
    }
    if (typeof url === 'string' && url.includes('/api/auth/request-login')) {
      return Promise.resolve(response);
    }
    return Promise.reject(new Error('no mock configured for ' + url));
  });
}
```

And in each existing test body, replace:
- `fetchMock.mockResolvedValueOnce(okResponse());` → `mockRequestLogin(okResponse());`
- `fetchMock.mockResolvedValueOnce(errResponse(500));` → `mockRequestLogin(errResponse(500));`
- For the "disables the submit button" test that uses a deferred promise: leave the deferred promise pattern but register it via `fetchMock.mockImplementation` filtering on `/request-login` (the dev-mode probe still needs the default mock). Replace:

```tsx
fetchMock.mockImplementationOnce(
  () => new Promise<Response>((res) => (resolveFetch = res))
);
```

with:

```tsx
fetchMock.mockImplementation((url: string) => {
  if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ enabled: false }),
    } as unknown as Response);
  }
  return new Promise<Response>((res) => (resolveFetch = res));
});
```

Finally, adjust the existing happy-path test's assertion `expect(fetchMock).toHaveBeenCalledTimes(1)` to `expect(fetchMock).toHaveBeenCalledWith('/api/auth/request-login', expect.any(Object))` — the call-count assertion is now wrong because the probe also counts.

- [ ] **Step 6.6: Run the whole test file — all should pass**

```bash
cd frontend && pnpm --filter admin-portal test AuthLoginPage
```
Expected: 6 tests pass (4 existing updated + 2 new).

- [ ] **Step 6.7: Commit**

```bash
git add frontend/apps/admin-portal/src/components/auth/LoginPage.tsx frontend/apps/admin-portal/src/__tests__/AuthLoginPage.test.tsx
git commit -m "feat(admin-portal): LoginPage probes /auth/dev-mode + renders dev panel

Panel shell: email combobox, tenant select with None/_master/.../Custom,
disabled button (submit wiring in next commit). Existing magic-link tests
updated to tolerate the new probe fetch."
```

---

## Task 7: Frontend — dev panel submit + localStorage + error handling

**Files:**
- Modify: `frontend/apps/admin-portal/src/components/auth/LoginPage.tsx`
- Test: `frontend/apps/admin-portal/src/__tests__/AuthLoginPage.test.tsx`

- [ ] **Step 7.1: Add failing tests**

Append to the `describe('components/auth/LoginPage — dev panel', ...)` block in `AuthLoginPage.test.tsx`:

```tsx
  it('POSTs to /auth/dev-login with tier-0 body and navigates on success', async () => {
    const assignSpy = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, assign: assignSpy, origin: 'http://localhost:5175' },
    });

    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
        return Promise.resolve(
          devModeOn(['admin@dev.local'], ['_master', 'acme'])
        );
      }
      if (typeof url === 'string' && url.includes('/api/auth/dev-login')) {
        const body = JSON.parse(String(init?.body ?? '{}'));
        expect(body).toEqual({ email: 'admin@dev.local', tenant_id: null });
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ ok: true, redirect: '/admin' }),
        } as unknown as Response);
      }
      return Promise.reject(new Error('unexpected url ' + url));
    });

    const user = userEvent.setup();
    render(<LoginPage />);

    await waitFor(() =>
      expect(screen.getByTestId('dev-login-panel')).toBeInTheDocument()
    );
    await user.type(screen.getByTestId('dev-login-email'), 'admin@dev.local');
    await user.click(screen.getByTestId('dev-login-submit'));

    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith('/admin'));
  });

  it('sends custom tenant_id when "Custom…" is picked', async () => {
    const assignSpy = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, assign: assignSpy, origin: 'http://localhost:5175' },
    });

    let capturedBody: Record<string, unknown> | null = null;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
        return Promise.resolve(devModeOn(['admin@dev.local'], ['_master']));
      }
      if (typeof url === 'string' && url.includes('/api/auth/dev-login')) {
        capturedBody = JSON.parse(String(init?.body ?? '{}'));
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ ok: true, redirect: '/t/ghost/admin' }),
        } as unknown as Response);
      }
      return Promise.reject(new Error('unexpected url ' + url));
    });

    const user = userEvent.setup();
    render(<LoginPage />);
    await waitFor(() =>
      expect(screen.getByTestId('dev-login-panel')).toBeInTheDocument()
    );
    await user.type(screen.getByTestId('dev-login-email'), 'admin@dev.local');
    await user.selectOptions(
      screen.getByTestId('dev-login-tenant-select'),
      '__custom__'
    );
    await user.type(screen.getByTestId('dev-login-tenant-custom'), 'ghost');
    await user.click(screen.getByTestId('dev-login-submit'));

    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith('/t/ghost/admin'));
    expect(capturedBody).toEqual({ email: 'admin@dev.local', tenant_id: 'ghost' });
  });

  it('shows an env-off hint when the backend returns 404', async () => {
    fetchMock.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
        return Promise.resolve(devModeOn());
      }
      if (typeof url === 'string' && url.includes('/api/auth/dev-login')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({ error: 'not found' }),
        } as unknown as Response);
      }
      return Promise.reject(new Error('unexpected url ' + url));
    });

    const user = userEvent.setup();
    render(<LoginPage />);
    await waitFor(() =>
      expect(screen.getByTestId('dev-login-panel')).toBeInTheDocument()
    );
    await user.type(screen.getByTestId('dev-login-email'), 'admin@dev.local');
    await user.click(screen.getByTestId('dev-login-submit'));

    await waitFor(() =>
      expect(screen.getByTestId('dev-login-error')).toBeInTheDocument()
    );
    expect(screen.getByTestId('dev-login-error').textContent).toMatch(
      /AUTH_DEV_MODE/i
    );
  });

  it('pushes successful email to localStorage.recentPersonas (dedup, cap 5)', async () => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, assign: vi.fn(), origin: 'http://localhost:5175' },
    });
    // Seed prior history with 5 entries — oldest should be evicted.
    localStorage.setItem(
      'autoservice.dev.recentPersonas',
      JSON.stringify(['a@x', 'b@x', 'c@x', 'd@x', 'e@x'])
    );
    fetchMock.mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/api/auth/dev-mode')) {
        return Promise.resolve(devModeOn());
      }
      if (typeof url === 'string' && url.includes('/api/auth/dev-login')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ ok: true, redirect: '/admin' }),
        } as unknown as Response);
      }
      return Promise.reject(new Error('unexpected url ' + url));
    });

    const user = userEvent.setup();
    render(<LoginPage />);
    await waitFor(() =>
      expect(screen.getByTestId('dev-login-panel')).toBeInTheDocument()
    );
    await user.type(screen.getByTestId('dev-login-email'), 'new@x');
    await user.click(screen.getByTestId('dev-login-submit'));

    await waitFor(() => {
      const stored = JSON.parse(
        localStorage.getItem('autoservice.dev.recentPersonas') ?? '[]'
      );
      expect(stored).toEqual(['new@x', 'a@x', 'b@x', 'c@x', 'd@x']);
    });
  });
```

Add a cleanup hook at the top-level (below existing `afterEach`, inside the `describe` or at file scope):

```tsx
afterEach(() => {
  localStorage.clear();
});
```

- [ ] **Step 7.2: Run the tests — they should fail**

```bash
cd frontend && pnpm --filter admin-portal test AuthLoginPage
```
Expected: the 4 new tests fail — the button's onClick is a no-op stub.

- [ ] **Step 7.3: Wire up the submit handler + localStorage helper**

In `frontend/apps/admin-portal/src/components/auth/LoginPage.tsx`, add these helpers **above** `export function LoginPage(...)`:

```tsx
const DEV_RECENT_KEY = 'autoservice.dev.recentPersonas';

function readRecentPersonas(): string[] {
  try {
    const raw = localStorage.getItem(DEV_RECENT_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter((v): v is string => typeof v === 'string')
      : [];
  } catch {
    return [];
  }
}

function pushRecentPersona(email: string): void {
  const prev = readRecentPersonas().filter((e) => e !== email);
  const next = [email, ...prev].slice(0, 5);
  try {
    localStorage.setItem(DEV_RECENT_KEY, JSON.stringify(next));
  } catch {
    // ignore quota / disabled storage
  }
}
```

Then, **inside** the `LoginPage` component body, add the submit handler **after** `const busy = status === 'submitting';`:

```tsx
  const onDevSubmit = async () => {
    const trimmedEmail = devEmail.trim();
    if (!trimmedEmail) {
      setDevError('Persona email is required.');
      setDevStatus('error');
      return;
    }
    let tid: string | null;
    if (devTenantChoice === '') {
      tid = null;
    } else if (devTenantChoice === '__custom__') {
      const custom = devTenantCustom.trim();
      tid = custom ? custom : null;
    } else {
      tid = devTenantChoice;
    }
    setDevStatus('submitting');
    setDevError(null);
    try {
      const resp = await fetch('/api/auth/dev-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: trimmedEmail, tenant_id: tid }),
      });
      if (resp.status === 404) {
        setDevError(
          'Dev mode is off on the server. Set AUTH_DEV_MODE=1 and restart.'
        );
        setDevStatus('error');
        return;
      }
      if (!resp.ok) {
        setDevError(`Dev login failed (${resp.status})`);
        setDevStatus('error');
        return;
      }
      const data = await resp.json();
      pushRecentPersona(trimmedEmail);
      if (typeof window !== 'undefined' && data && typeof data.redirect === 'string') {
        window.location.assign(data.redirect);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setDevError(msg);
      setDevStatus('error');
    }
  };
```

Finally, update the dev submit button's `onClick` from the Task 6 placeholder to `onClick={onDevSubmit}`:

Replace:

```tsx
              onClick={() => {
                // Submit logic arrives in Task 7.
              }}
```

with:

```tsx
              onClick={onDevSubmit}
```

Also populate the combobox datalist with the merged recents + server personas. Replace the existing `<datalist id="dev-login-personas">` block from Task 6:

```tsx
<datalist id="dev-login-personas">
  {devMode.personas.map((p) => (
    <option key={p} value={p} />
  ))}
</datalist>
```

with:

```tsx
<datalist id="dev-login-personas">
  {(() => {
    const recent = readRecentPersonas();
    const merged: string[] = [];
    for (const p of [...recent, ...devMode.personas]) {
      if (!merged.includes(p)) merged.push(p);
    }
    return merged.map((p) => <option key={p} value={p} />);
  })()}
</datalist>
```

- [ ] **Step 7.4: Run the tests — all should pass**

```bash
cd frontend && pnpm --filter admin-portal test AuthLoginPage
```
Expected: 10 tests pass (4 existing + 2 Task 6 + 4 Task 7).

- [ ] **Step 7.5: Run any other touched frontend tests to confirm no regression**

```bash
cd frontend && pnpm --filter admin-portal test
```
Expected: full admin-portal suite green.

- [ ] **Step 7.6: Commit**

```bash
git add frontend/apps/admin-portal/src/components/auth/LoginPage.tsx frontend/apps/admin-portal/src/__tests__/AuthLoginPage.test.tsx
git commit -m "feat(admin-portal): dev panel submit + localStorage persona history

- POST /api/auth/dev-login with {email, tenant_id}; navigate to response.redirect.
- Custom tenant input when 'Custom…' picked; empty custom falls back to null.
- 404 response surfaces AUTH_DEV_MODE hint.
- Successful logins push email to autoservice.dev.recentPersonas (dedup, cap 5).
- datalist merges localStorage history with server personas."
```

---

## Task 8: Final integration smoke check

No new code. Manual verification that the feature works end-to-end.

- [ ] **Step 8.1: Start the dev stack**

```bash
make run-web &
sleep 3
cd frontend && pnpm dev:admin &
```

- [ ] **Step 8.2: Probe the backend directly**

```bash
curl -s http://localhost:8000/api/auth/dev-mode | python -m json.tool
```
Expected: `{"enabled": true, "personas": [...], "tenants": ["_master", "_local_admin", "cinnox"]}` (or similar based on your local `plugins/`).

- [ ] **Step 8.3: Verify dev-login mints a session**

```bash
curl -s -i -X POST http://localhost:8000/api/auth/dev-login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@dev.local","tenant_id":null}'
```
Expected: HTTP/1.1 200 OK; `Set-Cookie: auth_session=...; HttpOnly; ...`; body `{"ok":true,"redirect":"/admin"}`.

- [ ] **Step 8.4: Open the admin portal in a browser**

Visit `http://localhost:5175`. Expected:
- The magic-link form is visible.
- Below it, a dashed separator labeled "Developer quick login".
- Email combobox with `admin@dev.local` in the datalist.
- Tenant select with `None (tier-0 master)`, `_master`, `_local_admin`, `cinnox`, `Custom…`.
- Clicking "Dev login →" with email filled lands you at `/admin` (or `/t/<tid>/admin`) already logged in — the `<AuthGate>` does not bounce you back.

- [ ] **Step 8.5: Verify prod-mode negation**

Kill the backend. Restart it **without** the env var:

```bash
kill %1
uv run uvicorn channels.web.app:app --host 0.0.0.0 --port 8000 &
sleep 2
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/auth/dev-mode
# Expected: 200
curl -s http://localhost:8000/api/auth/dev-mode
# Expected: {"enabled": false}
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/api/auth/dev-login -H 'Content-Type: application/json' -d '{}'
# Expected: 404
```

Then reload the admin portal — the dev panel should no longer render.

- [ ] **Step 8.6: Tidy up + stop the dev stack**

```bash
make stop
```

No commit for this task — it's pure verification. If any step fails, stop and fix the underlying code (create a new task).

---

## Self-Review (already performed)

**Spec coverage check:**
- §3.1 env gate → Task 1 (module-level `DEV_MODE_ENABLED`) + Task 5 (Makefile).
- §3.2 `GET /auth/dev-mode` disabled path → Task 1. Enabled path → Task 2.
- §3.2 `POST /auth/dev-login` disabled → Task 3. Enabled → Task 4.
- §3.3 session reuse (same `auth.create_session`) → Task 4 step 4.3.
- §4 config schema (`auth.dev.personas`, `tenant_include_examples`) → Task 2 helpers.
- §5.1 probe → Task 6 useEffect.
- §5.2 UI layout (combobox, tenant select, Custom) → Task 6 JSX.
- §5.3 submit + 404 error + localStorage → Task 7.
- §5.4 test-id hooks → Task 6-7 JSX attributes.
- §6 security: module-level env read (Task 1), 404 not 403 (Task 3), audit log (Task 4), `WARNING` log (Task 4), session-id-prefix only (Task 4), `CLAUDE.md` warning (Task 5).
- §7 testing — all backend + frontend cases mapped to tasks 1-4, 6-7.

**Placeholder scan:** All steps show concrete code; no TBD/TODO/"similar to above". The Task 6 button `onClick` has a placeholder-with-comment that's explicitly replaced in Task 7 Step 7.3 — that's intentional incremental TDD, not a plan-gap.

**Type consistency:** `DEV_MODE_ENABLED` (Python const), `DevMode` (TS interface), `dev-login-panel` / `dev-login-email` / `dev-login-tenant-select` / `dev-login-tenant-custom` / `dev-login-submit` / `dev-login-error` (test-ids) — all used consistently across tasks. `autoservice.dev.recentPersonas` localStorage key — one source in Task 7 helpers, referenced in tests.

No gaps. Plan ready for execution.
