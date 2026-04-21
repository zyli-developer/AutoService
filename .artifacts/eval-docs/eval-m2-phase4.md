# Eval: M2 Phase 4 — DreamScheduler

**Backfill · 2026-04-21 · covers batch-6 (T4B.1 + T4B.2 + T4B.3)**
**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §2.2, §2.6, §9 (risk table — idle/cool-down thresholds)
**Tasks**: [docs/plans/m2/2026-04-20-tasks.yaml](../../docs/plans/m2/2026-04-20-tasks.yaml) T4B.1..T4B.3
**PRD constraints**: CON-04 (red line preserved), CON-06 (dream pool isolation upstream), CON-07 (no PROJECT_ROOT violations, conventions)

## 预期行为

- **T4B.1 `should_trigger(tid, cfg, mempool, runs_db, now=?)`** (spec §2.6, **Yellow**) — Pure decision function gating the cost-bearing `run_dream` call.
  - Returns `(fire: bool, reason_code: str)` from an **11-code vocabulary** (exhaustiveness enforced by meta-test `test_all_emitted_reason_codes_are_in_the_expected_vocabulary`).
  - **Rule ordering** (enforced by `test_running_check_runs_before_cool_down_check` and peer ordering tests):
    1. manual off-switch
    2. already-running (concurrent-run guard)
    3. cool-down (60min default)
    4. coverage gate (never-active tenant blocks)
    5. risk-high soft gate (proposals_emitted>0 in 30-day window)
    6. idle / scheduled branch (idle_threshold=30min, scheduled ±10min window)
  - Defaults match spec §9 risk table: `idle_threshold_min=30`, `cool_down_min=60`, `SCHEDULED_WINDOW_MIN=10`.
  - Backwards-compat alias: dialog stores `low_peak` (legacy) treated as synonym for spec §2.6 `idle` via `_IDLE_TRIGGERS` set.
- **T4B.2 `DreamScheduler`** (spec §2.6) — asyncio loop.
  - Enumerates active tenants (sandbox dirs + `plugins/*/`, filtered `status=='active'`).
  - Evaluates `should_trigger` per tenant; spawns `run_dream` for those that fire.
  - **Never raises** — individual tenant errors are logged + swallowed (a single crashy tenant cannot kill the scheduler).
  - Wired into `web_gateway.py` via `@app.on_event("startup"/"shutdown")`; disabled by `DREAM_SCHEDULER_DISABLED=1` for CI.
  - `start()` idempotent (double-start is no-op); `stop()` without `start()` is safe.
- **T4B.3 `refresh(tid)`** (spec §2.6 dynamic reconfig) —
  - `DreamScheduler.refresh(tid)` + module-level `refresh(tid)`.
  - Called by `dream_config_dialog.on_config_confirmed(tid)` after `/dream-config confirm` persists to disk.
  - Invalidates only the target tenant's cached config entry (other tenants keep their cache).
  - Safe no-op when no scheduler is registered (CLI / test contexts).
  - Cancel path MUST NOT call refresh (idle cancel is neutral).

## 验收标准

- [x] `pytest tests/dream_scheduler/test_should_trigger.py` → 16 passed — commit `5d614bc` · Yellow review: inline reviewer **APPROVED**
  - Manual off / scheduled-window / idle / cool-down / active-run / coverage / risk-high / unknown-trigger branches all covered; 2 meta-tests (rule ordering, reason-code vocabulary drift detection).
- [x] `pytest tests/dream_scheduler/test_scheduler_loop.py` → 10 passed — commit `5d614bc`
  - Discovery (sandbox + plugins), lifecycle (double-start/stop), firing, skipping, per-tenant error isolation, clean cancel.
- [x] `pytest tests/dream_scheduler/test_refresh.py` → 7 passed — commit `5d614bc`
  - Cache invalidation scope, no-scheduler no-op, error swallowing, /dream-config confirm integration, cancel-path-no-refresh.
- [x] Phase 4 total: **33 new tests + 0 regression** across 132 pre-existing green (bootstrap, cc_pool, dream_agent, dream_runs, api).
- [x] Yellow review summary (commit `5d614bc` body): rule ordering correct; default thresholds match spec §9; reason-code vocabulary exhaustive; risk-high fails-open on DB error to prevent permanent gating on a corrupt runs DB.

## 关键 invariant

- **CON-04 upheld upstream** — Phase 4 never bypasses the Dream loop's draft-only contract; it only gates **when** `run_dream` is invoked, never what the loop does. The red line is enforced at the Phase-3 tool + loop layers and is unmodified here.
- **CON-06 upheld upstream** — The scheduler does not change the dream pool sizing or isolation; it just reuses `run_dream` which already routes to the `role='dream'` size-1 pool. Multi-tenant firing events serialise naturally through that single slot.
- **Rule ordering is load-bearing** — The ordering manual → running → cool-down → coverage → risk → idle is an invariant against cost explosion (spec §9 "cc_pool dream client 抢 customer 名额" mitigation). `test_running_check_runs_before_cool_down_check` pins it.
- **Exhaustive reason codes** — Drift in the reason-code vocabulary would silently break dashboards/observability; the vocabulary meta-test is deliberately over-broad so additions require explicit opt-in.
- **Loop robustness** — The scheduler MUST NOT die from a single tenant's config/runs-db corruption. Per-tenant exceptions are logged + swallowed (verified by `test_individual_tenant_error_does_not_kill_loop`).
- **Dynamic reconfig scoping** — `refresh(tid)` mutates only the target tenant's cache; other tenants' cached configs MUST remain valid to avoid thundering-herd reloads.
- **CON-07** — scheduler uses `Path(__file__).resolve().parent.parent` for PROJECT_ROOT detection; no wildcard imports; unrelated code untouched.

## Spec ambiguities resolved

- **`low_peak` vs `idle`** — Dialog persists `low_peak` (legacy); spec §2.6 says `idle`. Treated as aliases in `_IDLE_TRIGGERS` to keep already-persisted tenant configs valid. Documented in commit `5d614bc` body.
- **Scheduled-time format** — Spec §2.2 says "simple HH:MM (M2 MVP: within 10 minutes)". Implemented as `scheduled_at` field parsed as `HH:MM` with ±10min window (`SCHEDULED_WINDOW_MIN=10`).
- **risk=high signal source** — Spec doesn't prescribe. Implemented as `dream_runs.proposals_emitted > 0` within a 30-day window — keeps the scheduler decoupled from the `proposals` table's schema.

## Evidence

| Artifact | Location |
|----------|----------|
| Test files | `tests/dream_scheduler/test_should_trigger.py` (16), `test_scheduler_loop.py` (10), `test_refresh.py` (7) |
| Implementation | `autoservice/dream_scheduler.py` (new), `autoservice/dream_config_dialog.py`, `autoservice/api_routes.py`, `autoservice/web_gateway.py` |
| Commit | `5d614bc` |
| Task status rows | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 4 table |
