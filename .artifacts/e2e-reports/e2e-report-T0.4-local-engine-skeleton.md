---
type: e2e-report
id: e2e-report-001
status: executed
producer: skill-4
created_at: "2026-04-15"
updated_at: "2026-04-15"
related:
  - test-diff-001
  - test-plan-001
  - eval-doc-001
---

# E2E Report: T0.4 LocalEngine skeleton

## Summary

| Suite | Collected | Passed | Failed | Skipped | Duration |
|---|---|---|---|---|---|
| tests/conversation_engine/ (new) | 42 | **42** | 0 | 0 | 0.36s |
| tests/contract/ (regression gate) | 220 | **160** | 0 | 60 | 0.79s |

All green. TC-026 (contract regression gate) passed with the pre-change baseline preserved (160 passed / 60 skipped, unchanged). No previously-skipped contract tests transitioned after LocalEngine was added — the 60 skips are not gated on LocalEngine.

## Commands

```bash
.venv/Scripts/python.exe -m pytest tests/conversation_engine/ -v --asyncio-mode=auto
.venv/Scripts/python.exe -m pytest tests/contract/
```

Platform: win32, Python 3.14.3, pytest 9.0.3, pytest-asyncio 1.3.0 (mode=auto).

## Test-case coverage (TC-IDs → pytest nodes)

| TC-ID | Node(s) | Result |
|---|---|---|
| TC-001 | test_tc001_import_local_engine | PASSED |
| TC-002 | test_tc002_instantiate_local_engine | PASSED |
| TC-003 | test_tc003_protocol_structural_check | PASSED |
| TC-004 ~ TC-021 | test_tc{004..021}_* (18 cases) | PASSED |
| TC-022 | test_tc022_every_async_method_hint_matches_regex[16 params] + test_tc022b_subscribe + test_tc022c_register_hook | PASSED (18/18) |
| TC-023 | test_tc023_no_autoservice_engine_dir | PASSED |
| TC-024 | test_tc024_no_enum_redefinition_in_local_engine | PASSED |
| TC-025 | test_tc025_init_exports_include_local_engine_without_regressing_t01 | PASSED |
| TC-026 | `pytest tests/contract/` separate invocation | PASSED (160/160) |

## Regression analysis

- **Contract suite baseline** (pre-T0.4, on origin/dev @ 2cbbf8c): 160 passed / 60 skipped
- **Post-T0.4**: 160 passed / 60 skipped — **identical**
- No previously-passing tests failed
- No previously-skipped tests transitioned (neither to passed nor failed)

Conclusion: adding `LocalEngine` + extending `__init__.py` did not perturb the frozen M0 contract surface.

## Artifacts referenced

- test-diff-001 (.artifacts/test-diffs/test-diff-T0.4-local-engine-skeleton.md)
- test-plan-001 (.artifacts/test-plans/test-plan-T0.4-local-engine-skeleton.md)
- eval-doc-001 (.artifacts/eval-docs/eval-T0.4-local-engine-skeleton.md)

## Follow-ups

- T0.5 (WS gateway skeleton) will consume `LocalEngine` via `ConversationEngine` Protocol typing.
- The 60 skipped contract tests warrant a separate audit during Phase 1: are they future-proofing for business logic, or stale skips? Out of scope for T0.4.
