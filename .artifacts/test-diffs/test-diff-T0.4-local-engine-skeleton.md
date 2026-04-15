---
type: test-diff
id: test-diff-001
status: draft
producer: skill-3
created_at: "2026-04-15"
updated_at: "2026-04-15"
related:
  - test-plan-001
  - eval-doc-001
evidence: []
---

# Test Diff: T0.4 LocalEngine skeleton

## Source
- Test plan: test-plan-001 (.artifacts/test-plans/test-plan-T0.4-local-engine-skeleton.md)
- Eval doc: eval-doc-001

## Changes

### New test cases (tests/conversation_engine/test_local_engine.py)

| Function | TC-ID | Domain | Validates |
|---|---|---|---|
| test_tc001_import_local_engine | TC-001 | imports | LocalEngine re-exported from package __init__ |
| test_tc002_instantiate_local_engine | TC-002 | ctor | LocalEngine() returns an instance |
| test_tc003_protocol_structural_check | TC-003 | Protocol | 18 Protocol methods present and callable |
| test_tc004_create_conversation_raises | TC-004 | lifecycle | raises NotImplementedError + T1A.1 (lifecycle) |
| test_tc005_get_conversation_raises | TC-005 | lifecycle | raises NotImplementedError + T1A.1 |
| test_tc006_list_active_conversations_raises | TC-006 | lifecycle | raises on 3 filter combos + T1A.1 |
| test_tc007_close_conversation_raises | TC-007 | lifecycle | raises + T1A.1 (lifecycle) |
| test_tc008_set_csat_raises | TC-008 | lifecycle | raises + T1A.1 |
| test_tc009_join_raises | TC-009 | participant | raises + T1A.1 (participant) |
| test_tc010_leave_raises | TC-010 | participant | raises + T1A.1 (participant) |
| test_tc011_switch_mode_raises | TC-011 | mode | raises + T1A.1 (mode) |
| test_tc012_send_message_raises | TC-012 | messages | raises + T1A.1 (messages) |
| test_tc013_edit_message_raises | TC-013 | messages | raises + T1A.1 |
| test_tc014_delete_message_raises | TC-014 | messages | raises + T1A.1 |
| test_tc015_get_messages_raises | TC-015 | messages | raises on 3 paging modes + T1A.1 |
| test_tc016_handle_command_raises | TC-016 | command | raises + T2A.1 |
| test_tc017_set_timer_raises | TC-017 | timer | raises + T1A.2 |
| test_tc018_cancel_timer_raises | TC-018 | timer | raises + T1A.2 |
| test_tc019_subscribe_raises | TC-019 | event-bus | async-gen iteration raises + T1A.3 |
| test_tc020_query_events_raises | TC-020 | event-bus | raises + T1A.3 |
| test_tc021_register_hook_raises | TC-021 | hooks | sync raises + T1A.3 (hooks) |
| test_tc022_every_async_method_hint_matches_regex | TC-022 | regex | 16 async methods parametrized regex check |
| test_tc022b_subscribe_hint_matches_regex | TC-022 | regex | subscribe separate (iteration semantics) |
| test_tc022c_register_hook_hint_matches_regex | TC-022 | regex | register_hook separate (sync) |
| test_tc023_no_autoservice_engine_dir | TC-023 | path | autoservice/engine/ forbidden, not present |
| test_tc024_no_enum_redefinition_in_local_engine | TC-024 | path | local_engine.py text does not redefine enums |
| test_tc025_init_exports_include_local_engine_without_regressing_t01 | TC-025 | exports | __all__ includes LocalEngine; T0.1 exports preserved |

Total: 27 test functions realizing 25 TC-IDs (TC-022 split into 3 to handle async / async-gen / sync method shapes). TC-026 intentionally deferred to skill-4.

### New fixtures (tests/conversation_engine/conftest.py)

| Name | Scope | Provides |
|---|---|---|
| engine | function | fresh LocalEngine() per test |
| participant_customer | function | Participant(role=CUSTOMER) with UTC-aware joined_at |

### New / modified source files

- **added** `autoservice/conversation_engine/local_engine.py` (18 Protocol methods, all raising `NotImplementedError("T1A.x/T2A.1: <hint>")`)
- **modified** `autoservice/conversation_engine/__init__.py` — appended `from .local_engine import LocalEngine` + added `"LocalEngine"` to `__all__`
- **added** `tests/conversation_engine/__init__.py` (empty)
- **added** `tests/conversation_engine/conftest.py`
- **added** `tests/conversation_engine/test_local_engine.py`

### Not modified (M0 contract freeze)

- `autoservice/conversation_engine/protocol.py`
- `autoservice/conversation_engine/types.py`
- `autoservice/conversation_engine/events.py`
- `autoservice/conversation_engine/errors.py`

No new `autoservice/engine/` directory was created.

## Skeleton implementation notes

- `subscribe` is an async generator: body is `raise NotImplementedError("T1A.3: event bus")` followed by an unreachable `yield` so Python recognizes it as `AsyncIterator[Event]` at the typing level. Raise fires on iteration, not on call.
- `register_hook` is declared in the Protocol as `def` (sync); implementation raises synchronously.
- `LocalEngine.__init__(config=None)` accepts an optional config mapping (stored but unused in skeleton) so Phase 1 can extend without breaking callers.

## Validation

- Syntax: all 4 Python files pass `ast.parse()` (verified)
- Import smoke: `from autoservice.conversation_engine import LocalEngine, ConversationEngine; LocalEngine()` succeeds (verified)
- Fixture graph: engine / participant_customer are function-scoped, no circular deps
- Naming: `test_tc{NNN}_{action}` — maps 1:1 to TC-IDs for traceability
- No `pytest.mark.order` used (these are independent unit-level tests, not phased E2E)

## Known follow-ups

- Ensure `pytest-asyncio` is present in the dev env before skill-4 runs
- TC-026 (tests/contract/ regression gate) is expected to execute in skill-4 as a separate pytest invocation
- 60 currently-skipped contract tests may transition state (skipped → passed/failed) once LocalEngine exists; skill-4 report should surface this
