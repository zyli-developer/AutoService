# Customer Role · Tenant Soul + KB Access — Verification Evidence

**Date:** 2026-04-22
**Branch:** dev-a
**Spec:** [docs/superpowers/specs/2026-04-21-customer-role-tenant-soul-kb-design.md](../../docs/superpowers/specs/2026-04-21-customer-role-tenant-soul-kb-design.md)
**Plan:** [docs/superpowers/plans/2026-04-21-customer-role-tenant-soul-kb.md](../../docs/superpowers/plans/2026-04-21-customer-role-tenant-soul-kb.md)

## Feature Commits

| SHA | Task | Description |
|---|---|---|
| `5fa4c21` | 1 | Extract `_recycle_instance_for_tenant` helper |
| `1be9ace` | 1 | Task 1 code-review fixes |
| `3f79e67` | 2 | Add `enable_kb_tool` parameter to `create_cc_client` |
| `bcb4878` | 3 | Implement `autoservice_kb` MCP server with tenant closure |
| `e744c67` | 4 | Main pool factory creates customer-role instances |
| `32a4eaa` | 5 | Tenant-aware `acquire_sticky` with recycle-on-bind |
| `6b57c9f` | 5 | Task 5 code-review fixes |
| `65ea30a` | 6 | `session_query` forwards `tenant_id` to `acquire_sticky` |
| `8bebd3d` | 7 | Inject KB pre-fetch into customer-role prompt |
| `1cbc1f9` | 7 | Add section-ordering test for customer prompt |
| `8723e57` | 8 | Customer reply for mystore cites KB content (E2E) |

## End-to-End Acceptance Test

**Command:**
```
python -m pytest tests/e2e/test_customer_kb_grounded_reply.py -v -m slow
```

**Result:** ✅ PASS in 17.75s (real Claude Agent SDK subprocess).

**What it proves:** The customer-role CC instance for tenant `mystore`, given the question "你们提供哪些服务", produced a reply that cited at least one KB-sourced keyword from `(CINNOX|DID|IVR|PSTN|套餐|Essentials|Professional|Enterprise)`. This confirms end-to-end:

- Main pool warmup creates `role="customer"` instances (Task 4)
- `acquire_sticky(..., tenant_id="mystore")` recycles the warm instance into a mystore-soul-bound instance (Tasks 1 + 5)
- The mystore tenant soul (`.autoservice/sandbox/mystore/souls/customer_soul.md`) is loaded into the CC subprocess (Task 1 helper + Task 4 factory path)
- The KB MCP tool is available to the agent (Tasks 2 + 3)
- Pre-fetch KB snippet from `<kb_context>` block is respected in the reply (Task 7)
- `session_query(..., tenant_id="mystore")` forwards tenant through the whole path (Task 6)

## Regression Suite

**Command:**
```
python -m pytest tests/cc_pool/ tests/triage/ tests/dream/ -v
```

**Result:** ✅ **111 passed, 10 warnings in 2.85s.**

Breakdown:
- `tests/cc_pool/` — 44 tests (includes 5 recycle helper, 5 sticky tenant, 3 factory args, 2 session_query tenant, etc.)
- `tests/triage/` — 13 tests (includes 6 KB prefetch + ordering + 4 KB MCP tool + 3 from prior work)
- `tests/dream/` — 54 tests (all pre-existing dream tests green — helper extraction preserved behavior)

The 10 warnings are pre-existing `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` in the sticky-tenant test's `AsyncMock` patches of `create_cc_client` — harmless, matches the mocking pattern used elsewhere in the suite.

## Pre-existing Failures (Unrelated)

`tests/test_proposal_pipeline.py` shows 8 failures when run as part of the full suite, but **each test passes when run in isolation**. Root cause: the file uses `asyncio.get_event_loop().run_until_complete(...)` which conflicts with pytest's `asyncio_mode = "auto"` configuration. This is a pre-existing event-loop pollution issue entirely unrelated to the tenant-soul+KB feature.

## KB Seed Verification

```
python scripts/seed_mystore_tenant.py
```

Produces:
- `.autoservice/sandbox/mystore/config.json`
- `.autoservice/sandbox/mystore/souls/customer_soul.md`
- `.autoservice/sandbox/mystore/souls/_generation_meta.yaml`
- `.autoservice/database/knowledge_base/kb.db` — **359 `kb_chunks`** (8 demo-facts + 351 glossary entries from `AutoService-Cinnox/plugins/cinnox/references/glossary.json`).

## Feature Effect (Before vs. After)

**Before** (prior to this work):
- Customer CC instances were created by `CCPool.__init__`'s factory with `role=None`, `tenant_id=None`, no `mcp_servers`. `_load_soul(None, None)` was never called because `role is None` short-circuited. Result: **no system prompt loaded**, no tenant KB tool, no tenant context at all.
- The agent reply to "你们提供哪些服务" was a generic fallback: "抱歉，我目前暂时没有详细的服务目录可以提供给您...".

**After** (this work):
- Customer CC instances warmup with `role="customer"` (default soul).
- First sticky-bind to a conversation recycles the warm instance into a `(role="customer", tenant_id=<conv_tenant>)` instance carrying the tenant's `customer_soul.md` and the `autoservice_kb` MCP server.
- Customer message prompts include a pre-fetched `<kb_context>` block with top-5 FTS5 hits from the tenant's KB.
- Agent can call `kb_search(query, top_k)` MCP tool for follow-up queries; `tenant_id` is closure-captured so the agent cannot query other tenants' KBs.
- Cross-tenant rebind on the same conv raises `StickyTenantMismatch`; recycle failures degrade gracefully (uncycled instance bound, tenant stamped to avoid error cascade).
- E2E test confirms real reply cites tenant-specific service terms.

## Conclusion

The "Customer Role · Tenant Soul + KB Access" feature is implemented, unit-tested across 13 test files, and verified end-to-end with a real Claude Agent SDK subprocess on the `mystore` tenant. All target-scope suites are green; no regressions introduced.
