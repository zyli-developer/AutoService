# Test diff: batch-4 (Phase 3 · T3B.4 — run_dream agent loop, Yellow)

**Backfill · 2026-04-21**
**Commit**: `ec972cd`
**Source**: `git show ec972cd -- tests/`
**Yellow review**: inline code-reviewer pass, **APPROVED** (superpowers:code-reviewer subagent unavailable at run time — documented in commit body).

新增 **10 tests** in 1 file.

## 新增文件

- `tests/dream_agent/test_run_dream.py` — **10 tests** (T3B.4 run_dream async loop)

## 覆盖的场景

**Spec §2.2 + §2.4 agent loop contract**:

- `test_max_tool_turns_cap_triggers_overrun` — cap (10) hit → `status='overrun'` written to dream_runs
- `test_natural_termination_records_completed` — `end_turn` stop reason → `status='completed'`
- `test_dream_runs_row_persisted` — terminal row written to DB regardless of path
- `test_proposals_are_draft_and_tenant_scoped` — **CON-04 pinned at loop layer** — even with a scripted LLM trying to cross tenants or change status, rows come out `status='draft'` and tenant_id is the loop's bound value
- `test_llm_exception_records_failed` — LLM exception during body → `status='failed'` with exception captured on runs row
- `test_kb_search_and_list_souls_callable_from_loop` — dispatch wiring works end-to-end (not just in tool unit tests)
- `test_fallback_soul_used_when_soul_file_missing` — `_FALLBACK_DREAM_SOUL` constant used when `<tenant>/souls/dream_soul.md` absent
- `test_context_includes_recent_memory_and_history` — initial context shape (recent memory + historical proposals) verified
- `test_zero_max_tool_turns_yields_overrun_immediately` — edge case cap=0; exclusive-upper-bound semantics
- `test_tool_validation_error_becomes_tool_result_not_crash` — tool-layer `ValueError` (invalid risk_level / target_role) surfaces as `is_error=True` tool_result so the model can self-correct within the turn budget — does NOT crash the loop

## 已修 regression bug

- None. 99 regression tests across `tests/bootstrap`, `tests/migrations`, `tests/dream_runs`, `tests/dream_agent` (pre-T3B.4), `tests/soul_generator` all green.
- cc_pool architectural concession documented: `CCPool.acquire()` at T3B.4 time didn't accept `role=` / `tenant_id=` kwargs; `_acquire_dream_client` tries the spec shape and falls back on TypeError with a TODO(T3B.5) marker. Out-of-scope to modify cc_pool here; production callers must supply an `llm_send` closure until T3B.5 lands (which it does in batch-5).

## Yellow review (inline)

Commit body records the reviewer pass:
- Red-line CON-04 preserved at both tool layer (status hard-coded) and loop layer (tenant_id threaded from loop, never from LLM input)
- Turn-cap exclusive-upper-bound semantics verified by scripted-LLM tests
- All Important findings addressed; Minor findings (unused `DREAM_MODEL` constant, cosmetic formatting) deferred to T3B.5
- One docstring fix applied during review (run_dream.llm_send param doc now states `None` unsupported at T3B.4 scope, defers to T3B.5)

## Evidence

- +561 test lines in 1 new test file
- Commit body records: 10/10 passing + 99/99 regression passing + reviewer APPROVED
