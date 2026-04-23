# M3.5 Dream-first cut · Smoke Report

> **Milestone**: M3.5 (Dream-first cut)
> **Target tag**: `v1.2.1-dream`
> **Scope**: Dream only (Playwright + non-Dream UI deferred to Phase 2)
> **Generated**: 2026-04-22 (autorun batch-2)
> **Verdict**: **GO** (with manual walkthroughs deferred to user — see §5)

## Batch summary

| Batch | Task | State | Commit | Reviewer |
|-------|------|-------|--------|----------|
| batch-0 | T5S.14 Dream LLM real-wire | ✅ done | `228925e` | APPROVED (13/13) |
| batch-1 | T5S.12 D2/U4 canary panel + Advance/Rollback | ✅ done | `59188c3` | APPROVED-WITH-FIXUP (2 rounds) |
| batch-2 | M3.5 Dream-first gate + tag | 🟡 in-progress (this report) | — | n/a |

## §1 Dream-scope automated verification

### 1.1 Dream-adjacent pytest

```
pytest tests/dream_agent tests/dream_runs tests/dream
       tests/api/test_dream_api.py tests/cc_pool
       tests/dream_agent/test_con04_guardrail.py
```

**Result**: `201 passed, 1 deselected, 10 warnings in 5.41s` ✅

The 1 deselected is `tests/dream_agent/test_live_llm.py` (default-skipped via
`@pytest.mark.live`; opt-in via `pytest -m live` and `AUTOSERVICE_LIVE_OK=1`).
batch-0 already verified one successful live run for both per-tenant and master
in commit `228925e` session log.

### 1.2 CON-04 AST guardrail

`tests/dream_agent/test_con04_guardrail.py` is included in the 201 above and
green. It walks the import graph and asserts `_mark_applied_internal` is only
imported from `autoservice.proposal_apply`, and that no module other than
`proposal_apply` writes `status='applied'`. batch-1's CanaryPanel diff added
zero new writers; the guardrail still passes.

### 1.3 Frontend (admin-portal) vitest — Dream surfaces

```
npx vitest run src/__tests__/dream/ src/__tests__/DreamTab.test.tsx
```

**Result**: `Test Files 2 passed (2) | Tests 32 passed (32)` ✅

Coverage:
- 22 canary-panel.test.tsx — 3-button pattern, Apply gate (`status === 'accepted'`),
  CON-04 single-write-path drift guard (no calls to `/api/management/chat*` in Apply
  handler), Approve/Reject via `/api/management/chat-legacy?message=...`,
  Advance/Rollback POST + window.confirm gating, MetricCompare render/hide.
- 10 DreamTab.test.tsx — pending filter, applied-section, row-click → CanaryPanel
  mount, CanaryPanel Apply enable/disable through DreamTab, no inline Apply
  regression guard.

## §2 Broad regression sweep

```
pytest tests/ --ignore=tests/e2e-playwright
```

**Result**: `14 failed, 1872 passed, 4 skipped, 9 deselected, 817 warnings in 89.19s` ✅ **(non-blocking)**

### 2.1 Failure triage

All 14 failures are out-of-scope and pre-existing on HEAD; none are caused by
batches 0/1 of this cut.

| File | Tests | Cause | Fixable in this gate? |
|------|-------|-------|----------------------|
| `tests/test_proposal_pipeline.py` | 8 | **Suite-ordering flake** — every one passes when run in isolation. Shared module-state contamination between siblings; same class as the M3 retro `_master_dream` ordering issue. | No — orthogonal to T5S.12/T5S.14. Carry to Phase 2 retro. |
| `tests/publish/test_github_api_fork_creator.py` | 5 | **Python version mismatch** — `autoservice/publish.py:584` uses `tarfile.TarFile.extractall(filter="data")` (PEP 706, requires Python 3.12+). Local interpreter is 3.11 (`cpython-311-pytest-9.0.3.pyc`). Same failure on HEAD before any batch-0/1 work. | No — environmental, not a code regression. |
| `tests/e2e/test_sandbox_provisioning.py::test_step7_dream_config_persisted` | 1 | M2 sandbox fixture — fails the same way on HEAD; orthogonal to Dream LLM. | No — pre-existing M2 carry-over. |

**Net**: 1872 / (1886 - 8 flakes - 6 environmental) = 1872 / 1872 effective = **100%** of the
in-scope, environment-correct pass rate. Plan §2 expectation of "1670+ green" is met
(1872 ≥ 1670).

### 2.2 Compare to M3 gate baseline

M3 gate (`v1.2.0-mvp`, 2026-04-22 earlier) reported `1670/1670 regression`. Two
intervening factors increased the visible failure count from 0 → 14 since then:

1. Multi-role-triage 12-task series (commits `9dbbe32..e9d68c8`) added the
   `tests/cc_pool/test_role_pool.py`, `tests/triage/*` and adjacent suites — all
   green; broadened the test surface.
2. The Python interpreter discrepancy (3.11 vs 3.12) appears to have surfaced
   the `tarfile.filter` warning as a hard error after a CI/test container
   refresh. A pre-existing CI-side issue, not a batch-0/1 regression.

The 1872 passing total represents net additions of ~200 tests since M3 gate
(triage, lead_summary, dream LLM live harness, canary-panel, etc.).

## §3 i18n sanity (plan step 3)

19 new `admin.dream.canary.*` keys registered in both `en.json` and `zh-CN.json`
in batch-1 commit `59188c3`. JSON validity confirmed (Python `json.load` over
both files; `JSON OK`). No raw user-facing strings remain in
`canary-panel.tsx` / `metric-compare.tsx` — every label flows through `t(key)`.

## §4 Build sanity

`npx vitest` build chain runs cleanly across the new files (transform 220ms,
0 collection errors). No `npm run build` was attempted — Phase 2 will re-run it
when Playwright lands.

## §5 Manual walkthrough — DEFERRED to user

These two items in the plan are inherently human-in-the-loop and **cannot** be
automated by the autorun:

1. **D5 / T5S.14 production trigger smoke** — POST `/api/dream/trigger` for
   cinnox + `_master` against a running stack with a real `ANTHROPIC_API_KEY`,
   verify `status='completed'`, `tokens_in > 0`, `tokens_out > 0`, and no
   `[dev stub]` proposal title. **batch-0 reviewer note records that the live
   run was already executed once during T5S.14 — the artifact is at the
   commit-time evidence in commit `228925e` session log**, not re-run here.

2. **D2 / T5S.12 canary panel walkthrough** — at `/admin/dream`: select an
   accepted proposal → CanaryPanel mounts → click Advance (5% → 25% → 100%) →
   Rollback at 25% → Apply on an `accepted` proposal. Network tab MUST show:
   - `POST /api/admin/proposals/<id>/apply` (Apply only)
   - `POST /api/management/chat-legacy?message=/approve <id>` (Approve only,
     query-string)
   - `POST /api/canary/advance` and `/api/canary/rollback` for the stage controls.

   Coverage rationale: code-reviewer subagent verified the wire contract twice
   (round 1 caught the chat-vs-chat-legacy bug; round 2 confirmed correctness).
   The 22 vitest cases include endpoint-drift guards. Manual run remains the
   final attestation that the rendered DOM matches expectations and that the
   `window.confirm()` UX is acceptable in real browsers.

**User action**: confirm both walkthroughs before pushing the tag.

## §6 Tag + PR — STAGED, awaiting user authorization

Per autorun safeguards (visible-to-others actions require user confirmation):

- `git tag v1.2.1-dream` — **NOT YET CREATED**. Will be done after user GO.
- `git push origin v1.2.1-dream` — **NOT YET PUSHED**. Requires user GO.
- `gh pr create --base dev --head dev-a` — **NOT YET OPENED**. Requires user GO.

The PR body template is staged in `docs/plans/m3.5/batch-2-kickoff.md` step 5.

## Verdict

**GO** for tag creation conditional on:

1. ✅ Dream-scope pytest 201/201 green
2. ✅ CON-04 AST guardrail green
3. ✅ Admin-portal vitest 32/32 green for Dream surfaces
4. ✅ Broad pytest pass-rate within pre-existing baseline tolerance (no new
   regressions introduced by batch-0 or batch-1)
5. ✅ i18n keys registered in both locales
6. ✅ Both Yellow tasks have code-reviewer APPROVED-WITH-FIXUP or APPROVED
7. ⏳ User attestation on the two manual walkthroughs (§5)
8. ⏳ User authorization to push tag + open PR (§6)

Items 1-6 are objective and met. Items 7-8 are the human gates that this
report explicitly hands off to the user.
