---
type: test-diff
id: test-diff-003
status: draft
producer: skill-3
created_at: "2026-04-16"
updated_at: "2026-04-16"
related:
  - test-plan-003
  - eval-doc-004
evidence: []
---

# Test Diff: T1A.3 EventBus

## Source
- Test plan: test-plan-003 (.artifacts/test-plans/plan-T1A.3-eventbus.md)

## Changes

### New test cases

| File | Function | TC | Domain | Validates |
|------|----------|-----|--------|-----------|
| test_event_bus.py | test_tc001_eventbus_import_and_instantiate | TC-001 | event_bus | Import + instantiate |
| test_event_bus.py | test_tc019_sqlite_schema_auto_created | TC-019 | event_bus | SQLite schema creation |
| test_event_bus.py | test_tc012_sqlite_persistence_across_instances | TC-012 | event_bus | Persistence across restarts |
| test_event_bus.py | test_tc017_multi_subscriber_fanout | TC-017 | event_bus | 3-way fan-out |
| test_event_bus.py | test_tc018_subscriber_cancel_cleanup | TC-018 | event_bus | Cancel cleans up |
| test_event_bus.py | test_tc020_high_frequency_emit_not_blocking | TC-020 | event_bus | 50 emits < 2s |
| test_local_engine.py | test_tc_subscribe_conv_scope | TC-002 | subscribe | Conv scope filter |
| test_local_engine.py | test_tc_subscribe_event_types_filter | TC-003 | subscribe | Event type filter |
| test_local_engine.py | test_tc_subscribe_squad_scope | TC-004 | subscribe | Squad scope filter |
| test_local_engine.py | test_tc_subscribe_global_scope | TC-005 | subscribe | Global scope |
| test_local_engine.py | test_tc_subscribe_since_sequence_conv | TC-006 | subscribe | Replay + live |
| test_local_engine.py | test_tc_subscribe_viewer_role_filters_side | TC-008 | subscribe | CUSTOMER hides SIDE |
| test_local_engine.py | test_tc_query_events_limit | TC-009 | query | Limit |
| test_local_engine.py | test_tc_query_events_type_filter | TC-010 | query | Type filter |
| test_local_engine.py | test_tc_query_events_since_and_until | TC-011 | query | Combo filter |
| test_local_engine.py | test_tc_hook_on_event | TC-013 | hooks | on_event dispatch |
| test_local_engine.py | test_tc_hook_on_conversation_created | TC-014 | hooks | on_conv_created |
| test_local_engine.py | test_tc_hook_on_mode_changed | TC-015 | hooks | on_mode_changed |
| test_local_engine.py | test_tc_hook_exception_isolation | TC-016 | hooks | Q8c isolation |
| test_local_engine.py | test_tc_hook_on_conversation_closed | TC-021 | hooks | on_conv_closed |
| test_local_engine.py | test_tc_hook_on_participant_joined | TC-022 | hooks | on_participant_joined |
| test_local_engine.py | test_tc_hook_multi_hook_isolation | TC-023 | hooks | Multi-hook isolation |

### New helper classes

| File | Name | Purpose |
|------|------|---------|
| test_local_engine.py | _RecordingHook | Records all hook calls for assertions |
| test_local_engine.py | _FailingHook | Always raises to test Q8c isolation |

### Modified files
- `tests/conversation_engine/test_event_bus.py`: new file, 6 test cases
- `tests/conversation_engine/test_local_engine.py`: appended 16 test cases + 2 helper classes

## Validation
- Syntax: all files pass `ast.parse()`
- Imports: all resolve (EventBus import will resolve after implementation)
- Naming: follows existing `test_tc_` convention
- No ordering conflicts (no `pytest.mark.order` used — tests are independent)

## Notes
- TC-007 (ULID since_sequence for squad scope) deferred — will be tested after ULID generation is confirmed
- TC-024 (regression) is implicit — running existing suite validates no regression
