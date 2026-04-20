---
type: test-plan
id: plan-T6C.1
status: confirmed
producer: skill-2
created_at: "2026-04-17T17:00:00+08:00"
trigger: "T6C.1 completed — regression coverage needed"
source_task: T6C.1
related_artifacts: ["plan-T6A.1"]
---

# Test Plan: T6C.1 — CSAT Rating End-to-End

## Trigger

Task T6C.1 completed. Implementation spans backend (`_push_csat_request` in message_router.py)
and frontend (CSATRating.tsx, useConversation.ts). Yellow task — full-stack with new protocol frame.

## Test Cases

### TC-014: /resolve triggers csat_request frame to customer
- **Priority**: P0
- **Source**: code-diff (T6C.1 verification #1)
- **Module**: gateway/message_router
- **Precondition**: Active conversation with customer WS connected
- **Steps**:
  1. Operator sends `/resolve` command for conversation
  2. Read customer WebSocket
- **Expected**:
  - Customer receives `csat_request` frame (S10)
  - Frame contains `conversation_id`

### TC-015: csat_response records score in BillingMetrics
- **Priority**: P0
- **Source**: code-diff (T6C.1 verification #2-#3)
- **Module**: gateway/message_router, plugins/metrics_plugin
- **Precondition**: CSAT request sent, BillingMetrics instance wired
- **Steps**:
  1. Customer sends `csat_response` frame with `score: 4`
  2. Check BillingMetrics state
- **Expected**:
  - `metrics_plugin.csat_scores` contains 4
  - `BillingMetrics.record_csat()` called with score=4

### TC-016: CSAT score range validation (1-5)
- **Priority**: P1
- **Source**: coverage-gap (boundary testing)
- **Module**: gateway/message_router
- **Precondition**: CSAT request sent
- **Steps**:
  1. Send `csat_response` with score=0 (below range)
  2. Send `csat_response` with score=6 (above range)
  3. Send `csat_response` with score=1 (min valid)
  4. Send `csat_response` with score=5 (max valid)
- **Expected**:
  - score=0 and score=6: rejected or clamped
  - score=1 and score=5: accepted and recorded

### TC-017: CSAT request uses squad-filtered broadcast
- **Priority**: P1
- **Source**: code-diff (_push_csat_request uses _broadcast_to_squad)
- **Module**: gateway/message_router
- **Precondition**: 2 operators on different squads
- **Steps**:
  1. Resolve conversation in squad "web-support"
  2. Check which operators see the CSAT notification
- **Expected**:
  - Only operators subscribed to "web-support" see CSAT event
  - Other squad operators do NOT

### TC-018: No customer WS connected — csat_request does not error
- **Priority**: P2
- **Source**: coverage-gap (edge case)
- **Module**: gateway/message_router
- **Precondition**: Conversation exists but customer disconnected
- **Steps**:
  1. Operator sends `/resolve`
- **Expected**:
  - No crash or unhandled exception
  - Conversation still marked resolved

## Summary

| Priority | Count |
|----------|-------|
| P0       | 2     |
| P1       | 2     |
| P2       | 1     |
| **Total**| **5** |

## Risk

- **High**: CSAT is full-stack (WS frame + frontend + billing) — integration test must cover the frame flow, not just unit
- **Medium**: Score validation (TC-016) — if not enforced, garbage data enters billing
