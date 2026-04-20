---
type: test-plan
id: plan-T6A.2
status: confirmed
producer: skill-2
created_at: "2026-04-17T17:00:00+08:00"
trigger: "T6A.2 completed — regression coverage needed"
source_task: T6A.2
related_artifacts: ["plan-T6A.1"]
---

# Test Plan: T6A.2 — Squad-Filtered Message Broadcast

## Trigger

Task T6A.2 completed. Implementation in `autoservice/gateway/message_router.py` (_broadcast_to_squad)
and `autoservice/plugins/squad_plugin.py`. Depends on T6A.1 subscription registry.

## Test Cases

### TC-009: Customer message only reaches squad-subscribed operator
- **Priority**: P0
- **Source**: code-diff (T6A.2 verification #1-#2)
- **Module**: gateway/message_router, plugins/squad_plugin
- **Precondition**: Operator A subscribed to "web-support", Operator B subscribed to "vip"
- **Steps**:
  1. Customer sends message in conversation assigned to squad "web-support"
  2. Check which operators receive the broadcast
- **Expected**:
  - Operator A receives customer_frame
  - Operator B does NOT receive it

### TC-010: Multiple squads complete isolation
- **Priority**: P0
- **Source**: code-diff (T6A.2 verification #3)
- **Module**: gateway/message_router, plugins/squad_plugin
- **Precondition**: 3 operators across 2 squads, 2 conversations in different squads
- **Steps**:
  1. Conv-1 (squad=web-support): customer sends message
  2. Conv-2 (squad=vip): customer sends message
- **Expected**:
  - web-support operators only get Conv-1 message
  - vip operators only get Conv-2 message
  - Cross-squad leakage = 0

### TC-011: No squad assigned — fallback broadcast to all
- **Priority**: P1
- **Source**: code-diff (backward compatibility fallback)
- **Module**: gateway/message_router
- **Precondition**: Conversation with no squad_id, multiple operators connected
- **Steps**:
  1. Customer sends message in unassigned conversation
- **Expected**:
  - ALL connected operators receive the message
  - No error thrown

### TC-012: Squad assignment via channel_routing config
- **Priority**: P1
- **Source**: code-diff (squad_plugin.on_conversation_created)
- **Module**: plugins/squad_plugin
- **Precondition**: squad_config = {channel_routing: {"web": "web-support"}}
- **Steps**:
  1. Create conversation from "web" channel
  2. Check squad assignment
- **Expected**:
  - `squad_plugin.get_squad(conv_id)` returns "web-support"

### TC-013: Squad reassignment updates broadcast routing
- **Priority**: P2
- **Source**: code-diff (squad_plugin.reassign)
- **Module**: plugins/squad_plugin, gateway/message_router
- **Precondition**: Conversation assigned to "web-support", Operator A on web-support, Operator B on vip
- **Steps**:
  1. Reassign conversation to "vip"
  2. Customer sends message
- **Expected**:
  - Operator B receives message (new squad)
  - Operator A does NOT receive message

## Summary

| Priority | Count |
|----------|-------|
| P0       | 2     |
| P1       | 2     |
| P2       | 1     |
| **Total**| **5** |

## Risk

- **Medium**: Squad fallback (TC-011) must not mask real routing bugs — test with explicit assertion
