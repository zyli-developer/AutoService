# Eval: batch-12 — T7B.1 TenantContext middleware + T7B.2 tenant_root() helper

**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §3.2 + §3.3
**Tasks**: T7B.1 (TenantContext middleware — deployment-mode URL branching) + T7B.2 (`tenant_root()` on-disk path helper)
**Batch**: batch-12 · Phase 7 · both Green · **serial** (T7B.1 consumes T7B.2 indirectly via bootstrap)
**Backend prereqs**:
- batch-0 `get_deployment_mode()` + `get_tenant_id()` live in `autoservice/bootstrap.py`
- batch-1 lifespan startup fires `ensure_master_tenant()` / `ensure_local_admin()` per mode
- batch-8 auth middleware (`require_tenant_access`) assumes `request.state.tenant_id` — middleware here populates it
- `autoservice/master_tenant.py` already has `MASTER_TENANT_ID = "_master"` + `LOCAL_ADMIN_TENANT_ID = "_local_admin"` constants

## 预期行为

### T7B.2 — `tenant_root(tenant_id: str | None) -> Path` (implement FIRST)

New helper added to `autoservice/bootstrap.py`. Returns the correct on-disk root for a tenant's sandbox/fork data regardless of deployment mode.

**Resolution rules (spec §3.3):**

1. **Internal/system tenants (prefix `_`)** — deterministic regardless of mode:
   - `_master` → `PROJECT_ROOT / ".autoservice/sandbox/_master/"`
   - `_local_admin` → `PROJECT_ROOT / "plugins/_local_admin/"`
   - Any other `_`-prefixed tenant ID raises `ValueError` (defensive — only two internal tenants exist today).

2. **Regular tenants** — follow deployment mode:
   - **master mode** (`get_deployment_mode() == "master"`) → `PROJECT_ROOT / ".autoservice/sandbox/<tid>/"`
   - **tenant mode** (`get_deployment_mode() == "tenant"`) → `PROJECT_ROOT / "plugins/<tid>/"`

3. **`tenant_id=None` (fallback)** — calls `get_tenant_id()`:
   - tenant mode → resolves to `get_tenant_id()` then recurses (→ `plugins/<self>/`)
   - master mode → `get_tenant_id()` returns None; helper falls back to `_master` (spec §3.3's "tenant_id == '_master'" branch is the sensible master-default; a request reaching `tenant_root(None)` in master mode has not yet been tenant-scoped by the middleware, and `_master` is the global platform tenant). Documented as a conscious choice — alternative "raise" was rejected because that would punish callers that legitimately want the global/platform default.

4. **`PROJECT_ROOT` derivation** — follows the CON-07 invariant used elsewhere in the codebase (`master_tenant.PROJECT_ROOT`, `cc_pool._PROJECT_ROOT`, etc.): `Path(__file__).resolve().parent.parent`. Exposed as `bootstrap.PROJECT_ROOT` so tests can `monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)` — matches the existing pattern in `tests/bootstrap/test_lifespan_wire.py`.

**Non-goals for T7B.2** (spec §3.3 mentions but defers):
- Archived sandbox fallback (`_newest_archived(tenant_id)`) — not in M2 scope; flagged as future work. Regular master-mode tenant whose sandbox is missing will still return the path (consumers handle `not .exists()`).
- `TenantNotFound` exception — not raised here; callers doing fs operations will get `FileNotFoundError` with a meaningful path in it.

### T7B.1 — TenantContext middleware (spec §3.2)

New `@app.middleware("http")` installed in `autoservice/web_gateway.create_app()`, after the CORS `add_middleware` call (see **middleware placement** below). Populates `request.state` and — in tenant mode — rewrites URLs so the fork's single-tenant runtime can use **URL-flat routes** (spec §3.2 closing "fork 模式 URL-flat" decision).

**Behaviour by mode:**

| Incoming path | Master mode | Tenant mode (`self_tid=acme`) |
|---------------|-------------|-------------------------------|
| `/chat` | pass-through (URL-flat always valid) | pass-through |
| `/admin` | pass-through | pass-through |
| `/t/acme/chat` | pass-through (URL preserved for multi-tenant views) | **rewrites to `/chat`** (strip `/t/<self>`) |
| `/t/bob/chat` | pass-through | **403** (cross-tenant attempt — single-tenant fork cannot serve other tenants) |
| `/t/acme` (no trailing) | pass-through | **rewrites to `/`** |

**State population (both modes):**
- `request.state.deployment_mode = "master" | "tenant"`
- `request.state.tenant_id = <str | None>`:
  - master mode → `None` (per-request tenant is determined by downstream auth/resolver, not the middleware)
  - tenant mode → the self tenant id from `get_tenant_id()`

**Middleware placement (order matters)** — after inspecting the existing `create_app` body: the only `add_middleware` call today is `CORSMiddleware` at line ~205. Starlette runs middleware in **reverse** registration order around the endpoint, so:
- CORS registered first → runs outermost (first on request, last on response)
- Our TenantContext registered **via `@app.middleware("http")` after** the CORS call → runs inside CORS on the request path.

That's what we want: CORS preflight `OPTIONS` responses should not be rewritten by our logic, and any `403` we return should still get CORS headers attached. Decision recorded below in "Spec ambiguities resolved".

**ASGI scope rewrite** — use `request.scope["path"] = new_path`. FastAPI/Starlette re-reads `scope["path"]` on each `request.url.path` access, so downstream routes match against the rewritten path. We do NOT mutate `raw_path` or `query_string`; the query remains intact.

**Early-return for cross-tenant 403** — uses `fastapi.responses.JSONResponse` (already imported elsewhere in the project via `api_routes`), NOT `HTTPException` — because middleware that raises returns a 500 unless wrapped in `except`. Returning a response is the documented FastAPI middleware idiom.

## 验收标准

### tests/fork_runtime/test_tenant_root.py (~6 tests)

| # | Scenario | Expected |
|---|----------|----------|
| 1 | `tenant_root("_master")` in master mode | `PROJECT_ROOT / ".autoservice/sandbox/_master"` |
| 2 | `tenant_root("_master")` in tenant mode | same — internal tenant is mode-agnostic |
| 3 | `tenant_root("_local_admin")` in master mode | `PROJECT_ROOT / "plugins/_local_admin"` |
| 4 | `tenant_root("_local_admin")` in tenant mode | same — internal tenant is mode-agnostic |
| 5 | `tenant_root("acme")` in master mode | `PROJECT_ROOT / ".autoservice/sandbox/acme"` |
| 6 | `tenant_root("acme")` in tenant mode (self=acme) | `PROJECT_ROOT / "plugins/acme"` |
| 7 | `tenant_root(None)` in master mode | `PROJECT_ROOT / ".autoservice/sandbox/_master"` (fallback to `_master`) |
| 8 | `tenant_root(None)` in tenant mode | `PROJECT_ROOT / "plugins/<self>"` |

Fixture pattern: `monkeypatch.chdir(tmp_path)` + `_write_local_cfg(...)` + `monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)` + `bootstrap.get_deployment_mode.cache_clear()` between tests (mirrors `test_get_deployment_mode.py`).

### tests/fork_runtime/test_tenant_context.py (~6 tests)

Builds a FastAPI app via `web_gateway.create_app()` + TestClient. Installs a tiny echo route (`/echo`, `/t/{tid}/echo`, `/chat`, `/t/{tid}/chat`) at runtime using `app.add_api_route()` before TestClient enter, OR just hits existing `/api/session/mode` / custom paths that echo `request.url.path` from state.

| # | Scenario | Expected |
|---|----------|----------|
| 1 | Master + GET `/t/acme/chat` | passthrough — 404 is fine (route may not exist), BUT middleware should NOT rewrite; we assert `request.state.deployment_mode == "master"` via echo endpoint + `request.state.tenant_id is None` |
| 2 | Master + GET `/admin` | passthrough; `deployment_mode == "master"` |
| 3 | Tenant(self=acme) + GET `/t/acme/chat` | rewritten — downstream receives `/chat` (echo endpoint mounted at `/chat`) |
| 4 | Tenant(self=acme) + GET `/t/bob/chat` | 403 JSON `{"error": "cross-tenant access denied ..."}` |
| 5 | Tenant(self=acme) + GET `/chat` (URL-flat) | passthrough to `/chat` |
| 6 | Tenant(self=acme) + GET `/t/acme/echo` — assert `request.state.deployment_mode == "tenant"` + `request.state.tenant_id == "acme"` in the echo body |

Use the same config-fixture pattern as `test_lifespan_wire.py`. Need `monkeypatch.setattr(master_tenant, "PROJECT_ROOT", tmp_path)` too because app startup calls `ensure_master_tenant()` / `ensure_local_admin()` which write to `PROJECT_ROOT`.

## 关键 invariant

- **CON-07 PROJECT_ROOT pattern preserved** — `Path(__file__).resolve().parent.parent` remains the module-level anchor; tests monkeypatch the module attribute.
- **Spec §3.2 fork-side URL-flat** — tenant mode MUST rewrite `/t/<self>/*` → `/*`. Cross-tenant in tenant mode MUST be 403 (spec says 404 in the snippet but current prompt says 403 + error body; we prefer 403 because that distinguishes "you cannot do this here" from "path doesn't exist" and the fork's route table genuinely doesn't know about `/t/bob/...`; 404 would be the downstream FastAPI response if the middleware returned no response and let the request fall through. Flagged below.).
- **Spec §3.3 tenant_root** — internal tenants (`_`-prefixed) are mode-agnostic; regular tenants branch on mode.
- **Zero regression** — batch-8 auth `require_tenant_access` already reads `request.state.tenant_id` but was historically set in `auth.py`'s `get_session` path. Our middleware populates it earlier; `require_tenant_access` should still work. Verified by running `tests/auth/` to completion.
- **Startup order** — middleware must install BEFORE `app.state.engine` is used (it isn't — only `on_event("startup")` hooks touch engine). Our `@app.middleware("http")` decorator can live anywhere between CORS registration and the final `return app`. Slot it right after the existing CORS block for clarity.
- **CORS order** — middleware registered via `@app.middleware("http")` AFTER `add_middleware(CORSMiddleware, ...)` runs **inside** CORS in Starlette's stack. That's the desired order (CORS wraps everything including 403s).
- **CON-03 no new deps** — only uses `fastapi.responses.JSONResponse`, `fastapi.Request`, already in the dep tree.

## Spec ambiguities resolved

- **`tenant_root(None)` in master mode** — spec §3.3 does not say. Decision: return `_master`'s path. Rationale: master-mode callers that don't know a tenant yet are almost always platform-scoped (e.g., ManagementChat, SLA dashboards) and `_master` is the platform-ops tenant by definition (spec §2.7). Alternative "raise" was rejected because T7B.6's ManagementChat would need to special-case `None` immediately, duplicating the `_master` default. Test 7 pins this behaviour.
- **Cross-tenant response code in tenant mode** — spec snippet §3.2 says `Response(status_code=404)`; prompt says 403 with body. Decision: **403 JSON body**. A fork genuinely cannot serve other tenants (capability gap, not missing route); 403 expresses that. Returning a JSON body (not a naked 403 page) matches the rest of the API surface (`api_routes.py` returns structured errors). Documented in the code docstring.
- **Middleware placement vs CORS** — prompt says "must run AFTER CORS". Starlette's middleware stack is reverse-order, so "runs after CORS on the request path" means "registered after CORS" (because registration order is outside→in, and Starlette wraps new middleware inside existing ones). Confirmed by reading Starlette's `Router.__init__` middleware chaining.
- **Path `/t/<self>` (no trailing slash)** — spec §3.2 doesn't call this out. Decision: strip the prefix; result `""` becomes `/`. Covers users who type `/t/acme` without trailing slash and expect the fork's home route.
- **Dream scheduler / CCPool startup** — both fire on `@app.on_event("startup")`. Disable them in the test via `DREAM_SCHEDULER_DISABLED=1` + `POOL_MODE=0` to avoid filesystem side-effects during TestClient startup.

## Evidence

| Artifact | Location |
|----------|----------|
| `tenant_root()` impl | `autoservice/bootstrap.py` (new function) |
| TenantContext middleware | `autoservice/web_gateway.py` (new `@app.middleware("http")` + new helper test route module if needed) |
| T7B.2 tests | `tests/fork_runtime/test_tenant_root.py` |
| T7B.1 tests | `tests/fork_runtime/test_tenant_context.py` |
| Package init | `tests/fork_runtime/__init__.py` |
| Task status row | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 7 — T7B.1 + T7B.2 |

## Future work (flagged)

- **Archived sandbox fallback** (`_newest_archived(tenant_id)`) — spec §3.3 mentions. Defer; add when a task actually needs resolved-from-archive reads.
- **`TenantNotFound` exception** — spec §3.3 mentions. Defer; fs ops surface `FileNotFoundError` with full path today.
- **WebSocket `?tenant=` enforcement** (spec §3.2 closing line) — handled in a later task; current WS endpoints don't route on tenant yet.
