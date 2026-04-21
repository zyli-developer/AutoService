# Test diff: batch-3 (Phase 3 · T3B.1 + T3B.2 + T3B.3 — dream agent tools)

**Backfill · 2026-04-21**
**Commit**: `e18b183`
**Source**: `git show e18b183 -- tests/`
**Dispatch**: single subagent (a74376f) — serial because all three tasks touch `autoservice/dream_agent.py`.

新增 **33 tests** across 3 files (commit body originally cited 34; measured live count after parametrize resolution is 33).

## 新增文件

- `tests/dream_agent/__init__.py` — new package marker
- `tests/dream_agent/test_emit_proposal_tool.py` — **16 tests** (T3B.1)
- `tests/dream_agent/test_kb_search_tool.py` — **8 tests** (T3B.2)
- `tests/dream_agent/test_list_souls_tool.py` — **9 tests** (T3B.3)

## 覆盖的场景

**T3B.1 `emit_proposal`** (spec §2.3, CON-04 red line):
- Signature guard: function signature contains **no** `status` kwarg (attempting to pass one raises TypeError)
- SQLite row written with `status='draft'` hard-coded
- JSON payload returned also has `status='draft'`
- `risk_level` enum validation (rejects invalid values with ValueError)
- `target_role` enum validation (rejects invalid values with ValueError)
- Round-trip via `ProposalPipeline.get_proposal`
- tenant_id scoping (writes only target tenant's row)
- Plus 9 edge / boundary cases

**T3B.2 `kb_search`** (spec §2.4):
- FTS path hit: sandbox `kb.db` present
- Fallback path: `plugins/<tid>/` when sandbox missing
- Empty query → `[]` (no raise)
- Missing KB → `[]` (graceful)
- Empty KB (schema but no rows) → `[]`
- Malformed FTS expression → `[]` (graceful, no raise)
- top-K slicing honored
- tenant scoping

**T3B.3 `list_souls`** (spec §2.2 "不含自己"):
- Enumerates `<tenant>/souls/*.md`
- Default `exclude_self=True` filters `dream_soul.md`
- `exclude_self=False` includes it
- 500-char excerpt included per file
- Missing souls dir → `[]`
- Empty souls dir → `[]`
- Falls back from sandbox to plugins tree
- 5-role set discovered when all present

## 已修 regression bug

- **FTS JOIN bug fix** vs soul_generator: T3B.2 kb_search uses a corrected FTS JOIN pattern that soul_generator's identical-shape lookup had a latent flaw in. Dream agent avoids the buggy code path; no regression on soul_generator itself (its bug never manifested in practice because its call shape dodged it).

## Evidence

- +598 test lines across 3 new test files (+ 1 init.py marker)
- Commit body: "34 cases across tests/dream_agent/" (pre-parametrize count)
