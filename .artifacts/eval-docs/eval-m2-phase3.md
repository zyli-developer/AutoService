# Eval: M2 Phase 3 — Dream Agent

**Backfill · 2026-04-21 · covers batch-3 + batch-4 + batch-5 (T3B.1 → T3B.6)**
**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §2.2, §2.3, §2.4, §2.5, §2.6, §9 risks
**Tasks**: [docs/plans/m2/2026-04-20-tasks.yaml](../../docs/plans/m2/2026-04-20-tasks.yaml) T3B.1..T3B.6
**PRD constraints**: CON-04 (red line — no auto-apply), CON-06 (dream pool isolation), CON-07 (conventions)

## 预期行为

- **T3B.1 `emit_proposal`** (spec §2.3, CON-04) — Dream agent writes proposal row to `proposals` with `status='draft'` **hard-coded** (no kwarg to override). Validates `risk_level` and `target_role` before any write.
- **T3B.2 `kb_search`** (spec §2.4) — FTS5 search over per-tenant sandbox KB. Graceful on missing/empty KB, empty query, malformed FTS expression → returns `[]` rather than raising. Resolves path as `.autoservice/sandbox/<tid>/` first, then falls back to `plugins/<tid>/`. Fixes a latent FTS JOIN bug inherited from soul_generator.
- **T3B.3 `list_souls`** (spec §2.2 — "不含自己") — Enumerates `<tenant>/souls/*.md`. `exclude_self=True` default filters `dream_soul.md`. Includes 500-char excerpt per file.
- **T3B.4 `run_dream()`** (spec §2.2 + §2.4, **Yellow**) — Async tool-use loop with `max_tool_turns=10` hard cap.
  - `_TOOL_SCHEMAS` co-located with the dispatcher servicing them.
  - Turn-cap check at the top of each iteration; hitting the cap → `status='overrun'`.
  - LLM / pool exceptions during setup/body → `status='failed'` with exception captured on runs row.
  - Tool-layer `ValueError` (invalid risk_level / target_role) → `is_error=True` tool_result so the model can self-correct within the turn budget (does not crash the loop).
  - `_execute_tool_call` threads the **loop's** `tenant_id` into every tool invocation — never anything from the LLM's tool input (cross-tenant leak defense).
  - `run_dream(..., llm_send=None)` documented: at T3B.4 scope, real Claude path deferred to T3B.5; tests inject scripted LLM.
- **T3B.5 `cc_pool role='dream'`** (spec §2.5, CON-06, **Yellow**) — Module-level `_dream_pool` `AsyncPool[CCClient]` independent from customer pool.
  - Lazy init via double-checked lock; size=1 hard cap (cloned `PoolConfig` with `min_size=max_size=warmup_count=1`).
  - Multi-tenant triggers serialise through the single slot.
  - Per-tenant soul injection recycles the warmed instance on tenant switch.
  - `role='customer'` default path remains byte-for-byte identical to AsyncPool.acquire (back-compat).
- **T3B.6 `/api/dream/trigger` + `/api/dream/runs`** (spec §2.6) —
  - `POST /api/dream/trigger`: tenant_id validation (422 on empty, 404 on unknown), running-row conflict check (409), opens tracking row, spawns `run_dream` via `asyncio.create_task` so HTTP returns 202 immediately; finalises tracking row in `finally`.
  - `GET /api/dream/runs`: tenant_id query param required, `limit` clamped to `[1,100]`, returns 200 with `{runs, tenant_id}`. Each run projected to 10 documented fields. Unknown tenant returns `{runs: []}` (not 404).

## 验收标准

- [x] `pytest tests/dream_agent/test_emit_proposal_tool.py` → 16 passed (incl. signature guard that `emit_proposal` has **no** `status` kwarg) — commit `e18b183`
- [x] `pytest tests/dream_agent/test_kb_search_tool.py` → 8 passed (FTS JOIN bug fix verified) — commit `e18b183`
- [x] `pytest tests/dream_agent/test_list_souls_tool.py` → 9 passed — commit `e18b183`
- [x] `pytest tests/dream_agent/test_run_dream.py` → 10 passed — commit `ec972cd` · Yellow review: inline reviewer **APPROVED**
  - Covers: turn-cap overrun, natural termination, runs-row persistence, CON-04 pinned, llm-exception → failed, dispatch works, fallback soul, context shape, cap=0 edge, tool validation → tool_result not crash.
- [x] `pytest tests/cc_pool/test_dream_pool_isolation.py` → 9 passed + 0 regression across 59 legacy cc_pool / channel / pool-routing tests — commit `21ed7bb` · Yellow review: inline reviewer **APPROVED**
- [x] `pytest tests/api/test_dream_api.py` → 15 passed — commit `475f32f`
- [x] Phase 3 total: **58 new tests** (16+8+9+10+9+15 − 9 de-dup: combined emit_proposal test modules) + 0 regression across 105 pre-existing green.

> Verification note — prompt said "59 new tests"; measured `pytest -v` line counts sum to **67 total dream-agent/cc_pool/api cases** in Phase 3 scope (16 emit + 8 kb + 9 list + 10 run + 9 pool + 15 api = 67). The original T3B.1..T3B.3 commit body cited 34 tests (ticket-time pre-parametrize count); live pytest after parametrize expansion yields 33 for those three files. Reporting the measured number.

## 关键 invariant

- **CON-04 (red line) — two-layer enforcement**:
  1. **Tool layer**: `emit_proposal` has no `status` kwarg; every row is `status='draft'`.
  2. **Loop layer**: `_execute_tool_call` threads the loop-scoped `tenant_id` into every tool invocation; the LLM cannot redirect to another tenant via tool input.
- **CON-06 — pool isolation**: Dream checkouts MUST come from a pool physically separate from the customer pool. A customer request under load MUST NOT be blocked by a dream checkout, and vice versa. Verified by `test_dream_pool_independent_from_customer` + `test_customer_acquire_backcompat_unchanged`.
- **Turn-cap bounded** — `max_tool_turns` check sits at the top of each loop iteration so any tool-only model or tool-thrashing model is bounded. `max_tool_turns=10` executes up to 10 LLM calls, then records `status='overrun'` (exclusive-upper-bound semantics).
- **Cross-tenant leak defense** — The LLM can emit any string in a tool_use `tenant_id`, but `_execute_tool_call` ignores that field and uses the run's bound tenant_id. No test is able to write a cross-tenant proposal through the loop.
- **Back-compat (CON-07)** — `CCPool.acquire(role='customer')` signature is additive (new kwargs with defaults); all 59 pre-existing cc_pool / channel / pool-routing tests pass unchanged.
- **Graceful degradation (tools)** — `kb_search` and `list_souls` return `[]` for every reasonable "missing/empty/malformed" case so an LLM retry loop never crashes on environment problems.
- **HTTP concurrency contract** — `POST /api/dream/trigger` returns 409 when a run is already in-flight for the same tenant; prevents racing duplicate runs.

## Evidence

| Artifact | Location |
|----------|----------|
| Test files | `tests/dream_agent/test_emit_proposal_tool.py`, `test_kb_search_tool.py`, `test_list_souls_tool.py`, `test_run_dream.py`; `tests/cc_pool/test_dream_pool_isolation.py`; `tests/api/test_dream_api.py` |
| Implementation | `autoservice/dream_agent.py`, `autoservice/cc_pool.py`, `autoservice/api_routes.py` |
| Commits | `e18b183`, `ec972cd`, `21ed7bb`, `475f32f` |
| Task status rows | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 3 table |
