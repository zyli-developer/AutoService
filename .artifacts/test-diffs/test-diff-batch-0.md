# Test diff: batch-0 (Phase 1 · T1B.1 + T1B.2)

**Backfill · 2026-04-21**
**Commits**: `178919c` (T1B.1) + `9def883` (T1B.2, yellow)
**Source**: `git diff 178919c~1..9def883 -- tests/`

新增 **19 tests** across 4 files (+ 2 regression fixes in 1 legacy file).

## 新增文件

- `tests/bootstrap/__init__.py` — new package marker
- `tests/bootstrap/test_get_deployment_mode.py` — **8 tests** (T1B.1)
- `tests/soul_generator/__init__.py` — new package marker
- `tests/soul_generator/test_dream_role.py` — **11 tests** (T1B.2)

## 修改文件

- `tests/test_soul_generator.py` — 2 regression fixes:
  - `test_load_all_templates` now skips dream (no `agents/dream/soul.md` template on disk)
  - `test_save_creates_files` uses `len(AGENT_ROLES)` instead of hardcoded 4

## 覆盖的场景

**T1B.1 `bootstrap.get_deployment_mode` / `get_tenant_id`** (spec §1.3 + §3.1):
- master mode default when `deployment_mode` missing
- master mode explicit
- tenant mode with matching `plugins/<tid>/config.json.tenant_id`
- tenant mode with **mismatched** tenant_id → `AssertionError`
- invalid mode string → `AssertionError`
- `get_tenant_id()` returns None for master
- `get_tenant_id()` returns tenant_id for tenant mode
- dream.* block loadable in schema

**T1B.2 soul_generator 5-role extension** (spec §2.3, CON-04):
- `dream` appended to `AGENT_ROLES`; set == 5 roles
- `_KB_QUERIES["dream"]` present and non-empty
- `_FALLBACK_DREAM_SOUL` constant exists + core markers
- Red-line literal preservation (`test_fallback_dream_soul_preserves_red_line_literal`)
- Brand-neutrality: dream fallback NOT brand-substituted
- Dream `dry_run=True` → fallback routing
- Dream LLM raises → fallback routing
- `generate_souls` covers all 5 roles
- `save_drafts` meta records per-role mode

## 已修 regression bug

- None introduced; 2 legacy `tests/test_soul_generator.py` cases adjusted for role-count extension (not bug fixes, api-shape migrations).
- Yellow review (T1B.2) picked up 2 non-blocking suggestions, implemented inline: red-line lock-in literal test + brand-neutrality test.

## Evidence

- Commit `178919c`: +121 lines across 2 test files
- Commit `9def883`: +152 lines in `test_dream_role.py` (+6/-1 in legacy `test_soul_generator.py`)
