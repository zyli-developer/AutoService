# Test diff: batch-1 (Phase 1 · T1B.3 + T1B.4 + T1B.5)

**Backfill · 2026-04-21**
**Commit**: `dc49ff0`
**Source**: `git show dc49ff0 -- tests/`

新增 **11 tests** across 3 files.

## 新增文件

- `tests/bootstrap/test_ensure_master_tenant.py` — **4 tests** (T1B.3)
- `tests/bootstrap/test_ensure_local_admin.py` — **4 tests** (T1B.4)
- `tests/bootstrap/test_lifespan_wire.py` — **3 tests** (T1B.5)

## 覆盖的场景

**T1B.3 `ensure_master_tenant()`** (spec §2.7):
- Full sandbox structure provisioned at `.autoservice/sandbox/_master/`
- M2 fields (`tier=0`, `kind=platform`, `canary.stages=[100]`) present
- 5-role souls written (dry_run → fallback, no LLM at startup)
- Idempotent on re-invocation

**T1B.4 `ensure_local_admin()`** (spec §2.8):
- Provisions at `plugins/_local_admin/` **NOT** sandbox (fork repos have no sandbox concept)
- `kind=fork` (distinguishes from master's `kind=platform`)
- 5 souls provisioned
- Idempotent on re-invocation

**T1B.5 lifespan wire** (spec §1.3):
- master mode → `ensure_master_tenant` called
- tenant mode → `ensure_local_admin` called
- Missing `config.local.yaml` → non-fatal (log + continue)

## 已修 regression bug

- None. All pre-existing tests remain green.
- Internal design improvement: deep-copies `DEFAULT_DREAM_CFG` via JSON round-trip to prevent alias sharing across internal tenants (not a bug fix, defense-in-depth).

## Evidence

- +197 lines across 3 new test files (no modifications to existing tests)
- Commit body: "11 new tests across tests/bootstrap/"
