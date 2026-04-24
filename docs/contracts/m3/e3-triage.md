# Contract · M3 Epic E3 · Triage Dispatch Enhancement

**Version**: v1.0 · **Frozen**: 2026-04-21
**Design spec**: [docs/superpowers/specs/2026-04-21-m3-e3-triage-enhancement-design.md](../../superpowers/specs/2026-04-21-m3-e3-triage-enhancement-design.md)
**Stories covered**: E3.1, E3.2, E3.3, E3.4

## 1. SLA Metrics (E3.1)

### 1.1 MetricType Extension

Existing [sla_aggregator.py:71-76](../../../autoservice/sla_aggregator.py#L71-L76) has 7 metrics. Add:

```python
class MetricType(Enum):
    # ... existing 7 ...
    POOL_WAIT_MS     = "pool_wait_ms"        # new
    POOL_UTILIZATION = "pool_utilization"    # new (gauge)
```

### 1.2 AsyncPool Metrics Surface ([socialware/pool.py](../../../socialware/pool.py))

New methods on `AsyncPool`:

```python
class AsyncPool(Generic[T]):
    def metrics(self) -> PoolMetrics: ...

@dataclass(frozen=True)
class PoolMetrics:
    available_count: int
    busy_count: int
    queue_length: int
    wait_time_histogram_ms: dict[str, int]  # bucket → count (e.g. "0-100": 42)
    emitted_at: int                         # epoch ms
```

Wait-time tracked via `checkout_started_at` - `checkout_granted_at` delta. Histogram buckets: `0-100`, `100-500`, `500-1000`, `1000-5000`, `5000+`.

### 1.3 Per-Tenant SLA Thresholds

Per OQ-E3-1 default: M3 opens per-tenant for `pool_wait_ms` + `first_reply_ms` only. Other 7 metrics stay global in M3; full coverage deferred to M3.5.

Schema:
```python
# autoservice/sla_aggregator.py
SLA_THRESHOLDS: dict[tuple[str, MetricType], float] = {
    # ('global', MetricType.FIRST_REPLY_MS): 60_000,
    # ('tenant-A', MetricType.POOL_WAIT_MS): 2_000,
    # keyed by (tenant_id | 'global', metric); tenant-specific overrides global fallback
}
```

Resolution order in `check_threshold(tenant_id, metric, value)`:
1. Lookup `(tenant_id, metric)` → if found, use
2. Fallback `('global', metric)` → use
3. No threshold → no alert

### 1.4 Alert Delivery to Operator Console

**[CORRECTION applied from E3 subagent finding]**: AlertEngine is already WS-wired to `_admin_connections` at [web_gateway.py:285-326](../../../autoservice/web_gateway.py#L285-L326). Add **parallel** path to `_operator_connections`, tenant-scope filtered:

```python
def _push_alert_to_operators(alert: Alert, tenant_id: str):
    conns = _operator_connections.get(tenant_id, [])   # tenant-scoped, no cross-leak
    for conn in conns:
        asyncio.create_task(conn.send_json({"type": "sla.alert", "alert": alert.to_dict()}))
```

Hooks into `AlertEngine._notify_fn` alongside existing admin push.

## 2. Handoff Protocol (E3.2)

### 2.1 Tag Grammar

Agent output may contain:
```
<handoff to="ROLE" reason="FREE_TEXT_STRING" />
```

- `ROLE` must be one of: `customer | lead | translate | triage | dream` (matches `AgentRole` enum)
- `reason` is free-text (OQ-E3-2 default), UTF-8, max 200 chars; may be missing
- Tag is self-closing; no nesting; one tag per agent turn (subsequent tags ignored)

### 2.2 Parser Contract

Mirror existing [sentiment.py:69-92](../../../autoservice/sentiment.py#L69-L92) shape:

```python
# autoservice/handoff.py
@dataclass(frozen=True)
class HandoffResult:
    target_role: AgentRole
    reason: str | None
    raw_tag: str

def parse_handoff(agent_output: str) -> tuple[HandoffResult | None, str]:
    """Returns (result, cleaned_output).
    
    - result is None if no valid tag present
    - cleaned_output strips the tag from output (for customer-facing rendering)
    - malformed tags are DROPPED (not raise); adversarial inputs return (None, original)
    """
```

### 2.3 Re-Triage Trigger

On parser hit in output-processing pipeline:

1. Emit event `handoff.detected` with `{conversation_id, from_role, to_role, reason}`
2. Release sticky session via `cc_pool.release_sticky(conversation_id)`
3. Acquire new role: `cc_pool.acquire(role=target, tenant_id=...)` — no changes needed per cc_pool.py:393-454 existing support
4. Re-seed new role with compressed history (§4)
5. Emit `role.switched` event

## 3. classify_intent DB (E3.3)

Existing YAML at [autoservice/classify_intent.yaml](../../../autoservice/classify_intent.yaml) becomes DB-backed.

### 3.1 Schema

```sql
CREATE TABLE classify_intent_config (
    tenant_id   TEXT NOT NULL,
    intent      TEXT NOT NULL,
    keywords    TEXT NOT NULL,             -- JSON array of strings
    threshold   REAL NOT NULL,             -- 0.0-1.0
    model_tier  TEXT NOT NULL,             -- 'fast' | 'deep'
    route_role  TEXT NOT NULL,             -- target AgentRole
    updated_at  INTEGER NOT NULL,
    updated_by  TEXT,                      -- admin email
    PRIMARY KEY (tenant_id, intent)
);
```

### 3.2 Migration (Idempotent)

On first run: if `classify_intent_config` is empty, seed from `classify_intent.yaml` with `tenant_id='_default'`. Every new tenant inherits `_default` via `FastClassifier.for_tenant(tid)` fallback.

### 3.3 Hot-Reload (Existing Infrastructure)

**[FINDING from E3 subagent]**: `FastClassifier.for_tenant()` + `clear_tenant_cache()` already exist at [model_router.py:91-114](../../../autoservice/model_router.py#L91-L114). CRUD endpoints hit `clear_tenant_cache(tenant_id)` on write.

### 3.4 CRUD Endpoints (admin role required)

```
GET    /api/admin/{tenant_id}/classify-intent                     → list
GET    /api/admin/{tenant_id}/classify-intent/{intent}            → single
PUT    /api/admin/{tenant_id}/classify-intent/{intent}            → upsert (triggers cache clear)
DELETE /api/admin/{tenant_id}/classify-intent/{intent}            → reset to _default
```

## 4. History Compression (E3.4, CON-11)

### 4.1 Scope (CON-11)

**M3 trigger only**: on role-switch in re-triage (§2.3 step 4). Does NOT run on dream agent context, does NOT compress for token-budget reasons. Broad rollout → M4+.

### 4.2 Contract

```python
# autoservice/history_compressor.py
def compress_for_role_switch(
    conversation_id: str,
    history: list[Message],
    target_role: AgentRole,
    model: str = "haiku",   # OQ-E3-3 default
) -> CompressionResult:
    """Returns CompressionResult with summary + recent_tail messages.
    
    - Triggered only when len(history) >= 20 (threshold per PRD §2 E3.4)
    - If len < 20, returns CompressionResult(summary=None, tail=history) (no-op)
    - Uses haiku by default; tenant opt-in sonnet via tenant.config.compression_model
    - Cost-tracked; breach of daily budget raises CompressionBudgetExceeded
    """

@dataclass(frozen=True)
class CompressionResult:
    summary: str | None
    tail: list[Message]         # last N raw messages (N=3)
    tokens_used: int
    cost_cents: float
```

### 4.3 Re-Seed Format

New role receives:
```
[Conversation summary so far]
{summary}

[Recent messages]
{tail formatted as existing conversation_history format}
```

## 5. "Don't Do" List

1. **Don't** parse multiple `<handoff>` tags in one agent turn — first valid wins
2. **Don't** allow handoff to `_master` or undefined roles
3. **Don't** compress history outside role-switch context (CON-11 scope limit)
4. **Don't** hot-reload classify_intent via file-watch — use DB + cache invalidation only
5. **Don't** emit `sla.alert` to operators of other tenants — tenant-scope enforced at push time
6. **Don't** add per-tenant threshold for metrics outside OQ-E3-1 approved list in M3

## 6. Open Questions (Defaults Applied)

| OQ | Default |
|---|---|
| OQ-E3-1 per-tenant metrics in M3 | `pool_wait_ms` + `first_reply_ms` only |
| OQ-E3-2 handoff reason format | free-text (max 200 chars) |
| OQ-E3-3 compression model | `haiku` default; tenant opt-in `sonnet` via config |

## 7. Test Requirements

- `tests/handoff/test_parser.py` — adversarial inputs (nested, malformed, truncated, injection)
- `tests/triage/test_role_switch.py` — e2e: handoff → release → acquire new role → compressed re-seed
- `tests/sla/test_per_tenant_threshold.py` — resolution order (tenant → global)
- `tests/pool/test_metrics.py` — counter accuracy under 100 async checkouts
- `tests/classify_intent/test_db_backing.py` — migration idempotent; CRUD triggers cache clear
- `tests/history_compressor/test_summarize.py` — cost budget guardrail; quality check (summary + tail <2K tokens for 50-msg history)
