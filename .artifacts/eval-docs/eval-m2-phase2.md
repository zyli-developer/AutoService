# Eval: M2 Phase 2 — Schema migrations

**Backfill · 2026-04-21 · covers batch-2 (T2B.1 + T2B.2 + T2B.3)**
**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §2.4, §3.7
**Tasks**: [docs/plans/m2/2026-04-20-tasks.yaml](../../docs/plans/m2/2026-04-20-tasks.yaml) T2B.1..T2B.3
**PRD constraints**: CON-03 (SQLite stdlib), CON-05 (tier=0 for internal tenants), CON-07 (no wildcard imports, preserve project conventions)

## 预期行为

- **T2B.1** (spec §2.4) — `autoservice/proposal_pipeline.py` gains `tenant_id TEXT NOT NULL DEFAULT '_master'` on `proposals`.
  - Idempotent `apply_schema(conn)` module helper: fresh DB runs full schema; legacy DB ALTERs when column missing; already-migrated DB is no-op.
  - `idx_proposals_tenant(tenant_id)` index added.
  - `create_proposal(tenant_id=...)` kw-arg; stored proposal dict carries `tenant_id`.
- **T2B.2** (spec §2.4) — `autoservice/memory_pool.py` gains `tenant_id TEXT NOT NULL DEFAULT '_master'` on `memory_turns`.
  - New API: `recent(tenant_id, limit=20)`, `last_message_at(tenant_id)`.
  - `record_turn(tenant_id='_master')` kw-arg for back-compat.
  - `turn_index` counter scoped to `(tenant_id, conversation_id)` — defends against cross-tenant `conversation_id` collisions.
  - 2 tenant indexes + init-order fix (indexes must run after ALTER TABLE on legacy DBs).
  - `DEFAULT_TENANT_ID='_master'` module constant.
- **T2B.3** (spec §2.4 + §3.7) — `autoservice/dream_runs.py` NEW.
  - DB path: `.autoservice/database/dream_runs.db` (aligned with existing convention; divergence from spec §2.4 path `.autoservice/dream/runs.db` documented in commit body).
  - Schema: `id, tenant_id, started_at, ended_at, status ('running'|'completed'|'failed'|'overrun'), tool_calls, tokens_in, tokens_out, proposals_emitted, error`.
  - Index: `idx_dream_runs_tenant(tenant_id, started_at DESC)`.
  - Repository functions take explicit `sqlite3.Connection` (no singleton): `init_schema / open_connection / start_run / update_run / end_run / get_run / list_runs`.
  - `end_run` validates terminal status ∈ {completed, failed, overrun}.

## 验收标准

- [x] `pytest tests/migrations/test_proposals_tenant_id_migration.py` → 6 passed (commit `1f42aa4`, subagent a471feed)
- [x] `pytest tests/migrations/test_memory_pool_tenant_id_migration.py` → 9 passed (commit `1f42aa4`, subagent a5f2cbf)
- [x] `pytest tests/dream_runs/test_dream_runs.py` → 12 passed (commit `1f42aa4`, subagent a869663)
  - 8 required tests + 4 guard tests (invalid status rejected, limit cap, missing get, file-based round-trip).
- [x] Regression: 67 legacy tests across proposal/dream/morning scope — all green, zero regressions.
- [x] Combined batch-2: **27 new + 67 regression = 94 passing, 0 regressions**.

## 关键 invariant

- **Backward-compat (CON-02 / M1 non-destruction)** — All three tables MUST keep M1 rows readable. Achieved by `DEFAULT '_master'` on the new `tenant_id` column so existing rows are attributed to the internal tenant automatically.
- **Idempotency** — `apply_schema` and `init_schema` helpers MUST be safe to run on every startup (fresh, half-migrated, already-migrated). Verified by per-case tests.
- **CON-05** — `'_master'` is the only acceptable default tenant_id for legacy rows because `_master` is the tier=0 platform-internal tenant reserved by the spec.
- **CON-03** — SQLite stdlib `sqlite3` only; no ORMs, no external migration frameworks. All schema changes are plain DDL in Python.
- **Tenant scoping defense** — T2B.2's `(tenant_id, conversation_id)` composite for `turn_index` is an anti-collision invariant; two tenants writing conversations with identical UUIDs (unlikely but formally possible) must not corrupt each other's ordering.
- **Run state machine (dream_runs)** — `end_run` MUST reject non-terminal statuses, enforcing that no run leaves the running state except through one of the three terminal labels.

## Evidence

| Artifact | Location |
|----------|----------|
| Test files | `tests/migrations/test_proposals_tenant_id_migration.py` (6), `tests/migrations/test_memory_pool_tenant_id_migration.py` (9), `tests/dream_runs/test_dream_runs.py` (12) |
| Implementation | `autoservice/proposal_pipeline.py`, `autoservice/memory_pool.py`, `autoservice/dream_runs.py` (new) |
| Commit | `1f42aa4` (three-subagent parallel dispatch) |
| Task status rows | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 2 table |
