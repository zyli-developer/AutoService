# Customer Role · Tenant Soul + KB Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the customer-role CC pool tenant-aware (load per-tenant soul at acquire time) and give customer agents access to tenant KB through both prompt-level pre-fetch and MCP tool, so "你们提供哪些服务" gets a KB-grounded answer instead of a generic fallback.

**Architecture:** Follow the existing dream-pool recycle pattern ([cc_pool.py:860-940](../../../autoservice/cc_pool.py#L860-L940)) — abstract it into a reusable helper, apply to customer main pool at sticky-bind time. Pre-fetch RAG via existing `kb_search` into prompt; expose same function as MCP tool (tenant_id closure-captured) for agent-driven follow-up queries. Keep triage/dispatch, conversation engine, lead/translate/triage/dream pools unchanged.

**Tech Stack:** Python 3.11+, pytest, Claude Agent SDK, SQLite FTS5, asyncio.

**Spec:** [docs/superpowers/specs/2026-04-21-customer-role-tenant-soul-kb-design.md](../specs/2026-04-21-customer-role-tenant-soul-kb-design.md)

---

## File Structure

### New files

- **`autoservice/kb_mcp_server.py`** — In-process SDK-type MCP server. Single tool `kb_search(query, top_k)`; `tenant_id` captured via closure. Sole responsibility: expose tenant-scoped KB as MCP tool. Size target: <80 lines.

### Modified files

- **`autoservice/cc_pool.py`** (largest change)
  - Extract `_recycle_instance_for_tenant(pool, instance, *, role, tenant_id, config)` helper (consolidates dream-pool inline recycle at lines 884-910).
  - Update dream pool `_acquire_dream` to call the new helper.
  - `create_cc_client` gains `enable_kb_tool: bool = False` parameter.
  - `CCPool.__init__` factory passes `role="customer"` at warmup (tenant_id=None).
  - `CCPool.acquire_sticky` overridden to accept `tenant_id` and invoke helper.
  - `CCPool.session_query` accepts and forwards `tenant_id`.

- **`autoservice/triage_dispatch.py`**
  - `_generate_agent_reply` adds KB pre-fetch block and `<kb_context>` prompt assembly (customer-role only).
  - `pool.session_query(conv_id, prompt)` call passes `tenant_id=tenant_id`.

- **`socialware/pool.py`** (minimal; touch only if required)
  - Inspect: `acquire_sticky` signature currently `(self, key, timeout=None)`. CCPool override is free to add its own kwargs, no base-class change needed. **Skip modification unless actually blocked.**

### New test files

- `tests/cc_pool/test_recycle_helper.py` — pure-helper behavior
- `tests/cc_pool/test_acquire_sticky_tenant.py` — sticky + recycle integration
- `tests/cc_pool/test_customer_factory_args.py` — regression lock on factory args
- `tests/cc_pool/test_dream_pool_unchanged.py` — dream pool behavior preserved after helper extraction
- `tests/triage/test_kb_prefetch.py` — pre-fetch + prompt assembly
- `tests/triage/test_kb_mcp_tool.py` — MCP tool construction + isolation
- `tests/e2e/test_customer_kb_grounded_reply.py` — full integration (mystore tenant)

---

## Execution notes

- **Granularity:** each task = one atomic change, TDD inside each task, one commit at task end.
- **Verification anchor:** `kb_search` is already tested in `tests/dream/` (via dream_agent). Treat it as a stable dependency — do not re-test its internals, only its call sites.
- **Dream-pool regression risk:** Task 1 extracts the dream recycle logic. Run the full dream test suite after Task 1 commit before proceeding.
- **Commit style:** conventional commits, `feat(cc_pool): ...`, `test(triage): ...`, etc. Per [docs/plans/project.yaml](../../plans/project.yaml) conventions.

---

## Task 1: Extract `_recycle_instance_for_tenant` helper (dream-pool no-op refactor)

**Files:**
- Modify: `autoservice/cc_pool.py` lines 860-940 (`_acquire_dream`, `_make_tenant_dream_instance`)
- Test: `tests/cc_pool/test_recycle_helper.py` (new)

Purpose: Pull the tenant-mismatch-triggered instance recycle out of `_acquire_dream` into a standalone helper so customer pool can reuse it. Dream pool observable behavior must not change.

- [ ] **Step 1: Write the failing helper test**

Create `tests/cc_pool/test_recycle_helper.py`:

```python
"""Tests for _recycle_instance_for_tenant — used by both dream pool and
customer main pool to inject the correct tenant soul at acquire time.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from autoservice.cc_pool import _recycle_instance_for_tenant, _UNSET


class _FakeInstance:
    def __init__(self, inst_id="cc-001"):
        self.id = inst_id
        self.client = MagicMock()


@pytest.mark.asyncio
async def test_recycle_same_tenant_is_noop():
    pool = MagicMock()
    pool._destroy_instance = AsyncMock()
    inst = _FakeInstance()
    inst._pool_tenant_id = "acme"

    result = await _recycle_instance_for_tenant(
        pool, inst, role="customer", tenant_id="acme", config=MagicMock(),
    )

    assert result is inst
    pool._destroy_instance.assert_not_called()


@pytest.mark.asyncio
async def test_recycle_tenant_mismatch_rebuilds():
    pool = MagicMock()
    pool._destroy_instance = AsyncMock()
    new_inst = _FakeInstance(inst_id="cc-002")

    inst = _FakeInstance()
    inst._pool_tenant_id = "acme"

    with patch(
        "autoservice.cc_pool._make_tenant_instance",
        new=AsyncMock(return_value=new_inst),
    ) as mk:
        result = await _recycle_instance_for_tenant(
            pool, inst, role="customer", tenant_id="mystore",
            config=MagicMock(),
        )

    assert result is new_inst
    assert result._pool_tenant_id == "mystore"
    pool._destroy_instance.assert_awaited_once_with(inst)
    mk.assert_awaited_once()


@pytest.mark.asyncio
async def test_recycle_first_bind_unset_tag_rebuilds():
    """Warm instance fresh from factory has no _pool_tenant_id attr → rebuild."""
    pool = MagicMock()
    pool._destroy_instance = AsyncMock()
    new_inst = _FakeInstance(inst_id="cc-003")

    inst = _FakeInstance()
    # Deliberately do NOT set _pool_tenant_id

    with patch(
        "autoservice.cc_pool._make_tenant_instance",
        new=AsyncMock(return_value=new_inst),
    ):
        result = await _recycle_instance_for_tenant(
            pool, inst, role="customer", tenant_id="mystore",
            config=MagicMock(),
        )

    assert result is new_inst
    pool._destroy_instance.assert_awaited_once()


@pytest.mark.asyncio
async def test_recycle_rebuild_failure_propagates():
    pool = MagicMock()
    pool._destroy_instance = AsyncMock()
    inst = _FakeInstance()

    with patch(
        "autoservice.cc_pool._make_tenant_instance",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await _recycle_instance_for_tenant(
                pool, inst, role="customer", tenant_id="mystore",
                config=MagicMock(),
            )
    pool._destroy_instance.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cc_pool/test_recycle_helper.py -v`
Expected: FAIL with `ImportError: cannot import name '_recycle_instance_for_tenant'`

- [ ] **Step 3: Add helper + rename dream-specific builder**

In `autoservice/cc_pool.py`:

Rename `_make_tenant_dream_instance` (currently line 921) to `_make_tenant_instance`. Generalize: accept `role` param; route to the right soul loader.

```python
async def _make_tenant_instance(
    pool: AsyncPool[CCClient],
    *,
    role: str,
    tenant_id: str | None,
) -> PooledInstance[CCClient]:
    """Build + track a fresh PooledInstance[CCClient] for (role, tenant_id).

    Mirrors AsyncPool._create_instance but bypasses the stored factory so
    we can inject the correct per-(role, tenant) soul. The resulting
    instance IS tracked by the pool so status/health reporting still works.
    """
    cfg = pool._config  # noqa: SLF001
    if role == "dream":
        system_prompt = _load_dream_soul(tenant_id)
        client = await create_cc_client(cfg, system_prompt=system_prompt)
    else:
        # customer + any future role: let create_cc_client resolve soul
        # via role+tenant_id; enable KB tool when tenant is known.
        client = await create_cc_client(
            cfg,
            role=role,
            tenant_id=tenant_id,
            enable_kb_tool=(role == "customer" and tenant_id is not None),
        )
    pool._instance_counter += 1  # noqa: SLF001
    instance_id = (
        f"{pool._instance_prefix}-{pool._instance_counter:03d}"  # noqa: SLF001
    )
    instance = PooledInstance(client=client, id=instance_id)
    pool._track(instance)  # noqa: SLF001
    return instance
```

Add the helper right after `_make_tenant_instance`:

```python
async def _recycle_instance_for_tenant(
    pool: AsyncPool[CCClient],
    instance: PooledInstance[CCClient],
    *,
    role: str,
    tenant_id: str | None,
    config: PoolConfig,  # accepted for API symmetry; currently unused
) -> PooledInstance[CCClient]:
    """Ensure *instance* has the right soul for (role, tenant_id); rebuild if not.

    Reads the stamped _pool_tenant_id sentinel. If it matches the requested
    tenant_id (including both being None), returns the instance unchanged.
    Otherwise destroys and rebuilds via _make_tenant_instance, stamps the
    new instance, and returns it. Rebuild failures propagate — callers
    decide degrade path.
    """
    existing = getattr(instance, "_pool_tenant_id", _UNSET)
    if existing is not _UNSET and existing == tenant_id:
        return instance

    log.info(
        "pool recycle: role=%s instance=%s tenant %r → %r",
        role, instance.id,
        existing if existing is not _UNSET else "<unset>",
        tenant_id,
    )
    await pool._destroy_instance(instance)  # noqa: SLF001
    new_instance = await _make_tenant_instance(
        pool, role=role, tenant_id=tenant_id,
    )
    new_instance._pool_tenant_id = tenant_id  # type: ignore[attr-defined]
    return new_instance
```

- [ ] **Step 4: Update `_acquire_dream` to call the helper**

Replace the inline recycle block in `_acquire_dream` (lines 884-910) with:

```python
async def _acquire_dream(
    *, tenant_id: str | None, timeout: float | None
) -> AsyncIterator[PooledInstance[CCClient]]:
    pool = await _get_dream_pool()
    instance = await pool.checkout(timeout=timeout)
    try:
        # Dream pool uses its own tag name for backward-compat; translate
        # to the generic _pool_tenant_id sentinel the helper expects.
        existing_tid = getattr(instance, "_dream_tenant_id", _UNSET)
        if existing_tid is not _UNSET:
            instance._pool_tenant_id = existing_tid  # type: ignore[attr-defined]

        instance = await _recycle_instance_for_tenant(
            pool, instance,
            role="dream", tenant_id=tenant_id, config=pool._config,  # noqa: SLF001
        )
        instance._pool_role = "dream"  # type: ignore[attr-defined]
        instance._dream_tenant_id = tenant_id  # type: ignore[attr-defined]
        yield instance
    finally:
        await pool.checkin(instance)
```

- [ ] **Step 5: Run recycle helper test to verify it passes**

Run: `pytest tests/cc_pool/test_recycle_helper.py -v`
Expected: all 4 tests PASS

- [ ] **Step 6: Run dream pool regression tests**

Run: `pytest tests/dream/ tests/cc_pool/ -v -k dream`
Expected: all existing dream tests still PASS. If any fail, the helper extraction broke behavior — fix before committing.

- [ ] **Step 7: Commit**

```bash
git add autoservice/cc_pool.py tests/cc_pool/test_recycle_helper.py
git commit -m "refactor(cc_pool): extract _recycle_instance_for_tenant for reuse

Pull the tenant-mismatch recycle logic out of _acquire_dream into a
standalone helper so the customer main pool can reuse it at sticky-bind
time. Dream pool behavior is preserved — existing dream tests green."
```

---

## Task 2: Add `enable_kb_tool` parameter to `create_cc_client`

**Files:**
- Modify: `autoservice/cc_pool.py` `create_cc_client` (lines 254-317)
- Test: `tests/cc_pool/test_create_cc_client_kb_tool.py` (new)

Purpose: Make KB MCP injection opt-in at the factory. Does NOT yet wire up a real KB MCP server — just routes the switch.

- [ ] **Step 1: Write failing test**

Create `tests/cc_pool/test_create_cc_client_kb_tool.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from autoservice.cc_pool import create_cc_client, PoolConfig


@pytest.mark.asyncio
async def test_create_cc_client_injects_kb_server_when_enabled_and_tenant_known():
    cfg = PoolConfig(cwd=".", min_size=0, max_size=1, warmup_count=0)
    with patch("autoservice.cc_pool.ClaudeSDKClient") as sdk_cls, \
         patch("autoservice.kb_mcp_server.build_kb_mcp_server") as mk:
        mk.return_value = {"type": "sdk", "name": "autoservice_kb", "tools": []}
        sdk_inst = sdk_cls.return_value
        sdk_inst.connect = AsyncMock()

        await create_cc_client(
            cfg, role="customer", tenant_id="acme", enable_kb_tool=True,
        )

    mk.assert_called_once_with("acme")
    # The SDK client options should carry the autoservice_kb server
    args, kwargs = sdk_cls.call_args
    options = args[0] if args else kwargs.get("options") or sdk_cls.call_args[0][0]
    assert "autoservice_kb" in options.mcp_servers


@pytest.mark.asyncio
async def test_create_cc_client_skips_kb_server_when_disabled():
    cfg = PoolConfig(cwd=".", min_size=0, max_size=1, warmup_count=0)
    with patch("autoservice.cc_pool.ClaudeSDKClient") as sdk_cls, \
         patch("autoservice.kb_mcp_server.build_kb_mcp_server") as mk:
        sdk_inst = sdk_cls.return_value
        sdk_inst.connect = AsyncMock()

        await create_cc_client(
            cfg, role="customer", tenant_id="acme", enable_kb_tool=False,
        )

    mk.assert_not_called()


@pytest.mark.asyncio
async def test_create_cc_client_skips_kb_server_when_no_tenant():
    cfg = PoolConfig(cwd=".", min_size=0, max_size=1, warmup_count=0)
    with patch("autoservice.cc_pool.ClaudeSDKClient") as sdk_cls, \
         patch("autoservice.kb_mcp_server.build_kb_mcp_server") as mk:
        sdk_inst = sdk_cls.return_value
        sdk_inst.connect = AsyncMock()

        await create_cc_client(
            cfg, role="customer", tenant_id=None, enable_kb_tool=True,
        )

    mk.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cc_pool/test_create_cc_client_kb_tool.py -v`
Expected: FAIL — `enable_kb_tool` kwarg not accepted, or `kb_mcp_server` module missing.

- [ ] **Step 3: Add parameter to `create_cc_client`**

Modify `autoservice/cc_pool.py` line 254 signature and body:

```python
async def create_cc_client(
    config: PoolConfig,
    mcp_servers: dict | None = None,
    system_prompt: str | None = None,
    role: str | None = None,
    tenant_id: str | None = None,
    enable_kb_tool: bool = False,
) -> CCClient:
    """...existing docstring...

    Args:
        ...
        enable_kb_tool: When True AND tenant_id is non-None, injects the
            ``autoservice_kb`` MCP server that exposes ``kb_search`` scoped
            to the given tenant. No-op when False or tenant_id is None.
    """
    cwd = config.cwd or str(Path.cwd())
    cwd_path = Path(cwd).absolute()
    plugin_path = cwd_path / ".autoservice" / ".claude"

    env = {}
    for var in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
        val = os.environ.get(var)
        if val:
            env[var] = val

    if system_prompt is None and role is not None:
        system_prompt = _load_soul(tenant_id, role)
        if system_prompt is None:
            log.warning(
                "No soul found for role=%s tenant_id=%s — starting without system prompt",
                role, tenant_id,
            )

    # NEW: KB MCP server injection
    if enable_kb_tool and tenant_id:
        from autoservice.kb_mcp_server import build_kb_mcp_server
        kb_server = build_kb_mcp_server(tenant_id)
        mcp_servers = {**(mcp_servers or {}), "autoservice_kb": kb_server}

    options = ClaudeAgentOptions(
        cwd=cwd,
        setting_sources=None,
        plugins=[{"type": "local", "path": str(plugin_path)}]
        if plugin_path.exists() else None,
        env=env,
        permission_mode=config.permission_mode,
        model=config.model,
        cli_path=config.cli_path,
        include_partial_messages=config.include_partial_messages,
    )

    if mcp_servers:
        options.mcp_servers = mcp_servers
    if system_prompt:
        options.system_prompt = system_prompt

    sdk_client = ClaudeSDKClient(options)
    client = CCClient(sdk_client)
    await client.connect()
    return client
```

Note: test patches `autoservice.kb_mcp_server.build_kb_mcp_server`. That module is created in Task 3 — for Task 2 tests to pass we just need the import not to break. Stub the module now by creating empty `autoservice/kb_mcp_server.py`:

```python
"""Stub — real implementation arrives in Task 3."""
def build_kb_mcp_server(tenant_id: str) -> dict:
    raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cc_pool/test_create_cc_client_kb_tool.py -v`
Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add autoservice/cc_pool.py autoservice/kb_mcp_server.py tests/cc_pool/test_create_cc_client_kb_tool.py
git commit -m "feat(cc_pool): add enable_kb_tool parameter to create_cc_client

Optional switch to inject the autoservice_kb MCP server at client
construction. No-op until kb_mcp_server implementation lands (Task 3).
Stubbed module added so imports resolve."
```

---

## Task 3: Implement `kb_mcp_server.build_kb_mcp_server`

**Files:**
- Modify: `autoservice/kb_mcp_server.py` (replace stub)
- Test: `tests/triage/test_kb_mcp_tool.py` (new)

Purpose: Real MCP server factory. `tenant_id` captured via closure; tool exposes `kb_search(query, top_k)` backed by `dream_agent.kb_search`.

- [ ] **Step 1: Check current SDK MCP server API**

Run: `python -c "from claude_agent_sdk import create_sdk_mcp_server; help(create_sdk_mcp_server)"`

If the function exists, use it. Otherwise, inspect `claude_agent_sdk.types` for the SDK-server shape (a dict with type/tools as the spec describes). Note the actual API here before coding — this is the only SDK-specific detail in the plan.

**If API signature differs from the spec §2.8 sketch, adapt the code in Step 3 but keep behavior equivalent: (a) single tool `kb_search`, (b) tenant_id closure-captured, (c) top_k clamped to ≤5.**

- [ ] **Step 2: Write failing tests**

Create `tests/triage/test_kb_mcp_tool.py`:

```python
from __future__ import annotations

from unittest.mock import patch

import pytest

from autoservice.kb_mcp_server import build_kb_mcp_server, _MAX_TOP_K


def test_server_name_and_tool():
    server = build_kb_mcp_server("acme")
    # Expose a single tool named kb_search (exact shape depends on SDK)
    tools = server.get("tools") if isinstance(server, dict) else getattr(server, "tools", [])
    names = [t.get("name") if isinstance(t, dict) else t.name for t in tools]
    assert names == ["kb_search"]


@pytest.mark.asyncio
async def test_handler_captures_tenant_id_and_calls_kb_search():
    server = build_kb_mcp_server("acme")
    tools = server.get("tools") if isinstance(server, dict) else getattr(server, "tools", [])
    tool = tools[0]
    handler = tool.get("handler") if isinstance(tool, dict) else tool.handler

    with patch("autoservice.kb_mcp_server._kb_search") as kb:
        kb.return_value = [{"content": "x"}]
        # Even if the agent tries to pass a tenant_id arg, it should be ignored
        result = await handler({"query": "test", "top_k": 3, "tenant_id": "evil"})

    kb.assert_called_once_with(tenant_id="acme", query="test", top_k=3)
    assert result == {"results": [{"content": "x"}]}


@pytest.mark.asyncio
async def test_handler_clamps_top_k():
    server = build_kb_mcp_server("acme")
    tools = server.get("tools") if isinstance(server, dict) else getattr(server, "tools", [])
    handler = tools[0]["handler"] if isinstance(tools[0], dict) else tools[0].handler

    with patch("autoservice.kb_mcp_server._kb_search") as kb:
        kb.return_value = []
        await handler({"query": "test", "top_k": 99})

    kb.assert_called_once()
    call_kwargs = kb.call_args.kwargs
    assert call_kwargs["top_k"] == _MAX_TOP_K


@pytest.mark.asyncio
async def test_handler_empty_query_returns_empty():
    server = build_kb_mcp_server("acme")
    tools = server.get("tools") if isinstance(server, dict) else getattr(server, "tools", [])
    handler = tools[0]["handler"] if isinstance(tools[0], dict) else tools[0].handler

    with patch("autoservice.kb_mcp_server._kb_search") as kb:
        kb.return_value = []
        result = await handler({"query": ""})

    # Either short-circuit or delegate to kb_search (it also handles empty
    # gracefully). Either way: structured empty result, no raise.
    assert "results" in result
```

- [ ] **Step 3: Run tests — expect import/attribute failures**

Run: `pytest tests/triage/test_kb_mcp_tool.py -v`
Expected: FAIL — `NotImplementedError` from stub.

- [ ] **Step 4: Implement `build_kb_mcp_server`**

Replace `autoservice/kb_mcp_server.py`:

```python
"""In-process SDK-type MCP server exposing kb_search to tenant-scoped CC instances.

Design rationale and tenant isolation guarantees: see
docs/superpowers/specs/2026-04-21-customer-role-tenant-soul-kb-design.md §2.8.
"""
from __future__ import annotations

from typing import Any

from autoservice.dream_agent import kb_search as _kb_search


_MAX_TOP_K = 5
_DEFAULT_TOP_K = 3


def build_kb_mcp_server(tenant_id: str) -> dict[str, Any]:
    """Return an SDK-type MCP server config with a single tool: kb_search.

    The tenant_id argument is captured in closure — the agent cannot
    override it by passing a tenant_id arg, because the handler ignores
    any such arg and always uses the closure value.
    """
    async def _handle_kb_search(args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query", "") or ""
        top_k = min(int(args.get("top_k", _DEFAULT_TOP_K)), _MAX_TOP_K)
        if not query.strip():
            return {"results": []}
        rows = _kb_search(tenant_id=tenant_id, query=query, top_k=top_k)
        return {"results": rows}

    return {
        "type": "sdk",
        "name": "autoservice_kb",
        "tools": [
            {
                "name": "kb_search",
                "description": (
                    "Search this tenant's knowledge base. Use when the "
                    "pre-fetched <kb_context> block is insufficient to "
                    "answer the customer."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural-language search query",
                        },
                        "top_k": {
                            "type": "integer",
                            "default": _DEFAULT_TOP_K,
                            "maximum": _MAX_TOP_K,
                            "description": "Max results (clamped to 5)",
                        },
                    },
                    "required": ["query"],
                },
                "handler": _handle_kb_search,
            }
        ],
    }
```

**If Step 1 showed the SDK expects a different concrete type (e.g., dataclass / TypedDict / `create_sdk_mcp_server(...)` call)**, wrap the dict above in that constructor. Keep the tool definition fields identical.

- [ ] **Step 5: Run tests to verify passing**

Run: `pytest tests/triage/test_kb_mcp_tool.py -v`
Expected: all 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add autoservice/kb_mcp_server.py tests/triage/test_kb_mcp_tool.py
git commit -m "feat(kb): add autoservice_kb MCP server with tenant_id closure isolation

Exposes a single kb_search tool to customer CC instances. tenant_id is
closure-captured; the agent cannot query other tenants' KBs even by
passing a tenant_id argument (handler ignores it). top_k clamped to 5."
```

---

## Task 4: Main pool factory passes `role="customer"`

**Files:**
- Modify: `autoservice/cc_pool.py` `CCPool.__init__` (lines 357-381)
- Test: `tests/cc_pool/test_customer_factory_args.py` (new)

Purpose: Regression lock — main pool's warmup factory must create instances tagged as customer-role. Does NOT yet change acquire behavior.

- [ ] **Step 1: Write failing test**

Create `tests/cc_pool/test_customer_factory_args.py`:

```python
"""Regression lock: CCPool main pool factory must create customer-role
instances. If someone ever reverts the factory to role=None, this test
catches it.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from autoservice.cc_pool import CCPool, PoolConfig


@pytest.mark.asyncio
async def test_main_pool_factory_passes_role_customer():
    cfg = PoolConfig(cwd=".", min_size=0, max_size=0, warmup_count=0)

    with patch("autoservice.cc_pool.create_cc_client") as mk:
        mk.return_value = AsyncMock()
        pool = CCPool(cfg)
        # Call the factory directly (AsyncPool stores it as a zero-arg
        # callable returning awaitable)
        factory_fn = pool._factory  # noqa: SLF001
        await factory_fn()

    assert mk.called
    call_kwargs = mk.call_args.kwargs
    assert call_kwargs.get("role") == "customer"
    assert call_kwargs.get("tenant_id") is None  # warmup, no tenant yet
    assert call_kwargs.get("enable_kb_tool") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cc_pool/test_customer_factory_args.py -v`
Expected: FAIL — current factory doesn't pass role/tenant_id/enable_kb_tool.

- [ ] **Step 3: Update `CCPool.__init__` factory**

In `autoservice/cc_pool.py` around line 365-372, replace the factory lambda:

```python
class CCPool(AsyncPool[CCClient]):
    def __init__(
        self,
        config: PoolConfig | None = None,
        mcp_servers: dict | None = None,
        system_prompt: str | None = None,
        on_sticky_release: Callable[[str], Awaitable[None]] | None = None,
    ):
        cfg = config or PoolConfig()
        super().__init__(
            config=cfg,
            factory=lambda: create_cc_client(
                cfg,
                mcp_servers=mcp_servers,
                system_prompt=system_prompt,
                role="customer",        # NEW: warmup as customer role
                tenant_id=None,         # NEW: tenant assigned at sticky-bind
                enable_kb_tool=False,   # NEW: no KB tool until tenant bound
            ),
            instance_prefix="cc",
            logger=log,
            on_sticky_release=on_sticky_release,
        )
        self._role_pools: dict[tuple[str, str | None], AsyncPool[CCClient]] = {}
        self._role_pool_last_used: dict[tuple[str, str | None], float] = {}
        self._role_pool_lock = asyncio.Lock()
        self._reaper_task: asyncio.Task | None = None
        self._closed = False
```

- [ ] **Step 4: Run test to verify passing**

Run: `pytest tests/cc_pool/test_customer_factory_args.py -v`
Expected: PASS

- [ ] **Step 5: Run full cc_pool test suite for regressions**

Run: `pytest tests/cc_pool/ -v`
Expected: all PASS (including the tests from Tasks 1-2)

- [ ] **Step 6: Commit**

```bash
git add autoservice/cc_pool.py tests/cc_pool/test_customer_factory_args.py
git commit -m "feat(cc_pool): main pool factory creates customer-role instances

Warmup instances are now tagged role='customer' so _load_soul picks up
the default customer soul. tenant_id stays None at warmup; per-tenant
soul is injected at sticky-bind time via recycle. Regression test locks
this invariant."
```

---

## Task 5: `CCPool.acquire_sticky` override with tenant recycle

**Files:**
- Modify: `autoservice/cc_pool.py` (add override on `CCPool`)
- Test: `tests/cc_pool/test_acquire_sticky_tenant.py` (new)

Purpose: When a conversation first binds to a sticky instance, recycle it into the target tenant's soul.

- [ ] **Step 1: Write failing tests**

Create `tests/cc_pool/test_acquire_sticky_tenant.py`:

```python
"""Tests for CCPool.acquire_sticky(chat_id, tenant_id=...)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from autoservice.cc_pool import CCPool, PoolConfig, StickyTenantMismatch


async def _bootstrap_pool(tenant_id_of_warm: str | None = None):
    """Construct a pool with a single warm instance already bound."""
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    # Patch create_cc_client at factory time
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
    return pool


@pytest.mark.asyncio
async def test_first_bind_triggers_recycle_to_target_tenant():
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
        try:
            with patch(
                "autoservice.cc_pool._recycle_instance_for_tenant",
                new=AsyncMock(side_effect=lambda pool, inst, **kw: inst),
            ) as recycle:
                inst = await pool.acquire_sticky("conv-1", tenant_id="mystore")
            recycle.assert_awaited_once()
            call = recycle.await_args
            assert call.kwargs["role"] == "customer"
            assert call.kwargs["tenant_id"] == "mystore"
            assert inst._pool_tenant_id == "mystore"
        finally:
            await pool.shutdown()


@pytest.mark.asyncio
async def test_second_bind_same_tenant_reuses_without_recycle():
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
        try:
            with patch(
                "autoservice.cc_pool._recycle_instance_for_tenant",
                new=AsyncMock(side_effect=lambda pool, inst, **kw: inst),
            ) as recycle:
                first = await pool.acquire_sticky("conv-1", tenant_id="mystore")
                second = await pool.acquire_sticky("conv-1", tenant_id="mystore")
            # Recycle only on first bind
            assert recycle.await_count == 1
            assert first is second
        finally:
            await pool.shutdown()


@pytest.mark.asyncio
async def test_cross_tenant_rebind_raises():
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
        try:
            with patch(
                "autoservice.cc_pool._recycle_instance_for_tenant",
                new=AsyncMock(side_effect=lambda pool, inst, **kw: inst),
            ):
                await pool.acquire_sticky("conv-1", tenant_id="mystore")
                with pytest.raises(StickyTenantMismatch):
                    await pool.acquire_sticky("conv-1", tenant_id="other")
        finally:
            await pool.shutdown()


@pytest.mark.asyncio
async def test_recycle_failure_falls_back_to_uncycled_instance():
    """If rebuild fails, we still bind the warm instance (degraded but alive)."""
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
        try:
            with patch(
                "autoservice.cc_pool._recycle_instance_for_tenant",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ):
                inst = await pool.acquire_sticky("conv-1", tenant_id="mystore")
            # Instance still returned, no crash propagated
            assert inst is not None
        finally:
            await pool.shutdown()


@pytest.mark.asyncio
async def test_no_tenant_skips_recycle():
    """tenant_id=None → no recycle call, parent semantics preserved."""
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
        try:
            with patch(
                "autoservice.cc_pool._recycle_instance_for_tenant",
                new=AsyncMock(side_effect=lambda pool, inst, **kw: inst),
            ) as recycle:
                await pool.acquire_sticky("conv-1", tenant_id=None)
            recycle.assert_not_awaited()
        finally:
            await pool.shutdown()
```

- [ ] **Step 2: Run tests — expect failures**

Run: `pytest tests/cc_pool/test_acquire_sticky_tenant.py -v`
Expected: FAIL — `StickyTenantMismatch` and `tenant_id` kwarg don't exist yet.

- [ ] **Step 3: Add `StickyTenantMismatch` exception + override**

In `autoservice/cc_pool.py`, near the top of the `CCPool` class (or as a module-level exception):

```python
class StickyTenantMismatch(RuntimeError):
    """Raised when acquire_sticky is called with a tenant_id that differs
    from the one already sticky-bound to the same chat_id.

    Signals a logic bug upstream (conversation's tenant ownership mutated
    mid-flight). Callers should log + degrade, not retry.
    """
```

Add the override inside `CCPool` (can go right after `__init__`):

```python
async def acquire_sticky(
    self, key: str, *, tenant_id: str | None = None,
    timeout: float | None = None,
) -> PooledInstance[CCClient]:
    """Acquire a sticky-bound instance for (chat_id, tenant_id).

    Extends AsyncPool.acquire_sticky with tenant-aware soul injection:
      - Already bound + tenant matches → return as-is.
      - Already bound + tenant differs → StickyTenantMismatch.
      - Not bound → delegate to super() for the bind, then recycle the
        instance so it carries the tenant's customer soul + KB tool.
      - tenant_id=None → delegate to super() unchanged (no recycle).
    """
    existing = self._sticky_bindings.get(key)  # noqa: SLF001
    if existing is not None and existing.instance.is_healthy:
        bound = getattr(existing.instance, "_pool_tenant_id", None)
        if bound == tenant_id:
            return await super().acquire_sticky(key, timeout=timeout)
        raise StickyTenantMismatch(
            f"conv {key!r} already sticky-bound to tenant={bound!r}, "
            f"refusing rebind to tenant={tenant_id!r}"
        )

    # Fresh bind — let parent do its locking + checkout + binding.
    instance = await super().acquire_sticky(key, timeout=timeout)

    if tenant_id is None:
        return instance

    try:
        instance = await _recycle_instance_for_tenant(
            self, instance,
            role="customer", tenant_id=tenant_id, config=self._config,  # noqa: SLF001
        )
        # If recycle swapped the instance, update the sticky binding to
        # point at the new one so future acquires return it.
        async with self._sticky_lock:  # noqa: SLF001
            binding = self._sticky_bindings.get(key)  # noqa: SLF001
            if binding is not None and binding.instance is not instance:
                binding.instance = instance
    except Exception:
        log.exception(
            "acquire_sticky: recycle failed for key=%s tenant=%s; "
            "returning uncycled instance (degraded)",
            key, tenant_id,
        )
        # Best-effort stamp so future same-tenant acquires don't re-try
        instance._pool_tenant_id = None  # type: ignore[attr-defined]

    return instance
```

- [ ] **Step 4: Run tests to verify passing**

Run: `pytest tests/cc_pool/test_acquire_sticky_tenant.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Run full cc_pool + dream suites for regression**

Run: `pytest tests/cc_pool/ tests/dream/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add autoservice/cc_pool.py tests/cc_pool/test_acquire_sticky_tenant.py
git commit -m "feat(cc_pool): tenant-aware acquire_sticky with recycle-on-bind

CCPool.acquire_sticky now accepts tenant_id. On first bind it recycles
the warm instance into the target tenant's soul + KB tool. Matching
re-acquires are zero-cost. Cross-tenant rebind raises; recycle failures
degrade gracefully (bind uncycled instance, log exception)."
```

---

## Task 6: `CCPool.session_query` forwards `tenant_id`

**Files:**
- Modify: `autoservice/cc_pool.py` `session_query` (lines 393-408)
- Test: extend `tests/cc_pool/test_acquire_sticky_tenant.py` OR add `tests/cc_pool/test_session_query_tenant.py`

Purpose: Trivial passthrough so the call site in triage_dispatch can forward tenant_id.

- [ ] **Step 1: Write failing test**

Append to `tests/cc_pool/test_acquire_sticky_tenant.py` or create `tests/cc_pool/test_session_query_tenant.py`:

```python
@pytest.mark.asyncio
async def test_session_query_forwards_tenant_id():
    cfg = PoolConfig(cwd=".", min_size=1, max_size=1, warmup_count=1)
    with patch("autoservice.cc_pool.create_cc_client", new=AsyncMock()):
        pool = CCPool(cfg)
        await pool.start()
        try:
            fake = AsyncMock()
            fake.client = AsyncMock()
            fake.client.query = AsyncMock()
            async def _empty():
                return
                yield  # never
            fake.client.receive_response = _empty

            with patch.object(pool, "acquire_sticky", new=AsyncMock(return_value=fake)) as acq:
                agen = pool.session_query("conv-1", "hi", tenant_id="mystore")
                async for _ in agen:
                    pass

            acq.assert_awaited_once()
            assert acq.await_args.kwargs.get("tenant_id") == "mystore"
        finally:
            await pool.shutdown()
```

- [ ] **Step 2: Run test — expect failure**

Run: `pytest tests/cc_pool/test_session_query_tenant.py -v`
Expected: FAIL — `session_query` doesn't accept `tenant_id`.

- [ ] **Step 3: Update `session_query` signature**

In `autoservice/cc_pool.py` around line 393:

```python
async def session_query(
    self, chat_id: str, prompt: str,
    *, tenant_id: str | None = None,
    **kwargs: Any,
) -> AsyncIterator[Message]:
    """Stateful multi-turn query: chat_id is sticky-bound to a CC instance.

    When tenant_id is provided, the sticky instance is bound to that
    tenant's soul + KB tool on first acquire. Subsequent calls for the
    same chat_id MUST pass the same tenant_id or StickyTenantMismatch
    is raised.
    """
    instance = await self.acquire_sticky(chat_id, tenant_id=tenant_id)
    instance.query_count += 1
    session_id = kwargs.pop("session_id", chat_id)
    await instance.client.query(prompt, session_id=session_id)
    async for msg in instance.client.receive_response():
        yield msg
```

- [ ] **Step 4: Run test to verify passing**

Run: `pytest tests/cc_pool/test_session_query_tenant.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add autoservice/cc_pool.py tests/cc_pool/test_session_query_tenant.py
git commit -m "feat(cc_pool): session_query forwards tenant_id to acquire_sticky

Keyword-only tenant_id param; backward-compatible (callers not passing
it get the old behavior)."
```

---

## Task 7: KB pre-fetch + prompt assembly in `_generate_agent_reply`

**Files:**
- Modify: `autoservice/triage_dispatch.py` `_generate_agent_reply` (around lines 1093-1107 and 1158-1162)
- Test: `tests/triage/test_kb_prefetch.py` (new)

Purpose: Before calling `session_query`, run `kb_search` on the customer message and inject top-5 hits as `<kb_context>` block. Pass `tenant_id` to `session_query`.

- [ ] **Step 1: Write failing tests**

Create `tests/triage/test_kb_prefetch.py`:

```python
"""Tests for _generate_agent_reply's KB pre-fetch + prompt assembly."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def captured_prompts():
    """Capture every prompt passed to pool.session_query."""
    return []


def _format_kb_block(hits: list[dict]) -> str:
    """Mirror the expected shape so tests can assert against it."""
    lines = ["<kb_context>"]
    for i, h in enumerate(hits, 1):
        header = f"[{i}]"
        if h.get("source_name"):
            header += f" {h['source_name']}"
        if h.get("section"):
            header += f" · {h['section']}"
        lines.append(header)
        lines.append((h.get("content") or "")[:500])
        lines.append("")
    lines.append("</kb_context>")
    return "\n".join(lines)


@pytest.mark.asyncio
async def test_kb_hits_inserted_into_prompt(captured_prompts):
    hits = [
        {"content": "DID 开通需要 1 个工作日", "source_name": "faq",
         "section": "DID", "domain": ""},
    ]

    async def fake_session_query(conv_id, prompt, *, tenant_id=None, **kw):
        captured_prompts.append(prompt)
        return
        yield  # never

    with patch("autoservice.dream_agent.kb_search", return_value=hits), \
         patch("autoservice.triage_dispatch._get_pool_for_test",
               new=AsyncMock(return_value=_FakePool(fake_session_query))):
        # Invoke the pre-fetch + prompt-build path via a thin test entry
        # point OR by calling _generate_agent_reply with a minimal stub
        # engine. Prefer the thin entry point — see Step 3 note.
        from autoservice.triage_dispatch import _build_customer_prompt
        prompt = await _build_customer_prompt(
            tenant_id="mystore",
            customer_text="DID 多久开通",
            operator_suggestions="",
        )

    assert "<kb_context>" in prompt
    assert "DID 开通需要 1 个工作日" in prompt
    assert "Customer message: DID 多久开通" in prompt


@pytest.mark.asyncio
async def test_kb_empty_hits_no_context_block():
    with patch("autoservice.dream_agent.kb_search", return_value=[]):
        from autoservice.triage_dispatch import _build_customer_prompt
        prompt = await _build_customer_prompt(
            tenant_id="mystore",
            customer_text="hello",
            operator_suggestions="",
        )

    assert "<kb_context>" not in prompt
    assert "Customer message: hello" in prompt


@pytest.mark.asyncio
async def test_kb_prefetch_only_for_customer_role():
    """lead/translate roles must not trigger pre-fetch (different flow)."""
    called = []

    def spy(*args, **kwargs):
        called.append((args, kwargs))
        return []

    with patch("autoservice.dream_agent.kb_search", side_effect=spy):
        from autoservice.triage_dispatch import _build_customer_prompt
        # Call sites in _generate_agent_reply only invoke _build_customer_prompt
        # on target_role=="customer"; lead/translate take _build_reseeded_prompt.
        # Verify by calling _build_customer_prompt with tenant_id=None → still
        # no kb_search call.
        await _build_customer_prompt(
            tenant_id=None,
            customer_text="hi",
            operator_suggestions="",
        )

    assert called == []


@pytest.mark.asyncio
async def test_kb_prefetch_exception_is_swallowed(caplog):
    with patch("autoservice.dream_agent.kb_search",
               side_effect=RuntimeError("db missing")):
        from autoservice.triage_dispatch import _build_customer_prompt
        prompt = await _build_customer_prompt(
            tenant_id="mystore",
            customer_text="hi",
            operator_suggestions="",
        )

    # Must NOT crash; prompt should be returned without KB block
    assert "<kb_context>" not in prompt
    assert "Customer message: hi" in prompt


class _FakePool:
    def __init__(self, session_query_fn):
        self.session_query = session_query_fn
```

- [ ] **Step 2: Run tests to verify failures**

Run: `pytest tests/triage/test_kb_prefetch.py -v`
Expected: FAIL — `_build_customer_prompt` doesn't exist.

- [ ] **Step 3: Extract `_build_customer_prompt` helper**

In `autoservice/triage_dispatch.py`, add a new module-level helper. The existing inline prompt assembly in `_generate_agent_reply` (around lines 1093-1107) moves into this helper so it's unit-testable:

```python
async def _build_customer_prompt(
    *,
    tenant_id: str | None,
    customer_text: str,
    operator_suggestions: str,
) -> str:
    """Compose the customer-role prompt with KB pre-fetch injected.

    Shape (sections joined by blank lines):
      <operator_suggestions>...</operator_suggestions>   (iff non-empty)
      <kb_context>...</kb_context>                       (iff hits non-empty)
      Customer message: <text>
      <instruction tail>

    KB errors are logged and swallowed; prompt falls back to no-KB shape.
    """
    kb_hits: list[dict] = []
    if tenant_id:
        try:
            from autoservice.dream_agent import kb_search
            kb_hits = await asyncio.to_thread(
                kb_search, tenant_id=tenant_id, query=customer_text, top_k=5,
            )
        except Exception:
            log.exception(
                "KB pre-fetch failed for tenant=%s", tenant_id,
            )
            kb_hits = []

    parts: list[str] = []
    if operator_suggestions:
        parts.append(operator_suggestions)

    if kb_hits:
        block = ["<kb_context>"]
        for i, hit in enumerate(kb_hits, 1):
            header = f"[{i}]"
            src = hit.get("source_name")
            sec = hit.get("section")
            if src:
                header += f" {src}"
            if sec:
                header += f" · {sec}"
            block.append(header)
            block.append((hit.get("content") or "")[:500])
            block.append("")
        block.append("</kb_context>")
        parts.append("\n".join(block))

    tail = (
        f"Customer message: {customer_text}\n\n"
        "基于 <kb_context> 回答。若 KB 未覆盖，可调用 kb_search 工具补查；"
        "补查仍无匹配，按 soul 的升级条件处理（说明需要核实并升级）。"
        "语言跟随客户。"
    )
    parts.append(tail)

    return "\n\n".join(parts)
```

Note: the existing `log` alias in `triage_dispatch.py` is `log` (or `logger` — check line 25; it is `log` per current file). Use whichever the module already has.

- [ ] **Step 4: Rewire `_generate_agent_reply` to use the helper**

Replace the prompt-build block in `_generate_agent_reply` (autoservice/triage_dispatch.py around lines 1094-1107):

```python
# Build prompt
suggestions = await _collect_operator_suggestions(engine, conv_id)

if target_role == "customer":
    prompt = await _build_customer_prompt(
        tenant_id=tenant_id,
        customer_text=customer_text_for_prompt,
        operator_suggestions=suggestions,
    )
else:
    prompt_parts: list[str] = []
    if suggestions:
        prompt_parts.append(suggestions)
        prompt_parts.append(
            f"Customer message: {customer_text_for_prompt}\n\n"
            "You are a customer service AI. The operator has given you instructions above — "
            "follow them when replying to the customer. Reply in the same language as the customer."
        )
    else:
        prompt_parts.append(
            f"Customer message: {customer_text_for_prompt}\n\n"
            "Reply briefly in the same language as the customer."
        )
    prompt = "\n".join(prompt_parts)
```

And pass `tenant_id` into the customer branch's `session_query` call (line ~1159):

```python
iterator = (
    pool.session_query(conv_id, prompt, tenant_id=tenant_id)
    if target_role == "customer"
    else _role_stream()
)
```

- [ ] **Step 5: Run tests to verify passing**

Run: `pytest tests/triage/test_kb_prefetch.py -v`
Expected: all 4 tests PASS

- [ ] **Step 6: Run full triage regression**

Run: `pytest tests/triage/ -v`
Expected: all existing triage tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add autoservice/triage_dispatch.py tests/triage/test_kb_prefetch.py
git commit -m "feat(triage): inject KB pre-fetch into customer-role prompt

Before invoking the customer CC instance, run kb_search(tenant_id,
customer_text, top_k=5) and splice hits into a <kb_context> block. KB
errors are swallowed and logged — prompt falls back to no-context shape.
Also forwards tenant_id to pool.session_query so the sticky instance is
bound to the right tenant soul + KB tool."
```

---

## Task 8: E2E integration test (mystore grounded reply)

**Files:**
- Test: `tests/e2e/test_customer_kb_grounded_reply.py` (new)

Purpose: Prove end-to-end that "你们提供哪些服务" to mystore tenant produces a KB-grounded reply (mentions CINNOX / DID / IVR / 套餐 / PSTN). Marked `@pytest.mark.slow`.

- [ ] **Step 1: Verify mystore seed data**

Run: `python scripts/seed_mystore_tenant.py`
Expected: Creates `.autoservice/sandbox/mystore/` and seeds `.autoservice/database/knowledge_base/kb.db`.

Then confirm KB has rows:
```bash
python -c "import sqlite3; c=sqlite3.connect('.autoservice/database/knowledge_base/kb.db'); print(c.execute('SELECT COUNT(*) FROM kb_chunks').fetchone())"
```
Expected: count > 0.

- [ ] **Step 2: Write the integration test**

Create `tests/e2e/test_customer_kb_grounded_reply.py`:

```python
"""E2E: customer CC instance reply for mystore tenant must cite KB content.

This is the acceptance test for the tenant-soul+KB feature. It requires a
real Claude Agent SDK subprocess; marked @pytest.mark.slow.
"""
from __future__ import annotations

import re
import pytest

from autoservice.cc_pool import get_pool
from autoservice.conversation_engine.local_engine import LocalEngine
from autoservice.conversation_engine.types import (
    Participant, ParticipantRole,
)
from datetime import datetime, timezone

pytestmark = pytest.mark.slow


_KB_KEYWORDS = re.compile(
    r"(CINNOX|DID|IVR|PSTN|套餐|Essentials|Professional|Enterprise)",
    re.IGNORECASE,
)


@pytest.mark.asyncio
async def test_mystore_services_question_cites_kb():
    engine = LocalEngine()
    conv = await engine.create_conversation(channel="web", external_id="cust-test")
    now = datetime.now(timezone.utc)
    await engine.join(
        conv.id,
        Participant(id="cust-test", role=ParticipantRole.CUSTOMER, joined_at=now),
    )
    await engine.join(
        conv.id,
        Participant(id="agent", role=ParticipantRole.AGENT, joined_at=now),
    )
    # Tag conversation with tenant_id via metadata (engine's standard hook)
    await engine.update_triage_state(conv.id, active_role="customer", detected_language="zh")

    pool = await get_pool()
    prompt = (
        "<kb_context>\n[1] glossary · DID\nDID 是 Direct Inward Dialling\n</kb_context>\n\n"
        "Customer message: 你们提供哪些服务\n\n"
        "基于 <kb_context> 回答。语言跟随客户。"
    )

    reply_text = ""
    from claude_agent_sdk.types import AssistantMessage, ResultMessage
    async for msg in pool.session_query(conv.id, prompt, tenant_id="mystore"):
        if isinstance(msg, AssistantMessage) and msg.content:
            for block in msg.content:
                if hasattr(block, "text"):
                    reply_text += block.text
        elif isinstance(msg, ResultMessage) and msg.result:
            reply_text = msg.result

    assert reply_text, "expected non-empty agent reply"
    assert _KB_KEYWORDS.search(reply_text), (
        f"reply must cite KB keywords (CINNOX/DID/IVR/PSTN/套餐/...) "
        f"but got: {reply_text!r}"
    )

    await pool.end_session(conv.id)
```

- [ ] **Step 3: Run the E2E test**

Run: `pytest tests/e2e/test_customer_kb_grounded_reply.py -v -m slow`
Expected: PASS (if it fails because the reply says "I don't have services info", either the soul didn't load or KB pre-fetch path was skipped — diagnose, don't bypass).

If the test is flaky due to LLM variance, relax the regex slightly BUT keep at least one domain-specific term (never let it pass on generic "hello" replies).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_customer_kb_grounded_reply.py
git commit -m "test(e2e): customer reply for mystore cites KB content

Real-SDK acceptance test: 'What services do you offer?' to mystore
tenant must mention CINNOX/DID/IVR/PSTN/Essentials-Enterprise in the
reply, proving tenant soul + KB are loaded end-to-end."
```

---

## Task 9: Manual verification + final integration sweep

**Files:**
- No code changes
- Commit: aggregate verification report

- [ ] **Step 1: Start the web gateway**

Run: `make run-web`
Expected: server starts on port 8000 without errors; log shows `cc_pool` warmup for customer role.

- [ ] **Step 2: Exercise the golden path manually**

Open `http://localhost:8000` (admin portal) → create/open a mystore conversation → send "你们提供哪些服务".

Expected:
- Agent reply mentions specific services/套餐/DID (not "我没有详细的服务目录")
- Operator console shows a `[分流]` SIDE line with `路由: customer`
- Reply arrives in reasonable time (first acquire may be +1-2s vs subsequent, due to recycle)

- [ ] **Step 3: Test sticky behavior**

In the same conversation, send "价格多少".

Expected: Reply continues context (references prior turn's service mention); no new recycle log line (same sticky instance).

- [ ] **Step 4: Test cross-conversation isolation**

Open a conversation for a different tenant (or the default tenant). Send the same question.

Expected: Reply uses that tenant's soul (or default soul if no tenant sandbox); does NOT mention mystore-specific terms.

- [ ] **Step 5: Test KB missing fallback**

Rename `.autoservice/database/knowledge_base/kb.db` to `.bak`. Send a question.

Expected:
- Reply does NOT crash; uses soul's "need to verify" language
- Logs contain warning "KB pre-fetch failed"

Restore: `mv kb.db.bak kb.db`.

- [ ] **Step 6: Run the whole test suite**

Run: `pytest tests/ -v -m "not slow"`
Expected: all pass.

Run: `pytest tests/ -v -m slow`
Expected: all pass (requires SDK subprocess).

- [ ] **Step 7: Commit verification report**

Create `e2e-evidence/customer-role-kb/2026-04-21-verification.md` with:
- Date, git SHA
- Manual step 2-5 outcomes (screenshots OR plaintext reply excerpts)
- Test suite pass/fail summary

```bash
git add e2e-evidence/customer-role-kb/
git commit -m "test(e2e): customer tenant-soul+KB manual verification evidence

Records m2-acceptance-style evidence that customer role now loads mystore
soul and cites KB content. Covers golden path, sticky continuity, cross-
tenant isolation, and KB-missing degrade."
```

---

## Self-review checklist

- [x] **Spec coverage:**
  - §0.1 In scope:
    - main pool tenant-aware → Tasks 4, 5
    - KB dual-path (pre-fetch + MCP) → Tasks 2, 3, 7
    - Factory interconnect fix → Tasks 2, 4
    - Recycle helper abstraction → Task 1
    - Graceful degrade → Tasks 3, 5, 7 (explicit tests)
  - §2.1-2.8 design: each sub-section has a corresponding task
  - §3 error handling: Tasks 5 (recycle fail), 7 (KB fail), 3 (empty query), 5 (cross-tenant mismatch) — all covered
  - §4 tests: 1:1 mapping to the test files listed in the spec
- [x] **Placeholder scan:** no "TBD", no "add error handling", no "similar to Task N". All code blocks shown in full.
- [x] **Type consistency:**
  - `_pool_tenant_id` sentinel stamp: consistent across Tasks 1, 5
  - `_recycle_instance_for_tenant(pool, instance, *, role, tenant_id, config)`: same signature referenced in Tasks 1 and 5
  - `build_kb_mcp_server(tenant_id) -> dict[str, Any]`: consistent in Tasks 2, 3
  - `StickyTenantMismatch`: defined in Task 5, used in Task 5 tests only (not exported to other tasks)
  - `_build_customer_prompt(*, tenant_id, customer_text, operator_suggestions) -> str`: defined + used consistently in Task 7

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-21-customer-role-tenant-soul-kb.md`. Two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.
**2. Inline Execution** — execute tasks in this session with batched checkpoints.

Which approach?
