# E2E report: batch-8 (P5 auth gating, T5B.5 / T5B.6)

Total: **204 pass / 0 fail** across the batch-scope regression suite.
Related artifacts: `eval-doc-010` (pre-implementation eval), `test-diff-012` (coverage summary). Commit: `98b21ff`.

Command:
```
python -m pytest tests/auth/ tests/bootstrap/ tests/cc_pool/ tests/dream_agent/ \
                 tests/dream_runs/ tests/dream_scheduler/ tests/api/ tests/soul_generator/
```

Result: `204 passed, 40 warnings in 7.22s`.

## New tests (from this batch)

- green: **16**
  - `tests/auth/test_require_tenant_access.py` — 11 tests (T5B.5):
    anon 401, invalid session 401, matching tenant allowed, cross-tenant 403,
    tier-0 bypass, revoked 401, expired 401, internal-tenant "_" prefix bypass,
    static factory match, static factory deny, no-target auth-only.
  - `tests/auth/test_session_mode.py` — 5 tests (T5B.6):
    anon shape, master admin tier=0, tenant admin tier=1, master brand default,
    tenant brand from plugins/<tid>/config.json.
- red: 0

## Regression (preexisting tests)

- green: **188**
  - `tests/auth/` (batch-7 · repository + request-login + verify + logout): 20
  - `tests/bootstrap/` (config + lifespan + master/local-admin bootstrap)
  - `tests/cc_pool/` (role-dispatch + dream pool isolation)
  - `tests/dream_agent/` (run_dream + tool loop)
  - `tests/dream_runs/` (schema + repo)
  - `tests/dream_scheduler/` (should_trigger + scheduler loop + refresh)
  - `tests/api/` (dream trigger / runs; `test_session_mode.py` updated to M2 shape — 2 tests same count but new contract; counted as regression-green because the shape change is an intentional contract bump in T5B.6)
  - `tests/soul_generator/` (5-role souls including dream)
- red: 0

## Contract-shape change

`tests/api/test_session_mode.py` (2 tests) was updated in this batch to assert the M2 AuthGate shape per spec §4.5:

- Before (M1): `{mode, role}` — `role: "platform_admin"` carried auth state.
- After (M2): `{mode, tenant_id, authenticated, authenticated_as, tier, brand_name}` — `tier` + `authenticated_as` supersede `role`.

This is a declared contract bump (T5B.6 deliverable), not a regression. The old `role` field is gone; frontend M1 code that read it will need a one-line switch to `tier === 0` when T6F.1 lands.

## Out-of-scope pre-existing failures (NOT caused by batch-8)

Same as batch-7: `tests/test_proposal_pipeline.py` (10 cases) + 2 `tests/contract/` cases fail due to test-isolation pollution inherited from earlier phases (confirmed pre-existence via `git stash` in the batch-7 report). NOT batch-8 regressions; excluded from verification scope per dispatch prompt.

## Evidence

| Artifact | Location |
|----------|----------|
| Code | `autoservice/auth.py` (+ AuthContext, require_tenant_access, require_tenant_access_for, ~155 lines added), `autoservice/api_routes.py` (extended `/api/session/mode`, ~80 lines added / 10 lines removed) |
| New tests | `tests/auth/test_require_tenant_access.py` (11), `tests/auth/test_session_mode.py` (5) |
| Updated tests | `tests/api/test_session_mode.py` (2; M1→M2 shape bump) |
| Commit | `98b21ff` |
| Task status rows | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 5 table (T5B.5 + T5B.6 → ✅ done), batch-8 row, progress summary (21→23 done, 17→15 pending, 55%→61%), session log |
| Eval-doc | `.artifacts/eval-docs/eval-batch-8-auth-gating.md` (eval-doc-010) |
| Test-diff | `.artifacts/test-diffs/test-diff-batch-8.md` (test-diff-012) |
