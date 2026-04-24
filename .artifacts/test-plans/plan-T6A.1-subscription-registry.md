---
type: test-plan
id: plan-T6A.1
status: confirmed
producer: skill-2
created_at: "2026-04-17T17:00:00+08:00"
trigger: "T6A.1 completed — regression coverage needed"
source_task: T6A.1
related_artifacts: []
---

# Test Plan: T6A.1 — Subscription Registry + subscription_added (S13)

## Trigger

Task T6A.1 completed. Implementation in `autoservice/gateway/subscription_registry.py` and
`autoservice/gateway/message_router.py`. No existing E2E coverage.

## Test Cases

### TC-001: Subscribe with conversation scope
- **Priority**: P0
- **Source**: code-diff (T6A.1 deliverable)
- **Module**: gateway/message_router, gateway/subscription_registry
- **Precondition**: WebSocket connection established, valid session
- **Steps**:
  1. Send `subscribe` frame with `scope: {conversation_id: "conv_123"}`
  2. Read response frame
- **Expected**:
  - Response type = `subscription_added`
  - Contains `subscription_id` (non-empty string)
  - Contains `scope` matching request
  - `subscription_registry.count` incremented by 1

### TC-002: Subscribe with squad scope
- **Priority**: P0
- **Source**: code-diff (T6A.1 deliverable)
- **Module**: gateway/message_router, gateway/subscription_registry
- **Precondition**: WebSocket connection established as operator
- **Steps**:
  1. Send `subscribe` frame with `scope: {squad_id: "web-support"}`
  2. Read response frame
- **Expected**:
  - Response type = `subscription_added`
  - Contains valid `subscription_id`
  - Registry `get_by_scope("squad:web-support")` returns entry

### TC-003: Subscribe with global scope on admin WS
- **Priority**: P1
- **Source**: code-diff (scope validation logic)
- **Module**: gateway/subscription_registry
- **Precondition**: WebSocket connection on `/ws/admin` path
- **Steps**:
  1. Send `subscribe` frame with `scope: {global: true}`
  2. Read response frame
- **Expected**:
  - Response type = `subscription_added`
  - Registry `get_by_scope("global")` returns entry

### TC-004: Subscribe with global scope on non-admin WS — rejected
- **Priority**: P0
- **Source**: code-diff (access control)
- **Module**: gateway/subscription_registry
- **Precondition**: WebSocket connection on `/ws/operator` (not admin)
- **Steps**:
  1. Send `subscribe` frame with `scope: {global: true}`
  2. Read response frame
- **Expected**:
  - Error frame returned (4013 or equivalent)
  - Registry count unchanged

### TC-005: Subscribe with invalid scope (zero or multiple scope types)
- **Priority**: P0
- **Source**: code-diff (scope validation)
- **Module**: gateway/message_router
- **Precondition**: WebSocket connection established
- **Steps**:
  1. Send `subscribe` with `scope: {}` (empty)
  2. Send `subscribe` with `scope: {conversation_id: "c1", squad_id: "s1"}` (multiple)
- **Expected**:
  - Both return error frames
  - No subscription created in registry

### TC-006: Unsubscribe removes subscription
- **Priority**: P0
- **Source**: code-diff (T6A.1 deliverable #4)
- **Module**: gateway/message_router, gateway/subscription_registry
- **Precondition**: Active subscription exists
- **Steps**:
  1. Subscribe → get `subscription_id`
  2. Send `unsubscribe` frame with that `subscription_id`
  3. Read response
- **Expected**:
  - Response type = `subscription_removed`
  - Registry `count` decremented
  - `get_by_session(session_id)` no longer contains that subscription

### TC-007: Session disconnect evicts all subscriptions
- **Priority**: P0
- **Source**: code-diff (T6A.1 deliverable #5)
- **Module**: gateway/subscription_registry
- **Precondition**: Session with 2+ active subscriptions
- **Steps**:
  1. Create 2 subscriptions on same session
  2. Simulate session disconnect (call `evict_by_session`)
- **Expected**:
  - All subscriptions for that session removed
  - Fan-out tasks cancelled
  - Registry count reduced by 2

### TC-008: Fan-out delivers events to subscriber
- **Priority**: P0
- **Source**: code-diff (async _fanout task)
- **Module**: gateway/message_router
- **Precondition**: Active subscription on conversation scope
- **Steps**:
  1. Subscribe to `conversation_id: "conv_123"`
  2. Emit an event for conv_123 via engine
  3. Read WebSocket
- **Expected**:
  - Subscriber receives event frame with correct payload
  - Non-subscribers do NOT receive it

## Summary

| Priority | Count |
|----------|-------|
| P0       | 6     |
| P1       | 2     |
| **Total**| **8** |

## Risk

- **High**: Subscription fan-out is async — timing-sensitive tests need proper await/drain
- **Medium**: Global scope ACL depends on WS path detection — mock must reflect real routing
