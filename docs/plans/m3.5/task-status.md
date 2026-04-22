# M3.5 Mini-sprint · Task Status (Dream-first cut)

> **Plan**: [2026-04-22-execution-plan.md](2026-04-22-execution-plan.md) · [2026-04-22-execution-plan.yaml](2026-04-22-execution-plan.yaml)
> **Tasks**: [2026-04-22-tasks.yaml](2026-04-22-tasks.yaml)
> **Source sprint doc**: [docs/plans/m3.5-mini-sprint.md](../m3.5-mini-sprint.md)
> **Branch**: `dev-a` (working directly — no worktree)
> **Target tag**: `v1.2.1-dream` (was `v1.2.1-ui` — retargeted after 2026-04-22 pivot)
> **Revision**: 2026-04-22 — Playwright + non-Dream UI moved to deferred Phase 2

> **Update cadence** — per [CLAUDE.md § /autorun conventions](../../../CLAUDE.md):
> update this file at every batch boundary (same commit as code, or trailing
> `chore(m3.5):` commit). Never dispatch the next batch without updating it.

## Phase

| Phase | Description | State |
|-------|-------------|-------|
| P5 (Dream cut) | D5 LLM real-wire + D2 canary panel + gate | pending |
| P5 (Phase 2 — deferred) | Playwright Epic1-4 + non-Dream UI (U1/U2/U3/U5/U6) | deferred |

## Batch progress (Dream cut)

| Batch | Name | State | Start | Gate |
|-------|------|-------|-------|------|
| batch-0 | D5 Dream LLM real-wire (T5S.14, yellow) | **done** | 2026-04-22 | ✅ 201 mock green + live LLM PASSED 30s via local SDK + reviewer APPROVED |
| batch-1 | D2 Canary panel + 3-button Apply (T5S.12, yellow) | pending | 2026-04-23 | vitest green + manual walk + reviewer APPROVED |
| batch-2 | M3.5 Dream-first gate + tag v1.2.1-dream | pending | 2026-04-24 | smoke GO + regression + tag + PR |

## Active tasks (Dream cut)

| # | ID | Alias | Task | Batch | Type | State | Implementer | Review | Commit |
|---|----|-------|------|-------|------|-------|-------------|--------|--------|
| 1 | T5S.14 | D5 | Dream LLM real-wire (T3B.5 + T4S.4b) | batch-0 | 🟡 | **done** | orchestrator (opus) | ✅ APPROVED (code-reviewer subagent, 13/13) | `m3.5 batch-0` |
| 2 | T5S.12 | D2/U4 | Canary panel w/ 3-button Apply | batch-1 | 🟡 | pending | — | code-reviewer required | — |
| 3 | GATE-M3.5-dream | — | M3.5 smoke + tag v1.2.1-dream | batch-2 | 🟢 | pending | — | — | — |

## Deferred — Phase 2 mini-sprint (artifacts kept, not executed this cut)

Per user pivot 2026-04-22. Re-activate after `v1.2.1-dream` ships.

| # | ID | Alias | Task | Reason |
|---|----|-------|------|--------|
| D1 | T5S.1  | —  | Playwright scaffold + config + CI | Phase 2 |
| D2 | T5S.2  | —  | Epic1 Onboarding suite | Phase 2 |
| D3 | T5S.3  | —  | Epic2 Realtime-chat suite (large) | Phase 2 |
| D4 | T5S.4  | —  | Epic3 Dashboards suite | Phase 2 |
| D5 | T5S.5  | —  | Epic4 Dream-learning suite | Phase 2 (re-activates naturally once T5S.12 + T5S.14 ship) |
| D6 | T5S.6  | U1 | Operator login page | Phase 2 |
| D7 | T5S.7  | U2 | Admin Team page | Phase 2 |
| D8 | T5S.8  | U3 | Classify-intent keyword editor | Phase 2 |
| D9 | T5S.10 | U5 | SLA alert toast + banner | Phase 2 |
| D10 | T5S.11 | U6 | Admin-invite landing | Phase 2 |
| D11 | T5S.13 | D3 | Im-block renderer | Still blocked on T3S.7-hotfix (independent of Phase 2 decision) |

**States**: pending / in-progress / spec-review / quality-review / done / blocked / deferred

## Summary (Dream cut)

- **Active**: 2 tasks + 1 gate step
- **Type split**: 2 🟡 Yellow · 1 🟢 Green (gate)
- **Deferred**: 10 tasks + 1 still-blocked
- **Estimated**: ~13-18h human / ~3-4h AI / 3 calendar days

## Shipped ahead of M3.5 (for auditor traceability)

Landed in M3 batch-10.5 (commit `2e50ac1`):

- **D1** Dream status band → `DreamTab.tsx` status card
- **D4** Dream runs history → `DreamTab.tsx` 最近运行 table

## Session log

(most recent at top — updated at every batch boundary)

- 2026-04-22 — **batch-0 done**. T5S.14 D5 Dream LLM real-wire shipped. Implementation:
  - `autoservice/cc_pool.py` — `CCClient.call_with_tools` (JSON-in/JSON-out local-SDK tool-use wrapper) + `_dream_role` gate (non-dream clients raise) + SDK type imports for test monkeypatch
  - `autoservice/dream_agent.py` — removed `RuntimeError` at L1117, added default `llm_send` closure path over pool's `call_with_tools` (run_dream signature unchanged; existing mock seam intact)
  - `autoservice/master_dream_agent.py` — full rewrite: static skeleton → real LLM tool-loop via shared `_run_agent_loop`; `_render_signal_context` surfaces cross-tenant signals in prompt; `before_ids/after_ids` snapshot for robust emit attribution
  - `autoservice/api_routes.py` — `_run_and_mark` routing flipped: `DREAM_DEV_STUB=1` now short-circuits BOTH master and per-tenant (was per-tenant only); default path is real LLM
  - `CLAUDE.md` — new "Dream Dev Stub" section under Dev Auth Bypass explaining post-T5S.14 semantics
  - `pyproject.toml` — registered `live` pytest marker + default-excluded from `pytest` runs
  - **Tests**: 4 new files (1005 lines); 3 M3-era `test_master_dream_routing.py` tests adapted from `cc_pool=None` skeleton pattern to `_FakeCCPool`-driven tool-loop
  - **Verification**: 201 mocked tests green + live test PASSED 30s via local `claude_agent_sdk` (`AUTOSERVICE_LIVE_OK=1` + env `claude.exe`, non-zero tokens, no stub title)
  - **Reviewer**: code-reviewer subagent APPROVED (13/13 checks — CON-04 5-layer intact, no `import anthropic`, dream-role scoping correct, DREAM_DEV_STUB gate correct, seam back-compat preserved). 2 non-blocking follow-up suggestions carried forward (TODO: revisit CLI tool serialization when SDK gains native Anthropic-shape; `_coerce_usage` maybe shared util)
  - **Note on execution**: initial background subagent stalled after 10min watchdog; orchestrator (main-thread opus) took over for implementation phase. The stalled agent's 4 TDD test files (RED baseline) were usable as-is.
  - Next: batch-1 T5S.12 D2 canary panel.
- 2026-04-22 — User pivot: defer Playwright + non-Dream UI to Phase 2; focus M3.5 on Dream engine (D5 + D2). Plan revised to 3-batch Dream cut; target tag `v1.2.1-dream`. 10 tasks moved to `deferred_phase_2` (artifacts kept). Ready for `/prd2impl:skill-5-start-task T5S.14` or `/prd2impl:skill-8-batch-dispatch batch-0`.
- 2026-04-22 — `/prd2impl:skill-3-task-gen` + `/prd2impl:skill-4-plan-schedule` (initial 5-batch plan generated before user pivot).
