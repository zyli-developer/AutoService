# E2E report: batch-14 (P7 smoke + mgmt-chat · T7S.5 + T7B.6 parallel)

## Scope

Backend regression + new tests for T7S.5 (fork-mode boot smoke) + T7B.6 (/api/management/chat → _master).

## Total

- **187 pass / 0 fail** across `tests/api/ tests/auth/ tests/cc_pool/ tests/dream_agent/ tests/bootstrap/ tests/fork_runtime/ tests/setup/`
- Duration: 11.30s
- 160 pre-existing FastAPI `on_event` deprecation warnings (unrelated; M3 cleanup candidate)

## New tests (batch-14)

- T7S.5: 5 boot smoke cases (plugins/_local_admin provisioned, root route non-500, URL-flat rewrite, cross-tenant denies, lifespan shutdown clean)
- T7B.6: 7 management-chat cases (valid reply, empty/missing 422, routes to _master, pool unavailable 503, no-stub regression guard, legacy signature compat)
- **Total: 12 new tests, all green**

## New vs regression classification

| Scope | New pass | Regression pass | New fail | Regression fail |
|-------|---------|-----------------|----------|-----------------|
| tests/fork_runtime/test_boot_smoke.py | 5 | 0 | 0 | 0 |
| tests/api/test_management_chat.py | 7 | 0 | 0 | 0 |
| tests/fork_runtime/ (batch-12) | 0 | 12 | 0 | 0 |
| tests/bootstrap/ | 0 | 20 | 0 | 0 |
| tests/api/ (batch-5, 7, 8, 11) | 0 | 70 | 0 | 0 |
| tests/auth/ (batch-7, 8) | 0 | 36 | 0 | 0 |
| tests/cc_pool/ (batch-5) | 0 | 12 | 0 | 0 |
| tests/dream_agent/ (batch-3, 4) | 0 | 25 | 0 | 0 |

## Preexisting failures (unchanged baseline)

Out of scope for batch-14; confirmed unchanged by prior e2e-reports:
- 10 backend failures in `tests/contract/` + `tests/test_proposal_pipeline.py` (unrelated; test-order pollution + contract drift; M3 cleanup)
- Frontend suites not in scope for batch-14 (backend-only batch)

## Batch-14 commit trail (race-aware)

- `dec0934` — register eval-doc-018 (T7S.5)
- `cefa9a5` — register eval-doc-019 (T7B.6)
- `3d643a1` — register test-diff-019 (T7S.5)
- `0572822` — link eval-doc-018 ↔ test-diff-019
- `df6b3a8` — **feat(m2): T7S.5 fork-mode boot smoke test** (by subagent af480a78, clean single-file commit)
- `7a114b0` — register test-diff-021 (T7B.6) — written by subagent aa885bef before it stalled
- Main orchestrator takeover: link + e2e-report + T7B.6 code commit + batch close

## Race/timeout observation

T7B.6 subagent (aa885bef89b3169af) wrote `autoservice/api_routes.py` + `tests/api/test_management_chat.py` + registered eval-doc-019 + registered test-diff-021, then stalled before committing code or updating task-status. Main orchestrator verified 7/7 tests green and took over the remaining closing steps. Good hygiene: no code was lost; all produced artifacts landed correctly due to per-type ID partitioning in the registry.

## 关联 artifact

- eval-doc-018 (T7S.5) ↔ test-diff-019 (T7S.5)
- eval-doc-019 (T7B.6) ↔ test-diff-021 (T7B.6)

## Verdict

**batch-14 ✅ GO** — 12 new tests green, 0 new regression, artifacts complete. Phase 7 now complete (6/6 tasks: T7B.1, T7B.2, T7F.3, T7S.4, T7S.5, T7B.6). Remaining: batch-15 (T8B.1 ForkCreator yellow L + T8B.2 runbook config) + batch-16 (T8S.3 E2E acceptance yellow L).
