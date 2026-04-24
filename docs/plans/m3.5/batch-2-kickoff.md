# batch-2 · M3.5 Dream-first gate + tag — Kickoff

> **Goal**: validate Dream scope end-to-end, regression, tag `v1.2.1-dream`, open PR dev-a → dev.
> **Duration**: Day 3 (2026-04-24) · 1-2h human / ~30min AI.
> **Scope**: Dream only. Playwright gate explicitly deferred to Phase 2 mini-sprint.

## Pre-checks

- [ ] batch-0 gate passed — T5S.14 D5 Dream LLM real-wire merged, code-reviewer APPROVED
- [ ] batch-1 gate passed — T5S.12 D2 canary panel merged, code-reviewer APPROVED, minimal Apply button removed from DreamTab
- [ ] `task-status.md` reflects both batches as `done`
- [ ] Branch `dev-a` clean; commits cover code + status + any follow-ups

## Step-by-step

### 1. Smoke test (Dream scope)

```bash
# Invoke the milestone smoke skill explicitly scoped to Dream
/prd2impl:skill-10-smoke-test M3.5 --scope dream
```

Expected artifact: `.artifacts/milestones/m3.5/smoke-report.md` with:
- D5 production trigger smoke (cinnox + master) → both LLM-backed
- D2 canary panel manual walkthrough evidence
- AST guardrail `test_ast_emit_proposal.py` green
- VCR unit + live opt-in both green
- Explicit "Playwright deferred to Phase 2" note

Verdict: **GO** before proceeding.

### 2. Regression sweep

```bash
# Full Dream-adjacent regression (no Playwright)
pytest tests/dream_agent tests/dream_runs tests/dream tests/api/test_dream_api.py \
       tests/cc_pool tests/guardrails/test_ast_emit_proposal.py

# M2 + M3 baseline (Dream already included above)
pytest tests/ --ignore=tests/e2e-playwright
```

Expected: `1670+` tests green (existing M2+M3 baseline + new Dream suites).

### 3. i18n sanity

The Dream-first cut does not add user-facing copy outside the canary panel. Spot-check `frontend/packages/admin-portal/src/components/dream/canary-panel.tsx` for raw strings and move to `frontend/packages/i18n/` if any were added. No blocker.

### 4. Tag + push

```bash
git checkout dev-a
git pull --ff-only
git tag v1.2.1-dream
git push origin v1.2.1-dream
```

### 5. Open PR dev-a → dev

```bash
gh pr create --base dev --head dev-a \
  --title "M3.5 Dream-first cut (v1.2.1-dream): D5 LLM real-wire + D2 canary panel" \
  --body "$(cat <<'EOF'
## Summary

- **D5 / T5S.14** — Dream engine now speaks to a real LLM in production for both per-tenant (cinnox) and master triggers. `DREAM_DEV_STUB` retained as offline-dev fallback only. `cc_pool.client.call_with_tools` added as a scoped tool-use surface for Dream role clients.
- **D2 / T5S.12** — Canary panel consolidates Apply button into a single 3-button flow (`[Reject] [Approve] [🔒 Apply]`) with 5% → 25% → 100% progress bar + rollback + metric compare. The minimal Apply button at `DreamTab.tsx` is removed.

## Deferred (Phase 2 mini-sprint)

Per user pivot 2026-04-22, the following stay in `docs/plans/m3.5/` but are NOT in this cut:

- T5S.1-T5S.5 (Playwright scaffold + Epic1-4 suites)
- T5S.6-T5S.8, T5S.10, T5S.11 (non-Dream UI — U1/U2/U3/U5/U6)
- T5S.13 D3 im-block renderer (blocked by external T3S.7-hotfix)

## Test plan

- [x] `pytest tests/dream_agent tests/dream_runs tests/dream tests/api/test_dream_api.py tests/cc_pool` green
- [x] `pytest -m live tests/dream_agent/test_live_llm.py` — one successful live run per agent
- [x] `pytest tests/guardrails/test_ast_emit_proposal.py` — CON-04 AST guardrail green
- [x] M2 + M3 baseline regression green (`pytest tests/ --ignore=tests/e2e-playwright`)
- [x] Manual walkthrough: cinnox trigger → real proposal; master trigger → LLM-backed; canary panel advance/rollback/apply cycle
- [x] code-reviewer APPROVED for both yellow tasks (T5S.14, T5S.12)

## Smoke report

See `.artifacts/milestones/m3.5/smoke-report.md`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

## Gate

- [ ] `.artifacts/milestones/m3.5/smoke-report.md` → GO
- [ ] Regression green (M2 + M3 base + Dream suites)
- [ ] Tag `v1.2.1-dream` pushed
- [ ] PR dev-a → dev opened; body enumerates deferred tasks
- [ ] `task-status.md` updated with final session-log entry

## Closing

1. Update [task-status.md](task-status.md): `GATE-M3.5-dream` → `done`; milestone row → `shipped`; session log records tag + PR URL.
2. Commit: `chore(m3.5): Dream-first cut shipped (v1.2.1-dream); Playwright + non-Dream UI deferred to Phase 2` — commit separate from the PR body if needed.
3. User decides whether to kick off Phase 2 immediately (run `/prd2impl:skill-4-plan-schedule --plans-dir docs/plans/m3.5 --scope playwright-ui`) or let it rest.
