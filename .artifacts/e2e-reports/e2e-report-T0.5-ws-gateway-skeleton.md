---
type: e2e-report
id: e2e-report-002
status: executed
producer: skill-4
created_at: "2026-04-15"
updated_at: "2026-04-15"
related:
  - test-plan-002
  - eval-doc-002
---

# E2E Report: T0.5 WebSocket gateway skeleton

## Summary

| Suite | Collected | Passed | Failed | Skipped | Duration |
|---|---|---|---|---|---|
| tests/gateway/ (new) | 30 | **30** | 0 | 0 | 0.21s |
| tests/contract/ (regression gate, TC-027) | 220 | **160** | 0 | 60 | (no change) |
| tests/conversation_engine/ (T0.4 regression) | 42 | **42** | 0 | 0 | (no change) |
| **combined scope** | **292** | **232** | **0** | **60** | 0.60s |

All green in the T0.5 scope. Contract regression gate passed (160/60 identical to baseline).

## Commands

```bash
.venv/Scripts/python.exe -m pytest tests/gateway/ -v
.venv/Scripts/python.exe -m pytest tests/contract/ tests/conversation_engine/ tests/gateway/
```

Platform: win32, Python 3.14.3, pytest 9.0.3, FastAPI 0.135.3, Pydantic 2.13.0, starlette 1.0.0.

## Test-case coverage (TC-IDs → pytest nodes)

| TC-ID | Node(s) | Result |
|---|---|---|
| TC-001 ~ 004 | test_tc001_~_tc004 (app build) | PASSED 4/4 |
| TC-005-007 | test_tc005_006_007_handshake_viewer_role (3 parametrize) | PASSED 3/3 |
| TC-008-009 | test_tc008, test_tc009 | PASSED |
| TC-010-011 | test_tc010_011_envelope_missing_field (4 parametrize: id/ts/type/payload) | PASSED 4/4 |
| TC-012-016 | test_tc012 ~ test_tc016 | PASSED 5/5 |
| TC-017-022 | test_tc017 ~ test_tc022 | PASSED 6/6 |
| TC-023-025 | test_tc023, test_tc024, test_tc025 | PASSED 3/3 |
| TC-026 | test_tc026_cors_allows_frontend_ports (3 origins) | PASSED 3/3 |
| TC-027 | separate `pytest tests/contract/` invocation | PASSED (160/160) |

## Regression analysis

- **tests/contract/** baseline (pre-T0.5): 160 passed / 60 skipped — **identical post-T0.5** → contract gate green
- **tests/conversation_engine/** (T0.4): 42 passed — **identical post-T0.5** → no T0.4 regression
- **tests/test_init_discuss.py::test_reuses_existing_worktree_for_new_session**: **pre-existing failure**, not a T0.5 regression. Verified by stashing T0.5 changes and re-running — the test still fails on the baseline. Out of scope; should be tracked separately.

## Implementation correction during skill-4

One iteration was required:

- Initial run: 29/30. `test_tc010_011_envelope_missing_field[payload]` failed because `Envelope.payload` had `default_factory=dict`, so Pydantic silently filled missing `payload` with `{}` and the frame became a valid `ping` → returned `pong` instead of `error`.
- Fix: removed `default_factory`, making `payload` a required field (empty object must be explicit). All 30 passed after.

## Artifacts referenced

- test-plan-002 (.artifacts/test-plans/test-plan-T0.5-ws-gateway-skeleton.md)
- eval-doc-002 (.artifacts/eval-docs/eval-T0.5-ws-gateway-skeleton.md)

## Follow-ups

- Pre-existing failure in `tests/test_init_discuss.py` — file tracking issue separately.
- The Phase 1 T1A.1 work that implements Engine methods will naturally invalidate the `5000_INTERNAL` error mapping path in the gateway; the skeleton-era handling code should be deleted when `NotImplementedError` stops being raised.
- Batch 1 联调 (kickoff §5): DevB's customer-chat SPA (T0.6) connects to `ws://localhost:9999/ws/customer` and expects `client_hello → server_hello` to work. This skeleton supports that flow end-to-end against `LocalEngine` — business frames will receive `5000_INTERNAL error` with `engine_hint`, which DevB's UI should surface as "coming soon" in dev mode.
