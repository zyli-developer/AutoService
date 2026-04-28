# Operator Web 租户数据隔离 — 设计文档

**Date**: 2026-04-28
**Author**: brainstorming session, hjj.gemini@gmail.com
**Scope**: Operator console (frontend/apps/operator-console) + 其消费的后端 API/WS
**Status**: Draft, pending implementation plan

---

## 1. 背景

AutoService 后端已经做了相当一部分多租户基础（`tenant_id` 概念、auth/sessions schema、`require_tenant_access` 装饰器、message_router 的会话粘性绑定、operator 表的 1:1 tenant 绑定、前端 `useTenantId` / `useSessionMode` hook、admin-portal 的 Master/Tenant 双 layout），但 **operator console 的"列表/查询"链路没有做租户过滤**，导致：

- 客服登录后通过 `GET /api/conversations/active` 看到**所有租户**的活跃会话卡片（用户已观察到的痛点）
- WS `subscribe` 作用域只含 `squad_id`，跨租户事件会被推到错误的 operator 客户端
- 多个 operator 数据源（SLA / billing / metrics / proposals）端点同样无租户过滤

> **注**：本仓根目录 2026-04-28-multi-tenant-gap-analysis.md 中关于 operator console 部分有多处不准确（e.g. 引用了未合并 worktree 的 `web_gateway.py`、误把 operators schema 标在 `auth.py`、误指 `operator-console/src/components/shell/AdminRail.tsx`）。本设计基于对 HEAD 代码的独立核对，不依赖该 gap 文档的结论。

## 2. 范围

### 2.1 In scope

只覆盖 operator console 直接消费的链路：

- 6 个 HTTP API endpoint（`/conversations/active`, `/sla/summary`, `/billing/invoices`, `/metrics/takeover-trend`, `/metrics/operator-leaderboard`, `/proposals`）
- WS subscribe 协议扩展（`scope.tenant_id`）
- `conversation_engine` 的 query 类方法签名变更（mandatory `tenant_id`）
- `gateway/message_router.py` 写入侧的 tenant_id 兜底
- 一次性 SQLite migration：把所有无 `metadata.tenant_id` 的历史 conversation 归到 `_master`
- 新增模块 `autoservice/auth_scope.py`（授权助手）
- 前端 `useOperatorWS.ts` 两处改动（subscribe + fetch 都带 `tenant_id`）
- 测试覆盖

### 2.2 Out of scope（单独 PR / 后续）

- **CRM / contacts 隔离**：`autoservice/crm.py` 的表 schema 没有 `tenant_id` 列。需要 schema migration + 4 个查询函数改造，工作量与 operator console 隔离独立，留给后续 PR
- **Feishu channel 注入 tenant_id**：CLAUDE.md §"Channel feature parity" 已标记 ❌ no tenant injection；需要 Feishu org_id ↔ AutoService tenant_id 的业务侧映射，未在范围内
- **KB row-level isolation**：当前 `kb_core` 是 file-level 隔离（`sandbox/<tid>/kb/kb.db`），已能避免跨租户查询；row-level 改造留给规模化场景
- **`/api/cc_pool/runtime`**：平台健康指标，本质跨租户聚合；如果需要按租户过滤是独立设计问题
- **operator 1:N tenant**：当前 `operators` 表是 1 行 1 个 tenant_id；本设计的 API/WS 协议留 `tenant_id` 参数口子，但 1:N 的 grants 表 / UI 切换器 / sessions schema 扩展不在范围

## 3. 设计前提（决策点）

四个核心决策都已在 brainstorming 中确认：

| 决策点 | 选择 | 含义 |
|------|------|------|
| Q1 operator ↔ tenant 关系 | C：1:1 + 前向兼容 | 现在每 operator 单 tenant；API/WS 协议保留 `tenant_id` 参数；未来切到 1:N 时仅 `auth_scope.py` 改实现，调用侧不动 |
| Q2 隔离执行点 | B：引擎层 mandatory | `conversation_engine` 查询方法签名 `tenant_id: str` 必填，无 `None` default。类型系统就拦下漏写 |
| Q3 存量与写入侧 | A：strict + 全归 `_master` | 一次性 migration 把所有无 `metadata.tenant_id` 的历史 conv 归到 `_master`；写入侧任何无 tenant_id 的路径强制兜底为 `_master` 并 warning |
| Q4 WS 推送过滤 | A：客户端显式声明 `scope.tenant_id` | subscribe scope 复合 key（`tenant:T1\|squad:S1`），服务端用 `auth_scope` 验证 ⊆ accessible_tenants，索引精确路由 |

## 4. 已具备的能力（不需要重做）

| 能力 | 位置 | 状态 |
|------|------|------|
| `operators` 表已有 `tenant_id NOT NULL` + UNIQUE(tenant_id, email) | `autoservice/operators.py:61-95` | ✅ |
| `GET /api/auth/operator/me` 返回 `tenant_id` | `autoservice/operator_routes.py:262-280` | ✅ |
| `require_tenant_access` 装饰器（验 path tenant ∈ session） | `autoservice/auth.py:431-492` | ✅ |
| 前端 `useTenantId()` hook（从 `/me` 读取） | `frontend/packages/shared/useTenantId.ts` | ✅ |
| `useSessionMode()` hook | `frontend/packages/shared/useSessionMode.ts` | ✅ |
| RBAC viewer/responder/admin 矩阵 | `autoservice/rbac.py:32-74` | ✅ |
| `_master` / `_local_admin` tier=0 内部租户标识 | `autoservice/master_tenant.py:34-56` | ✅ |
| `proposal_pipeline` 表已有 `tenant_id` 列（仅 query 没用） | `autoservice/proposal_pipeline.py:78` | ✅（写入端） |
| message_router 在 web channel 创建 conv 时已尝试盖 `metadata.tenant_id` | `autoservice/gateway/message_router.py:530-533` | ⚠️ 条件性，需要补刀 |

## 5. 架构

### 5.1 单一过滤入口：`autoservice/auth_scope.py`

新增模块，所有 tenant 过滤决策的唯一入口：

```python
from dataclasses import dataclass
from autoservice.auth import SessionRow

@dataclass(frozen=True)
class TenantScope:
    """An operator's tenant-access decision for one request/subscribe."""
    effective_tenant_id: str
    accessible_tenants: frozenset[str]
    is_platform_admin: bool  # tier=0 (_master / _local_admin)


def get_accessible_tenants(session: SessionRow) -> frozenset[str]:
    """1:1 today: returns {session.tenant_id}.
    Future 1:N evolution lives only here: add grants-table read.
    Tier-0 platform admins return frozenset() and rely on
    is_platform_admin gate instead.
    """
    ...


def resolve_effective_tenant(
    session: SessionRow,
    requested_tenant_id: str | None,
) -> TenantScope:
    """Decide which tenant_id this request operates on.

    Rules:
      - requested=None and tenant operator → effective = session.tenant_id
      - requested ∈ accessible → effective = requested
      - requested ∉ accessible AND not platform_admin → 403
      - platform_admin can pass any tenant_id including '_master'
    """
    ...
```

**关键不变量**：1:N 的演进只改这一个文件，所有调用点不动。

### 5.2 引擎层（B 路线）

`autoservice/conversation_engine/protocol.py`、`local_engine.py`、`sqlite_store.py` 中所有 query 类方法签名变更：

| 方法 | 旧签名 | 新签名 |
|------|------|------|
| `list_active_conversations` | `(*, operator_id, squad_id)` | `(*, tenant_id: str, operator_id, squad_id)` |
| `get_messages` | `(conv_id, viewer_role, limit)` | `(conv_id, *, tenant_id: str, viewer_role, limit)` |
| `list_conversations_in_takeover_by` | `(operator_id)` | `(*, tenant_id: str, operator_id)` |
| `get_conversation` | `(conv_id)` | `(conv_id, *, tenant_id: str)` — 验证 `conv.metadata.tenant_id == tenant_id`，不匹配 raise `TenantMismatch` |

实现：所有内存/持久化层的查询都加 `WHERE metadata.tenant_id = ?`（SQLite JSON1：`json_extract(metadata, '$.tenant_id') = ?`）。

**`tenant_id="_master"` 是合法显式值**（表示"我现在是 platform admin，要看 master / 跨租户视图"），不是 sentinel；调用侧通过 `auth_scope` 解析得到，引擎不做额外授权。

### 5.3 API 层（6 个端点）

每个端点都套同一模板：

```python
@api_router.get("/conversations/active")
async def list_active_conversations(
    request: Request,
    tenant_id: str | None = None,    # forward-compat (Q1 C 路线)
    squad_id: str | None = None,
    operator_id: str | None = None,
):
    session = require_operator_session(request)
    scope = resolve_effective_tenant(session, tenant_id)
    convs = await engine.list_active_conversations(
        tenant_id=scope.effective_tenant_id,
        operator_id=operator_id,
        squad_id=squad_id,
    )
    ...
```

涉及端点（`autoservice/api_routes.py`）：

1. `GET /conversations/active` (line 445) — 直接走 engine
2. `GET /sla/summary` (line 490) — `sla_aggregator` 加 `tenant_id` 参数
3. `GET /billing/invoices` (line 518) — 底层 query 加 `tenant_id`
4. `GET /metrics/takeover-trend` (line 534) — 同上
5. `GET /metrics/operator-leaderboard` (line 545) — 同上
6. `GET /proposals` (line 556) — `proposal_pipeline.list_proposals(tenant_id=...)`

每个底层 aggregator / pipeline 的 query 函数也要加 `tenant_id` 参数（沿用 B 路线"必填"规则）。

### 5.4 WS subscribe 协议（A 路线）

**前端** (`frontend/apps/operator-console/src/hooks/useOperatorWS.ts:145`)：

```typescript
const tenantId = useTenantId(); // already wired to /api/auth/operator/me
client.send('subscribe', {
  scope: { tenant_id: tenantId, squad_id: squadId },
});
```

**后端 subscribe handler**：

```python
scope_tid = scope.get("tenant_id")
tenant_scope = resolve_effective_tenant(session, scope_tid)
scope["tenant_id"] = tenant_scope.effective_tenant_id  # server overwrites for confirmation
```

**`subscription_registry._scope_key`** (`autoservice/gateway/subscription_registry.py:121-129`) 改为复合 key：

```python
def _scope_key(scope: dict[str, Any]) -> str | None:
    tid = scope.get("tenant_id")
    parts = []
    if tid:
        parts.append(f"tenant:{tid}")
    if scope.get("conversation_id"):
        # conv 已经隐含 tenant_id（conv.metadata），单独 key 即可
        return f"conv:{scope['conversation_id']}"
    if scope.get("squad_id"):
        parts.append(f"squad:{scope['squad_id']}")
    elif scope.get("global"):
        parts.append("global")
    return "|".join(parts) if parts else None
```

**事件发布侧**：engine 的 emit 路径已经能拿到 `conv.metadata.tenant_id`（migration 后所有 conv 都有），按 `tenant:T1|squad:S1` 等复合 key 索引订阅者。push 路径无需"先取候选再过滤"，索引直接命中。

`conv:` scope 不加 `tenant:` 前缀，因为 `conversation_id` 是全局唯一且 conv.metadata 已经隐含 tenant；订阅 conv 的客户端通过 `get_conversation(conv_id, tenant_id=...)` 在订阅时校验。

### 5.5 写入侧兜底

`autoservice/gateway/message_router.py:530-533`：

```python
# Before:
if ws is not None:
    tid = getattr(ws, "state_customer_tenant_id", None)
    if tid:
        meta["tenant_id"] = tid

# After:
tid = None
if ws is not None:
    tid = getattr(ws, "state_customer_tenant_id", None)
if not tid:
    logger.warning(
        "conv created without tenant_id, defaulting to _master: "
        "source=%s ws_state_keys=%s",
        source,
        list(getattr(ws, "state", {}).keys()) if ws else None,
    )
    tid = MASTER_TENANT_ID  # from autoservice.master_tenant
meta["tenant_id"] = tid
```

不允许 web channel 产出无 `tenant_id` 的 conversation。Feishu / 其他 channel 不在本次范围。

### 5.6 Migration

新建 `autoservice/migrations/2026_04_28_backfill_conv_tenant_id.py`，idempotent：

```sql
UPDATE conversations
SET metadata = json_set(metadata, '$.tenant_id', '_master')
WHERE json_extract(metadata, '$.tenant_id') IS NULL;
```

启动期 fixup（`local_engine.LocalEngine.__init__` 或类似的 cold-start hook）：扫描内存 `_conversations`，对没有 `metadata["tenant_id"]` 的写入 `_master` + warning（防止重启前未持久化的内存 conv 漏迁移）。

Migration 跑前后跑同一条 query 应当结果一致（idempotent 验证）。

### 5.7 前端改动清单

| 文件 | 改动 |
|------|------|
| `frontend/apps/operator-console/src/hooks/useOperatorWS.ts:145` | subscribe scope 加 `tenant_id` |
| `frontend/apps/operator-console/src/hooks/useOperatorWS.ts:152` | URL 加 `&tenant_id=${encodeURIComponent(tenantId)}` |

`useTenantId.ts` 不动，已经从 `/api/auth/operator/me` 拉到 tenant_id。`useSessionMode.ts` 不动。

## 6. 测试

新文件 `tests/operator_isolation/test_operator_console_tenant_isolation.py`（或拆分到对应模块下）：

| TC ID | 测试 |
|------|------|
| TC-1 | `list_active_conversations` 引擎方法不带 `tenant_id` 参数 → `TypeError`（B 路线类型守门） |
| TC-2 | 创建 T1/T2 各两条 conv，引擎调用 `list_active_conversations(tenant_id="T1")` 仅返回 T1 的 |
| TC-3 | `resolve_effective_tenant`：tenant operator T1 请求 `tenant_id="T2"` → 403 |
| TC-4 | `resolve_effective_tenant`：tier-0 platform admin 请求 `tenant_id="T2"` → 通过 |
| TC-5 | `resolve_effective_tenant`：requested=None → effective = session.tenant_id |
| TC-6 | API `GET /api/conversations/active` 不传 query 参数 → 仅返回 session.tenant_id 的 conv |
| TC-7 | API `GET /api/conversations/active?tenant_id=T2` 用 T1 operator session → 403 |
| TC-8 | WS `subscribe` scope `tenant_id=T2` 用 T1 operator session → 拒绝（错误事件 + close） |
| TC-9 | WS subscribe scope 不带 `tenant_id` → 服务端用 session.tenant_id 默认填入并回显 ack |
| TC-10 | WS event push：T1 conv 触发事件，T2 订阅者收不到（按复合 scope_key 路由验证） |
| TC-11 | `message_router` web 路径：`ws.state_customer_tenant_id` 缺失时，新建 conv 落到 `_master` 且 logger.warning 命中 |
| TC-12 | Migration idempotent：跑两次后 conv 表 `tenant_id` 分布一致 |
| TC-13 | Migration backfill：跑前有 N 条无 `metadata.tenant_id`，跑后该数量变为 0 |
| TC-14 | 6 个 API 端点均有"不传 tenant_id 用 session.tenant_id"和"传他人 tenant_id 拒绝"两组 case |

跨层 e2e（`tests/e2e/`）：两个 operator 登录两个 tenant，HTTP `/api/conversations/active` + WS `subscribe` 全程不见对方数据，断言 0 leakage。

## 7. 实施顺序与风险

| Step | PR 内容 | 风险 |
|------|------|------|
| 1 | Migration（含 idempotent test）+ 写入侧兜底 + 新增 `auth_scope.py`（独立可测） | 低；纯加法，不改任何调用签名 |
| 2 | **引擎签名改为 mandatory `tenant_id`，单 PR 原子** | **高**：blast radius 大，需 grep 所有 caller 一次性改完。漏一个 caller → CI 全红 |
| 3 | 6 个 API endpoint + 底层 aggregator/pipeline `tenant_id` 参数 | 中；按端点分别单测 |
| 4 | WS scope_key 复合化 + subscribe handler 验证 + push 路径验证 | 中；要兼容现有 squad-only 订阅（迁移期内） |
| 5 | 前端 `useOperatorWS` 两行改动 | 低 |
| 6 | E2E 测试 + 回归 | — |

**最大风险（Step 2）**：

- 缓解 1：在 PR 描述中粘贴 `grep -r 'list_active_conversations\|get_messages\|list_conversations_in_takeover_by\|get_conversation' --include='*.py'` 的完整结果，以 checklist 形式逐一勾选
- 缓解 2：所有测试与所有 caller 在同一 PR 内更新，**禁止跨 PR 拆分**
- 缓解 3：`master_dream` / `proposal_pipeline` / 任何后台任务的 caller 也要扫到（不只是 operator console 链路）

**写入侧兜底的风险**：`_master` 兜底可能掩盖真实的 tenant 解析 bug。缓解：`logger.warning` 必带，并在 `tests/observability/` 加一个测试断言"warning 触发"是异常路径而非常态。

## 8. 验收

完成以下即视为 operator console 多租户隔离就绪：

- [ ] 引擎层 4 个 query 方法签名 `tenant_id` 必填；不带参数调用直接 TypeError
- [ ] 6 个 operator-facing API 端点：默认走 session.tenant_id，传他人 tenant_id 返回 403
- [ ] WS subscribe `scope.tenant_id` 验证 ⊆ accessible，事件按复合 scope_key 精确路由
- [ ] Migration 跑后 `conversations` 表中 `metadata.tenant_id IS NULL` 的行数为 0；二次执行无变化
- [ ] message_router web 路径：无 ws.state_customer_tenant_id 时落 `_master` + warning
- [ ] E2E：两个 operator 各自登录 T1/T2，HTTP + WS 全程 0 跨租户数据泄漏
- [ ] 前端 `useOperatorWS` 两处都带 tenant_id（subscribe scope + fetch URL）

## 9. 参考与引用

- `2026-04-28-multi-tenant-gap-analysis.md`（本仓根，**不准确部分见本文 §1 末尾说明**）
- `docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md` — 租户 sandbox 基础设计
- `CLAUDE.md` §"Channel feature parity"（Feishu out-of-scope 的依据）
- `autoservice/master_tenant.py` — `_master` / `_local_admin` 内部租户语义
- `autoservice/operators.py:61-95` — operators 1:1 schema
- `autoservice/auth.py:431-492` — `require_tenant_access` 已有装饰器
- `autoservice/gateway/subscription_registry.py:21-129` — WS subscribe 数据结构

## 10. Open Questions

(none) — 所有核心决策点已在 brainstorming 中确认，剩余实现细节交给 implementation plan。
