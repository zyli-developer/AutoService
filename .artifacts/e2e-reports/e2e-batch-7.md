# E2E report: batch-7 (P5 auth core, T5B.1 / T5B.2 / T5B.3 / T5B.4)

Total: **188 pass / 0 fail** across the batch-scope regression suite.
Related artifacts: `eval-doc-009` (pre-implementation eval), `test-diff-011` (coverage summary). Commit: `442c02b`.

Command:
```
python -m pytest tests/auth/ tests/bootstrap/ tests/cc_pool/ tests/dream_agent/ \
                 tests/dream_runs/ tests/dream_scheduler/ tests/api/ tests/soul_generator/
```

## New tests (from this batch)

- green: 20
  - `tests/auth/test_repository.py` — 7 tests (T5B.1 schema + repo round-trips).
  - `tests/auth/test_request_login.py` — 5 tests (T5B.2 anti-enumeration, dev-log mode, validation).
  - `tests/auth/test_verify.py` — 5 tests (T5B.3 cookie + 302 + replay defence + un-burned expiry).
  - `tests/auth/test_logout.py` — 3 tests (T5B.4 idempotency + revoke + cookie clear).
- red: 0

## Regression (preexisting tests)

- green: **168**
  - `tests/bootstrap/` (config + lifespan + master/local-admin bootstrap)
  - `tests/cc_pool/` (role-dispatch + dream pool isolation)
  - `tests/dream_agent/` (run_dream + tool loop)
  - `tests/dream_runs/` (schema + repo)
  - `tests/dream_scheduler/` (should_trigger + scheduler loop + refresh)
  - `tests/api/` (dream trigger / runs endpoints)
  - `tests/soul_generator/` (5-role souls including dream)
- red: 0

## Out-of-scope pre-existing failures (NOT caused by batch-7)

When the *full* `tests/` tree runs (not the batch-scope subset above), `tests/test_proposal_pipeline.py` (10 cases) + `tests/contract/test_protocol_signatures.py::test_no_extra_protocol_methods` + `tests/contract/test_ws_schema_alignment.py::test_every_protocol_method_is_referenced` fail. Verified via `git stash` that these fail without batch-7 changes present. Root cause is test-isolation pollution inherited from earlier phases (proposal pipeline cases pass when run in isolation). Not a batch-7 regression; tracked separately.

## Evidence

| Artifact | Location |
|----------|----------|
| Code | `autoservice/auth.py` (new, 279 lines), `autoservice/api_routes.py` (+312 lines: `/api/auth/request-login`, `/verify`, `/logout`, helpers) |
| Tests | `tests/auth/test_repository.py`, `test_request_login.py`, `test_verify.py`, `test_logout.py` (20 tests) |
| Commit | `442c02b` |
| Task status rows | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 5 table, batch-7 row, session log |
| Eval-doc | `.artifacts/eval-docs/eval-batch-7-auth.md` (eval-doc-009) |
| Test-diff | `.artifacts/test-diffs/test-diff-batch-7.md` (test-diff-011) |
