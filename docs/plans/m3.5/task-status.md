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
| batch-1 | D2 Canary panel + 3-button Apply (T5S.12, yellow) | **done** | 2026-04-22 | ✅ 32/32 vitest (22 canary-panel + 10 DreamTab) + reviewer APPROVED-WITH-FIXUP (2 rounds) |
| batch-2 | M3.5 Dream-first gate + tag v1.2.1-dream | **staged — awaiting user GO for tag+push+PR** | 2026-04-22 | ✅ 201/201 Dream pytest + 32/32 Dream vitest + 1872/1886 broad regression (14 failures triaged as pre-existing/env) · ⏳ manual walkthrough + tag push need user confirmation |

## Active tasks (Dream cut)

| # | ID | Alias | Task | Batch | Type | State | Implementer | Review | Commit |
|---|----|-------|------|-------|------|-------|-------------|--------|--------|
| 1 | T5S.14 | D5 | Dream LLM real-wire (T3B.5 + T4S.4b) | batch-0 | 🟡 | **done** | orchestrator (opus) | ✅ APPROVED (code-reviewer subagent, 13/13) | `m3.5 batch-0` |
| 2 | T5S.12 | D2/U4 | Canary panel w/ 3-button Apply + Advance/Rollback | batch-1 | 🟡 | **done** | orchestrator (opus, autopilot-all) | ✅ APPROVED-WITH-FIXUP (code-reviewer ×2 — round 1 caught chat-vs-chat-legacy routing bug, round 2 all 8 CON-04 items PASS) | `m3.5 batch-1` |
| 3 | GATE-M3.5-dream | — | M3.5 smoke + tag v1.2.1-dream | batch-2 | 🟢 | **staged** | orchestrator (opus, autopilot-all) | n/a (Green) | smoke report `m3.5/smoke-report.md` |

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

- 2026-04-22 — **batch-2 staged (smoke GO; awaiting user authorization for tag + push + PR)**.
  - Dream-scope pytest: 201 passed, 1 deselected (live, opt-in) — `tests/dream_agent`,
    `tests/dream_runs`, `tests/dream`, `tests/api/test_dream_api.py`, `tests/cc_pool`,
    `tests/dream_agent/test_con04_guardrail.py`. CON-04 AST guardrail PASS (no new
    `status='applied'` writers).
  - Admin-portal vitest (Dream surfaces): 32/32 — 22 canary-panel + 10 DreamTab.
  - Broad regression `pytest tests/ --ignore=tests/e2e-playwright`: **1872 passed,
    14 failed, 4 skipped, 9 deselected**. All 14 failures triaged out-of-scope and
    pre-existing on HEAD (8 = `test_proposal_pipeline` suite-ordering flakes, all
    pass in isolation; 5 = `tests/publish/test_github_api_fork_creator.py` — Python
    3.12+ `tarfile.extractall(filter="data")` API on local 3.11; 1 = M2
    `test_step7_dream_config_persisted` carry-over). Effective in-scope pass rate:
    1872/1872 = 100%.
  - Smoke report: `.artifacts/milestones/m3.5/smoke-report.md` — verdict GO conditional
    on (a) user attestation of two manual walkthroughs (D5 production trigger × cinnox
    + master · D2 canary panel UX), (b) user authorization for `git tag v1.2.1-dream`
    + `git push origin v1.2.1-dream` + `gh pr create` (visible-to-others actions
    require explicit GO per autorun safeguards).
  - i18n: 19 new `admin.dream.canary.*` keys registered in en.json + zh-CN.json
    (batch-1 commit `59188c3`); both files JSON-valid.
  - **Next**: handoff to user for §5 + §6 of smoke-report.
- 2026-04-22 — **batch-1 done**. T5S.12 D2/U4 Dream Proposal canary panel shipped. Implementation:
  - `frontend/apps/admin-portal/src/components/dream/canary-panel.tsx` (new, ~325 lines) — 5-action panel: `[Reject] [Approve] [🔒 Apply]` main row + `[Rollback] [Advance]` stage controls under the progress bar. Apply is the sole writer of `status='applied'` (CON-04). Approve/Reject route through `/api/management/chat-legacy?message=/approve|/reject <id>` (M1 slash dispatcher; reviewer round 1 caught that `/api/management/chat` is the M2 `_master` LLM pass-through and does NOT dispatch slash commands). Advance/Rollback use `window.confirm()` per-stage before POST `/api/canary/advance` | `/api/canary/rollback`. Single `BusyAction` atom locks all 5 buttons during any in-flight op.
  - `frontend/apps/admin-portal/src/components/dream/metric-compare.tsx` (new, ~95 lines) — renders `monitor.breaches[]` as a compact pre/post table when non-empty; returns null otherwise.
  - `frontend/apps/admin-portal/src/components/DreamTab.tsx` — removed the inline per-row Apply button (M3 commit `2e50ac1`); rows now click-to-select; CanaryPanel mounts above the pending-proposals table for the selected proposal. Single source of truth per plan §4.
  - `frontend/apps/admin-portal/src/__tests__/DreamTab.test.tsx` — rewrote 2 old tests (inline Apply removed) + added 3 new integration tests (row-click mount, CanaryPanel Apply enable/disable, Apply endpoint contract).
  - `frontend/apps/admin-portal/src/__tests__/dream/canary-panel.test.tsx` (new, 22 tests) — TDD: RED first on missing import, GREEN after implementation. Adds endpoint-drift guard asserting no call lands on `/api/management/chat` (M2 endpoint).
  - `frontend/packages/i18n/src/locales/en.json` + `zh-CN.json` — 19 new `admin.dream.canary.*` keys registered in both locales.
  - **Verification**: 32/32 scoped vitest (22 canary-panel + 10 DreamTab) green. Pre-existing baseline of 24 unrelated admin-portal failures on HEAD unchanged (AdminWorkspace, ChannelConfigStep, etc. — out of T5S.12 scope).
  - **Reviewer**: code-reviewer subagent APPROVED-WITH-FIXUP across 2 rounds.
    - Round 1 verdict: **CHANGES-REQUESTED**. Caught a real bug: Approve/Reject initially POSTed JSON `{text: "/approve <id>"}` to `/api/management/chat`, which (a) expects `{message: "..."}` body and (b) doesn't dispatch slash commands (that's `/chat-legacy`). Also flagged missing Advance/Rollback buttons (plan §Scope §2) and a no-op `setSelectedProposalId((curr) => curr)` in DreamTab.
    - Round 2 verdict: **APPROVED-WITH-FIXUP**. All 3 fixups landed: chat-legacy endpoint + query-string; 5 new Advance/Rollback tests + confirm gating; cleaned DreamTab onReload. CON-04 rubric items #6 and #7 flipped FAIL→PASS. Open follow-ups (carryforward, non-blocking): i18n key registration (now done this commit), dynamic next-stage readout from backend rather than local STAGES array, `<ConfirmDialog>` modal when admin-portal gains one, `metric-compare.deltaClass` dead branch cleanup, `CanaryProgress` divergence comment.
  - **Autopilot-all DEFAULT-PICKED decisions** (recorded per skill-13 §6):
    1. Approve/Reject wiring — chose chat-legacy slash dispatcher over adding new REST endpoints (`POST /api/admin/proposals/{id}/accept|reject`). Rationale: REST expansion would push task outside plan's frontend-only `files_touched` scope and into Red territory (RBAC policy, audit log shape). Reversible: a future PR can thin-wrap `pp.update_status` as REST without changing the frontend.
    2. CanaryProgress not reused — inline progress bar in CanaryPanel rather than embedding the existing `components/CanaryProgress.tsx` (DashboardTab). Rationale: CanaryProgress renders `monitor.breaches[]` inline; embedding alongside MetricCompare would duplicate the breach display. Reversible: refactor CanaryProgress to accept `variant='compact'` later.
  - Next: batch-2 gate — full regression + smoke + tag `v1.2.1-dream`.
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
