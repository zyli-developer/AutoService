# Test diff: batch-2 (Phase 2 · T2B.1 + T2B.2 + T2B.3, parallel)

**Backfill · 2026-04-21**
**Commit**: `1f42aa4`
**Source**: `git show 1f42aa4 -- tests/`
**Dispatch**: 3-subagent parallel (a471feed, a5f2cbf, a869663) via superpowers:dispatching-parallel-agents; no file overlap.

新增 **27 tests** across 3 files (in 2 new test subtrees).

## 新增文件

- `tests/migrations/__init__.py` — new package marker
- `tests/migrations/test_proposals_tenant_id_migration.py` — **6 tests** (T2B.1, subagent a471feed)
- `tests/migrations/test_memory_pool_tenant_id_migration.py` — **9 tests** (T2B.2, subagent a5f2cbf)
- `tests/dream_runs/__init__.py` — new package marker
- `tests/dream_runs/test_dream_runs.py` — **12 tests** (T2B.3, subagent a869663)

## 覆盖的场景

**T2B.1 `proposals.tenant_id`** (spec §2.4):
- Fresh DB: full schema applied
- Legacy DB: ALTER TABLE adds column with `DEFAULT '_master'` backfill
- Already-migrated DB: no-op
- `apply_schema` idempotent across all three states
- `create_proposal(tenant_id=...)` kwarg writes tenant_id
- Stored proposal dict carries tenant_id
- Backward-compat: existing M1 rows default to `_master`
+ 48 regression passes in proposal/dream/morning scope.

**T2B.2 `memory_pool.tenant_id`** (spec §2.4):
- Fresh DB with tenant_id column
- Legacy DB ALTER TABLE + DEFAULT `_master`
- Tenant-scoped `recent(tid, limit)` returns correct slice
- `last_message_at(tid)` tenant-scoped
- `record_turn(tenant_id='_master')` back-compat kwarg
- `turn_index` counter scoped to `(tenant_id, conversation_id)` prevents cross-tenant collisions
- Init-order bug defense (indexes run after ALTER TABLE on legacy DBs)
- Two tenant indexes created and correctly used
- `DEFAULT_TENANT_ID` module constant exposed
+ 45 regression passes across memory_pool scope.

**T2B.3 `dream_runs.db` schema + repository** (spec §2.4, §3.7):
- 8 required: init_schema, start_run, end_run round-trip, get_run, list_runs, list_runs filter by tenant_id, tokens_in/out captured, proposals_emitted field
- 4 guards: invalid terminal status rejected, `limit` cap enforced, missing `get_run` raises, file-based round-trip (not just in-memory)
- Index `idx_dream_runs_tenant(tenant_id, started_at DESC)` present

## 已修 regression bug

- **T2B.2 internal fix**: init-order bug where tenant indexes ran before ALTER TABLE on legacy DBs. Subagent a5f2cbf corrected schema-helper ordering while making the migration idempotent. No regression caused; defensive correction before it could bite.
- **Combined batch-2**: 27 new + 67 regression = **94 passing, 0 regressions**.

## Evidence

- +743 test lines across 5 files (3 new test files + 2 init.py markers)
- Commit body: "27 new tests + 67 regression tests = 94 passing, 0 regressions"
