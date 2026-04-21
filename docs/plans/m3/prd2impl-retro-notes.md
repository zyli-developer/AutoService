# prd2impl Process Retrospective Notes (running)

**Goal**: accumulate learnings from running the full prd2impl pipeline on M3, feed back into optimizing the skill flow + process details.

**Scope**: M3 execution, 2026-04-21 onward. Each batch/milestone adds observations.

---

## Legend

- 🟢 **Works well** — keep as-is
- 🟡 **Friction** — process improvement opportunity
- 🔴 **Gap** — missing step or broken assumption
- 💡 **Insight** — cross-cutting pattern worth codifying

---

## Phase 1: Planning (skill-1 → skill-4)

### Findings

#### 🟢 `/ingest-docs` vs `/prd-analyze` split is useful
Entry A (PRD) for M3 worked clean: skill-1 extracted 22 stories from raw PRD without needing human-authored markdown. The 6 FLAG items surfaced in prd-structure.yaml caught real issues (M2 gate dependency, 18-vs-22 miscount, etc.).

#### 🔴 skill-1 PRD analyze does NOT cross-check against source PRDs
**High-value catch narrowly missed**: M3 PRD Epic E2 was a scope expansion **beyond v1.1 §8 Out of Scope** (whitelabel not-in-scope). skill-1 extracted all 22 stories without flagging this contradiction. Only caught when user asked me to read `AutoService-PRD-v1.1.md` and `AutoService-UserStories-v1.1.md` manually.

**Process improvement candidate**: skill-1 should auto-detect adjacent PRD docs (e.g., `docs/prd/*.md`) and cross-check:
- If a milestone PRD introduces new user stories, are they in the source UserStories doc?
- If §Out-of-Scope lists X, does the milestone PRD respect that?
- Flag any detected contradictions with `type: scope_drift` severity high.

Net impact in M3: **whole Epic E2 could have been avoided** if skill-1 had auto-flagged this. Saved ~30min of rework (errata writes) + prevented ~10 days of M3 scope inflation.

#### 🟢 skill-2 gap-scan subagent dispatch pattern works
3 parallel Explore agents (E1+E2 / E3+E4 / E5+E6) covered full codebase gap analysis in ~5min wall-clock. Output quality: 4 significant "already-implemented" corrections identified (AlertEngine WS-wired / FastClassifier cache / cc_pool 5-role support / parse_sentiment as handoff template).

#### 🟡 Gap-scan corrections don't flow back to prd-structure
skill-2 output `gap-analysis.yaml` had corrections like "AlertEngine is already wired, original gap note was inaccurate". These corrections land in gap-analysis but not in prd-structure (where existing_code refs live). Manual backfill step needed.

**Process improvement**: after skill-2 produces corrections, emit a "contract-refresh" hint telling user to update prd-structure existing_code fields, OR have skill-2 do it directly.

#### 💡 Design spec dispatch pattern scales well
skill-3-task-gen benefits enormously from having 5 Epic design specs produced by parallel subagents in advance. Each subagent:
- Reads the Epic's gap-analysis entries + PRD refs + existing code
- Produces ~300-500 line design spec with alternatives + OQs
- Time per spec: ~4-6min parallel

**Recommendation for prd2impl**: add an optional skill-2.5 "design-spec-draft" step between skill-2 and skill-3, auto-dispatching one subagent per module. Currently this is manual (user has to ask "please run brainstorming + writing-plans for each epic").

#### 🟢 14 OQ default values encoded in tasks.yaml meta
skill-3-task-gen produced 14 OQ defaults as a single authoritative source (`meta.default_oq_values`). Clean, auditable, commit-friendly. This is a good pattern — future tasks can reference OQs by ID.

---

## Phase 2: Execution (skill-5 → skill-8)

### batch-0 Contract Freeze

#### 🔴 Reviewer caught 4 Critical findings in E5 CON-04 contract
Independent `superpowers:code-reviewer` subagent on T0S.4 returned:
- **C1**: `sys._getframe` enforcement is bypassable (via `exec()` / symlink / `functools.partial`)
- **C2**: SELECT-then-UPDATE race in `apply_proposal` (concurrent approvals can both pass check)
- **C3**: Existing `VALID_STATUSES = {..., "implemented"}` conflicts with new `"applied"` — not reconciled
- **C4**: `proposal_audit` INSERT is write-unlocked (anyone can forge audit rows)

**What this tells us about contract drafting**:
- Initial contract authored by orchestrator (me) WITH access to E5 design spec still had 4 structural security holes
- Each was a "second-order" design decision — not in the PRD, not in the design spec, but implied
- **The reviewer is doing real work, not rubber-stamping**

**Process improvement**: 🔒 security-critical tasks MUST go through reviewer — the 1 mandatory review was worth more than the 5 self-reviews I could have done.

#### 💡 Contract version bump (v1.0 → v1.1) flow works
After CHANGES_REQUESTED, revising to v1.1 with an explicit Revision Log section kept the audit trail. The reviewer's 4 findings are documented, the fixes traceable. Suggest this as a standard pattern for 🔒 tasks.

#### 🟡 autorun §3 "commit after every group" vs CLAUDE.md "never commit unless asked"
Conflict between:
- autorun skill step 3.6: "Commit progress after every group boundary"
- project CLAUDE.md: "NEVER commit changes unless the user explicitly asks you to"

Resolution used: **present commit plan + ask explicitly**. User said "A" → commit. This worked but added a round-trip.

**Process improvement candidate**: skill-13-autorun should detect CLAUDE.md override and either:
- Pre-confirm at preflight ("I'll commit at each batch boundary — OK?") once, then proceed
- OR explicitly stage but not commit, and ask at each batch

#### 🟢 Scoped git-add (not `-A`) protects working tree
Adding only M3-specific paths prevented unrelated work-in-progress (multi-role-triage, e2e-evidence, node_modules, plugins/_local_admin) from being swept into the M3 commit. Clean commit boundary.

---

## Phase 3: Execution — batch-1 and onward (to be appended)

### batch-1 T1S.1 Operators Schema

#### 🟡 Contract spec path deviated at implementation time
Contract §3.1 specified `autoservice/auth/operators_schema.py` (package-style path). M2 `auth.py` is a single file, not a package. Implementing the contract literally would force a package refactor (move `auth.py` → `auth/__init__.py`) with 400+ lines of M2 code migrated. **Chose to deviate**: created `autoservice/operators.py` as a sibling module. No refactor required; matches project style (dream_agent.py, cc_pool.py, etc.).

**Process improvement**: skill-3-task-gen should validate contract paths against repo layout during task creation and flag inconsistencies. Or contract-writing (skill-4 / batch-0) should inspect existing code before prescribing paths.

#### 🔴 Contract spec used wrong column types (INTEGER vs TEXT)
Contract §2.1 specified `created_at INTEGER NOT NULL` (epoch ms). M2 `auth.py` uses `TEXT NOT NULL` for ISO 8601 strings. Mixing would cause downstream bugs (auth.py helpers coerce ISO strings, not epoch ms). **Chose to align with M2**: kept TEXT ISO throughout.

**Process improvement**: contract docs should not invent conventions where project-wide patterns exist. skill-1 / skill-2 should extract "house conventions" (timestamp format, ID generation, error types) from existing code and record them in prd-structure.yaml for contract authors to respect.

#### 🟢 TDD red-first worked well
Wrote all 14 tests before impl; the test list served as a structured checklist for what the module had to prove. Tests covered schema idempotency, 3 CHECK constraints, UNIQUE, FK with CASCADE, and 5 migration invariants (add column × 2, idempotent, preserve existing rows, default value, new value inserts).

#### 🟢 In-memory sqlite3 fixture pattern enabled fast iteration
Zero filesystem; each test gets a fresh `:memory:` DB with schema applied. 14 tests ran in 2.63s. **Copy this pattern for T1S.2 session tests.**

#### 💡 SQLite ALTER TABLE caveat surfaced
SQLite ≤ 3.39 cannot add CHECK constraints to existing columns via ALTER. Migration uses a plain `ADD COLUMN role TEXT NOT NULL DEFAULT 'tenant_admin'` and documents that value-enforcement lives in the application layer (invite-issue code path). Contract §3 already noted this correctly — but a naive implementer might try to add a CHECK.

**Process improvement**: contract docs for 🟢 Green tasks should call out known SQLite quirks when relevant. Could add a "platform constraints" appendix to contracts touching DB schema.

#### Time
| | Est | Actual |
|---|---|---|
| T1S.1 | 3h (M) | **~25min** including test authoring (inline; contract was explicit enough to skip "design" phase) |
| Reading M2 baseline | — | ~5min |

Total: ~30min. Contract-first + TDD enabled fast execution without losing quality (14 tests green, 65 regression green).

---

## Cross-Cutting Recommendations for prd2impl v0.3

Rolling up observations:

### R1: Auto-detect source-PRD contradictions in skill-1
[See phase-1 §🔴 finding]. High-value: could prevent entire-Epic scope inflation.

### R2: Propagate skill-2 gap-scan corrections to prd-structure
[See phase-1 §🟡 finding]. Currently manual backfill.

### R3: Add optional skill-2.5 design-spec-draft step
[See phase-1 §💡 finding]. Parallel subagent per module.

### R4: Tighten reviewer mandate on 🔒 CON-04 tasks
[See batch-0 §🔴 finding]. Bake into skill-3-task-gen task template that 🔒 → mandatory code-reviewer.

### R5: skill-13-autorun × CLAUDE.md commit-policy resolution
[See batch-0 §🟡 finding]. Preflight question or explicit staging-only mode.

### R6: Contract version bump pattern documentation
[See batch-0 §💡 finding]. Standardize Revision Log for 🔒 tasks.

---

## Metrics (tracked as execution proceeds)

| Batch | Tasks | Est hours | Actual hours | Rework loops | Reviewer catches |
|---|---|---|---|---|---|
| batch-0 | 4 (3G/1Y) | 4 | ~1.5 | 1 (T0S.4 v1.0→v1.1) | 4 Critical (C1-C4) |
| batch-1 | 1 (1G) | 3 | — | — | — |
| batch-2 | 2 (2G) | 6 | — | — | — |
| batch-3 | 2 (1Y/1G) | 6 | — | — | — |
| **M3-1** | **9** | **19** | — | — | — |
