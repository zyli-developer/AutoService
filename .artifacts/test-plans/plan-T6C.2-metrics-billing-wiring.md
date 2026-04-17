---
type: test-plan
id: plan-T6C.2
status: confirmed
producer: skill-2
created_at: "2026-04-17T17:00:00+08:00"
trigger: "T6C.2 completed — regression coverage needed"
source_task: T6C.2
related_artifacts: []
---

# Test Plan: T6C.2 — Metrics Plugin to BillingMetrics Wiring

## Trigger

Task T6C.2 completed. Implementation in `autoservice/plugins/metrics_plugin.py`.
Key: `on_mode_changed` → `record_takeover()`, `on_event(CSAT)` → `record_csat()`.

## Test Cases

### TC-019: Mode change to TAKEOVER triggers record_takeover()
- **Priority**: P0
- **Source**: code-diff (T6C.2 verification #1)
- **Module**: plugins/metrics_plugin, billing_metrics
- **Precondition**: MetricsPlugin initialized with BillingMetrics instance
- **Steps**:
  1. Call `metrics_plugin.on_mode_changed(conv, "AGENT", "TAKEOVER", "operator")`
  2. Check BillingMetrics state
- **Expected**:
  - `BillingMetrics.record_takeover()` called
  - `metrics_plugin.mode_changes["AGENT→TAKEOVER"]` incremented

### TC-020: Mode change to non-TAKEOVER does NOT trigger record_takeover
- **Priority**: P0
- **Source**: coverage-gap (negative test)
- **Module**: plugins/metrics_plugin
- **Precondition**: MetricsPlugin with BillingMetrics
- **Steps**:
  1. Call `on_mode_changed(conv, "TAKEOVER", "AGENT", "auto")`
- **Expected**:
  - `record_takeover()` NOT called
  - `mode_changes["TAKEOVER→AGENT"]` incremented (counter only)

### TC-021: CSAT event triggers record_csat()
- **Priority**: P0
- **Source**: code-diff (T6C.2 verification #1)
- **Module**: plugins/metrics_plugin, billing_metrics
- **Precondition**: MetricsPlugin with BillingMetrics
- **Steps**:
  1. Emit `CONVERSATION_CSAT_RECORDED` event with score=5
  2. Check BillingMetrics and metrics_plugin state
- **Expected**:
  - `BillingMetrics.record_csat(5)` called
  - `metrics_plugin.csat_scores` contains 5

### TC-022: MetricsPlugin works without BillingMetrics (graceful)
- **Priority**: P1
- **Source**: coverage-gap (optional dependency)
- **Module**: plugins/metrics_plugin
- **Precondition**: MetricsPlugin initialized with `billing_metrics=None`
- **Steps**:
  1. Call `on_mode_changed(conv, "AGENT", "TAKEOVER", "operator")`
  2. Emit CSAT event
- **Expected**:
  - No exception
  - Internal counters still increment
  - BillingMetrics calls skipped silently

### TC-023: /api/billing/summary returns real data after wiring
- **Priority**: P0
- **Source**: code-diff (T6C.2 verification #2)
- **Module**: api_routes
- **Precondition**: MetricsPlugin + BillingMetrics wired, some events recorded
- **Steps**:
  1. Record 2 takeovers + 1 CSAT via events
  2. GET `/api/billing/summary`
- **Expected**:
  - Response reflects real event counts (not seed data like "demo-conv-1")
  - Takeover count = 2

## Summary

| Priority | Count |
|----------|-------|
| P0       | 4     |
| P1       | 1     |
| **Total**| **5** |

## Risk

- **Medium**: Seed data in `_get_billing()` still exists for operator leaderboard — ensure test distinguishes real vs demo data
