# Eval: batch-8 auth gating (T5B.5 / T5B.6)

**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §5.3 (require_tenant_access) + §5.4 (scope table) + §4.5 (AuthGate → /session/mode shape)
**Tasks**: T5B.5 `require_tenant_access` middleware · T5B.6 `/api/session/mode` auth-state extension
**Batch**: batch-8 · Green · serial on `autoservice/auth.py` + `autoservice/api_routes.py` (+ optional web_gateway wiring)
**Related**: `eval-doc-009` (batch-7 auth core); this batch builds the gating layer on top of the sessions/tokens schema it introduced.

## 预期行为

### T5B.5 — `require_tenant_access` (autoservice/auth.py)

- Signature: FastAPI dependency helper, usable via `Depends(require_tenant_access)` on a route (when the tenant comes from path/query) or via a factory `require_tenant_access_for(target_tenant_id)` when the target is known at route-definition time.
- Input:
  - `request: Request` (for cookie + body/path access)
  - `target_tenant_id: str | None` (optional — when absent, dependency only validates auth; when present, it checks scope)
  - `conn` — the shared auth SQLite connection (defaults to `api_routes._get_auth_db()` so tests can inject via `_reset_auth_db_for_tests`)
- Returns `AuthContext` dataclass:
  - `admin_email: str`
  - `tenant_id: str | None` (None ↔ tier 0)
  - `tier: int` (0 for NULL session.tenant_id, else 1)
- Behaviour:
  1. Read cookie `AUTH_SESSION_COOKIE` (= `auth_session`, batch-7 name kept — see reconciliation note below).
  2. No cookie / unknown / expired / revoked session → `HTTPException(401, detail={"error": "unauthenticated"})`.
  3. Session.tenant_id IS NULL (tier-0 / `_master` / `_local_admin` internal admin) → **bypass**: always allow regardless of `target_tenant_id`.
  4. Session.tenant_id == `target_tenant_id` → allow.
  5. `target_tenant_id` starts with `_` (internal tenant like `_master` / `_local_admin`) → allow (spec §5.3 Rule 3 — same deployment's internal tenant is considered in-scope for any authenticated admin).
  6. Otherwise → `HTTPException(403, detail={"error": "cross-tenant access denied"})`.
- Side effect: sets `request.state.auth = AuthContext(...)` so downstream handlers can read it without re-querying.

### T5B.6 — `/api/session/mode` extension (autoservice/api_routes.py)

Current (batch-7-era) shape: `{mode: "master", role: "platform_admin"}`.

**New shape — unchanged keys plus 4 auth-state keys, spec §4.5**:

```json
{
  "mode": "master" | "tenant",
  "tenant_id": "<tid>" | null,
  "authenticated": bool,
  "authenticated_as": "<admin_email>" | null,
  "tier": 0 | 1 | null,
  "brand_name": "<string>"
}
```

Derivation rules:
- `mode` — read from `bootstrap.get_deployment_mode()` (defaults `master` on missing config).
- `tenant_id` — `bootstrap.get_tenant_id()` in tenant mode, else `null`.
- `authenticated` — `True` iff cookie is present AND `auth.lookup_session` returns a row.
- `authenticated_as` — `session.admin_email` when authenticated, else `null`.
- `tier` — `0` when session.tenant_id IS NULL, `1` when non-NULL, `null` when unauthenticated.
- `brand_name` — resolution chain:
  1. **Tenant mode**: read `plugins/<self_tid>/config.json["brand_name"]`; fall back to `"AutoService"`.
  2. **Master mode, tenant session**: read the corresponding sandbox config if present; fall back to `"AutoService"`.
  3. **Master mode, tier-0 / anon**: `"AutoService"` (platform default).

The endpoint is read-only and always 200 — anon callers see `authenticated: false`, `tier: null`, `authenticated_as: null` + the mode-appropriate `brand_name`.

## 验收标准

### `tests/auth/test_require_tenant_access.py` (~7 tests)

- `test_anon_no_cookie_returns_401` — no cookie → 401 with `{"error": "unauthenticated"}`.
- `test_invalid_session_cookie_returns_401` — cookie value not in sessions table → 401.
- `test_valid_session_matching_tenant_is_allowed` — session.tenant_id == target → 200 + AuthContext populated (tier=1, admin_email set).
- `test_valid_session_cross_tenant_denied_403` — session.tenant_id = "acme", target = "other" → 403 `{"error": "cross-tenant access denied"}`.
- `test_tier0_session_bypass_any_target` — session.tenant_id IS NULL, target arbitrary → allowed, AuthContext.tier == 0.
- `test_revoked_session_returns_401` — `auth.revoke_session` called → cookie presented → 401 (batch-7 `lookup_session` honours `revoked_at IS NULL`).
- `test_expired_session_returns_401` — session row with `expires_at < now` → 401.
- (Bonus) `test_internal_tenant_target_bypass` — session.tenant_id = "acme", target = "_local_admin" → allowed (Rule 3 deployment-internal).

### `tests/auth/test_session_mode.py` (~5 tests)

- `test_session_mode_anon_master_returns_unauthenticated_shape` — no cookie, master mode → `{mode: "master", tenant_id: null, authenticated: false, authenticated_as: null, tier: null, brand_name: "AutoService"}`.
- `test_session_mode_master_admin_tier_0` — authenticated with NULL session.tenant_id → `authenticated_as: "<email>", tier: 0, mode: "master"`.
- `test_session_mode_tenant_admin_tier_1` — authenticated with session.tenant_id = "acme" → `tier: 1, tenant_id: "acme"`.
- `test_session_mode_brand_name_platform_default` — master mode + anon → `brand_name: "AutoService"`.
- `test_session_mode_brand_name_from_tenant_config` — tenant mode (config.local.yaml `deployment_mode: tenant` + `tenant_id: "acme"` + `plugins/acme/config.json` with `brand_name: "Acme"`) → `brand_name: "Acme"`.

### Regression

Full batches 0–7 remain green:
```
python -m pytest tests/auth/ tests/bootstrap/ tests/cc_pool/ tests/dream_agent/ \
                 tests/dream_runs/ tests/dream_scheduler/ tests/api/ tests/soul_generator/
```
Expected: 188 + 12 new = 200 passing / 0 failing (pre-existing `tests/test_proposal_pipeline.py` / `tests/contract/` isolation-pollution failures are out-of-scope per batch-7 report).

## 关键 invariant

- **CON-05 tier=0 reservation** ([m2-task-hints.yaml](../../docs/plans/m2/2026-04-20-m2-task-hints.yaml)) — tier 0 is reserved for `_master` (master deployment) / `_local_admin` (tenant fork) internal administrators only. NULL session.tenant_id is the canonical signal; no other tier→0 derivation path exists. `require_tenant_access` MUST NOT grant tier-0 bypass to a non-NULL tenant_id even if the admin_email matches a known platform admin — the SESSION's tenant_id is authoritative.
- **Anon MUST NOT see other tenants' scope** — `/api/session/mode` for an unauthenticated caller MUST return only the self-descriptive fields (`mode`, `tenant_id` if in fork mode, default `brand_name`) and MUST NOT enumerate other tenants. `authenticated` / `authenticated_as` / `tier` are all `false` / `null` for anon callers.
- **Cross-tenant denial is 403, not 404** — a known-but-forbidden tenant_id returns 403 with a clear error so the frontend can distinguish "you can't access this" from "doesn't exist". 401 is reserved for "I don't know who you are".
- **Internal-tenant prefix exception** (spec §5.3 Rule 3) — `target_tenant_id.startswith("_")` implies deployment-internal; any authenticated session can access it. This is how a tier-1 fork admin reaches `_local_admin` in ChatTab without being tier-0.
- **Session revocation is immediate** — calling `auth.revoke_session` invalidates the cookie on the very next request. `lookup_session` already enforces `revoked_at IS NULL`; middleware MUST NOT short-circuit with its own cache.
- **Expired session is 401** — `lookup_session` already enforces `expires_at > now` so expired sessions fall into the "unauthenticated" bucket; middleware simply honours the None return.
- **Cookie name = `auth_session`** — batch-7 picked `auth_session` where spec §5.2 said `adm_s`. Batch-8 **keeps `auth_session`** and documents the reconciliation explicitly so T6F.2 (frontend AuthGate) lands against a stable name. The spec's `adm_s` value is deferred; no frontend code yet reads `adm_s`. Rename to `adm_s` (if desired) should be a single-line change in `api_routes.AUTH_SESSION_COOKIE` + matching frontend fetch; we pay the token-of-debt now and move on.

## Spec ambiguities resolved

- **Cookie name `auth_session` vs spec §5.2 `adm_s`** — keep batch-7's `auth_session` for now; T6F.2 frontend will read this same constant. Flagged in batch-7 eval-doc as "to be reconciled in T5B.5 / T6F.2" — decision recorded here is **keep `auth_session`**; rename deferred unless a frontend review surfaces a concrete reason.
- **Dependency signature** — spec §5.3 shows a closure-style factory `require_tenant_access(target_tenant_id)`. FastAPI's `Depends` prefers a callable with explicit annotated params. Implementation: expose BOTH — a plain `require_tenant_access(request, target_tenant_id=None, conn=...)` callable that FastAPI's `Depends` can resolve directly (when the route declares `target_tenant_id` as a path/query param we pick it up via `request.path_params`), and a `require_tenant_access_for(target_tenant_id: str)` factory for routes where the target is known statically. The dataclass `AuthContext` is the single return type.
- **`authenticated` vs `authenticated_as` === null** — spec §4.5 TypeScript union uses `authenticated: bool` as the discriminator. We include BOTH the discriminator AND the nullable email field for frontend ergonomics (`authenticated === true` = gate open; `authenticated_as` = display string).
- **`brand_name` lookup in master+tier-0 case** — for master-mode tier-0 session (admin of `_master`), we return `"AutoService"` as the brand (platform itself), NOT `_master`'s config.json brand_name. Rationale: tier-0 is the platform admin; platform brand = `"AutoService"`. Tenant sessions (tier 1) in master mode read from their sandbox config (M3 scope; M2 only has `_master` and optional tenant sessions which we fall back to `"AutoService"` for).
- **Target tenant extraction** — routes using the middleware pass `target_tenant_id` as a path/query/body param; the middleware simply reads `request.path_params.get("tenant_id")` or falls back to `None`. Callers wanting strict scope use the `require_tenant_access_for(tid)` factory which closes over the known id.

## Evidence

| Artifact | Location |
|----------|----------|
| Test files | `tests/auth/test_require_tenant_access.py`, `tests/auth/test_session_mode.py` |
| Implementation | `autoservice/auth.py` (+ `AuthContext`, `require_tenant_access`, `require_tenant_access_for`), `autoservice/api_routes.py` (extended `/api/session/mode`) |
| Task status rows | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 5 table — T5B.5 / T5B.6 |
