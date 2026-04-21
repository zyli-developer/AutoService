# prd2impl Bridge Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable superpowers design specs to flow into prd2impl's `/task-gen` pipeline without hand-writing `prd-structure.yaml`.

**Architecture:** Two changes in prd2impl (superpowers stays read-only). **A'** enriches `skill-0-ingest`'s design-spec extractor with regex (external_deps) + LLM fallback (user_stories). **B2** teaches `skill-3-task-gen` to degrade gracefully when `prd-structure.yaml` AND/OR `gap-analysis.yaml` absent, synthesizing skeleton modules from `task-hints.implementation_steps`.

**Tech Stack:** prd2impl skills are Markdown instruction documents (no compiled code). Tests are YAML fixture pairs under `skills/<name>/tests/fixtures/` + `tests/expected/` validated by invoking `/ingest-docs` or `/task-gen` on the fixture and diffing output.

---

## File Structure

### Fork working directory

All edits happen in a local fork clone at `C:/Users/nity/.claude-plugin-forks/prd2impl/`, pointed to by Claude Code settings. Upstream = `github.com/ezagent42/prd2impl` (exact slug confirmed in Task 0).

### Files touched

| File | Action | Purpose |
|------|--------|---------|
| `skills/skill-3-task-gen/SKILL.md` | modify | Add B2 degradation section |
| `skills/skill-0-ingest/lib/prd-extractor.md` | modify | Add external_deps regex + user_stories LLM fallback under role=design-spec |
| `skills/skill-0-ingest/SKILL.md` | modify | Emit extraction metadata (regex_fields / llm_fields) |
| `skills/skill-0-ingest/tests/fixtures/design-spec-extraction/deps-table.md` | create | A' regex test input (table form) |
| `skills/skill-0-ingest/tests/fixtures/design-spec-extraction/deps-bullets.md` | create | A' regex test input (bullet form) |
| `skills/skill-0-ingest/tests/fixtures/design-spec-extraction/sparse-no-deps.md` | create | A' LLM fallback test input |
| `skills/skill-0-ingest/tests/expected/design-spec-extraction/deps-table.prd-structure.yaml` | create | Expected output (regex path) |
| `skills/skill-0-ingest/tests/expected/design-spec-extraction/deps-bullets.prd-structure.yaml` | create | Expected output (regex path) |
| `skills/skill-0-ingest/tests/expected/design-spec-extraction/sparse-no-deps.prd-structure.yaml` | create | Expected output (LLM path — fuzzy match) |
| `skills/skill-3-task-gen/tests/fixtures/b2-degraded/{date}-task-hints.yaml` | create | B2 test input |
| `skills/skill-3-task-gen/tests/expected/b2-degraded/tasks.yaml` | create | B2 expected output (synthetic modules) |
| `docs/superpowers/specs/2026-04-21-prd2impl-bridge-enhancement-design.md` (AutoService repo) | modify | Spec reconciliation — correct gap-analysis statement |

---

### Task 0: Fork prd2impl + wire into Claude Code

**Files:**
- Create: `C:/Users/nity/.claude-plugin-forks/prd2impl/` (git clone)
- Modify: `C:/Users/nity/.claude/settings.json` (plugin source override)

- [ ] **Step 1: Find the upstream repo URL**

Run:
```bash
grep -r "prd2impl" C:/Users/nity/.claude/plugins/cache/ezagent42/prd2impl/0.2.2/README.md C:/Users/nity/.claude/plugins/cache/ezagent42/prd2impl/0.2.2/package.json | head -20
```

If no URL found: check `ezagent42` GitHub profile manually. Expected: `git@github.com:ezagent42/prd2impl.git` or `https://github.com/ezagent42/prd2impl.git`.

- [ ] **Step 2: Clone upstream to fork location**

Run:
```bash
mkdir -p C:/Users/nity/.claude-plugin-forks
cd C:/Users/nity/.claude-plugin-forks
git clone <upstream-url> prd2impl
cd prd2impl
git checkout -b feat/design-spec-bridge
```

Expected: fork at `C:/Users/nity/.claude-plugin-forks/prd2impl/` on branch `feat/design-spec-bridge`.

- [ ] **Step 3: Pin upstream SHA in fork README**

Append to `C:/Users/nity/.claude-plugin-forks/prd2impl/README.md`:

```markdown
---
## Fork status (hjj.gemini@gmail.com)

- Branched from upstream commit: <SHA from `git rev-parse HEAD`>
- Purpose: design-spec bridge enhancement (spec at AutoService `docs/superpowers/specs/2026-04-21-prd2impl-bridge-enhancement-design.md`)
- Re-base cadence: rebase onto upstream main before each feature commit
```

Run: `git -C C:/Users/nity/.claude-plugin-forks/prd2impl rev-parse HEAD` to get the SHA; substitute into the block above.

- [ ] **Step 4: Point Claude Code at the fork**

Read `C:/Users/nity/.claude/settings.json`. Look for a `plugins` or `pluginSources` key.

If key present with entry for `ezagent42/prd2impl`: update path to `C:/Users/nity/.claude-plugin-forks/prd2impl`.
If key absent: add a new entry. Example shape (verify against Claude Code plugin docs):

```json
{
  "pluginSources": {
    "ezagent42/prd2impl": {
      "type": "local",
      "path": "C:/Users/nity/.claude-plugin-forks/prd2impl"
    }
  }
}
```

If Claude Code plugin loader doesn't support local source override: fall back to manual sync — edit in the fork, then copy-paste changed files to `C:/Users/nity/.claude/plugins/cache/ezagent42/prd2impl/0.2.2/` for testing. Document this decision in the fork README.

- [ ] **Step 5: Regression check — existing skill still works**

In a fresh Claude Code session:
- Run `/ingest-docs docs/superpowers/specs/2026-04-21-chat-markdown-design.md` (AutoService repo).
- Expected: produces `task-hints.yaml` in current plans_dir (same behavior as pre-fork — since we haven't changed anything yet).

If behavior differs → plugin source override not working; revert to manual sync fallback.

- [ ] **Step 6: Commit fork bootstrap**

In the fork:
```bash
cd C:/Users/nity/.claude-plugin-forks/prd2impl
git add README.md
git commit -m "chore: fork bootstrap + design-spec bridge branch"
```

In AutoService repo: no changes yet.

---

### Task 1: Spec reconciliation — gap-analysis.yaml is required by skill-3

**Files:**
- Modify: `docs/superpowers/specs/2026-04-21-prd2impl-bridge-enhancement-design.md:§6.1, §6.2, §7.2`

**Context:** The spec §6.1 said `gap-analysis.yaml` is "optional", but `skill-3-task-gen/SKILL.md:23` marks it **Required**. For the design-spec workflow (chat-markdown-style), gap-analysis is typically absent. B2's scope must therefore cover missing gap-analysis too, not just missing prd-structure.

- [ ] **Step 1: Edit §6.1 — correct the "current behavior" description**

In `docs/superpowers/specs/2026-04-21-prd2impl-bridge-enhancement-design.md`, replace §6.1:

```markdown
### 6.1 Current behavior

`skill-3-task-gen` reads `{plans_dir}/{date}-prd-structure.yaml` (required) +
`{date}-gap-analysis.yaml` (required) + `{date}-task-hints.yaml` (optional).
Missing either required file → hard error.
```

- [ ] **Step 2: Edit §6.2 — extend B2 trigger to cover missing gap-analysis**

Replace the first line of §6.2:

```markdown
### 6.2 B2 change

If `task-hints.yaml` is present AND either `prd-structure.yaml` OR
`gap-analysis.yaml` (or both) are absent:

1. Synthesize in memory whatever is missing:
   - If `prd-structure` missing: skeleton `prd_structure` as described below
   - If `gap-analysis` missing: empty `gap_analysis: { gaps: [] }` —
     task generation proceeds off `implementation_steps` alone
```

Preserve the rest of §6.2 (skeleton module synthesis rules, non-persist,
traceability marker, warning format).

- [ ] **Step 3: Update §7.2 test scenarios**

Replace the table in §7.2 with:

```markdown
| Scenario | Inputs | Assertion |
|----------|--------|-----------|
| task-hints-only (neither gap nor prd) | `task-hints.yaml` only | `tasks.yaml` generated; warning printed; each task has `traceability: task-hints-only` |
| prd-only-missing | `task-hints.yaml` + `gap-analysis.yaml` | Tasks gain gap IDs but synthetic module IDs |
| gap-only-missing | `task-hints.yaml` + `prd-structure.yaml` | Tasks gain real module IDs but no gap refs |
| both present | all three yaml files | Regression — behavior identical to pre-change |
| only prd-structure (no hints, no gap) | `prd-structure.yaml` only | Hard error (no degradation path) |
| fully empty | empty plans_dir | Hard error |
```

- [ ] **Step 4: Commit spec correction**

In AutoService repo:
```bash
git add docs/superpowers/specs/2026-04-21-prd2impl-bridge-enhancement-design.md
git commit -m "$(cat <<'EOF'
docs(spec): correct gap-analysis.yaml required status; extend B2 scope

skill-3 actually requires gap-analysis.yaml alongside prd-structure.yaml.
B2 now covers missing gap-analysis too (common in design-spec workflow
where no gap-scan has run).
EOF
)"
```

---

### Task 2: B2 — write task-hints-only fixture + expected output

**Files:**
- Create: `C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-3-task-gen/tests/fixtures/b2-degraded/task-hints.yaml`
- Create: `C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-3-task-gen/tests/expected/b2-degraded/tasks.yaml`

- [ ] **Step 1: Create the task-hints fixture**

Write `C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-3-task-gen/tests/fixtures/b2-degraded/task-hints.yaml`:

```yaml
task_hints:
  source_type: "ingested"
  source_role: "design-spec"
  source_files: ["fixture-input.md"]
  file_changes:
    - path: "src/feature/A.ts"
      change_type: create
      purpose: "new feature A"
      source_anchor: "§5.1"
      related_gap_refs: []
    - path: "src/feature/B.ts"
      change_type: modify
      purpose: "wire A into B"
      source_anchor: "§5.2"
      related_gap_refs: []
  implementation_steps:
    - step: 1
      description: "Build feature A as a pure module with unit tests"
      depends_on_steps: []
      touches_files: ["src/feature/A.ts"]
      source_anchor: "§5.1"
    - step: 2
      description: "Wire feature A into B; regression tests"
      depends_on_steps: [1]
      touches_files: ["src/feature/B.ts"]
      source_anchor: "§5.2"
  non_goals:
    - "Feature C"
  test_strategy:
    preserved_testids: []
    new_tests: ["tests/A.test.ts"]
    e2e_delta: null
  risks: []
```

- [ ] **Step 2: Create the expected tasks.yaml**

Write `C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-3-task-gen/tests/expected/b2-degraded/tasks.yaml`:

```yaml
# Expected output when skill-3 runs in B2 task-hints-only mode.
# The exact task id format (TN{line}.{seq}) depends on project.yaml;
# assume line=S (shared) and phase=1 for this fixture.
# Exact fields may vary — match these as the fuzzy-compare criteria:
#   - tasks[*].traceability == "task-hints-only"
#   - tasks[*].synthesized_module_id matches MOD-01 or MOD-02
#   - len(tasks) >= 2 (one per implementation_step, possibly split by files)
tasks:
  - id: T1S.1
    name: "Build feature A as a pure module with unit tests"
    description: "Build feature A as a pure module with unit tests"
    line: shared
    type: green
    traceability: task-hints-only
    synthesized_module_id: MOD-01
    touches_files: ["src/feature/A.ts"]
    depends_on: []
  - id: T1S.2
    name: "Wire feature A into B; regression tests"
    description: "Wire feature A into B; regression tests"
    line: shared
    type: green
    traceability: task-hints-only
    synthesized_module_id: MOD-02
    touches_files: ["src/feature/B.ts"]
    depends_on: [T1S.1]
```

- [ ] **Step 3: Commit fixtures (no behavior change yet)**

```bash
cd C:/Users/nity/.claude-plugin-forks/prd2impl
git add skills/skill-3-task-gen/tests/fixtures/b2-degraded/ \
        skills/skill-3-task-gen/tests/expected/b2-degraded/
git commit -m "test(skill-3): add b2-degraded task-hints-only fixture + expected"
```

---

### Task 3: B2 — verify baseline failure (test-first)

**Files:** None modified; this is a test run to confirm current behavior errors as expected.

- [ ] **Step 1: Create temporary plans_dir with only task-hints.yaml**

```bash
mkdir -p /tmp/b2-test-plans
cp C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-3-task-gen/tests/fixtures/b2-degraded/task-hints.yaml \
   /tmp/b2-test-plans/2026-04-21-task-hints.yaml
ls /tmp/b2-test-plans/
```

Expected: single file `2026-04-21-task-hints.yaml`.

- [ ] **Step 2: Invoke /task-gen in a Claude session**

In a fresh Claude Code session (not subagent), run:
```
/task-gen --plans-dir /tmp/b2-test-plans
```

Expected: hard error mentioning missing `prd-structure.yaml` OR `gap-analysis.yaml`.

Record the exact error message — this is the baseline we'll replace with the B2 warning.

- [ ] **Step 3: Note baseline in commit message for Task 4**

Capture the error verbatim in a scratchpad (e.g. paste into the Task 4 commit body) — will use it to document the change.

---

### Task 4: B2 — add degradation logic to skill-3 SKILL.md

**Files:**
- Modify: `C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-3-task-gen/SKILL.md`

- [ ] **Step 1: Locate the input-loading section**

Run:
```bash
grep -n "Step 1\|Load Gap\|gap-analysis\|prd-structure" \
  C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-3-task-gen/SKILL.md | head -20
```

Identify the section that reads inputs (likely "Step 1: Load Gap Analysis" or similar around line 34).

- [ ] **Step 2: Insert B2 degradation block after the input-loading section**

Edit `skills/skill-3-task-gen/SKILL.md`. After the section that describes loading the required inputs, insert a new section `## B2 Degradation — task-hints-only mode` with this content:

````markdown
## B2 Degradation — task-hints-only mode

Skill-3 can operate without `prd-structure.yaml` and/or `gap-analysis.yaml`
provided `task-hints.yaml` is present and has a non-empty `implementation_steps` list.

### Trigger

At the end of Step 1 (Load Gap Analysis), check what was loaded:

- If `gap-analysis.yaml` was NOT found AND `task-hints.yaml` WAS found:
  synthesize `gap_analysis = { gaps: [] }` in memory.
- If `prd-structure.yaml` was NOT found AND `task-hints.yaml` WAS found:
  synthesize a skeleton `prd_structure` in memory (see §Skeleton synthesis below).
- If `task-hints.yaml` was NOT found OR `implementation_steps` is empty:
  do NOT synthesize — fall through to the original hard error.

The synthesized structures are **never written to disk** — they exist only for
the duration of this `/task-gen` invocation.

### Skeleton synthesis

```yaml
prd_structure:
  source_type: "synthesized-from-task-hints"
  source_role: "design-spec"
  modules:
    # One module per implementation_step entry
    - id: MOD-01
      name: "<step.description truncated to 60 chars>"
      description: "<step.description (full)>"
      prd_sections: []
      sub_modules:
        # One sub_module per file in step.touches_files
        - id: MOD-01a
          name: "<file basename>"
          description: "<file path>"
  user_stories: []
  nfrs: []
  constraints: []
  external_deps: []
```

Sequential numbering: MOD-01, MOD-02, ... matching the step numbers.
Sub-module suffix: MOD-01a, MOD-01b, ... per file within a step.

### Task output marker

Every task emitted under B2 degradation MUST include:

```yaml
tasks:
  - id: T<phase><line>.<seq>
    ...
    traceability: task-hints-only      # NEW field — absent in normal mode
    synthesized_module_id: MOD-NN      # NEW field — links to skeleton module
```

Downstream skills (contract-check, retro) key off `traceability: task-hints-only`
to skip checks that need real `user_stories` / `constraints` / `external_deps`.

### User-facing warning

Before writing `tasks.yaml`, print:

```
─────────────────────────────────────────────────────
B2 degradation mode active
─────────────────────────────────────────────────────
Missing: {list of absent required files}
Synthesized {N} skeleton modules (MOD-01..MOD-{N}) from implementation_steps.
user_stories / nfrs / constraints / external_deps are empty — downstream
skills (contract-check, retro) will skip checks that depend on these fields.
Re-run /ingest-docs on a richer source document to upgrade.
─────────────────────────────────────────────────────
```

### What does NOT change

- If all three input files present → zero behavior change.
- Synthesized structures are NEVER persisted. Running `/ingest-docs`
  afterward produces the real files; this skeleton was only scaffolding
  for this `/task-gen` invocation.
````

- [ ] **Step 3: Update §Input section to mark gap + prd as "required unless B2 applies"**

In the same file, find the `## Input` section and edit the two `Required` lines:

```markdown
- **Required (or B2 fallback)**: `{plans_dir}/*-gap-analysis.yaml` — see §B2 Degradation
- **Required (or B2 fallback)**: `{plans_dir}/*-prd-structure.yaml` — see §B2 Degradation
- **Optional**: `{plans_dir}/*-task-hints.yaml` — REQUIRED for B2 fallback mode
```

- [ ] **Step 4: Commit the degradation logic**

```bash
cd C:/Users/nity/.claude-plugin-forks/prd2impl
git add skills/skill-3-task-gen/SKILL.md
git commit -m "feat(skill-3): B2 degradation — task-hints-only mode

When prd-structure.yaml and/or gap-analysis.yaml absent but
task-hints.yaml present with non-empty implementation_steps,
synthesize skeletons in memory. Mark emitted tasks with
traceability: task-hints-only.

Baseline error pre-change:
  <paste from Task 3 Step 2 scratchpad>
"
```

---

### Task 5: B2 — verify degraded run produces expected tasks

**Files:** None modified; validation only.

- [ ] **Step 1: Rerun /task-gen against the degraded plans_dir**

The `/tmp/b2-test-plans/` dir from Task 3 still has only `task-hints.yaml`. In a fresh Claude Code session (to pick up the fork changes):
```
/task-gen --plans-dir /tmp/b2-test-plans
```

Expected:
- Warning banner printed (§B2 Degradation wording).
- `/tmp/b2-test-plans/tasks.yaml` created.

- [ ] **Step 2: Diff output against expected**

```bash
diff -u \
  C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-3-task-gen/tests/expected/b2-degraded/tasks.yaml \
  /tmp/b2-test-plans/tasks.yaml
```

Expected: differences only in comments + task id prefix (depends on `project.yaml` which this test doesn't have). The three load-bearing invariants MUST match:

1. `tasks[*].traceability` is `task-hints-only` for every task.
2. `tasks[*].synthesized_module_id` is populated.
3. `len(tasks) == 2` (one per `implementation_step`).

If any invariant missing → go back to Task 4 Step 2 and fix the skeleton synthesis rules in SKILL.md.

- [ ] **Step 3: Regression check — both files present**

Create `/tmp/b2-regression-plans/` with both `task-hints.yaml` AND a real `prd-structure.yaml` + `gap-analysis.yaml` (copy from any existing passing fixture like `skills/skill-3-task-gen/tests/fixtures/*` if present; otherwise copy from AutoService `docs/plans/feat-chat-markdown/`).

Run `/task-gen --plans-dir /tmp/b2-regression-plans`.

Expected:
- NO B2 warning banner.
- Output `tasks.yaml` has NO `traceability` field.
- Output `tasks.yaml` has NO `synthesized_module_id` field.

If B2 fires when it shouldn't → the trigger in Task 4 Step 2 is too loose; tighten the "AND task-hints was found" condition.

- [ ] **Step 4: Edge case — empty implementation_steps**

Create `/tmp/b2-empty-plans/2026-04-21-task-hints.yaml`:
```yaml
task_hints:
  source_type: "ingested"
  source_role: "design-spec"
  source_files: ["x.md"]
  file_changes: []
  implementation_steps: []
  non_goals: []
  test_strategy: null
  risks: []
```

Run `/task-gen --plans-dir /tmp/b2-empty-plans`.

Expected: hard error (same as Task 3 baseline — B2 must not engage with empty steps).

If B2 engages → add the `len(implementation_steps) > 0` guard to Task 4 Step 2's trigger list.

- [ ] **Step 5: Commit B2 validation evidence**

Collect the three command outputs (Step 1, Step 3, Step 4) into `skills/skill-3-task-gen/tests/expected/b2-degraded/validation-log.txt`:

```bash
cd C:/Users/nity/.claude-plugin-forks/prd2impl
# (write validation-log.txt using the Edit or Write tool based on your session's captured output)
git add skills/skill-3-task-gen/tests/expected/b2-degraded/validation-log.txt
git commit -m "test(skill-3): B2 validation evidence — degraded + regression + edge"
```

---

### Task 6: A' regex — external_deps fixtures + expected outputs

**Files:**
- Create: `skills/skill-0-ingest/tests/fixtures/design-spec-extraction/deps-table.md`
- Create: `skills/skill-0-ingest/tests/fixtures/design-spec-extraction/deps-bullets.md`
- Create: `skills/skill-0-ingest/tests/expected/design-spec-extraction/deps-table.prd-structure.yaml`
- Create: `skills/skill-0-ingest/tests/expected/design-spec-extraction/deps-bullets.prd-structure.yaml`

- [ ] **Step 1: Write the table-form fixture**

`skills/skill-0-ingest/tests/fixtures/design-spec-extraction/deps-table.md`. **Deliberately omits §Scope** — keeps this fixture single-purpose (regex external_deps only, no LLM trigger):

```markdown
# Test Feature — Design

## 1. Goal
Exercise the external_deps table parser.

## 4. Component
Renders markdown.

## 8. Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| react-markdown | ^9.0.1 | core markdown renderer |
| remark-gfm | ^4.0.0 | GitHub-flavored extensions |
| rehype-highlight | ^7.0.0 | syntax highlighting |
| highlight.js | ^11.9.0 | syntax highlighter engine |
```

- [ ] **Step 2: Write the bullet-form fixture**

`skills/skill-0-ingest/tests/fixtures/design-spec-extraction/deps-bullets.md`. Same shape — no §Scope:

```markdown
# Test Feature — Design

## 1. Goal
Exercise the external_deps bullet parser.

## 4. Component
Renders markdown.

## 8. Dependencies

- `react-markdown@^9.0.1` — core markdown renderer
- `remark-gfm@^4.0.0` — GitHub-flavored extensions
- `rehype-highlight@^7.0.0` — syntax highlighting
- `highlight.js@^11.9.0` — syntax highlighter engine
```

- [ ] **Step 3: Write the expected output (shared shape for both fixtures)**

Both fixtures expect the SAME external_deps list. Write
`skills/skill-0-ingest/tests/expected/design-spec-extraction/deps-table.prd-structure.yaml`.

**Note:** `extraction` metadata block is NOT in this expected file — it's added under Task 10 (which also updates this expected to include it). Keep the expected file in sync with the SKILL.md state at each task boundary.

```yaml
prd_structure:
  source_type: "ingested"
  source_role: "design-spec"
  source_files: ["deps-table.md"]
  modules:
    - id: MOD-01
      name: "Component"
      description: "Renders markdown."
      prd_sections: ["§4 Component"]
      sub_modules: []
  user_stories: []
  nfrs: []
  constraints: []
  external_deps:
    - id: DEP-01
      name: "react-markdown"
      version: "^9.0.1"
      purpose: "core markdown renderer"
      source_anchor: "§8 Dependencies"
    - id: DEP-02
      name: "remark-gfm"
      version: "^4.0.0"
      purpose: "GitHub-flavored extensions"
      source_anchor: "§8 Dependencies"
    - id: DEP-03
      name: "rehype-highlight"
      version: "^7.0.0"
      purpose: "syntax highlighting"
      source_anchor: "§8 Dependencies"
    - id: DEP-04
      name: "highlight.js"
      version: "^11.9.0"
      purpose: "syntax highlighter engine"
      source_anchor: "§8 Dependencies"
```

Copy this to `deps-bullets.prd-structure.yaml` with one line changed:
`source_files: ["deps-bullets.md"]`.

- [ ] **Step 4: Run the fixtures against CURRENT (pre-change) extractor to confirm failure**

In a fresh Claude Code session, for each fixture:
```
/ingest-docs C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-0-ingest/tests/fixtures/design-spec-extraction/deps-table.md --plans-dir /tmp/a-regex-test
```

Expected:
- `/tmp/a-regex-test/*-prd-structure.yaml` produced but with `external_deps: []` (current extractor skips deps).

Record this as "baseline before regex enhancement" — evidence the test is meaningful.

- [ ] **Step 5: Commit fixtures + baseline evidence**

```bash
cd C:/Users/nity/.claude-plugin-forks/prd2impl
git add skills/skill-0-ingest/tests/fixtures/design-spec-extraction/deps-table.md \
        skills/skill-0-ingest/tests/fixtures/design-spec-extraction/deps-bullets.md \
        skills/skill-0-ingest/tests/expected/design-spec-extraction/deps-table.prd-structure.yaml \
        skills/skill-0-ingest/tests/expected/design-spec-extraction/deps-bullets.prd-structure.yaml
git commit -m "test(skill-0): add external_deps fixtures (table + bullet)

Baseline: current extractor produces external_deps: [] for both — this
pins the gap that the next commit closes."
```

---

### Task 7: A' regex — add external_deps extraction to prd-extractor

**Files:**
- Modify: `C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-0-ingest/lib/prd-extractor.md`

- [ ] **Step 1: Locate the role=design-spec section**

```bash
grep -n "design-spec\|external_deps" \
  C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-0-ingest/lib/prd-extractor.md | head -20
```

Identify the subsection that handles `role=design-spec` (per spec §5.1, currently extracts modules/nfrs/constraints only).

- [ ] **Step 2: Insert the external_deps extraction subsection**

In `lib/prd-extractor.md`, within the `role=design-spec` subsection, after the `constraints` extraction block, append:

````markdown
### external_deps extraction (role=design-spec)

Locate the section heading matching (case-insensitive):
- `Dependencies` / `Dependency`
- `依赖` / `外部依赖`
- Numbered variants like `## 8. Dependencies`, `## N. 依赖`

If no matching heading → `external_deps: []` (not a warning; dep-less specs are valid).

Inside the matching section, detect one of two sub-formats:

**Format A — markdown table**:

```markdown
## 8. Dependencies
| Package | Version | Purpose |
|---------|---------|---------|
| react-markdown | ^9.0.1 | core renderer |
```

Parse columns (flexible ordering, case-insensitive headers):
- `Package` / `Name` / `Library` → `name`
- `Version` / `Ver` → `version`
- `Purpose` / `Description` / `Why` → `purpose`

For each data row emit:
```yaml
- id: DEP-NN            # sequential, starting DEP-01
  name: "<name>"         # strip backticks
  version: "<version>"
  purpose: "<purpose>"
  source_anchor: "<heading>"
```

**Format B — bullet list**:

```markdown
## 8. Dependencies
- `react-markdown@^9.0.1` — core markdown renderer
- `remark-gfm@^4` — GFM extensions
```

Parse each bullet via regex:
- Capture from leading backtick-wrapped token: `<name>@<version>` → name, version.
- Capture text after `—` or `:` → purpose.

If a bullet lacks `@` (no version): `version: null`.
If a bullet lacks `—` / `:` (no purpose): `purpose: null`.

### Numbering

IDs are sequential across all deps in the section: DEP-01, DEP-02, ...
If multiple Dependencies sections somehow exist (shouldn't, but defensive): continue numbering across them.

### Output merge

After extraction, splice the emitted `external_deps` list into the
in-progress `prd_structure` object alongside the existing `modules` /
`nfrs` / `constraints` additions.
````

- [ ] **Step 3: Run fixtures — table form**

```
/ingest-docs C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-0-ingest/tests/fixtures/design-spec-extraction/deps-table.md --plans-dir /tmp/a-regex-table
```

Diff:
```bash
diff -u \
  C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-0-ingest/tests/expected/design-spec-extraction/deps-table.prd-structure.yaml \
  /tmp/a-regex-table/2026-04-21-prd-structure.yaml
```

Expected: zero diff on the `external_deps` block (4 entries, DEP-01..04, matching names/versions/purposes).

Acceptable diff: `source_files` array formatting (yaml inline vs block) — non-load-bearing. Module count + module name should match. `extraction` block is intentionally absent in both at this task boundary (added in Task 10).

- [ ] **Step 4: Run fixtures — bullet form**

```
/ingest-docs C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-0-ingest/tests/fixtures/design-spec-extraction/deps-bullets.md --plans-dir /tmp/a-regex-bullets
```

Diff against `deps-bullets.prd-structure.yaml`. Same acceptance criteria.

If bullet parsing fails (e.g. misses the `@` split) → refine Step 2's regex description; re-run.

- [ ] **Step 5: Commit regex extractor**

```bash
cd C:/Users/nity/.claude-plugin-forks/prd2impl
git add skills/skill-0-ingest/lib/prd-extractor.md
git commit -m "feat(skill-0): external_deps regex for role=design-spec

Supports table + bullet forms. §8 Dependencies / §依赖 heading detection.
Fixtures: tests/fixtures/design-spec-extraction/deps-{table,bullets}.md"
```

---

### Task 8: A' LLM fallback — sparse-spec fixture + expected

**Files:**
- Create: `skills/skill-0-ingest/tests/fixtures/design-spec-extraction/sparse-no-deps.md`
- Create: `skills/skill-0-ingest/tests/expected/design-spec-extraction/sparse-no-deps.prd-structure.yaml`

- [ ] **Step 1: Write the sparse fixture**

`skills/skill-0-ingest/tests/fixtures/design-spec-extraction/sparse-no-deps.md`:

```markdown
# Tenant Notifications — Design

## 1. Goal
Send in-app notifications to tenant admins when a sub-tenant joins.

## 2. Scope
| Surface | Persona | Trigger |
|---------|---------|---------|
| admin-portal notifications panel | tenant admin | sub-tenant onboards |
| email digest | tenant admin | daily rollup |

## 4. Component
A notifications service with in-app + email channels.
```

Deliberately lacks `§Dependencies`. `§Scope` has 2 surfaces with 1 persona.

- [ ] **Step 2: Write the expected output (fuzzy shape)**

`skills/skill-0-ingest/tests/expected/design-spec-extraction/sparse-no-deps.prd-structure.yaml`:

```yaml
# Expected output for sparse-no-deps.md.
# LLM-synthesized user_stories — exact wording will differ per run;
# match on these load-bearing invariants:
#   - len(user_stories) == 2 (one per surface)
#   - each story's `persona` ∈ { "tenant admin" } (verbatim from §Scope)
#   - each story has `source: synthesized`
#   - extraction.llm_fields == [user_stories]
#   - external_deps == [] (no §Dependencies in fixture)

prd_structure:
  source_type: "ingested"
  source_role: "design-spec"
  source_files: ["sparse-no-deps.md"]
  extraction:
    regex_fields: [modules, nfrs, constraints, external_deps]
    llm_fields: [user_stories]
  modules:
    - id: MOD-01
      name: "Component"
      description: "A notifications service with in-app + email channels."
      prd_sections: ["§4 Component"]
      sub_modules: []
  user_stories:
    # LLM output — exact strings will vary; structure invariants pinned above
    - id: US-01
      module: MOD-01
      persona: "tenant admin"
      action: "<LLM-generated>"
      goal: "<LLM-generated>"
      acceptance_criteria: []
      prd_ref: "§2 Scope row 1"
      source: synthesized
    - id: US-02
      module: MOD-01
      persona: "tenant admin"
      action: "<LLM-generated>"
      goal: "<LLM-generated>"
      acceptance_criteria: []
      prd_ref: "§2 Scope row 2"
      source: synthesized
  nfrs: []
  constraints: []
  external_deps: []
```

- [ ] **Step 3: Commit fixture + expected**

```bash
cd C:/Users/nity/.claude-plugin-forks/prd2impl
git add skills/skill-0-ingest/tests/fixtures/design-spec-extraction/sparse-no-deps.md \
        skills/skill-0-ingest/tests/expected/design-spec-extraction/sparse-no-deps.prd-structure.yaml
git commit -m "test(skill-0): add sparse-no-deps fixture for LLM user_stories fallback"
```

---

### Task 9: A' LLM fallback — add user_stories synthesis to prd-extractor

**Files:**
- Modify: `C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-0-ingest/lib/prd-extractor.md`

- [ ] **Step 1: Insert the LLM fallback subsection**

In `lib/prd-extractor.md`, within the `role=design-spec` subsection (after external_deps extraction from Task 7), append:

````markdown
### user_stories LLM synthesis (role=design-spec)

User stories are not directly present in design specs. When the spec has
a `§Scope` / `§范围` / `§2 Scope` section, synthesize minimal stories via LLM.

### Trigger

Run the LLM pass IF AND ONLY IF:
1. A section heading matching `Scope` / `范围` was found, AND
2. Regex-extracted `user_stories` is empty (currently: always true for design-spec).

Otherwise: `user_stories: []`, no LLM call.

### Extract §Scope content

Capture the §Scope section from the first heading line through the next
`##`-level heading. This is the input to the LLM.

### LLM prompt

Invoke the LLM (model: `claude-sonnet-4-6`) with:

```
System: You extract user stories from design spec Scope sections. Output YAML only.

User: Extract user stories from this design spec's Scope section.

Rules:
- Produce one user story per surface/row. Max 6 stories.
- `persona` MUST be a string that appears verbatim in the Scope text.
- `action` + `goal` describe what the persona does on that surface, using the
  spec's own language. Do NOT invent features not hinted at in the Scope.
- `acceptance_criteria` MUST be []. Do not hallucinate ACs.
- Return YAML in this exact shape:

user_stories:
  - id: US-NN
    module: MOD-??          # pick from: [{modules_list}]
    persona: "..."
    action: "..."
    goal: "..."
    acceptance_criteria: []
    prd_ref: "§Scope row N"
    source: synthesized

Scope section:
---
{scope_text}
---

Modules available: {modules_list}
```

Substitute:
- `{scope_text}` = the extracted §Scope block.
- `{modules_list}` = comma-separated list of module IDs from the in-progress
  `prd_structure.modules`. If empty, pass `MOD-01` as a fallback and emit
  one synthetic module `MOD-01 "Scope"` so stories have a valid anchor.

### Parse LLM output

1. Parse the returned YAML (expect a top-level `user_stories:` key).
2. Validate each story:
   - `persona` must be a substring of the §Scope text (literal check).
     If a persona is not found verbatim → drop that story; log warning.
   - `acceptance_criteria` must be `[]` (empty list).
   - Sequential re-numbering of `id` after validation.
3. Splice into the in-progress `prd_structure.user_stories`.

### Error handling

- LLM call fails (timeout, quota) → `user_stories: []`, emit warning
  `LLM user_stories synthesis skipped: <reason>. Re-run /ingest-docs to retry.`
- LLM output not valid YAML → `user_stories: []`, emit warning + log the
  raw output for debugging (truncate to 1000 chars).
- No personas pass the verbatim-substring check → `user_stories: []`,
  warn `LLM produced 0 stories with valid personas; check Scope format`.

### Cost ceiling

Maximum 1 LLM call per `/ingest-docs` invocation. Cache Scope text in
memory if multiple design-spec files are ingested in the same run, but
still only one call per file.
````

- [ ] **Step 2: Run sparse fixture**

```
/ingest-docs C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-0-ingest/tests/fixtures/design-spec-extraction/sparse-no-deps.md --plans-dir /tmp/a-llm-test
```

Expected:
- LLM call fires (you should see it in the transcript).
- `/tmp/a-llm-test/*-prd-structure.yaml` has `user_stories` populated with 2 entries.
- Each entry has `persona: "tenant admin"` (verbatim from §Scope).
- Each entry has `source: synthesized`.
- `extraction.llm_fields: [user_stories]`.

- [ ] **Step 3: Validate invariants programmatically**

Run:
```bash
python - <<'PY'
import yaml, sys
with open("/tmp/a-llm-test/2026-04-21-prd-structure.yaml") as f:
    d = yaml.safe_load(f)
us = d["prd_structure"]["user_stories"]
assert len(us) == 2, f"expected 2 stories, got {len(us)}"
for s in us:
    assert s["persona"] == "tenant admin", f"bad persona: {s['persona']}"
    assert s["source"] == "synthesized"
    assert s["acceptance_criteria"] == []
assert d["prd_structure"]["extraction"]["llm_fields"] == ["user_stories"]
print("OK")
PY
```

Expected: prints `OK`.

If any assertion fails → inspect the LLM output, refine the prompt in Step 1, re-run.

- [ ] **Step 4: Negative trigger check — regression on deps-table fixture**

Re-run the deps-table fixture from Task 7 (which has NO §Scope by design — see Task 6 Step 1):
```
/ingest-docs .../deps-table.md --plans-dir /tmp/a-regex-table-2
```

Expected:
- NO LLM call (because §Scope absent → trigger condition 1 fails).
- `user_stories: []` in output.
- `external_deps` still populated (4 entries).

If LLM fires anyway → trigger logic in Step 1 is too loose; tighten the §Scope-presence check.

- [ ] **Step 5: Commit LLM fallback**

```bash
cd C:/Users/nity/.claude-plugin-forks/prd2impl
git add skills/skill-0-ingest/lib/prd-extractor.md
git commit -m "feat(skill-0): LLM user_stories synthesis for role=design-spec

Triggers when §Scope present and regex user_stories empty. sonnet-4-6,
≤1 call/ingest. Personas pinned to verbatim §Scope substrings."
```

---

### Task 10: A' extraction metadata — emit regex_fields + llm_fields

**Files:**
- Modify: `C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-0-ingest/SKILL.md`

- [ ] **Step 1: Locate the Phase 4 write section**

```bash
grep -n "Phase 4\|Write files\|prd_structure:" \
  C:/Users/nity/.claude-plugin-forks/prd2impl/skills/skill-0-ingest/SKILL.md | head -10
```

Identify where the in-memory `prd_structure` dict gets written to
`{plans_dir}/{date}-prd-structure.yaml` (likely §4.2).

- [ ] **Step 2: Insert extraction metadata population**

In §4.2 of `skill-0-ingest/SKILL.md`, before the write step, add:

```markdown
### Populate extraction metadata

Before writing `prd-structure.yaml`, add an `extraction` key to the
`prd_structure` dict recording which fields came from which path:

```python-like pseudocode
prd_structure["extraction"] = {
    "regex_fields": ["modules", "nfrs", "constraints", "external_deps"],
    "llm_fields": ["user_stories"] if llm_user_stories_ran else []
}
```

This field is consumed by downstream skills (skill-3-task-gen,
skill-12-contract-check) to decide where to apply fuzzy matching vs.
strict validation.

Only emit this metadata for `source_role: design-spec`. For `prd` /
`plan` / `user-stories` roles, omit the `extraction` key (all fields
came from regex; no LLM calls).
```

- [ ] **Step 3: Update expected fixtures to include extraction metadata**

Task 6 produced expected yamls WITHOUT `extraction`. Now that the field exists, update all three design-spec expected files to include it.

Edit `skills/skill-0-ingest/tests/expected/design-spec-extraction/deps-table.prd-structure.yaml` — insert after `source_files:`:

```yaml
  extraction:
    regex_fields: [modules, nfrs, constraints, external_deps]
    llm_fields: []
```

Edit `deps-bullets.prd-structure.yaml` — same insertion.

Edit `sparse-no-deps.prd-structure.yaml` — its `extraction` block already has `llm_fields: [user_stories]` from Task 8 Step 2. Leave it (it was aspirational; now real).

- [ ] **Step 4: Validate via deps-table fixture**

```
/ingest-docs .../deps-table.md --plans-dir /tmp/a-meta-test
```

Check:
```bash
python -c "
import yaml
d = yaml.safe_load(open('/tmp/a-meta-test/2026-04-21-prd-structure.yaml'))
assert 'extraction' in d['prd_structure']
assert d['prd_structure']['extraction']['regex_fields'] == ['modules', 'nfrs', 'constraints', 'external_deps']
assert d['prd_structure']['extraction']['llm_fields'] == []  # deps-table has no §Scope, no LLM
print('OK')
"
```

Expected: prints `OK`.

Diff the full output against the just-updated expected file — should match exactly (modulo `source_files` yaml formatting).

- [ ] **Step 5: Commit metadata field + expected updates**

```bash
cd C:/Users/nity/.claude-plugin-forks/prd2impl
git add skills/skill-0-ingest/SKILL.md \
        skills/skill-0-ingest/tests/expected/design-spec-extraction/deps-table.prd-structure.yaml \
        skills/skill-0-ingest/tests/expected/design-spec-extraction/deps-bullets.prd-structure.yaml
git commit -m "feat(skill-0): emit extraction.{regex_fields,llm_fields} metadata

Downstream skills key off this to decide validation strictness.
Only populated for role=design-spec. Expected fixtures updated to match."
```

---

### Task 11: E2E — re-ingest chat-markdown spec; diff against hand-written ground truth

**Files:** None modified; validation only.

- [ ] **Step 1: Set up clean plans_dir**

```bash
mkdir -p /tmp/e2e-chat-md
# Ensure nothing leaks from a prior run
rm -f /tmp/e2e-chat-md/*.yaml
```

- [ ] **Step 2: Re-ingest the real chat-markdown design spec**

In a fresh Claude Code session (AutoService repo):
```
/ingest-docs docs/superpowers/specs/2026-04-21-chat-markdown-design.md --plans-dir /tmp/e2e-chat-md
```

Expected output files:
- `/tmp/e2e-chat-md/2026-04-21-task-hints.yaml`
- `/tmp/e2e-chat-md/2026-04-21-prd-structure.yaml` ← **NEW — didn't exist before A' was implemented**

- [ ] **Step 3: Diff auto vs hand-written prd-structure**

Ground truth: `docs/plans/feat-chat-markdown/2026-04-21-prd-structure.yaml` (the hand-written one from the prior session).

```bash
diff -u \
  docs/plans/feat-chat-markdown/2026-04-21-prd-structure.yaml \
  /tmp/e2e-chat-md/2026-04-21-prd-structure.yaml
```

Acceptance (from spec §7.3):
1. `external_deps` — all 4 present (react-markdown / remark-gfm / rehype-highlight / highlight.js), matching versions.
2. `modules` — count 4 ± 1 (hand-written has 4).
3. `user_stories` — 4-5 stories (one per surface in chat-markdown's §2 Scope).
4. Each story's `persona` must appear verbatim in the spec's §2 Scope column values.

Expected drift (acceptable):
- Exact module descriptions (hand-written is more specific).
- Exact user_stories wording (LLM vs human).
- `nfrs` / `constraints` counts (extractor may be stricter than the human).

- [ ] **Step 4: If drift is beyond acceptance — iterate**

If `external_deps` count < 4 → regex in prd-extractor.md (Task 7) has a bug. Inspect which deps are missing; tighten the bullet/table regex; re-run Task 7 Step 3-4; re-run E2E Step 2.

If `user_stories` personas fail verbatim check → LLM prompt in Task 9 needs tightening; adjust the "persona must appear verbatim" enforcement; re-run Task 9 Step 2-3; re-run E2E Step 2.

- [ ] **Step 5: Record E2E evidence**

Append to the fork's `README.md` under the "Fork status" block:

```markdown
## E2E validation — chat-markdown

Ran /ingest-docs against docs/superpowers/specs/2026-04-21-chat-markdown-design.md.
- external_deps: 4/4 extracted
- modules: <N> (ground truth: 4)
- user_stories: <N> synthesized; <K>/<N> personas matched §Scope verbatim
- Diff vs hand-written: <brief summary>
```

- [ ] **Step 6: Commit E2E evidence**

```bash
cd C:/Users/nity/.claude-plugin-forks/prd2impl
git add README.md
git commit -m "docs: E2E validation log against AutoService chat-markdown spec"
```

---

### Task 12: Upstream PR prep

**Files:** None modified; PR preparation only.

- [ ] **Step 1: Rebase onto upstream main**

```bash
cd C:/Users/nity/.claude-plugin-forks/prd2impl
git fetch origin
git rebase origin/main
```

If conflicts: resolve using the design in this plan as the authoritative intent.

- [ ] **Step 2: Squash to 2 logical commits**

Target commit layout:
1. `feat(skill-3): B2 degradation — task-hints-only mode`
2. `feat(skill-0): design-spec bridge — external_deps regex + user_stories LLM synthesis + extraction metadata`

Use `git rebase -i` style (but interactive — the plan cannot do this; do it manually in a terminal session). Alternatively keep the per-task commits and let upstream decide squash policy.

- [ ] **Step 3: Push branch to fork**

```bash
cd C:/Users/nity/.claude-plugin-forks/prd2impl
# Push to your GitHub fork (remote name depends on how you cloned — likely 'origin' if cloned from your own fork, or add a 'personal' remote)
git remote -v
git push -u origin feat/design-spec-bridge
```

If upstream was cloned directly (no personal fork remote), first fork `ezagent42/prd2impl` on GitHub UI, then:
```bash
git remote rename origin upstream
git remote add origin <your-fork-url>
git push -u origin feat/design-spec-bridge
```

- [ ] **Step 4: Create PR**

```bash
gh pr create --repo ezagent42/prd2impl --title "feat: design-spec → task-gen bridge (A'+B2)" --body "$(cat <<'EOF'
## Summary
- **skill-3**: graceful B2 degradation — allow /task-gen with only task-hints.yaml by synthesizing skeleton modules from implementation_steps
- **skill-0**: design-spec extractor now emits full prd-structure (adds external_deps regex + user_stories LLM synthesis)
- **metadata**: new extraction.regex_fields / llm_fields lets downstream skills know provenance

## Motivation
Closes the gap where superpowers brainstorming design specs couldn't flow into /task-gen without hand-writing prd-structure.yaml. Spec + design doc in branching project: AutoService `docs/superpowers/specs/2026-04-21-prd2impl-bridge-enhancement-design.md`.

## Test plan
- [x] B2 task-hints-only fixture (skill-3/tests/fixtures/b2-degraded/)
- [x] B2 regression (both files present)
- [x] B2 edge case (empty implementation_steps)
- [x] A' external_deps fixtures (table + bullet forms)
- [x] A' user_stories LLM fallback fixture
- [x] E2E against real chat-markdown design spec — diff vs hand-written ground truth

## Risks
- LLM call introduces ≤1 sonnet call per /ingest-docs with §Scope; capped, warned on failure
- Skeleton module names truncate step.description to 60 chars — cosmetic

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Final AutoService-side commit — link plan + spec to fork PR**

In AutoService repo (branch `dev-a`), append to the spec `docs/superpowers/specs/2026-04-21-prd2impl-bridge-enhancement-design.md`:

```markdown
---

## Implementation status (2026-04-21)

- Fork branch: `C:/Users/nity/.claude-plugin-forks/prd2impl` @ `feat/design-spec-bridge`
- Upstream PR: <URL from gh pr create output>
- Plan: `docs/superpowers/plans/2026-04-21-prd2impl-bridge-enhancement.md`
```

Commit:
```bash
git add docs/superpowers/specs/2026-04-21-prd2impl-bridge-enhancement-design.md \
        docs/superpowers/plans/2026-04-21-prd2impl-bridge-enhancement.md
git commit -m "docs: link bridge-enhancement plan + upstream PR to spec"
```

---

## Self-review checklist (author)

Spec coverage:
- §5.2 external_deps → Tasks 6 (fixtures) + 7 (extractor)
- §5.3 user_stories LLM → Tasks 8 (fixture) + 9 (synthesis)
- §5.4 extraction metadata → Task 10
- §6.2 B2 degradation → Tasks 2-5
- §7.1 A' tests → Tasks 6, 8
- §7.2 B2 tests → Tasks 2, 5
- §7.3 E2E → Task 11
- §8 implementation order → Tasks 2-5 (B2 first), 6-7 (A' regex), 8-9 (A' LLM), 10 (metadata), 11 (E2E), 12 (PR)
- §4 fork location → Task 0
- Spec correction for gap-analysis → Task 1

Placeholder scan: no TBDs, no "similar to Task N", each step has concrete commands.

Type consistency: `traceability: task-hints-only` field name used in Task 4 skeleton + Task 2 expected yaml + Task 5 regression check — matches. `synthesized_module_id` same. `extraction.regex_fields` / `llm_fields` consistent across Tasks 6, 8, 10.

Known limitation: tests are invoked via `/ingest-docs` and `/task-gen` in a Claude session rather than an automated harness. prd2impl doesn't have one. An automated harness could be added later; not in scope for this plan.
