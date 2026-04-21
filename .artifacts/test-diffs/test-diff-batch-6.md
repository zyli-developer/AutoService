# Test diff: batch-6 (Phase 4 · T4B.1 + T4B.2 + T4B.3 — DreamScheduler)

**Backfill · 2026-04-21**
**Commit**: `5d614bc`
**Source**: `git show 5d614bc -- tests/`
**Yellow review (T4B.1)**: inline code-reviewer per CLAUDE.md §6, **APPROVED** (commit body).

新增 **33 tests** across 3 files.

## 新增文件

- `tests/dream_scheduler/__init__.py` — new package marker
- `tests/dream_scheduler/test_should_trigger.py` — **16 tests** (T4B.1, yellow)
- `tests/dream_scheduler/test_scheduler_loop.py` — **10 tests** (T4B.2)
- `tests/dream_scheduler/test_refresh.py` — **7 tests** (T4B.3)

## 覆盖的场景

**T4B.1 `should_trigger`** (spec §2.6 + §9 risk table):

- Manual off-switch always blocks (manual_off mode)
- Scheduled trigger fires within ±10min window
- Scheduled blocks outside window
- Idle trigger fires when `last_message_at` is old enough (default 30min)
- Idle blocks when tenant still active (recent message)
- Legacy `low_peak` alias treated as `idle`
- Cool-down blocks for 60min after last run
- Cool-down expired → allows trigger
- Active `running` row blocks immediately (concurrent-run guard)
- **Meta test** `test_running_check_runs_before_cool_down_check` — rule ordering pinned
- Never-active tenant blocks (coverage gate)
- `coverage=none` blocks
- `risk=high` without recent signal blocks
- `risk=high` with recent signal (proposals_emitted>0 in 30-day window) allows
- Unknown trigger code → safe-default block
- **Meta test** `test_all_emitted_reason_codes_are_in_the_expected_vocabulary` — drift detection over 11-code vocabulary

**T4B.2 scheduler loop** (spec §2.6):

- Discovery includes `_master` + sandbox tenants with `status=='active'`
- Discovery includes `_local_admin` from `plugins/`
- Discovery ignores tenants with missing config.json
- Loop iterates on a short interval and cancels cleanly
- Double-start is no-op
- Stop without start is safe
- Loop spawns `run_dream` for triggerable tenants
- Loop skips non-triggerable tenants
- **Per-tenant error isolation** — a single tenant's exception does not kill the loop
- Stop cancels loop task with no asyncio warning

**T4B.3 `refresh`** (spec §2.6 dynamic reconfig):

- `refresh(tid)` invalidates the target tenant's cached config entry
- Refresh scope is tenant-local (other tenants' cache untouched)
- Module-level `refresh()` no-op when no scheduler registered
- Module-level `refresh()` routes to registered scheduler
- Module-level `refresh()` swallows scheduler errors (log + continue)
- `/dream-config confirm` → `on_config_confirmed` → `refresh(tid)` full integration
- `/dream-config cancel` does NOT call refresh (neutral path)

## 已修 regression bug

- None. Zero regression across 132 pre-existing tests in `tests/bootstrap`, `tests/cc_pool`, `tests/dream_agent`, `tests/dream_runs`, `tests/api`.
- Backward-compat decision: `low_peak` (legacy trigger stored by dream_config_dialog) treated as synonym for spec §2.6 `idle` in `_IDLE_TRIGGERS` set — preserves already-persisted tenant configs without migration.

## Spec ambiguities resolved (recorded in commit body)

1. `low_peak` vs spec §2.6 `idle` — aliased via `_IDLE_TRIGGERS`.
2. Spec §2.2 "simple HH:MM (M2 MVP: within 10 minutes)" — implemented as `scheduled_at HH:MM` + `SCHEDULED_WINDOW_MIN=10`.
3. risk=high signal proxy — uses `dream_runs.proposals_emitted>0` (30-day window) rather than reading proposals table directly; keeps scheduler decoupled from proposal schema.

## Evidence

- +904 test lines across 3 new test files + 1 init.py marker
- Commit body: "33 new tests + 132 regression = zero regressions"
