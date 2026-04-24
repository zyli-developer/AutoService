# E2E report: batch-15 (P8 ForkCreator · T8B.1 + T8B.2)

## Scope

Backend regression + new tests for T8B.1 (GitHubApiForkCreator, yellow L) + T8B.2 (LocalTarballForkCreator runbook config step, green).

## Total

- **172 pass / 0 fail** across `tests/publish/ tests/bootstrap/ tests/fork_runtime/ tests/setup/ tests/api/ tests/auth/`
- Duration: 23.66s
- 160 pre-existing FastAPI `on_event` deprecation warnings (unrelated; M3 cleanup)

## New tests (batch-15)

- T8B.1: 11 cases (available probes × 3; create_fork success + org path + partial failure fork_name + timeout + gh-missing + stderr-logged + empty-tenant-reject; **regression guard: NEVER calls `gh repo delete`**)
- T8B.2: 8 cases (helper shape + validation + runbook step inclusion + ordering + HTTPS warning + snippet match + overwrite warning)
- **Total: 19 new tests, all green**

## New vs regression classification

| Scope | New pass | Regression pass | New fail | Regression fail |
|-------|---------|-----------------|----------|-----------------|
| tests/publish/ (batch-15 + M1 baseline) | 19 | ~40 | 0 | 0 |
| tests/bootstrap/ | 0 | 20 | 0 | 0 |
| tests/fork_runtime/ | 0 | 17 | 0 | 0 |
| tests/setup/ | 0 | 8 | 0 | 0 |
| tests/api/ | 0 | 40+ | 0 | 0 |
| tests/auth/ | 0 | 36 | 0 | 0 |

## Preexisting failures (unchanged baseline)

Out of scope for batch-15 — same as batch-13/14 baselines:
- `tests/contract/test_protocol_signatures.py`
- `tests/contract/test_ws_schema_alignment.py`
- `tests/test_proposal_pipeline.py` (event-loop test-order pollution)

Not caused by batch-15. M3 cleanup candidate.

## Yellow review (T8B.1) — APPROVED

Reviewer: `superpowers:code-reviewer` subagent (inline review, no subagent dispatch needed from the spawning subagent since rate-limit interrupted it — main orchestrator dispatched the reviewer post-hoc).

**All 4 red-line concerns PASS**:
1. NEVER auto-deletes forks — zero `gh repo delete` call sites; grep-level regression test `test_create_fork_NEVER_calls_gh_repo_delete`
2. Fork name populated on ALL post-create-success failures — walked all 3 except branches (FileNotFoundError / TimeoutExpired / CalledProcessError); invariant holds
3. Subprocess timeouts sane: _AUTH_CHECK_TIMEOUT_SEC=30, _FORK_CREATE_TIMEOUT_SEC=60 — pinned by tests
4. No silent stderr swallowing: CalledProcessError branch WARNING-logs stderr + embeds in `ForkCreationError.stderr` + message; TimeoutExpired also logged

**Non-blocking suggestions** (will not address in batch-15; M3 backlog):
- Fallback URL synthesis uses `"<user>"` literal when `org is None` — call `gh api user -q .login` for the real username
- `available()` silently swallows TimeoutExpired — DEBUG-log the cause
- Runbook `cat > ... <<'EOF'` overwrites unconditionally — consider `[ -f ... ] || cat > ...` for safety-by-default

## Race/rate-limit observation

Subagent aa8af5a28 hit daily rate limit after 31 tool uses (~440s). It had completed:
- Full T8B.1 + T8B.2 implementation in `autoservice/publish.py`
- All 19 tests written and green
- `eval-doc-020` registered (commit `326e905`)

Stalled before code commit, test-diff production, e2e-report, or task-status update. Main orchestrator took over:
- Ran reviewer subagent (inline code-reviewer) — APPROVED
- Produced this e2e-report
- Will register test-diff-XXX + e2e-report-XXX + link
- Commit code + task-status + artifacts

## 关联 artifact

- eval-doc-020 (batch-15 ForkCreator — reviewer APPROVED)

## Verdict

**batch-15 ✅ GO** — 19 new tests green, 0 regression, yellow-reviewer APPROVED. Phase 8 progress: 2/3 tasks done. Remaining: batch-16 T8S.3 E2E acceptance (yellow L, manual run with real Anthropic key + gh CLI + uvicorn — not CI).
