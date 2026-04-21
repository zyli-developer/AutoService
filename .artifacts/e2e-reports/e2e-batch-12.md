# E2E report: batch-12

Total: 1202 pass / 10 fail (all pre-existing, not caused by batch-12)

## New tests (from this batch)

- **green (17)**:
  - `tests/fork_runtime/test_tenant_root.py` — 10 tests (T7B.2)
  - `tests/fork_runtime/test_tenant_context.py` — 7 tests (T7B.1)
- **red**: none

## Regression (pre-existing tests)

Scope: `tests/` excluding `tests/e2e/` and `tests/integration_cc_pool.py` (requires live CCPool).

- **green**: 1185
- **red (10)** — all pre-existing, verified by re-running on `HEAD~3` (before batch-12 code):
  - `tests/contract/test_protocol_signatures.py::test_no_extra_protocol_methods` — missing signature entry for `list_conversations_in_takeover_by` (unrelated: message-router contract drift)
  - `tests/contract/test_ws_schema_alignment.py::test_every_protocol_method_is_referenced` — same root cause
  - `tests/test_proposal_pipeline.py` — 8 tests fail in full-suite order; **pass 15/15 when run in isolation** (test-order pollution from earlier suites leaking DB/env state; pre-existing before batch-12)

## Targeted regression evidence

```bash
$ python -m pytest tests/fork_runtime/ tests/bootstrap/ tests/api/ tests/auth/ -q
102 passed, 110 warnings in 6.96s
```

```bash
$ python -m pytest tests/fork_runtime/ -v
10 tests from test_tenant_root.py PASSED
 7 tests from test_tenant_context.py PASSED
17 passed in 1.42s
```

## Pre-existing-failure validation

```bash
# Baseline (without batch-12 changes, git stash):
$ python -m pytest tests/ --ignore=tests/e2e --ignore=tests/integration_cc_pool.py --ignore=tests/fork_runtime -q
10 failed, 1184 passed, 4 skipped
# → Same 10 failures, confirming batch-12 adds zero regressions.
```

## Artifacts

- Eval: `eval-doc-015` (`.artifacts/eval-docs/eval-batch-12-p7-middleware.md`)
- Test diff: `test-diff-016` (`.artifacts/test-diffs/test-diff-batch-12.md`)
- Code: `autoservice/bootstrap.py` (+ `tenant_root()` helper + module constants), `autoservice/web_gateway.py` (+ `tenant_context_middleware`)

## Notes

- Middleware is registered with the `@app.middleware("http")` decorator AFTER the `CORSMiddleware.add_middleware` call, so Starlette chains it **inside** CORS (reverse registration order). 403 responses from cross-tenant attempts still receive CORS headers — verified by TestClient responses in tenant-mode tests.
- `bootstrap.PROJECT_ROOT` module attribute added to enable monkeypatching in the test fixtures (mirrors `master_tenant.PROJECT_ROOT` pattern — CON-07).
- `DREAM_SCHEDULER_DISABLED=1` + `POOL_MODE=0` env gates in `test_tenant_context.py` fixture avoid filesystem side-effects when the FastAPI lifespan hooks fire in TestClient.
