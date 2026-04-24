# Batch M3-4 Kickoff · Playwright E2E (may defer to M3.5)

**Batches**: batch-11, batch-12 · **Milestone**: M3-4 · **Target**: 2026-05-02 EOD · **Duration**: ~15h
**Deferrable**: **YES** per CON-13 — does NOT block M3 gate

## Decision Point: Defer or Execute?

Before starting batch-11, decide:
- ✅ **Execute now** (default if timeline permits): run batch-11 + batch-12, M3 gate 2026-05-03
- ⏭️ **Defer to M3.5** (if timeline pressure): skip both, M3 gate 2026-05-01, file follow-up batch as M3.5 mini-sprint

If deferring: write a `chore(m3): defer M3-4 Playwright to M3.5` commit that:
1. Marks batch-11/12 status as 🚧 DEFERRED_M3.5 in task-status.md
2. Creates `docs/plans/m3/M3.5-playwright-kickoff.md` stub
3. Skips directly to batch-13 (gate)

---

## Pre-checks (if executing)

- [ ] batch-10 gate passed (M3-3 milestone complete)
- [ ] T4S.3 Apply button done (needed by T5S.5 Epic4 canary scenarios)
- [ ] `frontend/` dev servers run via `make start`
- [ ] M2 regression still green

---

## batch-11 · Playwright Scaffold (3h, solo)

| ID | Name | Owner | Deliverables |
|---|---|---|---|
| T5S.1 | scaffold + playwright.config.ts + CI + auth fixtures | Dev1 | `tests/e2e-playwright/playwright.config.ts`, `tests/e2e-playwright/fixtures/auth.ts`, `package.json` update |

**Decisions pre-set**:
- Framework: **Playwright + TypeScript** (matches frontend stack)
- Directory: `tests/e2e-playwright/` (separate from pytest `tests/e2e/`)
- Browsers: **chromium only** (cross-browser deferred M4+ per OQ-E6-2)
- CI: headless; evidence to `e2e-evidence/playwright/`
- Entry: `pnpm e2e` (add npm script)

**Gate**: `pnpm e2e --version` resolves; smoke spec runs against `make start` local stack

---

## batch-12 · 17-Story Suites (12h, 4 parallel lanes)

| ID | Name | Owner | Mode | Stories |
|---|---|---|---|---|
| T5S.2 | Epic1 Onboarding | Dev1 | solo | US-1.1, 1.2, 1.3, 1.4 |
| T5S.3 | Epic2 Realtime-chat (L) | subagent-1 | parallel | US-2.1, 2.2, 2.3, 2.4, 2.5, 2.6 |
| T5S.4 | Epic3 Dashboards | subagent-2 | parallel | US-3.1, 3.2, 3.3 |
| T5S.5 | Epic4 Dream-learning | Dev1 | solo_after_T5S.2 (needs T4S.3) | US-4.1, 4.2, 4.3, 4.4 |

**Story source**: [docs/plans/batches-M1-to-M5-kickoff.md §5 batch 14](../batches-M1-to-M5-kickoff.md) lines 271-296 + [UserStories v1.1](../../prd/AutoService-UserStories-v1.1.md)

**Per-suite structure** (all share common fixtures):
```
tests/e2e-playwright/
├── playwright.config.ts
├── fixtures/
│   ├── auth.ts          # operator/admin login fixtures
│   └── data-seed.ts     # tenant + KB seed
├── epic1-onboarding.spec.ts
├── epic2-realtime-chat.spec.ts
├── epic3-dashboards.spec.ts
└── epic4-dream-learning.spec.ts
```

**Flakiness mitigation**:
- Explicit `await expect(...).toBeVisible()` with default 5s timeout (no bare `click`)
- Network idle wait for WS-heavy flows (Epic2)
- Per-test fresh tenant (isolation via fixtures)

**Gate (M3-4 milestone)**:
- [ ] 17 specs green in chromium (OR: explicitly deferred to M3.5 via `chore(m3)` commit)
- [ ] Evidence in `e2e-evidence/playwright/` (screenshots + traces on failure)
- [ ] Suite runs in <10min total (acceptable for CI)

## Risks

- **R2**: Flakiness (common in Playwright). Mitigation: CON-13 defer path + explicit waits + fresh-tenant fixtures.
- **T5S.3 Epic2 is Large**: 6 stories × WS interactions. May overshoot into Day 10. If so → defer Epic2 to M3.5 while keeping Epic1/3/4 in M3.
- **T5S.5 Epic4 depends on T4S.3**: canary rollback scenario needs Apply button. Verify dep satisfied before starting.

## Next

→ `/prd2impl:skill-8-batch-dispatch batch-13` (M2 regression gate start)
