# M3 Collaboration Playbook

> M3-scoped (plans_dir=`docs/plans/m3/`). Team structure, workflow, commit conventions, contract change protocol, Yellow/Red SLAs.

## 1. Team Structure

**Solo line + Claude Code parallel subagents (parallel_capacity=2)**

| Role | Who | Branch | Responsibility |
|---|---|---|---|
| Main orchestrator | Dev1 + Claude Code | `dev-a` | Critical path execution; batch dispatch; integration |
| Subagent-1 | Dispatched by orchestrator | (same branch) | Parallel independent task inside a batch |
| Subagent-2 | Dispatched by orchestrator | (same branch) | Parallel independent task inside a batch |
| Code Reviewer | `superpowers:code-reviewer` subagent | — | Yellow task review; 🔒 CON-04 security review |

**Branch strategy**: Single-branch `dev-a`; frequent commits per CLAUDE.md convention. Merge to `dev` only at M3 gate.

---

## 2. Daily Workflow (Layered)

### Layer 1 — Independent task execution (most of the day)
- Orchestrator picks next task via `/prd2impl:skill-7-next-task` or batch-dispatch
- For each task: follow [cc-prompt-templates.md §1-3](cc-prompt-templates.md) (Opening → Running → Closing)
- Commit frequency: per task (or more granular for checkpoints)

### Layer 2 — Batch sync (every 2-4 tasks)
- When a batch's tasks all close: update Batch Progress table + run batch gate
- Commit: `chore(m3): batch-{N} gate passed + summary`
- Announce next batch in Session Log

### Layer 3 — Milestone gate (every 3-5 batches)
- Run milestone smoke: `/prd2impl:skill-10-smoke-test M3-{N}`
- Collect evidence → `.artifacts/milestones/m3-{N}-smoke.md`
- If gate passes: advance milestone in task-status.md Overall Progress

---

## 3. Commit Conventions

Based on Conventional Commits:

| Prefix | Use | Example |
|---|---|---|
| `feat(m3)` | Task-level functional code delivery | `feat(m3): T1S.2 operator login + operator_session cookie` |
| `test(m3)` | Test-only commit | `test(m3): T2S.1 RBAC P95<5ms benchmark` |
| `chore(m3)` | Status/plan artifacts, no prod code | `chore(m3): batch-4 gate passed; task-status updated` |
| `fix(m3)` | Bug fix during dev | `fix(m3): T1S.3 WS cookie TTL boundary` |
| `refactor(m3)` | Internal restructure, same behavior | `refactor(m3): extract invite_token from auth.py` |
| `docs(m3)` | docs/plans/m3/ or docs/superpowers/specs/ updates | `docs(m3): correct GAP-E3.1 existing_code` |

**Commit body must include** (per [CLAUDE.md §/autorun conventions](../../../CLAUDE.md#L120)):
- Verification command + result
- Test counts
- Yellow/🔒 task: reviewer judgment

**Claude co-authorship**:
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

**Never**: `--no-verify`, amending published commits, force-push to `dev`.

---

## 4. Contract Change Protocol

If mid-execution you discover a contract (docs/contracts/m3/) needs to change:

1. **Stop the task** — do not code around a stale contract
2. Update the contract doc in a dedicated commit: `docs(m3): update e{N} contract — {reason}`
3. Cascade: update [tasks.yaml](tasks.yaml) `deliverables` / `verification` if affected
4. Notify in Session Log: "contract change at {batch-N} — {summary}"
5. If the change breaks an already-completed task: add a follow-up task to `tasks.yaml` (P4 or later) to fix
6. Resume original task

**Rule**: Contracts are cheap to rewrite before code lands; expensive after. Batch-0 exists specifically to freeze them up-front.

---

## 5. Task Color SLAs

### 🟢 Green (26 tasks)
- No external review required
- Merge after self-verification pass
- Target: 1-2h (Small) / 2-8h (Medium) / >8h (Large)

### 🟡 Yellow (13 tasks)
- **Mandatory**: independent code-reviewer pass before Closing
- Reviewer tools:
  - `/superpowers:requesting-code-review` (preferred)
  - `Agent subagent_type=superpowers:code-reviewer`
- Review focuses: contract fidelity, test coverage ≥80%, M2 non-regression, security (auth/RBAC/CON-04)
- Reviewer judgment recorded in commit body
- If CHANGES_REQUESTED: fix → re-review before Closing

### 🔴 Red — **None in M3**
- Epic E2 descope removed the original 2 Red tasks (fork-internal emplace + tier_2 billing architecture decisions). All remaining work is Green/Yellow.

### 🔒 CON-04 Security-Critical (T4S.1, T4S.8 — subset of Yellow)
- **Two reviewers** required: automated (AST guardrail test) + human-style subagent
- Specific checks (from [E5 design spec](../../superpowers/specs/2026-04-21-m3-e5-dream-extension-design.md) §Cross-cutting guardrails):
  1. `apply_proposal` module has no imports from `dream_agent` / `master_dream_agent`
  2. Only `apply_proposal` writes `status='applied'`
  3. `status` string in forbidden files fails AST test
  4. `emit_proposal` signature lock test still passes
- PR description template must include CON-04 checklist

---

## 6. Open-Question Escalation

All 14 OQs captured in [tasks.yaml §meta.default_oq_values](tasks.yaml). When you hit a decision point in a task:

1. **Has default applied?** Yes → use default, note in commit body `(applying default OQ-{ID})`
2. **Is default wrong for your case?** → stop, write your override reasoning, ask user before coding
3. **New OQ not in list?** → add to `tasks.yaml meta.default_oq_values` via `docs(m3)` commit; surface in Session Log

---

## 7. Artifact Hygiene

- **Design specs**: `docs/superpowers/specs/2026-04-21-m3-e{N}-*-design.md` — read-only during execution; amend only via contract change protocol (§4)
- **.artifacts/**: per dev-loop-skills convention; NFR-07 requires full set per task closure
  - `.artifacts/tasks/{Tx.x}/` — eval-doc + test-plan + test-diff + e2e-report
  - `.artifacts/milestones/m3-{N}-smoke.md` — milestone gate evidence
  - `.artifacts/registry.json` — cross-skill index (dev-loop writes, prd2impl reads)
- **e2e-evidence/**: runtime evidence (screenshots, traces, logs) for Playwright + pytest e2e

---

## 8. Known Coordination Risks

| Risk | Mitigation |
|---|---|
| Two subagents edit the same file → merge conflict | `tasks.yaml` `may_touch` field lists risky files; orchestrator checks overlap before parallel dispatch |
| Subagent skips task-status update | §6 of cc-prompt-templates.md enforces 5 closing requirements inline in dispatch prompt |
| M2 regression fails after M3 code | Per-task pytest run (excl e2e) in Closing checklist |
| OQ drift (different tasks apply different defaults) | Single source: `tasks.yaml meta.default_oq_values`; cite OQ-ID in commit |
| Playwright flakiness delays gate | CON-13 M3.5 deferral path pre-documented in [execution-plan.yaml](execution-plan.yaml) |

---

## 9. Links

- [tasks.yaml](tasks.yaml) · [tasks.md](tasks.md) · [execution-plan.yaml](execution-plan.yaml) · [execution-plan.md](execution-plan.md)
- [task-status.md](task-status.md) (authoritative progress)
- [cc-prompt-templates.md](cc-prompt-templates.md) (Opening/Running/Closing)
- [PRD](../../prd/AutoService-M3-PRD.md) · [gap-analysis](2026-04-21-gap-analysis.yaml) · [prd-structure](2026-04-21-prd-structure.yaml)
- Design specs: [E1](../../superpowers/specs/2026-04-21-m3-e1-identity-rbac-design.md) · [E3](../../superpowers/specs/2026-04-21-m3-e3-triage-enhancement-design.md) · [E4](../../superpowers/specs/2026-04-21-m3-e4-compliance-country-filter-design.md) · [E5](../../superpowers/specs/2026-04-21-m3-e5-dream-extension-design.md) · [E6](../../superpowers/specs/2026-04-21-m3-e6-ops-gc-playwright-design.md)
