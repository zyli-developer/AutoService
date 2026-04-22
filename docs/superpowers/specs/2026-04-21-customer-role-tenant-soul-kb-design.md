# Customer Role · Tenant Soul + KB Access — Design

> 2026-04-21 · 承接 [multi-role triage dispatch](./2026-04-21-multi-role-triage-dispatch-design.md) §1.1 step 7。
>
> **一句话**：把 customer role 的 CC 实例接上 tenant-specific soul 和 tenant KB，让客户提问"你们提供哪些服务"时能基于商户知识库给出准确回答，而不是降级到"我没有详细的服务目录"。

---

## 0. Scope

### 0.1 In scope

- **main pool tenant-aware**：customer 走 main pool（保留 warmup + sticky）的同时，按 dream pool 模板在 `acquire_sticky` 时按需 recycle 出带 tenant soul 的实例。
- **KB 双路接入（hybrid）**：
  - Pre-fetch RAG：每条客户消息先 `kb_search(tenant_id, customer_text, top_k=5)`，命中结果拼进 prompt 的 `<kb_context>` 块。
  - MCP 工具：向 customer CC 实例暴露 `kb_search(query, top_k)` MCP 工具，`tenant_id` 闭包注入，agent 自己决定是否补查。
- **Factory 接线修正**：main pool factory 传 `role="customer"` 和 `tenant_id`，使 [cc_pool.py:289](../../../autoservice/cc_pool.py#L289) 的 soul 加载逻辑真正触发。
- **Recycle helper 抽公共**：把 dream pool 已有的"warm 实例 soul 不匹配时重建"逻辑（[cc_pool.py:866-932](../../../autoservice/cc_pool.py#L866-L932)）抽成 `_recycle_instance_for_tenant(inst, role, tenant_id, cfg)`，dream + customer 复用。
- **降级保底**：recycle 失败、tenant_id 缺失、KB 查询失败都走 graceful 降级，不影响主回路。

### 0.2 Out of scope

- **lead / translate / triage / dream 子池不改**：它们已经走 `_acquire_role_pool` 并注入 tenant soul（见 [cc_pool.py:543-544](../../../autoservice/cc_pool.py#L543-L544)）；本 spec 只补齐 customer 这一环。
- **KB 引擎升级**（vector search / rerank）：沿用现有 FTS5 `kb_search`（[dream_agent.py:231](../../../autoservice/dream_agent.py#L231)），质量问题后续单独 spec。
- **soul 行为调优**：若 KB 命中但 agent 仍回"不知道"，是 soul 迭代问题，不是本 spec 的系统 bug。
- **Per-tenant 独立进程部署**：多租户生产形态下每 tenant 一个 deployment，recycle 只在 dev / demo 单进程多 tenant 场景触发。
- **lead / translate 也接入 KB**：需要时再单独设计，本轮不碰。
- **Conversation engine / triage 决策 / gateway 路由**：无变动。

---

## 1. 架构总览

### 1.1 数据流

```
客户消息到达 _generate_agent_reply
  │
  ├─ triage_and_route (已有，不动)
  │    → decision.role, decision.previous_role
  │
  ├─ [新] KB pre-fetch (仅 target_role == "customer")
  │    hits = await asyncio.to_thread(
  │      kb_search, tenant_id, customer_text, top_k=5,
  │    )
  │
  ├─ [新] prompt 组装带 <kb_context>
  │    <operator_suggestions>...</operator_suggestions>  (可选)
  │    <kb_context>
  │      [1] {source_name} · {section}
  │      {content}
  │      ...
  │    </kb_context>
  │    Customer message: <text>
  │    基于 <kb_context> 回答；不足可调用 kb_search 工具；仍无则按 soul 升级。
  │
  ├─ [改] pool.session_query(conv_id, prompt, tenant_id=...)
  │    → acquire_sticky(conv_id, tenant_id=...)
  │         - 若 sticky 已绑定 && tenant 匹配 → 返回
  │         - 若 sticky 已绑定 && tenant 不匹配 → StickyTenantMismatch（不该发生）
  │         - 未绑定 → 从 warm 池取实例
  │                  → _recycle_instance_for_tenant(inst, "customer", tenant_id, cfg)
  │                    若 warm inst 的 _pool_tenant_id ≠ target → close + 重建
  │                  → 打 _pool_tenant_id 标签 → sticky 绑定
  │
  └─ agent 生成回复
       - system_prompt = tenant 的 customer_soul.md (或默认 soul 兜底)
       - mcp_servers 含 autoservice_kb（暴露 kb_search 工具，tenant_id 闭包）
       - prompt 已含 KB pre-fetch 片段
```

### 1.2 和现有代码的关系

| 模块 | 现状 | 本 spec 改动 |
|------|------|------------|
| [autoservice/cc_pool.py](../../../autoservice/cc_pool.py) | main pool factory 不传 role/tenant；dream pool 有自己的 recycle 逻辑 | main factory 传 role="customer"；抽 `_recycle_instance_for_tenant` 公共函数；dream 复用新 helper |
| [autoservice/cc_pool.py](../../../autoservice/cc_pool.py) `acquire_sticky` | 从 main pool 取，不考虑 tenant | 接受 `tenant_id` kwarg；按需 recycle；sticky 绑定记 `_pool_tenant_id` |
| [autoservice/triage_dispatch.py](../../../autoservice/triage_dispatch.py) `_generate_agent_reply` | customer 分支调 `pool.session_query(conv_id, prompt)` | 调用前做 KB pre-fetch；传 `tenant_id`；prompt 组装插 `<kb_context>` |
| [autoservice/cc_pool.py](../../../autoservice/cc_pool.py) `create_cc_client` | 接受 `role`/`tenant_id`/`system_prompt`/`mcp_servers` | 新增 `enable_kb_tool=True`：tenant_id 非空时自动注入 `autoservice_kb` MCP server |
| [autoservice/kb_mcp_server.py](../../../autoservice/kb_mcp_server.py) | 不存在 | 新建：`build_kb_mcp_server(tenant_id)` → SDK-type MCP server with `kb_search` tool |
| [socialware/pool.py](../../../socialware/pool.py) | `acquire_sticky(chat_id)` | 若签名不接受额外 kwarg，加 `**kwargs` 穿透；不影响现有行为 |
| [autoservice/dream_agent.py](../../../autoservice/dream_agent.py) `kb_search` | 已有，不动 | 作为 pre-fetch 和 MCP tool 的共同底层函数 |

---

## 2. 设计详情

### 2.1 `create_cc_client` 扩展

```python
async def create_cc_client(
    config: PoolConfig,
    mcp_servers: dict | None = None,
    system_prompt: str | None = None,
    role: str | None = None,
    tenant_id: str | None = None,
    enable_kb_tool: bool = True,  # 新增
) -> CCClient:
    ...
    # 现有 soul 加载逻辑不动 (line 289-295)

    # 新增：tenant_id 非空 && enable_kb_tool → 注入 KB MCP server
    if enable_kb_tool and tenant_id:
        from autoservice.kb_mcp_server import build_kb_mcp_server
        kb_server = build_kb_mcp_server(tenant_id)
        mcp_servers = {**(mcp_servers or {}), "autoservice_kb": kb_server}
    ...
```

**开关含义**：
- 默认 `True`：customer / lead / translate 等在业务路径上需要 KB
- 传 `False`：triage / dream 不需要 KB tool（triage 只做分类；dream 通过自己的 tool-use loop 直接调 Python 函数）

### 2.2 Main pool factory 改造

```python
# cc_pool.py CCPool.__init__
super().__init__(
    config=cfg,
    factory=lambda: create_cc_client(
        cfg,
        mcp_servers=mcp_servers,
        system_prompt=system_prompt,
        role="customer",          # 新增：warmup 用默认 customer soul
        tenant_id=None,           # 新增：warmup 时 tenant 未定，后续 recycle
        enable_kb_tool=False,     # warmup 无 tenant 不装 KB tool
    ),
    instance_prefix="cc",
    logger=log,
    on_sticky_release=on_sticky_release,
)
```

Warmup 实例：`role=customer` + `tenant_id=None` + 无 KB tool。打 `_pool_tenant_id=None` 标签。

### 2.3 `_recycle_instance_for_tenant` 公共 helper

抽出 dream pool 已有逻辑（[cc_pool.py:866-932](../../../autoservice/cc_pool.py#L866-L932)）：

```python
async def _recycle_instance_for_tenant(
    inst: PooledInstance[CCClient],
    *,
    role: str,
    tenant_id: str | None,
    config: PoolConfig,
) -> PooledInstance[CCClient]:
    """If inst's pinned tenant_id differs from target, close and rebuild.

    Returns the (possibly new) instance, tagged with _pool_tenant_id=target.
    On rebuild failure: logs, re-raises — caller decides degrade path.
    """
    current = getattr(inst, "_pool_tenant_id", "_UNSET_")
    if current == tenant_id:
        return inst  # 复用

    # tenant 不匹配 → close + rebuild
    try:
        await inst.client.disconnect()
    except Exception:
        log.warning("inst disconnect failed during recycle; continuing")

    new_client = await create_cc_client(
        config,
        role=role,
        tenant_id=tenant_id,
        enable_kb_tool=(role == "customer" and tenant_id is not None),
    )
    inst.client = new_client
    inst._pool_tenant_id = tenant_id
    return inst
```

Dream pool 现有的内联 recycle 代码替换为调用此 helper；行为等价（不回归）。

### 2.4 `acquire_sticky` 扩展

```python
async def acquire_sticky(
    self, chat_id: str, *, tenant_id: str | None = None,
) -> PooledInstance[CCClient]:
    existing = self._sticky_map.get(chat_id)  # 具体字段名以 socialware 实现为准
    if existing is not None:
        bound_tenant = getattr(existing, "_pool_tenant_id", None)
        if bound_tenant == tenant_id:
            return existing
        raise StickyTenantMismatch(
            f"conv {chat_id} already sticky-bound to tenant={bound_tenant}, "
            f"refusing rebind to tenant={tenant_id}"
        )

    # 未绑定 → 从 warm 池取 → recycle
    # 具体 API 以 socialware.pool.AsyncPool 现有 acquire_sticky 从哪拿实例为准
    # （当前实现走父类内部 _pop_idle / 新建 instance，不改这层语义）
    inst = await self._sticky_pop_or_new(chat_id)
    try:
        inst = await _recycle_instance_for_tenant(
            inst, role="customer", tenant_id=tenant_id, config=self._config,
        )
    except Exception:
        log.exception(
            "recycle failed for conv=%s tenant=%s; binding un-recycled instance",
            chat_id, tenant_id,
        )
        # 降级：用未 recycle 的 warm 实例（无 tenant soul，但流程不中断）

    self._bind_sticky(chat_id, inst)
    return inst
```

### 2.5 `session_query` 透传 tenant_id

```python
async def session_query(
    self, chat_id: str, prompt: str, *, tenant_id: str | None = None, **kwargs,
) -> AsyncIterator[Message]:
    instance = await self.acquire_sticky(chat_id, tenant_id=tenant_id)
    ...
```

调用端 [triage_dispatch.py:1159](../../../autoservice/triage_dispatch.py#L1159)：
```python
iterator = (
    pool.session_query(conv_id, prompt, tenant_id=tenant_id)
    if target_role == "customer"
    else _role_stream()
)
```

### 2.6 KB pre-fetch 逻辑

加在 [triage_dispatch.py:_generate_agent_reply](../../../autoservice/triage_dispatch.py#L1040) 内，triage 决策之后、prompt 组装之前：

```python
kb_hits: list[dict] = []
if tenant_id and target_role == "customer":
    try:
        from autoservice.dream_agent import kb_search
        kb_hits = await asyncio.to_thread(
            kb_search, tenant_id=tenant_id, query=customer_text, top_k=5,
        )
    except Exception:
        logger.exception("KB pre-fetch failed for conv=%s tenant=%s", conv_id, tenant_id)
        kb_hits = []
```

### 2.7 Prompt 组装

```python
parts: list[str] = []
if suggestions:
    parts.append(suggestions)

if kb_hits:
    kb_block = ["<kb_context>"]
    for i, hit in enumerate(kb_hits, 1):
        source = hit.get("source_name") or ""
        section = hit.get("section") or ""
        content = (hit.get("content") or "")[:500]  # 单条 500 字符上限
        header = f"[{i}]"
        if source:
            header += f" {source}"
        if section:
            header += f" · {section}"
        kb_block.append(header)
        kb_block.append(content)
        kb_block.append("")
    kb_block.append("</kb_context>")
    parts.append("\n".join(kb_block))

parts.append(f"Customer message: {customer_text_for_prompt}\n\n"
             "基于 <kb_context> 回答。KB 未覆盖可调用 kb_search 工具补查。"
             "补查仍无匹配则按 soul 的升级条件处理。语言跟随客户。")

prompt = "\n\n".join(parts)
```

### 2.8 KB MCP server (`autoservice/kb_mcp_server.py`)

```python
"""In-process SDK-type MCP server exposing kb_search to customer CC instances.

tenant_id is captured via closure — agent cannot alter which tenant's KB it
queries. Returns at most top_k=5 results, each with content/source/section.
"""
from __future__ import annotations

from typing import Any

from autoservice.dream_agent import kb_search as _kb_search


_MAX_TOP_K = 5


def build_kb_mcp_server(tenant_id: str) -> dict[str, Any]:
    """Return an SDK-type MCP server config with a single tool: kb_search.

    The tenant_id argument is captured in closure. The agent has no way to
    override it — enforcing per-tenant isolation at the tool layer (belt-and-
    suspenders on top of pool-level isolation).
    """
    async def _handle_kb_search(args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query", "")
        top_k = min(int(args.get("top_k", 3)), _MAX_TOP_K)
        rows = _kb_search(tenant_id=tenant_id, query=query, top_k=top_k)
        return {"results": rows}

    return {
        "type": "sdk",
        "name": "autoservice_kb",
        "tools": [{
            "name": "kb_search",
            "description": (
                "Search this tenant's knowledge base. Use when pre-fetched "
                "<kb_context> is insufficient to answer the customer."
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
                        "default": 3,
                        "maximum": _MAX_TOP_K,
                    },
                },
                "required": ["query"],
            },
            "handler": _handle_kb_search,
        }],
    }
```

**具体 SDK-type 语法以 `claude_agent_sdk` 实际 API 为准**（实现阶段需查 SDK 文档对齐）。

---

## 3. 错误处理 + 降级

| 场景 | 行为 |
|------|------|
| KB pre-fetch 异常 | 空 hits，不含 `<kb_context>`，agent 按"无 KB 匹配"话术；warning log，不中断 |
| MCP 工具调用异常 | SDK 自动返回 tool error，agent 可决定重试或放弃；不包装 |
| Recycle reconnect 失败 | warning log；用未 recycle 的 warm 实例（原 behavior）；SIDE 警告：`"[系统] customer 池实例创建失败，本轮无 tenant 上下文"` |
| `tenant_id=None` | 不 recycle、不注入 soul、不开 KB pre-fetch、不装 MCP tool；走裸路径 |
| 同 conv 跨 tenant | `StickyTenantMismatch` 异常；调用端捕获 → SIDE 警告 + 走降级路径 |
| KB 命中但 agent 回"不知道" | 超出本 spec 范围（soul 迭代问题） |

---

## 4. 测试策略

### 4.1 单测

| 文件 | 覆盖点 |
|------|--------|
| `tests/cc_pool/test_recycle_helper.py` | `_recycle_instance_for_tenant`：tenant 匹配跳过；不匹配 close + rebuild；rebuild 失败抛异常 |
| `tests/cc_pool/test_acquire_sticky_tenant.py` | 首次绑定触发 recycle；二次绑定直接复用；跨 tenant 抛 `StickyTenantMismatch` |
| `tests/cc_pool/test_customer_factory_args.py` | 回归锁：main pool factory 必须带 `role="customer"` |
| `tests/cc_pool/test_dream_pool_unchanged.py` | dream 复用新 helper 后行为不变（现有 dream 测试全绿） |
| `tests/triage/test_kb_prefetch.py` | hits 非空 → prompt 含 `<kb_context>`；空 → 不含；仅 customer role 触发；lead/translate 不触发 |
| `tests/triage/test_kb_mcp_tool.py` | MCP server 构造；tenant_id 闭包隔离（agent 传 tenant_id 参数无效）；top_k 夹到 5 |

### 4.2 集成测（`@pytest.mark.slow`）

`tests/e2e/test_customer_kb_grounded_reply.py`：
- 启动 mystore tenant 的 web_gateway
- 模拟客户发送"你们提供哪些服务"
- 断言回复文本包含以下关键词至少一个：`CINNOX` / `DID` / `IVR` / `套餐` / `PSTN`
- 断言 triage SIDE 消息的 `route_to` 是 `customer`

### 4.3 手工验证清单

1. `make run-web` → 用 mystore tenant 发"你们提供哪些服务" → 回复应该提到具体套餐/DID/IVR
2. 同对话追问"价格多少" → sticky 生效，同实例，延续上下文
3. 切到其他 tenant 对话 → 使用该 tenant 的 soul（或默认 soul 兜底）
4. 故意把 `.autoservice/database/knowledge_base/kb.db` 改名 → 回复不崩，按"无 KB 匹配"话术处理 + warning log 可见

---

## 5. 实施边界

### 5.1 文件改动清单

- **改**：[autoservice/cc_pool.py](../../../autoservice/cc_pool.py)
  - `create_cc_client` 加 `enable_kb_tool` 参数
  - `CCPool.__init__` factory 传 `role="customer"` + `enable_kb_tool=False`
  - 新增 `_recycle_instance_for_tenant`；dream pool 改调此 helper
  - `acquire_sticky` 支持 `tenant_id` kwarg
  - `session_query` 透传 `tenant_id`
- **改**：[autoservice/triage_dispatch.py](../../../autoservice/triage_dispatch.py)
  - `_generate_agent_reply` 加 KB pre-fetch 段
  - prompt 组装加 `<kb_context>`
  - `pool.session_query` 调用传 `tenant_id`
- **改**：[socialware/pool.py](../../../socialware/pool.py)（若需要）
  - `acquire_sticky` 签名加 `**kwargs` 穿透
- **新增**：[autoservice/kb_mcp_server.py](../../../autoservice/kb_mcp_server.py)
  - `build_kb_mcp_server(tenant_id)`

### 5.2 不改动的

- conversation_engine、triage 决策逻辑、gateway 路由
- lead / translate / triage / dream 现有子池路径
- KB 存储引擎 / FTS5 实现
- soul 内容本身

### 5.3 兼容性

- `tenant_id=None` 路径完全等价现有行为（无 tenant 时不注入、不查 KB）
- Dream pool 的 recycle 通过新 helper 实现，对外行为不变（现有 dream 测试全绿 = 验证）
- 已有 `pool.session_query(conv_id, prompt)` 调用（若存在）不传 `tenant_id` 时走兼容路径

---

## 6. 实施顺序建议（留给后续 plan）

1. 抽 `_recycle_instance_for_tenant` helper，dream pool 迁移到 helper（行为不变）
2. `create_cc_client` 加 `enable_kb_tool`；main pool factory 带 role="customer"
3. `acquire_sticky` / `session_query` 穿透 `tenant_id`
4. 新建 `kb_mcp_server.py`
5. `_generate_agent_reply` 加 KB pre-fetch + prompt 组装
6. 单测 → 集成测 → 手工验证

每步都可独立提交 + 独立回归。
