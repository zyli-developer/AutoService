---
title: M3 Epic E5 · Dream Extension (platform-level + semi-auto apply)
status: draft
date: 2026-04-21
prd_refs: [docs/prd/AutoService-M3-PRD.md §2 E5, §1.3 non-goals]
stories: [E5.1, E5.2]
red_line: CON-04
security_critical: true
---

> **RED LINE — CON-04 (read before anything else)**
>
> `dream_agent.emit_proposal(...)` hard-codes `status='draft'` and has **no** `status` kwarg. Dream agents (per-tenant or platform-level) MAY NEVER write `status='accepted'` or `status='applied'` directly. Every transition out of `draft` is the platform admin's conscious act, routed through `ProposalPipeline.update_status` (approve / reject / implement) or the new `apply_proposal(pid, admin_user_id)` introduced here. **Any PR that adds a status kwarg to `emit_proposal`, mirrors its body without the hard-coded `"draft"` string, or has dream code call `apply_proposal` is rejected on sight.** See `autoservice/dream_agent.py:208,219` for the enforcement sites and `tests/dream_agent/test_emit_proposal_tool.py:71-82` for the signature lock.

---

## 1. Context & Problem Statement

M2 landed a per-tenant Dream agent (`autoservice/dream_agent.py`, `autoservice/dream_scheduler.py`) that observes one tenant's recent conversations + KB + peer souls, and emits `status='draft'` proposals for that tenant only. The review flow (`/approve`, `/reject`) already exists on the admin portal (`autoservice/api_routes.py:147-194`).

Two gaps remain for M3:

- **Cross-tenant blindness (E5.1).** No agent today looks at platform-wide signals — cc_pool utilisation, SLA breach distributions across tenants, skill reuse patterns, aggregate proposal counts — to propose platform-level changes (e.g. "the cc_pool `dream` sub-pool is starved at 15:00 UTC across 6/8 tenants; consider raising `pool_size` from 1 → 2"). Operators notice these ad-hoc; there is no durable, auditable record of the reasoning.
- **Review ≠ apply conflation (E5.2).** `/approve` currently does two separate things in a single click: (a) marks the proposal `accepted`, and (b) activates canary staging (see `api_routes.py:160-172` where `CanaryRouter.advance()` fires as a side effect). There is no audit trail on who approved, no second confirmation step before production-affecting change, and no dedicated "apply" act that can later be extended to category-specific handlers (skill patch, cc_pool policy tweak, …). The red line (CON-04) holds — nothing auto-applies — but the bookkeeping around the human-in-the-loop is thin.

Neither gap is a trust-killer yet — M2's Dream proposals are all draft, and the canary stage rollback exists — but both leave an audit hole that a real platform-admin workflow would trip over within weeks of live traffic. E5 closes both without weakening CON-04.

## 2. Current State — evidence map

| Concern | File | Lines | What it shows |
|---|---|---|---|
| `emit_proposal` locked status | `autoservice/dream_agent.py` | 129-140 | Function signature: `category, title, description, suggestion, evidence, risk_level, target_role`. **No `status` kwarg.** |
| `emit_proposal` hard-coded status (payload) | `autoservice/dream_agent.py` | 208 | `"status": "draft",  # red-line CON-04 — never overridable` |
| `emit_proposal` hard-coded status (column) | `autoservice/dream_agent.py` | 219 | `"draft",          # red-line CON-04 — status column hard-coded` |
| LLM tool schema excludes status | `autoservice/dream_agent.py` | 459-519 | Tool `emit_proposal` `input_schema` has no `status` property; `required` list is explicit. |
| Tool dispatcher passes loop's `tenant_id` | `autoservice/dream_agent.py` | 754-820 | `_execute_tool_call` threads `tenant_id` from loop (not LLM input); calls plain `emit_proposal` which cannot raise status. |
| Signature-lock test | `tests/dream_agent/test_emit_proposal_tool.py` | 71-82 | `assert "status" not in sig.parameters` — any future diff that adds a status kwarg fails CI. |
| Tenant resolution | `autoservice/dream_agent.py` | 56-83 | `_resolve_tenant_root`: sandbox first (`.autoservice/sandbox/<tid>/`), then `plugins/<tid>/`. |
| Scheduler enumerates `_master` | `autoservice/dream_scheduler.py` | 465-508 | `_discover_active_tenants` includes `_master` because it lives under `.autoservice/sandbox/` with an active `config.json`. Today it's run through the **same** per-tenant `run_dream` path as any other tenant. |
| Master tenant bootstrap | `autoservice/bootstrap.py`, `autoservice/master_tenant.py` | bootstrap:31; master_tenant: all | `MASTER_TENANT_ID = "_master"`; `_master` scaffold includes `souls/` (including a fallback `dream_soul.md`) + `kb/` + `config.json` (tier=0). |
| Proposal schema | `autoservice/proposal_pipeline.py` | 29-42 | Columns: `id, created_at, data, status, category, tenant_id`. Status default `'draft'`. No `applied` state in schema today. |
| Valid statuses | `autoservice/proposal_pipeline.py` | 92 | `VALID_STATUSES = {"draft", "accepted", "rejected", "implemented"}` — **no `applied`**. |
| `update_status` state machine | `autoservice/proposal_pipeline.py` | 358-376 | Accepts any target status in `VALID_STATUSES`; **does not enforce** source → target transitions (comment promises `draft → accepted/rejected, accepted → implemented` but code does not check). |
| `/approve` handler | `autoservice/api_routes.py` | 148-178 | `pp.update_status(pid, "accepted")` → if still stage 0, calls `router.advance()`. No `admin_user_id` extracted from session. No audit log. |
| `/reject` handler | `autoservice/api_routes.py` | 181-195 | `pp.update_status(pid, "rejected")`. No `admin_user_id`. No audit log. |
| Auth session table | `autoservice/auth.py` | 57-71, 116-140 | Has `admin_sessions` with `user_id`, `expires_at`, etc. `operator_session` cookie lands in E1.1 (`docs/prd/AutoService-M3-PRD.md §Epic E1`). |

Two derived truths from the map:

1. **The red line holds at three layers today**: function signature (no kwarg), JSON payload string (`"draft"`), SQL column string (`"draft"`). Plus a signature-lock test that blocks a regression diff.
2. **`update_status` is the only writer of non-draft statuses**; `emit_proposal` is the only writer of draft; nothing else `INSERT`s into the `proposals` table. E5.2 must preserve this invariant — `apply_proposal` will become the sole writer of a fourth state (`applied`).

## 3. Design — E5.1 Platform-level Dream agent

### 3.1 Where the code lives

New module: **`autoservice/master_dream_agent.py`**.

Chosen over "add a `master_mode: bool` flag to `dream_agent.py`" because:

- **CON-04 blast-radius isolation.** The existing `dream_agent.py` is red-line real estate with a 3-layer hard-coded guarantee (§2). A flag branch inside the same module means every future edit to master-side aggregation has to clear the red-line review. A separate module keeps the blast radius of master-side changes off the protected file.
- **Tool-call cross-pollination risk.** Per-tenant Dream's tool set is `{kb_search, list_souls, emit_proposal}` — all tenant-scoped. Master-side Dream needs a different tool set (cross-tenant signal readers; see §3.3). Merging tool schemas into one module invites an LLM at tenant-scope accidentally seeing a cross-tenant tool name in system context.
- **Import discipline.** `master_dream_agent.py` can `from autoservice.dream_agent import emit_proposal` (reuse) but cannot be imported by `dream_agent.py` (no reverse dependency). This gives a one-way cone.

### 3.2 Soul template

New file: **`.autoservice/sandbox/_master/souls/dream_soul.md`** (aggregator persona).

Content overrides `_FALLBACK_DREAM_SOUL` (see `autoservice/soul_generator.py`'s constant used at `dream_agent.py:574`) with aggregator-specific instructions:

- "You observe signals **across** tenants, not within one tenant."
- "You never reference a specific tenant's private data in your proposal text — only aggregate statistics."
- "Your proposals are platform-level (`category='platform_level'`): changes to cc_pool policy, default skill bundle, scheduler knobs, default rules."
- "Anti-pattern: never propose a change to a specific tenant's soul / skill (that's the per-tenant Dream's job)."

Resolution order is already correct: `_load_dream_soul` (`dream_agent.py:549-574`) looks under `.autoservice/sandbox/_master/souls/dream_soul.md` first, falls back to the constant if missing. The new file is created by the `_master` bootstrap (`master_tenant.py:_generate_internal_souls`) — we add one line to write the aggregator soul instead of the generic one when `tenant_id == MASTER_TENANT_ID`.

### 3.3 Signal sources

Master-side Dream reads (read-only; never writes platform state):

| Signal | Source | Access | Shape returned |
|---|---|---|---|
| cc_pool utilisation | `autoservice/cc_pool.py` stats surface | `cc_pool.get_stats()` — existing method (check / extend if not platform-wide) | `{pool: str, size: int, in_use: int, queue_depth: int, acquires_last_1h: int, starvation_events_last_1h: int}` |
| SLA breach counts | `autoservice/sla_aggregator.py` | `sla.get_breach_counts(window_hours=24)` | `{tenant_id: str, breach_count: int, p95_ms: float}` per tenant |
| Skill usage stats | Plugin tool-call telemetry (M2 metric plugin) | `metrics.skill_usage(window_hours=24)` | `{skill_id, tenant_id, invocations, error_rate}` |
| Dream proposal counts per tenant | `proposals` table | `SELECT tenant_id, status, COUNT(*) FROM proposals WHERE created_at > ? GROUP BY tenant_id, status` | `{tenant_id: str, draft: int, accepted: int, rejected: int, implemented: int}` |
| Per-tenant complaint / CSAT | `autoservice/billing_metrics.py` | `billing_metrics.csat_by_tenant(window_hours=168)` | `{tenant_id, csat_avg, complaint_count}` |

These are exposed as a **new tool set** in `master_dream_agent.py`:

- `platform_signals_summary()` → dict of the above, one call produces the whole snapshot (keeps LLM turns low)
- `proposal_history(category=None, status=None, limit=20)` → recent platform-level proposals (own history, not per-tenant)
- `emit_proposal(category='platform_level', ...)` — **reused directly from `autoservice.dream_agent`** (see §3.5)

Notably **absent**: no `kb_search` (a platform aggregator reading one tenant's KB is a cross-tenant leak vector); no `list_souls` (master-side Dream does not touch tenant souls — CON-04 / the tenant-boundary principle). It only sees aggregated numbers plus its own historical proposals.

### 3.4 Signal ingestion contract — cross-tenant boundary

Master-side Dream is the **only** platform-level reader of cross-tenant data. Rules:

1. All signal fetchers return **aggregate-only** data (counts, averages, percentiles) unless the field is explicitly a tenant_id (needed for routing the proposal). Raw conversation turns, KB text, soul text, proposal bodies — never.
2. Signal fetchers run under the `_master` tenant's scheduler slot; they do not touch the `kb_search` or `list_souls` tools (those are tenant-scoped and would blur the boundary).
3. Access is mediated by a thin read-only view module `autoservice/platform_signals.py` (new) — a namespace that exposes the five fetchers above and nothing else. `master_dream_agent.py` imports this module; per-tenant `dream_agent.py` does not import it (enforced by a lint check + code review).
4. A tenant-scoped proposal (`category != 'platform_level'`) emitted from `master_dream_agent.py` is a bug; the tool wrapper in §3.5 enforces `category='platform_level'` at dispatch time.

### 3.5 Proposal emission — reuse, don't mirror

Master-side Dream calls **the same `emit_proposal` function** from `autoservice.dream_agent`:

```
from autoservice.dream_agent import emit_proposal  # the only permitted import
```

**Reuse over mirror, justified.** Mirroring — copying the body into `master_dream_agent.py` — risks drift: a future security patch to the original (e.g. tightening validation) would not propagate, and CON-04's 3-layer hard-code becomes 6-layer hard-code spread across two files. Reuse also means the signature-lock test (`test_emit_proposal_signature_has_no_status_kwarg`) already covers the master path.

`master_dream_agent.py`'s wrapper over `emit_proposal`:

- Passes `tenant_id="_master"` (always — never another tenant's id).
- Passes `category="platform_level"` (enforced; rejects LLM attempts to use any other category).
- Passes `target_role` from a **master-specific whitelist** (`{"cc_pool_policy", "scheduler", "rules_default", "platform"}`) — not `AGENT_ROLES` (those are per-tenant agent roles and meaningless at platform level). To support this, `emit_proposal` either (a) accepts `target_role` from a broader whitelist parameterised at call site, or (b) we extend `AGENT_ROLES` in `soul_generator.py` to include platform-level targets. **Option (b) is chosen** — smaller surface, keeps `emit_proposal`'s contract frozen.

**Not chosen:** branching `emit_proposal` on `tenant_id == "_master"` to relax validation. That would put a tenant-id comparison inside the red-line function and invite "for `_master` we can ... " arguments. Instead, we grow `AGENT_ROLES` once, then every caller lives under the same validator.

### 3.6 New proposal category — `platform_level`

Schema migration (additive, backwards-compatible):

- **No column change** — `category` is already free-form TEXT (`proposal_pipeline.py:29-42`).
- **`VALID_CATEGORIES` extension in `proposal_pipeline.py:90`** — add `"platform_level"` to the set. Existing filters + the analyzer's post-validation (`_llm_analyzer`) won't reject it.
- **Admin portal filter** — add a "Platform" tab alongside existing tenant tabs (implementation lives in the admin-portal SPA; surface here as a follow-up task in M3's E5 batch).

### 3.7 DreamScheduler routing

Change to `autoservice/dream_scheduler.py` (around line 510, `_read_tenant_dream_cfg` / the run dispatch site — exact line depends on current head):

```python
# pseudocode — not production code
if tenant_id == MASTER_TENANT_ID:
    await master_dream_agent.run_master_dream(
        cc_pool=..., proposals_db=..., runs_db=..., signals=platform_signals,
    )
else:
    await dream_agent.run_dream(tenant_id, cc_pool, ..., runs_db=...)
```

The branch is narrow: one if-check, two call sites, same surrounding try/except / dream_runs lifecycle. Per-tenant path is untouched.

### 3.8 Alternatives considered and rejected

| Alternative | Reason rejected |
|---|---|
| Single `dream_agent.py` with `master_mode: bool` flag | Puts cross-tenant signal-fetch code inside the red-line module; widens the review surface for every CON-04-sensitive edit. |
| Mirror `emit_proposal` body into `master_dream_agent.py` | CON-04 drift risk; signature-lock test no longer covers the mirror. (§3.5) |
| Event-bus subscription instead of polling signal summaries | Premature — no event bus exists; DreamScheduler's existing tick cadence (tens of minutes) is enough for platform-level signals. Parking lot item, not M3. |
| Master Dream writes tenant-scoped proposals | Violates the cross-tenant boundary (§3.4). Per-tenant Dream is the authority for tenant-scoped proposals. |
| Master Dream auto-applies platform proposals below risk threshold | **REJECTED — direct CON-04 red-line extension.** See §5. |

## 4. Design — E5.2 Semi-automatic apply

### 4.1 Where the code lives

New module: **`autoservice/proposal_apply.py`**.

Chosen over "extend `proposal_pipeline.py`":

- `proposal_pipeline.py` is the Dream Engine core (proposal creation + status update); putting a *category-dispatched apply handler registry* there blurs two concerns (propose vs. apply).
- Locating `apply_proposal` in its own module makes the "apply is the one writer of `status='applied'`" invariant reviewable at a glance — the whole file is about one operation.
- Category-specific apply handlers (§4.7) live alongside it naturally.

Chosen over "extend `dream_agent.py`":

- **Hard rule.** `dream_agent.py` must not gain any writer of non-draft status. Including a call-site inside `dream_agent.py` (even indirect) blurs the red line. `apply_proposal` does not belong in the same module as the Dream code paths.

### 4.2 Public surface

```
# File: autoservice/proposal_apply.py  (NEW)

@dataclass
class ApplyResult:
    proposal_id: str
    status_before: str          # what we saw when entering (for idempotency)
    status_after: str           # "applied" on success, unchanged on no-op
    applied_at: str | None      # ISO-8601 UTC; None when no-op / error
    admin_user_id: str
    handler: str | None         # name of the apply handler used, or None if no-op
    error: str | None           # populated only on hard errors (bad state)

def apply_proposal(
    pid: str,
    admin_user_id: str,
    *,
    proposals_db: sqlite3.Connection,
    audit_db: sqlite3.Connection,
    clock: Callable[[], datetime] = datetime_utcnow,
) -> ApplyResult:
    ...
```

### 4.3 Pre-condition & idempotency

```
1. proposal = load(pid)
2. if proposal is None: raise ProposalNotFound(pid)
3. if proposal.status == 'applied':
       # IDEMPOTENT no-op (NOT an error); re-reading is safe.
       return ApplyResult(..., status_before='applied', status_after='applied',
                          applied_at=<original>, handler=None, error=None)
4. if proposal.status != 'accepted':
       raise ApplyPreconditionError(
           f"apply requires status='accepted', saw {proposal.status!r}"
       )
5. handler = _HANDLERS.get(proposal.category)   # may be None → generic mark-applied path
6. result = handler.run(proposal) if handler else _default_apply(proposal)
7. tx:
       UPDATE proposals SET status='applied', data=<payload with status=applied>
           WHERE id=pid AND status='accepted'    # SQL-level race guard
       INSERT INTO proposal_audit (...)
8. return ApplyResult(status_after='applied', ...)
```

Notes on idempotency: the `AND status='accepted'` in step 7's `UPDATE` is what makes concurrent apply calls safe — the second caller sees rowcount 0, treats as "someone else applied", re-loads, and returns the idempotent no-op.

### 4.4 State machine extension

Current (per `proposal_pipeline.py:92` + docstring at 358-376):

```
VALID_STATUSES = {draft, accepted, rejected, implemented}
transitions (docstring):  draft → accepted | rejected
                          accepted → implemented
```

**Note:** the existing `update_status` **does not enforce** these transitions (any target in `VALID_STATUSES` is accepted). E5.2 ships alongside a tightening: `update_status` gains a transition table and rejects illegal source→target pairs. Without this tightening, apply-proposal's pre-condition can be bypassed by `update_status(pid, 'applied')` through a direct call.

Updated transition table:

```
draft     → accepted   (via /approve)
draft     → rejected   (via /reject)
accepted  → applied    (via apply_proposal ONLY)
accepted  → rejected   (allowed — reviewer changes mind before apply)
applied   → (terminal — no further transitions)
rejected  → (terminal)
```

`implemented` is retained as a historical alias for "applied and visible in production" — M3 treats `applied` as the new canonical name; `implemented` stays readable but no code writes it going forward. (Alternative: rename `implemented` → `applied` with a migration. Rejected — rename requires updating every existing row + admin portal filter; additive is lower-risk.)

Schema change: extend `VALID_STATUSES` to include `"applied"`. No column change, no migration (TEXT column).

### 4.5 Admin identity extraction

`apply_proposal(pid, admin_user_id)` does not know how to extract identity itself — that's the endpoint's job. Contract with the endpoint:

1. Request arrives at `POST /api/admin/proposals/<id>/apply` with an `admin_session` cookie.
2. Middleware (`autoservice/auth.py` lookup on `admin_sessions`) resolves the cookie to a `user_id` and a `tier` (0 = platform admin, 1 = tenant admin).
3. Endpoint checks authorisation:
   - **Platform-level proposal** (`category == 'platform_level'`) → requires `tier == 0`.
   - **Tenant-scoped proposal** (`tenant_id != "_master"`) → requires either `tier == 0` OR (`tier == 1` AND `session.tenant_id == proposal.tenant_id`).
4. On auth failure → HTTP 403, no DB write, no audit row.
5. On auth success → endpoint calls `apply_proposal(pid, admin_user_id=session.user_id, ...)`.

`apply_proposal` itself does not call `auth.py` — it trusts the caller. This keeps the function pure and easily unit-testable (pass a fake `admin_user_id` string). The *endpoint* is the trust boundary.

### 4.6 Audit log

New table `proposal_audit`:

```sql
CREATE TABLE IF NOT EXISTS proposal_audit (
    audit_id       TEXT PRIMARY KEY,          -- audit_<hex12>
    proposal_id    TEXT NOT NULL,
    admin_user_id  TEXT NOT NULL,
    action         TEXT NOT NULL CHECK(action IN ('approve','reject','apply')),
    timestamp      TEXT NOT NULL,             -- ISO-8601 UTC
    session_id     TEXT,                      -- admin_session row id at action time
    payload        TEXT                       -- optional JSON with handler name, error, etc.
);
CREATE INDEX IF NOT EXISTS idx_audit_proposal ON proposal_audit(proposal_id);
CREATE INDEX IF NOT EXISTS idx_audit_admin    ON proposal_audit(admin_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_ts       ON proposal_audit(timestamp);
```

All three admin-driven transitions write audit rows — `/approve` and `/reject` are retrofitted here (they currently write none; §2 evidence). `apply_proposal` writes in the same transaction as the `UPDATE proposals`.

### 4.7 Apply handlers — category → handler registry

"What does 'applied' physically do?" is proposal-type-dependent. Registry shape:

```python
# File: autoservice/proposal_apply.py

class ApplyHandler(Protocol):
    def run(self, proposal: dict) -> dict: ...   # returns handler metadata

_HANDLERS: dict[str, ApplyHandler] = {}

def register_handler(category: str, handler: ApplyHandler) -> None:
    _HANDLERS[category] = handler
```

M3 ships with these handlers (one per category currently in `VALID_CATEGORIES` plus `platform_level`):

| Category | Handler effect (M3 scope) | Physical change |
|---|---|---|
| `response_quality` | `mark_applied` (no-op apply) | Row status → `applied`; the proposal becomes visible in "applied history" tab. Actual skill change is still manual. |
| `workflow` | `mark_applied` | Same — workflow changes need human editing of skill files; apply here records the decision. |
| `knowledge_gap` | `mark_applied` | Same — KB authoring is outside the apply flow. |
| `tone` | `mark_applied` | Same as above. |
| `platform_level` | `mark_applied` | Same; the *effect* (e.g. change `cc_pool.dream_size`) is a separate ops change — apply records the approval of the recommendation. |

In other words, **M3's apply is audit-first** — every handler is `mark_applied` plus audit-row insert. Category-specific physical effects (auto-patch a skill file, write to a config store) are open questions (§7) and land post-M3 as new handlers registered behind the same `apply_proposal` call. This keeps M3 scope tight while opening the extension point.

### 4.8 Admin-portal UI

On the proposal detail page:

- **Approve** button (existing) — enabled when `status == 'draft'`; fires `/approve` → `status='accepted'`.
- **Apply** button (new) — enabled **only** when `status == 'accepted'`; fires `/api/admin/proposals/<id>/apply` → `status='applied'`.
- **Reject** button — enabled when `status in ('draft','accepted')`; tightened from the current implementation (today it's always enabled). Matches the new transition table (§4.4).
- **Applied by** metadata (new) — once applied, display `admin_user_id` + `applied_at` pulled from the audit row. Makes the "who pushed this live" question one glance answerable.

Visual separation is deliberate — two clicks for two decisions (review + apply), and a user with tenant_admin tier on a platform-level proposal sees Apply **disabled with tooltip** ("Platform admin required"), not hidden — better error mode.

### 4.9 New endpoint

```
POST /api/admin/proposals/{pid}/apply
Headers:  cookie: admin_session=...
Body:     (empty)
Responses:
  200 OK          { "proposal_id": "...", "status": "applied",
                    "applied_at": "...", "admin_user_id": "...",
                    "handler": "mark_applied" }
  200 OK (noop)   same payload, applied_at = original (idempotent re-apply)
  400 Bad Request { "error": "apply requires status='accepted'", "current_status": "draft" }
  403 Forbidden   { "error": "platform admin required" | "wrong tenant" }
  404 Not Found   { "error": "proposal not found" }
```

The 200-on-noop choice (vs 409 Conflict) is deliberate — the client retrying a flaky network request should see the same body as the first success. The body includes the original `applied_at` so the client can detect "this wasn't my call" if needed.

### 4.10 Alternatives considered and rejected

| Alternative | Reason rejected |
|---|---|
| Fold apply into `/approve` (one click) | Conflates review with apply; loses the two-step audit trail that's the entire point of E5.2. |
| Auto-apply on low-risk (`risk_level='low'`) | **REJECTED — CON-04 extension.** Any path from "Dream emits draft" to "platform state changes" without an explicit admin click is the red line. |
| Put `apply_proposal` inside `dream_agent.py` | Red-line module; writing non-draft status from there is a review trap. (§4.1) |
| Put `apply_proposal` inside `proposal_pipeline.py` | Separation of concerns + invariant reviewability. (§4.1) |
| Reuse `implemented` as "applied" without a new state | Works, but the admin-portal UX distinction between "review-approved" and "actually applied" gets lost; state names matter for audit clarity. |

## 5. Cross-cutting — RED-LINE guardrails

This section is the code-reviewer's checklist for any E5 PR.

### 5.1 Invariants (must hold after E5 lands)

1. `dream_agent.emit_proposal` signature remains unchanged — no `status` kwarg.
2. All `INSERT INTO proposals (..., status, ...)` writes status `'draft'`. Inserts from outside `emit_proposal` are forbidden.
3. All `UPDATE proposals SET status=...` where target is `'accepted'` live in `ProposalPipeline.update_status` (routed from `/approve`).
4. All `UPDATE proposals SET status=...` where target is `'rejected'` live in `ProposalPipeline.update_status` (routed from `/reject`).
5. All `UPDATE proposals SET status=...` where target is `'applied'` live **only** in `apply_proposal` in `autoservice/proposal_apply.py`.
6. `master_dream_agent.py` does not import `apply_proposal` or reference `proposal_apply`. One-way cone.
7. `apply_proposal` does not import `dream_agent` and does not reference `emit_proposal`. One-way cone, other direction.
8. Every transition out of `draft` produces one `proposal_audit` row.

### 5.2 Mechanical guards

- **Signature lock (existing, retain).** `tests/dream_agent/test_emit_proposal_tool.py::test_emit_proposal_signature_has_no_status_kwarg`.
- **New signature lock.** `tests/proposal_apply/test_apply_proposal_signature.py::test_apply_proposal_requires_admin_user_id` — verifies `admin_user_id` is a required positional / keyword parameter on `apply_proposal`.
- **New pre-condition test.** `tests/proposal_apply/test_apply_proposal_rejects_non_accepted_status` — parametrised over `{'draft', 'rejected', 'implemented', 'applied' (idempotent)}`; all but the last raise `ApplyPreconditionError`; the last is the idempotent no-op.
- **Grep-based invariant test.** `tests/guardrails/test_status_writer_locations.py` — static check: across the repo, only `proposal_apply.py` contains the string `"applied"` inside an `UPDATE proposals` context; only `proposal_pipeline.py` contains `"accepted"` / `"rejected"` in that context. Implemented as an AST walk in tests/ to avoid false positives from comments.
- **Schema-level guard (optional — defer if it slows migrations).** A DB trigger `BEFORE UPDATE ON proposals FOR EACH ROW WHEN NEW.status IN ('accepted','applied')` that raises if the calling code path signals it came from `dream_agent.*`. Rejected as primary guard (Python-level fakes can't trigger it; also raises complexity) — kept as parking-lot item for a defence-in-depth follow-up.

### 5.3 Code-review tier

Per `docs/plans/m3/2026-04-21-gap-analysis.yaml.red_line_verification.guardrails_for_e5_2`, E5.2 tasks are **Yellow-tier** and require a superpowers:code-reviewer subagent pass **before** the Closing step in `{plans_dir}/cc-prompt-templates.md §5`. Reviewer verdict must be quoted in the commit body.

E5.1 tasks that touch `master_dream_agent.py` or `platform_signals.py` are **Yellow** for the same reason — anything near the red line is Yellow until proven otherwise.

## 6. Test Strategy

### 6.1 Unit

- `apply_proposal` happy path: accepted → applied + audit row + rowcount=1.
- Pre-condition: `draft`, `rejected`, `implemented` → `ApplyPreconditionError`, no DB change, no audit row.
- Idempotency: already-`applied` → returns original `applied_at`, no new audit row.
- Race: concurrent apply (two calls with same pid) — one wins (rowcount=1), one no-ops (rowcount=0). Tested with two connections + threads.
- Handler registry: unknown category → `mark_applied` default handler; known category → registered handler called; handler raises → transaction rolled back, no partial audit.
- Master Dream signal wrapper: `platform_signals_summary()` returns aggregate-only shape; tenant-scoped fields limited to `tenant_id` + counts.
- Master Dream emit wrapper: rejects non-`platform_level` category; passes `tenant_id="_master"` to the underlying `emit_proposal`.

### 6.2 Security — negative tests

- **Dream bypass attempt.** Write a mock LLM that returns a tool_use trying `emit_proposal` with extra `status` field. Assert: `_execute_tool_call` strips it (it does today — see `dream_agent.py:787-800`, tool_input is enumerated field-by-field); the persisted row is still `'draft'`.
- **Direct SQL bypass attempt.** Test scans `autoservice/` for `UPDATE proposals SET status='applied'` outside `proposal_apply.py` → must return zero matches.
- **Non-admin session.** Endpoint test: unauthenticated request → 401/403 (auth middleware); session with no admin role → 403; no DB write, no audit row.
- **Cross-tenant tier_1 apply.** Tenant admin for tenant A tries to apply a proposal with `tenant_id='B'` → 403.
- **Tier_1 apply on platform_level.** Tenant admin tries to apply a `platform_level` proposal → 403 (platform admin required).
- **`update_status` tightening.** Call `update_status(pid, 'applied')` directly → raises (new transition-table enforcement).

### 6.3 Integration

- End-to-end approve → apply flow: seed draft → `/approve` → status=accepted + audit row (action='approve') → `/apply` → status=applied + audit row (action='apply') → verify both rows' `admin_user_id` match session.
- Master Dream run: stubbed LLM calls `platform_signals_summary` then `emit_proposal(category='platform_level', ...)` → row persists with `tenant_id='_master'`, `category='platform_level'`, `status='draft'`.
- DreamScheduler routing: `_master` tick dispatches to `master_dream_agent.run_master_dream`; other tenants still go through `dream_agent.run_dream`.

### 6.4 Regression

- Existing `/approve` + `/reject` still work end-to-end. (New audit-row write is additive — old clients that ignore audit still see the same status transitions.)
- `test_emit_proposal_signature_has_no_status_kwarg` still passes. (No change to `emit_proposal`.)
- Per-tenant Dream still emits `status='draft'` proposals for its own tenant; nothing in `master_dream_agent.py` mutates the per-tenant path.

## 7. Open Questions

1. **What does "apply" physically do for each proposal category?** M3 ships `mark_applied` for all — pure audit-first. Post-M3: should `category='workflow'` trigger a skill-file patch? Should `platform_level` with `target_role='cc_pool_policy'` call into `cc_pool` to change pool sizes at runtime? The handler registry is the extension point; the **content** of handlers beyond `mark_applied` is an open product question for the platform-admin experience review.
2. **`proposal_audit` retention policy.** Indefinite (never delete)? 1-year with monthly partitioning? Tie to billing cycle? Security-critical records argue for indefinite; DB size argues for periodic archive. Defer to Epic E6 (GC) scope.
3. **Post-apply notifications.** Should `apply_proposal` trigger a notification — to the tenant admin (if the proposal is tenant-scoped and was applied by a platform admin), or to the platform admin's team (all apply actions)? Current design emits an event to `web_gateway` for the admin-portal to update; broader notification is an open question.
4. **Master Dream's cross-tenant data access — read only, or can it write some platform config?** Design says read-only (§3.4). But if a `platform_level` proposal is applied and the handler is "raise `cc_pool.dream_size` by 1", then *somewhere* a writer exists — just not in Dream. Question: which module owns runtime platform config mutation? Candidate: `autoservice/cc_pool.py` + an admin endpoint, called from an apply handler. This is the frontier between E5 and E6 (ops).
5. **Should `implemented` be renamed to `applied` with a migration** (vs. the additive approach chosen here)? Low priority; audit clarity is already preserved by the new state. Parking-lot.

## 8. Non-goals

- **Any form of dream auto-apply** (per CON-04 and PRD §1.3 "Dream 任何'自动 accepted'变体 — 永不"). Including "risk_level=low auto-accept", "risk_level=low auto-apply", scheduled delayed apply, or retry-after-N-days-of-dormancy. All rejected on sight.
- **Cross-tenant learning** — master Dream observes aggregate signals; it does not move learned behaviour from tenant A into tenant B's soul / skill. Per PRD §1.3.
- **Distributed consensus on proposal application** — apply is single-admin, single-cluster. No quorum, no multi-region coordination.
- **Automatic rollback of an applied proposal** — rollback exists at the canary layer (`CanaryRouter`, unrelated to apply). Proposal state has no `rolled_back` state in M3.
- **Renaming or deleting `implemented` state.** (§4.4) Additive only.
- **Trigger-based schema enforcement of the red line.** (§5.2) Python-level tests + signature locks + reviewer discipline are the guard; DB triggers are parking-lot.

---

## Appendix A — File change summary

| File | Change | Category |
|---|---|---|
| `autoservice/master_dream_agent.py` | **NEW** — master-side Dream loop, tool schemas, run entry. | code |
| `autoservice/platform_signals.py` | **NEW** — read-only cross-tenant signal fetchers. | code |
| `autoservice/proposal_apply.py` | **NEW** — `apply_proposal` + `ApplyResult` + handler registry. | code |
| `autoservice/proposal_pipeline.py` | Extend `VALID_STATUSES` (add `applied`); extend `VALID_CATEGORIES` (add `platform_level`); tighten `update_status` transition table. | edit |
| `autoservice/soul_generator.py` | Extend `AGENT_ROLES` with platform-level targets (for master Dream's `target_role` validation). | edit |
| `autoservice/api_routes.py` | Add `/api/admin/proposals/{pid}/apply`; retrofit audit-row writes on `/approve` + `/reject`. | edit |
| `autoservice/dream_scheduler.py` | `_master` routes to `master_dream_agent.run_master_dream`; others unchanged. | edit |
| `autoservice/master_tenant.py` | Write aggregator `dream_soul.md` instead of generic fallback when bootstrapping `_master`. | edit |
| `.autoservice/sandbox/_master/souls/dream_soul.md` | **NEW** — aggregator persona text. | data |
| `autoservice/auth.py` (schema) | Add `proposal_audit` table definition + migration helper. | edit |
| `tests/proposal_apply/*.py` | **NEW** test suite — pre-condition, idempotency, audit, race, signature lock. | test |
| `tests/guardrails/test_status_writer_locations.py` | **NEW** — AST-walk invariant test for status-writer locations. | test |
| `tests/master_dream_agent/*.py` | **NEW** — signal wrapper, emit wrapper, scheduler routing. | test |
| `tests/dream_agent/test_emit_proposal_tool.py` | No change — existing signature lock retained. | test |

## Appendix B — Task breakdown hint (for /task-gen consumption)

1. **T-E5-1** Extend `VALID_STATUSES` + `VALID_CATEGORIES` + tighten `update_status` transitions; regression tests. (Green, small)
2. **T-E5-2** Audit table schema + `/approve` + `/reject` audit-row retrofit. (Green, small)
3. **T-E5-3** `proposal_apply.py` module + `ApplyResult` + default `mark_applied` handler + unit tests. (Yellow, medium — touches state writer)
4. **T-E5-4** `/api/admin/proposals/{pid}/apply` endpoint + auth checks + integration tests. (Yellow, medium)
5. **T-E5-5** Admin-portal UI: Apply button, tooltip, applied-by metadata. (Green, small)
6. **T-E5-6** `platform_signals.py` read-only fetchers + unit tests. (Green, medium)
7. **T-E5-7** `master_dream_agent.py` + aggregator soul + scheduler branch. (Yellow, medium — touches dream surface)
8. **T-E5-8** Guardrail test suite (`tests/guardrails/`) + AST-walk invariants. (Yellow, small — red-line enforcement)

Yellow tasks (T-E5-3, T-E5-4, T-E5-7, T-E5-8) route through `{plans_dir}/cc-prompt-templates.md §5` — superpowers:code-reviewer subagent verdict quoted in commit body before Closing.
