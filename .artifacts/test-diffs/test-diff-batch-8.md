# Test diff: batch-8 (P5 auth gating)

新增 **16 tests** across **2 new files** covering T5B.5 / T5B.6, plus **2 updated tests** in `tests/api/test_session_mode.py` to match the M2 shape. Related eval-doc: `eval-doc-010`.

## 新增文件

- `tests/auth/test_require_tenant_access.py` — 11 tests for `auth.require_tenant_access` + `require_tenant_access_for` (T5B.5).
- `tests/auth/test_session_mode.py` — 5 tests for the extended `/api/session/mode` shape (T5B.6).

## 修改文件

- `tests/api/test_session_mode.py` — 2 tests refactored from M1 `{mode, role}` shape to M2 AuthGate shape (same file, same count; assertion set updated). This is a legitimate contract-shape change, not a regression patch.

## 覆盖的场景

Cross-referenced from `eval-doc-010` §验收标准:

**T5B.5 — require_tenant_access (11 tests)**
- `test_anon_no_cookie_returns_401` — no cookie → 401 `{"error": "unauthenticated"}`.
- `test_invalid_session_cookie_returns_401` — cookie value with no matching session row → 401.
- `test_valid_session_matching_tenant_is_allowed` — session.tenant_id == path tenant_id → 200 + AuthContext(tier=1).
- `test_valid_session_cross_tenant_denied_403` — session.tenant_id='acme', path='other' → 403 `{"error": "cross-tenant access denied"}`.
- `test_tier0_session_bypass_any_target` — NULL session.tenant_id → AuthContext(tier=0) + allowed on any target.
- `test_revoked_session_returns_401` — `auth.revoke_session` → cookie replayed → 401 (lookup_session honours revoked_at).
- `test_expired_session_returns_401` — session row with past `expires_at` → 401.
- `test_internal_tenant_prefix_bypass` — session.tenant_id='acme', target='_local_admin' → allowed (spec §5.3 Rule 3: deployment-internal tenants are in-scope for any authenticated admin).
- `test_static_factory_matches_session_tenant` — `require_tenant_access_for("acme")` → session with matching tid → allowed.
- `test_static_factory_denies_mismatch` — `require_tenant_access_for("acme")` → session for "other" → 403.
- `test_no_target_dependency_only_validates_auth` — route with no `tenant_id` path param → middleware only validates auth, returns session ctx.

**T5B.6 — /api/session/mode extension (5 tests)**
- `test_session_mode_anon_master_returns_unauthenticated_shape` — anon in master mode → `{mode:"master", tenant_id:null, authenticated:false, authenticated_as:null, tier:null, brand_name:"AutoService"}`.
- `test_session_mode_master_admin_tier_0` — authenticated with NULL session.tenant_id → `tier:0`, `authenticated_as:<email>`, `brand_name:"AutoService"`.
- `test_session_mode_tenant_admin_tier_1` — session.tenant_id="acme" → `tier:1`, `tenant_id:"acme"`.
- `test_session_mode_brand_name_platform_default_master` — master-mode anon → `brand_name:"AutoService"`.
- `test_session_mode_brand_name_from_tenant_config` — tenant-mode fork with `plugins/acme/config.json["brand_name"]="Acme Corp"` → `brand_name:"Acme Corp"` (config.local.yaml declares `deployment_mode: tenant`).

## 已修 regression bug

None. The 2 updates to `tests/api/test_session_mode.py` reflect the intentional shape change in T5B.6 — the old `{mode, role}` contract is superseded by the M2 AuthGate contract per spec §4.5. All 204 tests across the batch-scope suite (`tests/auth/ tests/bootstrap/ tests/cc_pool/ tests/dream_agent/ tests/dream_runs/ tests/dream_scheduler/ tests/api/ tests/soul_generator/`) remain green.

Pre-existing `tests/test_proposal_pipeline.py` + `tests/contract/` isolation-pollution failures (documented in batch-7 e2e-report) are out-of-scope per the dispatch prompt.

## Spec decisions carried forward

- **Cookie name kept as `auth_session`** (not spec §5.2 `adm_s`).  `auth.AUTH_SESSION_COOKIE_NAME` mirrors `api_routes.AUTH_SESSION_COOKIE` — a single constant in `auth.py` is now the source of truth.  Rename deferred to frontend AuthGate (T6F.2) if needed.
- **`role` field removed** from `/api/session/mode` response — replaced by `tier` + `authenticated_as`.  Frontend M1 code that read `role: "platform_admin"` will need a one-line switch to `tier === 0` in T6F.1.
