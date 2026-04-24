# Test diff: batch-5 (Phase 3 · T3B.5 + T3B.6)

**Backfill · 2026-04-21**
**Commits**: `475f32f` (T3B.6) + `21ed7bb` (T3B.5, Yellow)
**Source**: `git diff 475f32f~1..21ed7bb -- tests/`
**Yellow review (T3B.5)**: inline code-reviewer pass, **APPROVED** (concerns 1–5 all PASS, commit body).

新增 **24 tests** across 2 files.

## 新增文件

- `tests/api/test_dream_api.py` — **15 tests** (T3B.6)
- `tests/cc_pool/test_dream_pool_isolation.py` — **9 tests** (T3B.5)

## 覆盖的场景

**T3B.6 `/api/dream/trigger` + `/api/dream/runs`** (spec §2.6):

- `test_trigger_valid_tenant_returns_202_and_run_id` — happy path returns 202 Accepted with `run_id`
- `test_trigger_missing_tenant_id_returns_422` — FastAPI validation
- `test_trigger_empty_tenant_id_returns_422` — empty-string guard
- `test_trigger_nonexistent_tenant_returns_404` — no sandbox/plugin dir
- `test_trigger_accepts_plugin_dir_tenant` — falls back from sandbox to plugins tree
- `test_trigger_concurrent_run_returns_409` — running-row conflict detection
- `test_trigger_allows_retrigger_after_completion` — 409 only while running, not after terminal
- `test_trigger_starts_background_task_not_blocking` — uses `asyncio.create_task`; HTTP returns immediately
- `test_runs_returns_empty_for_unknown_tenant` — empty list, NOT 404 (documented design)
- `test_runs_requires_tenant_id` — query param required
- `test_runs_returns_history_most_recent_first` — ordering by `started_at DESC`
- `test_runs_respects_limit_param` — limit honored
- `test_runs_limit_clamped_to_100` — upper clamp
- `test_runs_limit_clamped_to_min_one` — lower clamp
- `test_runs_serialization_shape` — 10 documented fields per run

**T3B.5 `cc_pool role='dream'`** (spec §2.5, CON-06):

- `test_dream_pool_independent_from_customer` — separate AsyncPool instance; dream checkout does not consume customer slots
- `test_dream_pool_size_one` — cloned PoolConfig min=max=warmup=1
- `test_dream_client_has_dream_soul_system_prompt` — per-tenant dream soul injected as system prompt
- `test_dream_fallback_soul_when_file_missing` — `_FALLBACK_DREAM_SOUL` used when `<tenant>/souls/dream_soul.md` absent
- `test_release_routes_to_correct_pool` — release(role=…) routes back to originating pool
- `test_unknown_role_raises` — defensive: unknown role kwarg → ValueError
- `test_shutdown_closes_both_pools` — lifecycle symmetry
- `test_customer_acquire_backcompat_unchanged` — `role='customer'` default path byte-for-byte unchanged
- `test_dream_tenant_switch_recycles_instance` — single size-1 slot recycled across tenants with new soul

## 已修 regression bug

- None. Zero regression across 59 pre-existing cc_pool / channel / pool-routing tests (T3B.5 verified in review concern #5 "back-compat of acquire(role='customer'): PASS").
- T3B.6: 15 new / 0 regression / 105 total green across tests/api, tests/bootstrap, tests/dream_runs, tests/dream_agent.

## Yellow review (T3B.5, inline)

Commit body records the 5 concerns and their outcomes:
- Concern 1 (pool actually independent): PASS (distinct AsyncPool instances; customer hot-path unchanged)
- Concern 2 (size=1 enforced): PASS (cloned PoolConfig)
- Concern 3 (per-tenant soul injection without cross-contamination): PASS (instance recycled with new system prompt per tenant switch)
- Concern 4 (CON-04 red-line in dream system prompt): PASS ("No self-modification" in fallback, "NEVER auto-apply" propagates from tenant-specific souls)
- Concern 5 (back-compat of acquire(role='customer')): PASS (59 existing tests pass unchanged; signature change additive)

## Evidence

- +745 test lines across 2 new test files
- Commits `475f32f` + `21ed7bb`
