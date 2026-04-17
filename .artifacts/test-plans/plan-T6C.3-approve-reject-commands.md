---
type: test-plan
id: plan-T6C.3
status: confirmed
producer: skill-2
created_at: "2026-04-17T17:00:00+08:00"
trigger: "T6C.3 completed — regression coverage needed"
source_task: T6C.3
related_artifacts: []
---

# Test Plan: T6C.3 — /approve /reject Real Execution

## Trigger

Task T6C.3 completed. Implementation in `autoservice/api_routes.py` (command handlers)
and `autoservice/proposal_pipeline.py` (update_status method).

## Test Cases

### TC-024: /approve #N updates proposal to accepted + activates canary
- **Priority**: P0
- **Source**: code-diff (T6C.3 verification #1)
- **Module**: api_routes, proposal_pipeline, canary_router
- **Precondition**: Proposal with id "prop_001" exists in DB with status="draft"
- **Steps**:
  1. Send `/approve #1` command (or `/approve prop_001`)
  2. Check proposal status
  3. Check canary router state
- **Expected**:
  - `proposal_pipeline.get_proposal("prop_001").status` = "accepted"
  - CanaryRouter.activate() called with proposal_id
  - Response confirms approval

### TC-025: /reject #N updates proposal to rejected
- **Priority**: P0
- **Source**: code-diff (T6C.3 verification #2)
- **Module**: api_routes, proposal_pipeline
- **Precondition**: Proposal "prop_002" exists with status="draft"
- **Steps**:
  1. Send `/reject #2`
  2. Check proposal status
- **Expected**:
  - `proposal_pipeline.get_proposal("prop_002").status` = "rejected"
  - CanaryRouter NOT activated
  - Response confirms rejection

### TC-026: /approve with invalid proposal ID returns error
- **Priority**: P0
- **Source**: code-diff (T6C.3 verification #3)
- **Module**: api_routes, proposal_pipeline
- **Precondition**: No proposal with id "prop_999"
- **Steps**:
  1. Send `/approve #999`
- **Expected**:
  - Error message returned (proposal not found)
  - No state changes

### TC-027: /approve already-accepted proposal — idempotent or error
- **Priority**: P1
- **Source**: coverage-gap (edge case)
- **Module**: proposal_pipeline
- **Precondition**: Proposal "prop_001" already in "accepted" status
- **Steps**:
  1. Send `/approve #1` again
- **Expected**:
  - Either idempotent (no error, no duplicate canary) or clear error message
  - No duplicate canary activation

### TC-028: Proposal ID parsing formats
- **Priority**: P1
- **Source**: code-diff (_parse_proposal_id supports #N and prop_xxxx)
- **Module**: api_routes
- **Precondition**: Proposals exist in DB
- **Steps**:
  1. `/approve #1` (numeric shorthand)
  2. `/approve prop_abc123` (full ID)
  3. `/approve` (no ID)
  4. `/approve #` (empty numeric)
- **Expected**:
  - #1 → resolves to first proposal
  - prop_abc123 → direct lookup
  - No ID → error message asking for ID
  - Empty # → error message

### TC-029: update_status validates status values
- **Priority**: P1
- **Source**: code-diff (VALID_STATUSES check)
- **Module**: proposal_pipeline
- **Precondition**: Draft proposal exists
- **Steps**:
  1. Call `update_status(id, "accepted")` — valid
  2. Call `update_status(id, "bogus")` — invalid
- **Expected**:
  - "accepted" succeeds
  - "bogus" raises ValueError or returns None

## Summary

| Priority | Count |
|----------|-------|
| P0       | 3     |
| P1       | 3     |
| **Total**| **6** |

## Risk

- **Medium**: Canary activation side effect — test must verify canary state, not just proposal status
- **Low**: DB persistence — update_status writes to SQLite, test should verify persistence across reads
