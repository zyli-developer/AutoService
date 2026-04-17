---
type: test-diff
id: test-diff-phase6-pb
status: draft
producer: skill-3
created_at: "2026-04-17T17:30:00+08:00"
updated_at: "2026-04-17T17:30:00+08:00"
related:
  - plan-T6A.1
  - plan-T6A.2
  - plan-T6C.1
  - plan-T6C.2
  - plan-T6C.3
evidence: []
---

# Test Diff: Phase 6 Protocol + Billing (T6A.1/A.2/C.1/C.2/C.3)

## Source
- Test plans: plan-T6A.1, plan-T6A.2, plan-T6C.1, plan-T6C.2, plan-T6C.3

## Changes

### New test cases

| File | Function | TC-ID | Domain | Validates |
|------|----------|-------|--------|-----------|
| tests/gateway/test_subscription_registry.py | test_tc001_subscribe_conversation_scope | TC-001 | subscription | add entry with conv scope |
| tests/gateway/test_subscription_registry.py | test_tc002_subscribe_squad_scope | TC-002 | subscription | squad scope indexing |
| tests/gateway/test_subscription_registry.py | test_tc003_subscribe_global_scope | TC-003 | subscription | global scope indexing |
| tests/gateway/test_subscription_registry.py | test_tc004_global_scope_non_admin_rejected | TC-004 | subscription | ACL enforcement via dispatch |
| tests/gateway/test_subscription_registry.py | test_tc005_invalid_scope_rejected | TC-005 | subscription | scope validation |
| tests/gateway/test_subscription_registry.py | test_tc006_unsubscribe_removes | TC-006 | subscription | remove + count decrement |
| tests/gateway/test_subscription_registry.py | test_tc007_session_evict | TC-007 | subscription | session disconnect cleanup |
| tests/gateway/test_subscription_registry.py | test_tc008_fanout_delivers_to_subscriber | TC-008 | subscription | scope-based lookup isolation |
| tests/gateway/test_squad_broadcast.py | test_tc009_message_reaches_correct_squad | TC-009 | squad | channel_routing assignment |
| tests/gateway/test_squad_broadcast.py | test_tc010_multi_squad_isolation | TC-010 | squad | multi-squad isolation |
| tests/gateway/test_squad_broadcast.py | test_tc011_fallback_default_squad | TC-011 | squad | default squad fallback |
| tests/gateway/test_squad_broadcast.py | test_tc012_explicit_squad_metadata | TC-012 | squad | metadata priority |
| tests/gateway/test_squad_broadcast.py | test_tc013_reassignment | TC-013 | squad | reassign to new squad |
| tests/gateway/test_csat_rating.py | test_tc014_resolve_triggers_csat_request | TC-014 | CSAT | _push_csat_request sends frame |
| tests/gateway/test_csat_rating.py | test_tc015_csat_response_records_score | TC-015 | CSAT | event → BillingMetrics |
| tests/gateway/test_csat_rating.py | test_tc016_csat_score_validation | TC-016 | CSAT | 1-5 range enforcement |
| tests/gateway/test_csat_rating.py | test_tc017_csat_squad_filtered | TC-017 | CSAT | broadcast via squad filter |
| tests/gateway/test_csat_rating.py | test_tc018_csat_no_customer_connected | TC-018 | CSAT | graceful no-subscriber |
| tests/test_metrics_billing.py | test_tc019_takeover_triggers_billing | TC-019 | billing | TAKEOVER → record_takeover() |
| tests/test_metrics_billing.py | test_tc020_non_takeover_no_billing | TC-020 | billing | non-TAKEOVER filtered |
| tests/test_metrics_billing.py | test_tc021_csat_event_triggers_billing | TC-021 | billing | CSAT event → record_csat() |
| tests/test_metrics_billing.py | test_tc022_graceful_without_billing | TC-022 | billing | None billing graceful |
| tests/test_metrics_billing.py | test_tc023_billing_api_real_data | TC-023 | billing | real event counts |
| tests/test_approve_reject.py | test_tc024_approve_updates_status | TC-024 | proposal | accepted + persist |
| tests/test_approve_reject.py | test_tc025_reject_updates_status | TC-025 | proposal | rejected status |
| tests/test_approve_reject.py | test_tc026_invalid_id_returns_none | TC-026 | proposal | non-existent ID |
| tests/test_approve_reject.py | test_tc027_approve_idempotent | TC-027 | proposal | re-approve safe |
| tests/test_approve_reject.py | test_tc028_id_parsing | TC-028 | proposal | #N and prop_xxx formats |
| tests/test_approve_reject.py | test_tc029_status_validation | TC-029 | proposal | invalid status rejected |

### New fixtures

| File | Name | Scope | Provides |
|------|------|-------|----------|
| test_subscription_registry.py | registry | function | empty SubscriptionRegistry |
| test_subscription_registry.py | make_entry | function | SubscriptionEntry factory |
| test_squad_broadcast.py | squad_plugin | function | SquadPlugin with channel_routing |
| test_squad_broadcast.py | make_conv | function | Conversation factory |
| test_csat_rating.py | billing | function | BillingMetrics instance |
| test_csat_rating.py | metrics | function | MetricsPlugin wired to billing |
| test_csat_rating.py | make_csat_event | function | CSAT Event factory |
| test_metrics_billing.py | metrics_with_billing | function | (MetricsPlugin, BillingMetrics) tuple |
| test_metrics_billing.py | metrics_standalone | function | MetricsPlugin without billing |
| test_approve_reject.py | pipeline | function | ProposalPipeline with tmp DB |
| test_approve_reject.py | seeded_pipeline | function | pipeline with 2 draft proposals |

### New files
- `tests/gateway/test_subscription_registry.py` — 8 test cases (T6A.1)
- `tests/gateway/test_squad_broadcast.py` — 5 test cases (T6A.2)
- `tests/gateway/test_csat_rating.py` — 5 test cases (T6C.1)
- `tests/test_metrics_billing.py` — 5 test cases (T6C.2)
- `tests/test_approve_reject.py` — 6 test cases (T6C.3)

## Validation
- Syntax: 5/5 files pass `ast.parse()`
- Imports: all key modules resolve
- Fixture graph: no circular deps (each file self-contained)
- Naming: follows `test_tc{NNN}_{action}` convention
- No pytest-order (project uses independent tests)
