# Contract · M3 Epic E5 · Dream Extension (🔒 CON-04 Red Line)

**Version**: v1.1 · **Frozen**: 2026-04-21 (v1.0 → v1.1 revision addresses code-reviewer Critical findings C1-C4; see §8 Revision Log)
**Design spec**: [docs/superpowers/specs/2026-04-21-m3-e5-dream-extension-design.md](../../superpowers/specs/2026-04-21-m3-e5-dream-extension-design.md)
**Stories covered**: E5.1 (platform dream), E5.2 (apply_proposal)
**Red line**: **CON-04 — Dream agents MAY NEVER write non-draft proposal status.**

---

## 🚨 CON-04 Red Line (non-negotiable)

1. `emit_proposal()` signature has **NO** `status` kwarg (signature-locked by test)
2. Status string `'draft'` is **hardcoded** inside `emit_proposal` in both JSON payload and SQL column
3. `apply_proposal()` is the **ONLY** writer of `status='applied'`
4. `proposal_apply.py` module has a **one-way import cone**: no imports from `dream_agent.py` or `master_dream_agent.py`; no reverse imports either
5. AST-walk guardrail test (T4S.8) asserts `status='applied'` / `status='accepted'` string literals appear **only** in `autoservice/proposal_apply.py` and `autoservice/proposal_pipeline.py:update_status`
6. Any PR that adds a `status` kwarg to `emit_proposal`, imports dream module into apply module, or introduces status-write string outside approved locations is **rejected on sight**

---

## 1. Platform-Level Dream (E5.1)

### 1.1 Module Layout

**Separate** from per-tenant dream to prevent tool-call pollination:

```
autoservice/
  dream_agent.py              # EXISTING — per-tenant (untouched except additive)
  master_dream_agent.py       # NEW in M3 — platform aggregator
  dream_scheduler.py          # EXISTING — routing logic extended
```

### 1.2 Scheduler Routing

In `dream_scheduler.py`:

```python
async def run_dream_for_tenant(tenant_id: str):
    if tenant_id == bootstrap.MASTER_TENANT_ID:  # '_master'
        await master_dream_agent.run_platform_dream()
    else:
        await dream_agent.run(tenant_id)
```

### 1.3 Master Dream Soul Template

Path: `.autoservice/sandbox/_master/souls/dream_soul.md`

Aggregator persona: reads cross-tenant read-only views, emits proposals about platform-level improvements (skill changes, cc_pool policy tweaks, shared rule additions). Never mutates tenant data.

### 1.4 Cross-Tenant Signal Ingestion (E5.1 deliverable)

Signals (read-only):

| Source | Metric | Purpose |
|---|---|---|
| cc_pool | per-tenant utilization | detect starvation / overprovisioning |
| sla_aggregator | breach counts per tenant | detect systematic SLA issues |
| skills registry | usage frequency across tenants | detect unused / overused skills |
| proposal_pipeline | per-tenant proposal counts + accept rates | detect dream health issues |
| complaint / csat aggregator | trend analysis | detect product quality regressions |

Contract:

```python
# autoservice/master_dream_agent.py
async def run_platform_dream() -> list[str]:
    """Run master-side dream. Returns list of proposal IDs emitted.
    
    All proposals written via emit_proposal(..., category='platform_level', ...)
    which still carries the CON-04 locked status='draft'.
    """
```

### 1.5 New Proposal Category

Extend proposal schema:

```sql
-- proposals.category CHECK constraint extended
CHECK(category IN (
    'soul_patch',          -- existing
    'knowledge_update',    -- existing
    'cc_pool_config',      -- existing
    'compliance_rule',     -- existing
    'skill_change',        -- existing
    'platform_level'       -- NEW in M3
))
```

---

## 2. apply_proposal (E5.2) — 🔒 Security-Critical

### 2.1 Module + Signature

Path: `autoservice/proposal_apply.py` (NEW).

```python
# autoservice/proposal_apply.py
# 🔒 CON-04 enforcement module.
# DO NOT import from dream_agent, master_dream_agent.
# DO NOT allow any caller to pass 'status' directly.

from dataclasses import dataclass

@dataclass(frozen=True)
class ApplyResult:
    proposal_id: str
    previous_status: str    # 'accepted'
    new_status: str         # 'applied'
    admin_user_id: str
    applied_at: int
    handler_result: dict    # from category-specific handler (M3: mark_applied only)
    idempotent: bool         # True if proposal was already 'applied'

def apply_proposal(
    conn,
    *,
    proposal_id: str,
    admin_user_id: str,
) -> ApplyResult:
    """Transition proposal status 'accepted' → 'applied' with audit.
    
    Pre-conditions (strict):
    - proposal exists
    - proposal.status == 'accepted' (else raise ProposalStateError)
    - admin_user_id is a valid admin session owner (tier-0 OR tenant_admin of proposal's tenant)
    
    Side effects:
    - UPDATE proposals SET status='applied' WHERE id=proposal_id  (only code path)
    - INSERT INTO proposal_audit
    - Dispatch to category handler (M3: mark_applied only)
    
    Idempotency:
    - If proposal.status == 'applied' already: return ApplyResult(idempotent=True); NOT an error
    """
```

### 2.2 State Machine Extension (REVISED v1.1 — addresses C1, C3)

**Existing state (2026-04-21)**: [proposal_pipeline.py:92](../../../autoservice/proposal_pipeline.py#L92) declares `VALID_STATUSES = {"draft", "accepted", "rejected", "implemented"}`. Existing doc comment at [line 361](../../../autoservice/proposal_pipeline.py#L361) says "draft → accepted | rejected, accepted → implemented".

**M3 changes**:
1. **Rename `implemented` → `applied`** (reviewer C3). `implemented` becomes a dead string. Migration on M3 first boot:
   ```sql
   UPDATE proposals SET status='applied' WHERE status='implemented';
   -- Update VALID_STATUSES source constant
   ```
   Rationale: PRD consistently uses "applied"; two similar-meaning terminal states invite confusion. If any production proposals have status='implemented', migration sweeps them to 'applied' atomically. Single terminal state simplifies state machine.

2. **Split `update_status` into public + private halves** (reviewer C1 — drop frame inspection):

```python
# autoservice/proposal_pipeline.py

VALID_STATUSES = {"draft", "accepted", "rejected", "applied"}   # 'implemented' removed

# PUBLIC: callable from any handler (approve/reject endpoints)
def update_status(self, proposal_id: str, new_status: str) -> dict | None:
    """Transition draft ↔ accepted ↔ rejected. Does NOT accept 'applied'.
    
    Value-layer rejection (no frame inspection):
    - if new_status == 'applied': raise ProposalStateError(
          "'applied' can only be written via apply_proposal.apply_proposal()")
    - Accepts only {'accepted', 'rejected'}.
    """

# PRIVATE module helper: ONLY proposal_apply.apply_proposal imports this.
# No public exports; not in __all__; module-private _mark_applied prefix.
def _mark_applied_internal(self, proposal_id: str, admin_user_id: str) -> dict | None:
    """Transition 'accepted' → 'applied'. NOT a public API.
    
    Enforced via import cone (Layer 3), not runtime introspection.
    Uses conditional UPDATE pattern (§2.3) for race-safety.
    """
```

The trust story: `update_status` is a **value-rejection** mechanism (no frame tricks); `_mark_applied_internal` is an **import-cone** mechanism (AST guardrail T4S.8 verifies its only caller is `proposal_apply`).

| From | To | Caller Path | Enforcement |
|---|---|---|---|
| `draft` | `accepted` | `/approve` → `update_status` | value check passes |
| `draft` | `rejected` | `/reject` → `update_status` | value check passes |
| `accepted` | `rejected` | `/reject` after accept → `update_status` | value check passes |
| `accepted` | **`applied`** | **`apply_proposal()` → `_mark_applied_internal`** | 🔒 import cone (Layer 3) + AST guardrail (Layer 4) |
| any → `applied` via `update_status` | raises `ProposalStateError` | value rejection (Layer 2b, no frame tricks) |
| `applied` | — | terminal | no further transitions |

### 2.3 Race-Safe Conditional UPDATE (REVISED v1.1 — addresses C2)

`_mark_applied_internal` MUST use atomic conditional UPDATE, not SELECT-then-UPDATE:

```python
def _mark_applied_internal(self, proposal_id, admin_user_id):
    with self.conn:  # BEGIN IMMEDIATE ... COMMIT atomic
        cursor = self.conn.execute(
            "UPDATE proposals SET status='applied' "
            "WHERE id=? AND status='accepted'",
            (proposal_id,)
        )
        if cursor.rowcount == 1:
            # Transition succeeded
            previous_status = 'accepted'
        elif cursor.rowcount == 0:
            # Either idempotent (already 'applied') or illegal (draft/rejected)
            row = self.conn.execute(
                "SELECT status FROM proposals WHERE id=?", (proposal_id,)
            ).fetchone()
            if row is None:
                raise ProposalNotFound(proposal_id)
            if row['status'] == 'applied':
                return {'idempotent': True, ...}   # no error
            raise ProposalStateError(
                f"Cannot apply: current status {row['status']!r} != 'accepted'")
        
        # Audit INSERT in SAME transaction
        self.conn.execute(
            "INSERT INTO proposal_audit (proposal_id, admin_user_id, action, ...) VALUES (...)",
            (...))
    return {...}
```

Concurrency invariants:
- Two concurrent apply_proposal calls on same pid: SQLite IMMEDIATE lock serializes; one UPDATEs (rowcount=1), the other sees status='applied' (rowcount=0, idempotent branch).
- No race window between check and transition.
- Audit row is **in same transaction** as state change — cannot have state-change-without-audit.

### 2.4 Audit Table (write-locked to proposal_apply — C4)

```sql
CREATE TABLE proposal_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id     TEXT NOT NULL REFERENCES proposals(id),
    admin_user_id   TEXT NOT NULL,
    action          TEXT NOT NULL CHECK(action IN ('approve', 'reject', 'apply')),
    previous_status TEXT NOT NULL,
    new_status      TEXT NOT NULL,
    session_id      TEXT,                      -- which admin session performed
    timestamp       INTEGER NOT NULL,
    details         TEXT                       -- JSON-encoded handler result
);

CREATE INDEX ix_proposal_audit_proposal ON proposal_audit(proposal_id);
CREATE INDEX ix_proposal_audit_admin ON proposal_audit(admin_user_id);
```

Retention: indefinite (OQ-E5-2 default). Archival deferred to M4+ (link to E6 sandbox GC pattern).

**C4 Enforcement**: `INSERT INTO proposal_audit` string literal is restricted to:
- `autoservice/proposal_apply.py` (apply action)
- `autoservice/api_routes.py` approve/reject handlers (for approve/reject audit)
- `autoservice/proposal_pipeline.py` (if refactored — `_mark_applied_internal`)

AST guardrail T4S.8 extended to check this additional invariant. Any other file containing the literal → CI fails.

### 2.5 Handler Registry (M3 Scope — OQ-E5-1)

```python
# autoservice/proposal_apply.py
_HANDLERS = {
    'soul_patch': mark_applied,
    'knowledge_update': mark_applied,
    'cc_pool_config': mark_applied,
    'compliance_rule': mark_applied,
    'skill_change': mark_applied,
    'platform_level': mark_applied,
}

def mark_applied(conn, proposal) -> dict:
    """M3 no-op: only writes state + audit. M4+ adds category-specific mutation."""
    return {'marked_applied_at': now_ms(), 'side_effects': None}
```

**Real runtime mutations (skill patch apply, cc_pool policy reload, etc.) are M4+ work.** This keeps M3 scope tight; audit trail is complete even without physical application.

### 2.6 HTTP Endpoint

```
POST /api/admin/proposals/{proposal_id}/apply
  auth:    admin role on proposal's tenant
           (for category='platform_level': tier-0 platform admin ONLY; tenant_admin INSUFFICIENT)
  success: 200 { result: ApplyResult }   # ApplyResult serialized via dataclasses.asdict
  errors:
    404 proposal not found
    409 proposal.status != 'accepted' (returns current status in body for debuggability)
    403 not an admin OR wrong tenant scope OR platform_level without tier-0

Response body:
  { "result": {
      "proposal_id": "...",
      "previous_status": "accepted",
      "new_status": "applied",
      "admin_user_id": "...",
      "applied_at": 1713...,
      "handler_result": {...},
      "idempotent": false
  } }
```

**Minor finding fix**: `apply_proposal()` function itself validates platform_level tier-0 requirement (not only HTTP layer), so internal callers (background jobs) also respect the rule.

### 2.7 Admin-Portal UI

- Apply button on proposal detail page — **separate from Approve button**
- Apply enabled **only** when `proposal.status == 'accepted'`
- Post-apply: badge changes to "applied · {date} · by {admin}"
- No "un-apply" — terminal state

---

## 3. CON-04 Defense in Depth (REVISED v1.1 — 5 layers)

| # | Layer | Mechanism | Enforcement |
|---|---|---|---|
| 1 | **Signature lock** | `emit_proposal` has no `status` kwarg | test [`test_emit_proposal_signature_has_no_status_kwarg`](../../../tests/dream_agent/test_emit_proposal_tool.py#L71-L82) |
| 2a | **String hardcode (emit)** | `'draft'` literal in dream_agent.py JSON + SQL | tests verify [dream_agent.py:208](../../../autoservice/dream_agent.py#L208) + [:219](../../../autoservice/dream_agent.py#L219) |
| 2b | **Value rejection (public update_status)** | public `update_status` raises `ProposalStateError` if `new_status == 'applied'` | no frame introspection; value-layer check; unit test |
| 3 | **Import cone** | `proposal_apply.py` ↔ dream modules isolated; only `proposal_apply.apply_proposal` imports `_mark_applied_internal` | AST-parse-based import test (not `sys.modules` snapshot) |
| 4 | **AST guardrail** (T4S.8) | Status-write string literals `'applied'`/`'accepted'` appear only in approved files; `INSERT INTO proposal_audit` in approved files only (C4) | CI-blocking AST walk test |

**What changed from v1.0**:
- **Dropped** frame inspection (`sys._getframe`) — reviewer C1 found it bypassable via `exec()`, symlinks, functools.partial
- **Added** Layer 2b: `update_status` does value-layer rejection of `'applied'` (no inspection needed)
- **Added** private `_mark_applied_internal` import-cone enforcement (Layer 3)
- **Added** C4 write-lock on `proposal_audit` INSERT to AST guardrail

Net: each layer is independent. Any single-layer failure is caught by at least one other layer. The stack moves enforcement from runtime (bypassable) to structural (import cone + AST) wherever possible.

## 4. "Don't Do" List (Critical)

1. **DON'T** add a `status` kwarg to `emit_proposal()` — signature-locked
2. **DON'T** call `emit_proposal()` from `apply_proposal()` — import cone forbids
3. **DON'T** write `status='applied'` outside `_mark_applied_internal` — AST test fails CI
4. **DON'T** `INSERT INTO proposal_audit` outside approved files — AST test fails CI (C4)
5. **DON'T** skip audit write in `apply_proposal` — audit is the trust story; audit must be in SAME transaction as status UPDATE
6. **DON'T** implement physical side-effects for handlers in M3 — `mark_applied` only
7. **DON'T** allow dream_agent to set proposal state via direct SQL — all status writes go through `update_status` or `_mark_applied_internal`
8. **DON'T** use `sys._getframe` for caller authorization — proven bypassable (reviewer C1); use import cone + value checks
9. **DON'T** SELECT-then-UPDATE for status transitions — use conditional UPDATE + rowcount (reviewer C2)
10. **DON'T** leave `'implemented'` as a valid status — M3 renames to `'applied'`; migration required on first boot (reviewer C3)
11. **DON'T** give master_dream_agent any write path beyond emit_proposal with locked draft
12. **DON'T** allow tenant_admin to apply a `platform_level` proposal — tier-0 ONLY; checked in `apply_proposal()` itself, not only HTTP layer (minor finding)

## 5. Open Questions (Defaults Applied)

| OQ | Default |
|---|---|
| OQ-E5-1 apply handler in M3 | `mark_applied` only (audit-first; physical apply → M4+) |
| OQ-E5-2 audit retention | indefinite (archival → M4+) |
| OQ-E5-3 platform-config mutation owner | defer to M4+ (apply handler stays no-op in M3) |

## 6. Test Requirements

### Mandatory (gate of T4S.1, T4S.8)

- `tests/dream_agent/test_emit_proposal_tool.py` — existing signature lock stays green
- `tests/dream_agent/test_apply_proposal.py` — pre-condition validation, **atomic conditional UPDATE race test** (C2: concurrent calls with 2 threads; exactly one transitions), idempotency, audit write in same transaction, admin role check, platform_level tier-0 check
- `tests/dream_agent/test_con04_guardrail.py` — AST walk asserting (a) `'applied'` string literal locations, (b) `INSERT INTO proposal_audit` literal locations (C4)
- `tests/dream_agent/test_apply_proposal_import_cone.py` — AST parse of `proposal_apply.py` imports: no `dream_agent`, no `master_dream_agent`; reverse also verified
- `tests/dream_agent/test_update_status_value_reject.py` — public `update_status(pid, 'applied')` raises `ProposalStateError` (C1: no frame inspection; pure value check)
- `tests/dream_agent/test_status_migration.py` — first-boot migration: rows with `status='implemented'` → `'applied'`; idempotent re-run
- `tests/dream_agent/test_master_routing.py` — DreamScheduler routes `_master` → master_dream_agent only

### Security / Negative tests

- Attempt `apply_proposal(status='applied')` — no such kwarg; fails
- Attempt direct SQL `UPDATE proposals SET status='applied'` from test — works in isolation (SQL is not sandboxed) BUT AST guardrail catches it in production code
- Attempt `apply_proposal` without admin_user_id — fails at signature
- Attempt `apply_proposal` on a draft proposal — raises `ProposalStateError`
- Attempt `apply_proposal` on a rejected proposal — raises `ProposalStateError`

## 7. Code Review Checklist (paste in T4S.1 commit body)

- [ ] `proposal_apply.py` has zero imports from `dream_agent.py` / `master_dream_agent.py` (verified by AST parse, not sys.modules snapshot)
- [ ] `apply_proposal()` signature has `admin_user_id` parameter (keyword-only)
- [ ] `apply_proposal()` pre-condition: atomic conditional UPDATE (not SELECT-then-UPDATE); same transaction as audit INSERT
- [ ] `apply_proposal()` platform_level tier-0 check done INSIDE the function (not only HTTP layer)
- [ ] Idempotent on already-applied proposals (no raise; returns `idempotent=True`)
- [ ] Concurrent `apply_proposal` on same pid: race test (2 threads; exactly 1 transitions, other idempotent)
- [ ] Public `update_status()` value-rejects `'applied'` (no frame inspection)
- [ ] Private `_mark_applied_internal` has no public export (`__all__` excludes it)
- [ ] Signature-lock test for `emit_proposal` still green
- [ ] AST guardrail test T4S.8 green — covers both `status='applied'` AND `INSERT INTO proposal_audit` literals
- [ ] `VALID_STATUSES` updated: `'implemented'` removed; migration runs on first boot
- [ ] No direct SQL `UPDATE proposals SET status=...` outside `update_status` / `_mark_applied_internal`

## 8. Revision Log

| Version | Date | Change |
|---|---|---|
| v1.0 | 2026-04-21 | Initial contract |
| v1.1 | 2026-04-21 | Addresses code-reviewer Critical findings C1 (drop frame inspection → import cone + value reject) + C2 (conditional UPDATE race-safe) + C3 (rename `implemented` → `applied` with migration) + C4 (write-lock `proposal_audit`). 5-layer defense (was 4). 12-item Don't-Do (was 7). Test suite extended. |
