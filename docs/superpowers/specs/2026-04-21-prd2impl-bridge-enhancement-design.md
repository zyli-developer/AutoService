# prd2impl Bridge Enhancement — Design

**Date**: 2026-04-21 · **Author**: brainstorm session (hjj.gemini@gmail.com + Claude) · **Status**: DRAFT (pending user review)

## 1. Goal

Let superpowers design specs flow into prd2impl's pipeline without hand-writing `prd-structure.yaml`. Close the currently-broken bridge between `/brainstorming` output and `/task-gen` input.

## 2. Scope

Two changes, both in prd2impl, none in superpowers:

- **A'** — Upgrade `skill-0-ingest/lib/prd-extractor.md`'s `role=design-spec` branch to produce a **complete** prd-structure (add `user_stories` + `external_deps`, currently skipped). Level-2 implementation: regex for structured sections, LLM fallback for prose-to-story synthesis.
- **B** — Make `skill-3-task-gen`'s `prd-structure.yaml` dependency degrade gracefully. B2 variant: when absent, synthesize a skeleton `modules[]` in memory from `task-hints.implementation_steps` instead of erroring.

## 3. Non-goals

- Modifying superpowers (brainstorming, writing-plans, any skill) — out-of-tree, read-only
- Adding a new `/command` — stays at `/ingest-docs` + `/task-gen`
- Full PRD auto-generation from a raw idea — only upgrades the `role=design-spec` path
- Migrating existing hand-written `prd-structure.yaml` files — forward-only; legacy files remain valid

## 4. Where changes live

prd2impl source repo at `D:/Work/h2os.cloud/prd2impl/` is the maintainer's own active development repo (not a fork, not a cache). Current branch `feat/design-spec-ingest` is already the ongoing dev line for design-spec ingestion (recent commits: v0.2.1, v0.2.2). We continue on this branch — **no fork, no `~/.claude/settings.json` change, no clone required**.

Deployment: plain git commits on `feat/design-spec-ingest`, tested in a separate Claude Code session that loads prd2impl from this repo. Release cadence (next version bump, changelog) is the maintainer's existing flow.

## 5. A' design — design-spec extractor enrichment

### 5.1 Current extraction (role=design-spec)

`lib/prd-extractor.md` currently pulls:

- `modules` — from `§Component` + `§Integration points` headings
- `nfrs` — from `§Performance` / `§Compatibility` sub-sections
- `constraints` — from `§Security` / `§Architecture` sub-sections

Skipped: `user_stories`, `external_deps`.

### 5.2 New regex: external_deps

Parse `§Dependencies` (or `§8 Dependencies`, `§依赖`) using two sub-formats:

**Format A — table**:

```markdown
## 8. Dependencies
| Package | Version | Purpose |
|---------|---------|---------|
| react-markdown | ^9.0.1 | core markdown renderer |
```

**Format B — bullet list**:

```markdown
- `react-markdown@^9.0.1` — core markdown renderer
- `remark-gfm@^4` — GFM extensions
```

Emit as:

```yaml
external_deps:
  - id: DEP-01
    name: "react-markdown"
    version: "^9.0.1"
    purpose: "core markdown renderer"
    source_anchor: "§8 Dependencies"
```

### 5.3 New LLM pass: user_stories synthesis (opt-in)

**Design tension:** `lib/prd-extractor.md:290-291` explicitly states `user_stories: []` is intentional for `role=design-spec` ("design-spec focuses on what/how, not who/why"). That decision remains the default. LLM synthesis is gated behind an **opt-in flag**:

```
/ingest-docs <files> --synthesize-user-stories
```

Without the flag → current behavior preserved (empty `user_stories` for design-spec).

When the flag is passed, trigger conditions still apply:
- `§Scope` section is present (detected by heading match)
- Regex extraction for `user_stories` yields empty (always true for design-spec)

Without `§Scope` but with the flag → emit warning `--synthesize-user-stories set but §Scope section not found; user_stories remains []`.

Prompt shape (single call, returns YAML):

```
You are extracting user stories from a design spec. The spec's §Scope section
lists surfaces/roles. Produce 3–6 user stories in this YAML shape:

user_stories:
  - id: US-NN
    module: MOD-??         # match to a module id from this list: [...]
    persona: "..."          # exact role string from §Scope
    action: "..."
    goal: "..."
    acceptance_criteria: []
    prd_ref: "§Scope row N"
    source: synthesized

Rules:
- One story per surface (max 6). If §Scope has more, pick the most user-visible.
- Persona MUST be a string that appears verbatim in §Scope.
- acceptance_criteria MAY be empty — do NOT hallucinate them.
- Output YAML only, no prose.
```

Model: sonnet (quality matters here; called ≤1× per `/ingest-docs`).

### 5.4 Output signaling

Extend `prd-structure.yaml` metadata so downstream knows what was synthesized vs extracted:

```yaml
prd_structure:
  source_type: "ingested"
  source_role: "design-spec"
  extraction:
    regex_fields: [modules, nfrs, constraints, external_deps]
    llm_fields: [user_stories]          # only present when --synthesize-user-stories fired AND produced stories
  ...
```

When `--synthesize-user-stories` was NOT passed: `llm_fields: []`.
When flag passed but `§Scope` missing OR LLM failed: `llm_fields: []` (same as no-flag case, so downstream treats it uniformly).

Downstream (skill-3, skill-12-contract-check) reads this to know where to apply fuzzy matching vs. strict validation.

## 6. B design — skill-3 degradation (B2)

### 6.1 Current behavior

`skill-3-task-gen` reads `{plans_dir}/{date}-prd-structure.yaml` (required) + `{date}-gap-analysis.yaml` (required) + `{date}-task-hints.yaml` (optional). Missing either required file → hard error.

### 6.2 B2 change

If `task-hints.yaml` is present with non-empty `implementation_steps`, AND either `prd-structure.yaml` OR `gap-analysis.yaml` (or both) are absent:

1. Synthesize in memory whatever is missing (NEVER persist to disk):

   - If `prd-structure.yaml` missing: synthesize a skeleton `prd_structure` with:
     - `modules[]` = one entry per `implementation_steps[]` entry
       - `id` = `MOD-NN` (sequential)
       - `name` = step.description truncated to 60 chars
       - `sub_modules` = `touches_files` mapped to simple `{id, name}` pairs
     - `user_stories: []`
     - `nfrs: []`
     - `constraints: []`
     - `external_deps: []`
     - Marker: `source: synthesized-from-task-hints`
   - If `gap-analysis.yaml` missing: synthesize `gap_analysis = { gaps: [] }` — task generation proceeds off `implementation_steps` alone, no gap-ID linking.

2. Generate `tasks.yaml` as normal using the synthesized structures alongside any real ones.
3. Each task gets a new field `traceability: task-hints-only` and (when prd-structure synthesized) a `synthesized_module_id` pointing to its skeleton module.
4. Print warning banner listing which files were missing.

If `task-hints.implementation_steps` is empty → hard error (nothing to synthesize from; same as the "neither present" case in §7.2).

Warning banner format:

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

### 6.3 Downstream impact

- `/task-status` — task list renders; phase grouping falls back to step number rather than module name (acceptable degradation).
- `/contract-check` — skips `user_stories`-level AC checks; still runs module-level diff.
- `/retro` — unaffected (reads `tasks.yaml`, not `prd-structure`).

### 6.4 What does NOT change

- If all three input files (prd-structure, gap-analysis, task-hints) are present → zero behavior change (regression guard).
- Synthesized structures are NEVER written to disk. If user runs `/ingest-docs` afterward, they get real files; the skeleton was only scaffolding for this `/task-gen` call.

## 7. Testing

### 7.1 A' — prd-extractor role=design-spec tests

Add fixtures under `skill-0-ingest/tests/fixtures/design-spec-extraction/`:

| Fixture | Shape | Assertion |
|---------|-------|-----------|
| `deps-table.md` | §8 Dependencies as markdown table (no §Scope) | `len(external_deps) == 4`; `DEP-01.version == "^9.0.1"` |
| `deps-bullets.md` | §8 Dependencies as bullet list (no §Scope) | Same count, bullet-form parser works |
| `sparse-opt-in.md` | §Scope only, no §Dependencies — run with `--synthesize-user-stories` | flag-off: `user_stories == []`; flag-on: 2 synthesized stories with `source: synthesized`, personas verbatim from §Scope |
| `real/chat-markdown-design.md` (DEFERRED — Task 11) | Copy of actual spec | DEP count = 4; `user_stories` (flag-on) 4-5 stories matching 4 surfaces |

### 7.2 B — skill-3 degradation tests

| Scenario | Inputs | Assertion |
|----------|--------|-----------|
| task-hints-only (neither gap nor prd) | `task-hints.yaml` only | `tasks.yaml` generated; warning printed; each task has `traceability: task-hints-only` |
| prd-only-missing | `task-hints.yaml` + `gap-analysis.yaml` | Tasks gain gap IDs but synthetic module IDs |
| gap-only-missing | `task-hints.yaml` + `prd-structure.yaml` | Tasks gain real module IDs but no gap refs |
| all three present | prd-structure + gap-analysis + task-hints | Regression — behavior identical to pre-change |
| only prd-structure (no hints, no gap) | `prd-structure.yaml` only | Hard error (no degradation path) |
| fully empty | empty plans_dir | Hard error |

### 7.3 End-to-end validation (DEFERRED)

Per user direction (2026-04-21), E2E validation against AutoService's `chat-markdown-design.md` is **deferred** until current AutoService M3 work settles. Synthetic fixtures under `skills/skill-0-ingest/tests/fixtures/design-spec-extraction/` + `skills/skill-3-task-gen/tests/fixtures/b2-degraded/` are sufficient for initial merge.

When reactivated, the acceptance criteria are:

- Re-run `/ingest-docs docs/superpowers/specs/2026-04-21-chat-markdown-design.md --synthesize-user-stories`
- Before: produces only `task-hints.yaml`
- After: produces `task-hints.yaml` + auto-synthesized `prd-structure.yaml` with `external_deps` = 4 (from §8) + `user_stories` = 4-5 (from §2 Scope with flag on)
- Diff auto vs hand-written `docs/plans/feat-chat-markdown/2026-04-21-prd-structure.yaml` — match on `external_deps` list, module count ±1, persona strings verbatim-in-§Scope

## 8. Implementation order

1. **B2 first** — skill-3 degradation. Self-contained, low-risk. Unlocks "run `/task-gen` without prd-structure" for any use case, not just design-spec. Gives an immediate release-valve for hand-writing workarounds.
2. **A' regex upgrade** — add `external_deps` extractor to `prd-extractor.md` role=design-spec branch. Deterministic, testable in isolation.
3. **A' LLM fallback** — add `user_stories` synthesis. Gated by trigger conditions (§5.3). Tested with sparse-spec fixture.
4. **E2E validation** — re-ingest chat-markdown design spec, diff against hand-written ground truth, iterate on prompt if drift is high.

## 9. Risks

| Risk | Mitigation |
|------|-----------|
| LLM synthesizes personas not in the spec | Prompt constrains persona to strings verbatim in §Scope; fixture test asserts persona membership |
| Existing users unaware `--synthesize-user-stories` flag exists | Document in skill-0 SKILL.md §Inputs; `/ingest-docs --help` (if present) mentions it; default stays `user_stories: []` so surprise factor is low |
| B2's synthesized module names are ugly (step descriptions are long) | 60-char truncation + defer to user to re-ingest for real prd-structure once they write one |
| Regex false-positive on `§8 Dependencies` when spec's §8 is actually "Testing" | Match the section by *heading text* ("Dependencies" / "依赖") not by number |
| LLM call cost / latency | Capped at ≤1 call per `/ingest-docs`; sonnet ≈ 1-2s; only when flag on |

## 10. Deferred to writing-plans

- Exact LLM model (sonnet-4.6 vs haiku-4.5 — quality/cost bench) — resolved during implementation: `claude-sonnet-4-6` (see [prd2impl PR #4](https://github.com/ezagent42/prd2impl/pull/4) prd-extractor.md §user_stories LLM synthesis)
- Flag name: `--synthesize-user-stories` confirmed non-clashing with existing skill-0 flags (`--tag`, `--plans-dir`)
- E2E timing — reactivate Task 11 after AutoService M3 quiescence

---

## 11. Implementation status (2026-04-21)

- **Work branch**: `D:/Work/h2os.cloud/prd2impl` @ `feat/design-spec-ingest` (8 commits ahead of origin pre-PR, all pushed)
- **Internal PR**: https://github.com/ezagent42/prd2impl/pull/4
- **Plan**: [docs/superpowers/plans/2026-04-21-prd2impl-bridge-enhancement.md](../plans/2026-04-21-prd2impl-bridge-enhancement.md)
- **Landed commits** (in PR branch, oldest first):
  - `42b27db` test(skill-3): B2 task-hints-only fixture
  - `dee3fbc` feat(skill-3): B2 degradation — task-hints-only mode
  - `a7d861b` fix(skill-3): explicit Step 1 → Step 1.5 bridge on missing inputs
  - `b78f3d0` test(skill-0): external_deps fixtures (table + bullet)
  - `9b6e537` feat(skill-0): extract external_deps for role=design-spec
  - `a917c37` test(skill-0): sparse-opt-in fixture for `--synthesize-user-stories`
  - `83c9427` feat(skill-0): opt-in `--synthesize-user-stories` for design-spec
  - `032a8de` feat(skill-0): emit `extraction.{regex_fields, llm_fields}` metadata
- **Task status**:
  - Tasks 0-4, 6-10, 12 — DONE
  - Task 5 (B2 real-run validation) + Task 11 (chat-markdown E2E) — DEFERRED, batched for post-M3 execution
- **Static validation**: fixture pairs under `prd2impl/skills/skill-{0,3}-*/tests/` verified by inspection (extraction metadata present in all design-spec expected files; DEP counts match; b2-degraded shape correct)
