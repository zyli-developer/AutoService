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

prd2impl is installed as a plugin at `C:/Users/nity/.claude/plugins/cache/ezagent42/prd2impl/0.2.2/`. Modifying the cache directly is fragile — a plugin update will wipe changes.

Deployment plan:

1. Fork prd2impl to a local working clone at `~/.claude-plugin-forks/prd2impl/` (git clone from upstream `ezagent42/prd2impl`).
2. Point Claude Code at the fork via `~/.claude/settings.json` plugin source override (exact key TBD during implementation).
3. Iterate there. Once stable, push the fork to `github.com/<user>/prd2impl` and PR to upstream.

Until PR merges, pin the upstream commit SHA in the fork's README so re-basing is traceable.

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

### 5.3 New LLM pass: user_stories synthesis

Trigger conditions (all must hold):

- `§Scope` section is present (detected by heading match)
- Regex extraction for `user_stories` yields empty (always true for design-spec today)

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
    llm_fields: [user_stories]          # only present when LLM fallback ran
  ...
```

Downstream (skill-3, skill-12-contract-check) reads this to know where to apply fuzzy matching vs. strict validation.

## 6. B design — skill-3 degradation (B2)

### 6.1 Current behavior

`skill-3-task-gen` reads `{plans_dir}/{date}-prd-structure.yaml` (required) + `{date}-task-hints.yaml` (optional) + `{date}-gap-analysis.yaml` (optional). Missing `prd-structure.yaml` → hard error.

### 6.2 B2 change

If `prd-structure.yaml` absent AND `task-hints.yaml` present AND `task-hints.implementation_steps` non-empty:

1. Synthesize a skeleton `prd_structure` **in memory** (not persisted to disk):
   - `modules[]` = one entry per `implementation_steps[]` entry
     - `id` = `MOD-NN` (sequential)
     - `name` = step.description truncated to 60 chars
     - `sub_modules` = `touches_files` mapped to simple `{id, name}` pairs
   - `user_stories: []`
   - `nfrs: []`
   - `constraints: []`
   - `external_deps: []`
2. Mark the synthesis in memory: `source: synthesized-from-task-hints`.

If `task-hints.implementation_steps` is empty → hard error (same as the "neither present" case in §7.2 — nothing to synthesize from).
3. Generate `tasks.yaml` as normal.
4. Each task gets a new field `traceability: task-hints-only`.
5. Print warning:

```
No prd-structure.yaml found; running in task-hints-only mode.
Synthesized {N} skeleton modules (MOD-01..MOD-{N}) from implementation_steps.
user_stories / nfrs / constraints / external_deps are empty — downstream
skills (contract-check, retro) will skip checks that depend on these fields.
```

### 6.3 Downstream impact

- `/task-status` — task list renders; phase grouping falls back to step number rather than module name (acceptable degradation).
- `/contract-check` — skips `user_stories`-level AC checks; still runs module-level diff.
- `/retro` — unaffected (reads `tasks.yaml`, not `prd-structure`).

### 6.4 What does NOT change

- If both files present → zero behavior change (regression guard).
- The synthesized `prd_structure` is NEVER written to disk. If user runs `/ingest-docs` afterward, they get a real file; the skeleton was only scaffolding for this `/task-gen` call.

## 7. Testing

### 7.1 A' — prd-extractor role=design-spec tests

Add fixtures under `skill-0-ingest/tests/fixtures/design-spec-extraction/`:

| Fixture | Shape | Assertion |
|---------|-------|-----------|
| `deps-table.md` | §8 Dependencies as markdown table | `len(external_deps) == 4`; `DEP-01.version == "^9.0.1"` |
| `deps-bullets.md` | §8 Dependencies as bullet list | Same count, bullet-form parser works |
| `sparse-no-deps.md` | §Scope only, no §Dependencies | `external_deps == []`; `llm_fields` includes `user_stories` |
| `real/chat-markdown-design.md` | Copy of actual spec | DEP count = 4 (react-markdown / remark-gfm / rehype-highlight / highlight.js); `user_stories` LLM-synthesized with 4-5 stories matching 4 surfaces |

### 7.2 B — skill-3 degradation tests

| Scenario | Inputs | Assertion |
|----------|--------|-----------|
| task-hints-only | `task-hints.yaml` present, no `prd-structure.yaml` | `tasks.yaml` generated; warning printed; each task has `traceability: task-hints-only` |
| both present | `prd-structure.yaml` + `task-hints.yaml` | Regression — behavior identical to pre-change |
| neither present | empty plans_dir | Hard error (no degradation path) |

### 7.3 End-to-end validation

Re-run `/ingest-docs docs/superpowers/specs/2026-04-21-chat-markdown-design.md`:

- Before this change: produces only `task-hints.yaml`
- After this change: produces `task-hints.yaml` + auto-synthesized `prd-structure.yaml`

Diff the auto-synthesized `prd-structure.yaml` against the hand-written one we produced earlier (`docs/plans/feat-chat-markdown/2026-04-21-prd-structure.yaml`) as ground truth. Acceptance: auto version should match on `external_deps` (all 4), on `modules` count (4 ± 1), on `user_stories` shape (4 surfaces → 4-5 stories). Exact persona strings may differ (LLM vs human) but must come from §Scope verbatim.

## 8. Implementation order

1. **B2 first** — skill-3 degradation. Self-contained, low-risk. Unlocks "run `/task-gen` without prd-structure" for any use case, not just design-spec. Gives an immediate release-valve for hand-writing workarounds.
2. **A' regex upgrade** — add `external_deps` extractor to `prd-extractor.md` role=design-spec branch. Deterministic, testable in isolation.
3. **A' LLM fallback** — add `user_stories` synthesis. Gated by trigger conditions (§5.3). Tested with sparse-spec fixture.
4. **E2E validation** — re-ingest chat-markdown design spec, diff against hand-written ground truth, iterate on prompt if drift is high.

## 9. Risks

| Risk | Mitigation |
|------|-----------|
| LLM synthesizes personas not in the spec | Prompt constrains persona to strings verbatim in §Scope; fixture test asserts persona membership |
| Plugin fork drifts from upstream | Pin upstream SHA in fork README; PR back once stable |
| B2's synthesized module names are ugly (step descriptions are long) | 60-char truncation + defer to user to re-ingest for real prd-structure once they write one |
| Regex false-positive on `§8 Dependencies` when spec's §8 is actually "Testing" | Match the section by *heading text* ("Dependencies" / "依赖") not by number |
| LLM call cost / latency | Capped at ≤1 call per `/ingest-docs`; sonnet ≈ 1-2s |

## 10. Deferred to writing-plans

- Exact LLM model (sonnet-4.6 vs haiku-4.5 — quality/cost bench)
- Exact settings.json key for plugin source override (depends on Claude Code plugin loader version)
- Whether fork pushes to public `github.com/<user>/prd2impl` or stays local during iteration
