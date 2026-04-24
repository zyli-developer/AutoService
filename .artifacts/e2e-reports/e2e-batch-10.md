# E2E report: batch-10 (P6 shell components T6F.3 + T6F.4)

**Scope**: `frontend/apps/admin-portal` vitest suite (full regression).

## Total

- **112 pass / 24 fail (136 tests across 26 files)** — same baseline as batch-9.
- **Batch-10 scope (3 files, 27 tests)**: 27/27 pass.

## New tests (batch-10)

- AdminRail variant prop: ~10 tests (master default + tenant icon set + legacy wizard removal + active-highlight preservation)
- AdminTopbar new props: 4 tests (brandName replace/empty, authenticatedAs render/empty)
- AvatarMenu logout integration: 3 tests (fetch POST /api/auth/logout, redirect to /login, network-error best-effort)

All green. Zero regression introduced by batch-10.

## Regression (preexisting tests)

All 112 that passed in batch-9 still pass. No new failures from batch-10 code.

## Preexisting failures (unchanged baseline)

24 failures across 9 unrelated files — i18n translation-key assertion mismatch (tests assert raw keys like `admin.wizard.rehearsal.ai_reply`, app renders English strings):
- AdminWorkspace.test.tsx
- VirtualRehearsalStep.test.tsx
- ComplianceCheckStep.test.tsx
- integration.test.tsx (2 files)
- ProposalsTab.test.tsx
- ChannelConfigStep.test.tsx
- DashboardTab.test.tsx
- DashboardTab.period.test.tsx
- CanaryProgress.test.tsx

These **are NOT caused by batch-10**; verified by prior batch-9 e2e-report (e2e-report-006) which recorded the same 24/9 baseline. Recommended cleanup task for M3: migrate assertions to match current translation output OR set up vitest i18n mocking.

## Subagent timeout note

Both T6F.3 and T6F.4 subagents (a68ca35d, a56018390) timed out mid-task (stream watchdog after 600-1000s). Forensic reconstruction: both agents completed the code impl + registered their eval-docs (eval-doc-012, eval-doc-013), but stalled before writing test-diff / running e2e-report / committing. Main orchestrator took over, manually added missing tests (AdminTopbar brandName/authenticatedAs; AvatarMenu logout fetch), produced this combined e2e-report, and commits the batch. Artifact lineage preserved: eval-doc-012/013 → test-diff-014 → e2e-report-XXX.

## 关联 artifact

- eval-doc-012 (T6F.3)
- eval-doc-013 (T6F.4)
- test-diff-014 (batch-10 combined)
