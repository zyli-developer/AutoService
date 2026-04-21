# Eval: T7B.6 — `/api/management/chat` → `_master` routing

**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §2.7 "A 的 ManagementChat 接入 `_master`"
**Task**: T7B.6 · Phase 7 · Green · batch-14 (parallel with T7S.5 in `tests/fork_runtime/`)
**Producer**: main orchestrator (no reviewer; Green task)
**Related**: eval-doc-015 (T7B.1/T7B.2 TenantContext + tenant_root — fork-runtime foundations) · eval-doc-014 (T6F.6 `/api/admin/chat` — symmetric `_local_admin` endpoint stub that this task mirrors on the master side)

## 预期行为

### Endpoint contract

`POST /api/management/chat` — master-deployment admin conversational endpoint (spec §2.7: "A 的 ManagementChat 接入 `_master`").

**Request body** (JSON): `{"message": <str>}`.

**Response** (200):
```json
{"reply": "<LLM reply string>"}
```

**Error shapes**:
| Status | Body | Condition |
|--------|------|-----------|
| 422 | `{"error": "message required"}` | `message` missing, empty after strip, or not a `str` |
| 503 | `{"error": "cc_pool unavailable (POOL_MODE disabled?)"}` | `cc_pool.get_pool()` returns falsy (tests / POOL_MODE off) |

### Backend pipeline — M1 stub → M2 real routing

M1 shipped `POST /api/management/chat` (module `autoservice/api_routes.py`, lines ~893+) as a **slash-command dispatcher + Dream-Engine config dialog**: the text body was parsed for `/rules`, `/status`, `/approve`, `/reject`, `/rollback`, `@Dream Engine`, or otherwise fell through to a hardcoded "我是 Dream Engine" stub reply. There was **no LLM call**. Tenant identity was a query-string default of `"default"`.

M2 per spec §2.7 flips this: the endpoint now routes the message through the real `cc_pool` with `tenant_id="_master"`. The platform admin A is literally chatting with the `_master` tenant's customer agent (which has the admin-tool persona once M3 wires the tools).

The old path **remains reachable under a new endpoint**: we rename the M1 dispatcher to `/api/management/chat-legacy` (in-file, below the new endpoint) so any M1-era integration tests that still hit slash-commands can update their URL. At M3 the legacy endpoint will be deleted once the `_master` agent's tool-use is verified. This rename is **additive** — no route is silently removed under a caller's feet.

The new endpoint:

1. Read JSON body → `message: str`.
2. 422 on missing / empty / wrong-type `message` (tested explicitly — not pydantic's default).
3. `pool = await cc_pool.get_pool()` — the module-level singleton (spec §2.7 ties `_master` to the same pool A uses; dream runs use a separate `_dream_pool`).
4. If `pool` is None / not started → 503 `{"error": "cc_pool unavailable …"}`. This is the test-injected path (monkeypatch `get_pool` → None) and also the POOL_MODE-off production path.
5. `async with pool.acquire(role="customer", tenant_id="_master") as instance:` — per spec §2.7 line "路由到 `cc_pool.acquire(role="customer", tenant_id="_master")`".
   - **Note on `tenant_id` for `role="customer"`**: today's `CCPool.acquire` (T3B.5, `autoservice/cc_pool.py:393-444`) passes `tenant_id` through only for `role="dream"`; the customer path calls `super().acquire(timeout=timeout)` and silently ignores `tenant_id`. **We still pass `tenant_id="_master"` explicitly** because (a) it is spec-mandated and forward-compatible: when the soul/tool injection for customer role lands (M3+), this call site will already be correct; (b) mock-based tests assert the exact kwargs, pinning the contract.
6. `await instance.client.query(message)` then collect text from `instance.client.receive_response()` — same pattern as `CCPool.query` (cc_pool.py:359-366).
7. Return `{"reply": collected_text}`.

### Admin-tool set (spec §2.7 future work — deferred)

Spec §2.7 lists an admin tool set the `_master` customer agent will eventually wield:
- `list_tenants()`
- `read_proposals(tenant_id?, status?)`
- `approve_proposal(id)` / `reject_proposal(id)`
- `trigger_dream(tenant_id)`
- `publish_sandbox(tenant_id)`
- `read_wizard_state(tenant_id)`

**M2 decision — DO NOT wire these in T7B.6.** Rationale:
- Spec §2.7 is silent on whether tools ship with the route-swap or as a follow-up.
- The tools are cross-cutting (touch `proposal_pipeline`, `dream_runs`, `wizard_state_log`) and adding six MCP tools mid-batch risks scope creep and widens the test surface well beyond "green" sizing.
- M1 `/api/admin/chat` symmetric stub (T6F.6) landed the same way — route first, tools later — so we stay consistent.

Flagged as future work below and in the repo's `docs/plans/m2/task-status.md` narrative; new task ID will be filed for M3.

### What stays out of scope

- `DreamConfigSession` dialog handling, `/rules` / `/status` / `/approve` / `/reject` / `/rollback` slash commands — moved to `/api/management/chat-legacy`.
- Inline widget mechanism (`proposal-card` / `metric` / `action-launch`) referenced in spec §2.7 — depends on the tool set.
- `_master` dream self-iteration (spec §2.7 bullet 4) — the dream loop is already landed in T3B.5/T3B.6/T4B.1; running it on `_master` just requires dream trigger on the right `tenant_id`, which is a deployment concern.

## 验收标准

### Tests in `tests/api/test_management_chat.py` (6 cases)

Follows the `tests/api/test_dream_api.py` pattern (TestClient, monkeypatch for pool isolation, fixture-built app). Mocks `cc_pool.get_pool` and the returned pool's `acquire` context manager to intercept the call — **no real Claude subprocess is spawned**.

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_management_chat_valid_message_returns_reply` | POST `{"message": "hi"}` → 200 + `{"reply": "mocked reply"}` |
| 2 | `test_management_chat_empty_message_returns_422` | POST `{"message": "  "}` → 422 `{"error": "message required"}`, pool never touched |
| 3 | `test_management_chat_missing_field_returns_422` | POST `{}` → 422, pool never touched |
| 4 | `test_management_chat_routes_to_master_not_null_tenant` | Assert `pool.acquire(...)` called with `role="customer"`, `tenant_id="_master"` — never `None`, never `"default"` |
| 5 | `test_management_chat_pool_unavailable_returns_503` | monkeypatch `get_pool` → `None` → 503, body has `cc_pool unavailable` |
| 6 | `test_management_chat_regression_no_stub_llm` | Grep-style regression guard: the new endpoint's source does **not** mention `DreamConfigSession`, `/approve`, `/rollback`, `@Dream Engine`, `Dream Engine 通用回复`, or any M1 stub reply string. Protects against an accidental merge back to the slash-command dispatcher. |

### Pre-existing tests preserved

- `tests/api/test_dream_api.py`, `tests/api/test_master_tenants.py`, `tests/api/test_session_mode.py`, `tests/api/test_rehearsal_review_persists.py` — all continue to pass. These do not exercise `/api/management/chat`; renaming the M1 handler to `-legacy` does not break them.
- `tests/auth/`, `tests/cc_pool/`, `tests/dream_agent/`, `tests/bootstrap/` — no overlap with the edited code paths; pytest regression suite confirms zero new failures.

## 关键 invariant

- **No stub LLM fallback** (spec §9 risk mitigation) — the new endpoint has **exactly one** success path: mock-or-real cc_pool → `query()` → `{"reply": ...}`. No `if DREAM_CONFIG_SESSION:`, no `return "我是 Dream Engine ..."`, no hardcoded "(stub)" prefix. Test #6 is the standing regression guard.
- **Spec-exact acquire signature** — `role="customer", tenant_id="_master"`. Not `role="dream"` (that's the nightly loop, spec §2.5). Not `tenant_id=None` (would fall back to bootstrap default — master deployment has `_master` seeded by `bootstrap.ensure_master_tenant`, T1B.*). Test #4 pins this.
- **503 on missing pool, not 500** — distinguishes "infra not ready" from "bug in handler". POOL_MODE toggles cc_pool off in low-resource dev environments; we must not 500 there.
- **422 with explicit error string** — matches sibling admin endpoints (`/api/dream/trigger`, `/api/admin/chat`) which all return `{"error": "<reason>"}` for 422 rather than pydantic's `{"detail": [...]}` shape. Consistent error envelope for the admin-portal to render.
- **Back-compat via rename, not delete** — `/api/management/chat-legacy` keeps M1 slash commands reachable. At M3 it disappears; announcing it at M2 gives integrations a one-milestone deprecation window.
- **Tenant id normalization** — `"_master"` is the sole accepted value at this endpoint. We do **not** accept `tenant_id` in the request body (spec §2.7 pins it server-side). Admin-portal selects which tenant to preview via `/t/<tid>/*` routing, not via this endpoint's body.

## Spec decisions recorded

- **Admin tool set deferred** — see "What stays out of scope" above. Filed as follow-up for M3.
- **Legacy dispatcher rename** — not explicitly called out in spec §2.7 but implied (M1 code path must go somewhere and spec says the M1 behaviour was "`DreamConfigSession` 或 stub LLM"). We chose rename-to-`-legacy` over delete to keep the slash-command UX alive for one more milestone.
- **Customer-role `tenant_id` is cosmetic today** — the wire-through is idempotent: cc_pool currently ignores it on the customer path. Rather than wait for the soul-injection PR, we pin the kwarg at this call site so the contract is locked by tests. When soul injection lands, no change here.
- **`instance.client.query` + `receive_response()` instead of `pool.query()`** — `pool.query()` is an async generator (yields messages). Collecting the full reply via `async for msg in pool.query(...)` would work, but it hides the `acquire()` call — and the spec pins the `acquire()` kwargs. Using `async with pool.acquire(...) as instance` makes the `tenant_id="_master"` assertion explicit and testable (test #4).

## Evidence

| Artifact | Location |
|----------|----------|
| Endpoint implementation | `autoservice/api_routes.py` — new `management_chat` handler; old handler renamed to `management_chat_legacy` |
| Tests | `tests/api/test_management_chat.py` (6 cases) |
| Task status row | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 7 — T7B.6 |

## Future work (flagged)

- **Admin tool set** (spec §2.7) — wire `list_tenants` / `read_proposals` / `approve_proposal` / `reject_proposal` / `trigger_dream` / `publish_sandbox` / `read_wizard_state` as MCP tools on the `_master` customer agent. Requires a new plugin under `plugins/_master/` or a deployment-level MCP config.
- **Inline widget rendering** — `proposal-card` / `metric` / `action-launch` shown as tool-call results in the admin-portal chat surface. Front-end batch.
- **Legacy endpoint deletion** — remove `/api/management/chat-legacy` at M3 once tool-use is verified in staging.
- **Soul injection for customer role** — the `tenant_id` passed to `acquire(role="customer", ...)` should load `plugins/<tid>/souls/customer_soul.md` (or `.autoservice/sandbox/<tid>/souls/...` in master mode). Today it is ignored by the customer path; dream path uses it. Unification is a `cc_pool` refactor.
- **Auth** — `/api/management/chat` is currently unauthenticated (matches `/api/admin/chat`'s M2 posture — see T6F.6 eval-doc). Add `Depends(auth.require_admin)` once the admin-tier distinction lands (auth tables already have role column per batch-7).
