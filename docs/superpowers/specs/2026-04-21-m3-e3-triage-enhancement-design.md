---
title: M3 Epic E3 · Triage Dispatch Enhancement
status: draft
date: 2026-04-21
prd_refs: [docs/prd/AutoService-M3-PRD.md §2 E3]
stories: [E3.1, E3.2, E3.3, E3.4]
---

# M3 Epic E3 — Triage Dispatch Enhancement

> 2026-04-21 · 承接 [M3 triage dispatch design §0.2 Out of scope](./2026-04-21-multi-role-triage-dispatch-design.md#02-out-of-scopem3).
>
> **一句话**：把 M2 triage dispatch 留下的 4 个坑填掉——SLA 精细监控（pool busy metrics + per-tenant 阈值 + operator 告警）、Handoff 协议（agent 主动切 role）、classify_intent 从 YAML 搬进 DB 给 admin 编辑、历史压缩服务给 re-seed 吃。

---

## 0. Scope 与和 M2 的连接

### 0.1 In scope（对应 PRD §2 E3）

- **E3.1 P1**：AsyncPool 暴露 busy/available/queue/wait-time 指标；SLAAggregator 接入 pool 等待时长；per-tenant SLA 阈值；AlertEngine → operator-console WS push（当前只推 admin）
- **E3.2 P1**：Agent 输出 `<handoff to="X">` tag parser；解析后触发 re-triage + role 切换 + sticky 释放；malformed tag 容错
- **E3.3 P2**：classify_intent 迁 SQLite（`classify_intent_config` 表）；seed from YAML；hot-reload；admin-portal 扩 keyword 编辑器（不独立页面，CON-10）
- **E3.4 P2**：History Compression 服务（>20 msg → LLM 摘要）；仅服务 triage re-seed（CON-11）；成本护栏

### 0.2 Out of scope（推 M4+）

- 跨 Epic 广泛使用 compression（dream 链路、customer 主回复），CON-11 明确只开 triage re-seed 口子
- SLA 指标 Prometheus/Grafana 导出（M3 内口径：operator-console WS push + per-record SIDE）
- Handoff 工具调用式（MCP tool）接口——M3 只做 inline tag
- classify_intent keyword 版本/审计回滚（只 last-write-wins）
- 非 triage 的 per-tenant 阈值（compression 的 LLM budget 允许 per-tenant；RBAC / operator-login 阈值归 Epic E1）

### 0.3 本 spec 与 [M3 triage dispatch design](./2026-04-21-multi-role-triage-dispatch-design.md) 的接续关系

| M2 spec §0.2 条目 | 本 spec 承接 |
|---|---|
| "SLA 精细监控：目标池等待时长、动态扩缩容、per-tenant SLA 告警" | §2.1 E3.1 |
| "Handoff 协议（agent 主动 `<handoff to="lead">` 标记）" | §2.2 E3.2 |
| "DB 化配置 + admin UI 编辑关键词" | §2.3 E3.3 |
| "长期历史摘要服务（超过 20 条的对话压缩）" | §2.4 E3.4（限于 triage re-seed） |
| "Path 2 summary-seeded 切换"（M2 认为比 history prefix 慢 ~1s） | 仍 M4+；E3.4 只做离线摘要，不给新 role prompt 走 Path 2 入口 |

---

## 1. Context & Problem Statement

### 1.1 M2 triage dispatch 承诺了什么

2026-04-21 的 [M3 triage dispatch design](./2026-04-21-multi-role-triage-dispatch-design.md)（以下简称 **"M2 triage spec"**，实装于 M2 批次）交付了 5 agent role 的 cc_pool 扩展、FastClassifier 快速分流、漂移探针、role 切换 re-seed、TRIAGE SIDE 消息广播。但留了 4 个"M3 收尾"项：

1. **SLA 只做 fallback、不做监控**（spec §0.2）：目标 role pool acquire 失败时降级到 customer 并写 SIDE 警告——这是"兜底"，不是"观测"。没有 pool busy metrics、没有等待时长直方图、没有 per-tenant 阈值、没有 alert 推送到 operator-console。
2. **没有 Handoff 协议**（spec §0.2 + 附录 A：*"Handoff — Agent 主动输出切换标记——本 spec 不实现"*）：切 role 只靠 drift probe（关键词命中变化），agent 不能主动说"我搞不定，给 lead"。
3. **关键词配置在 YAML 里**（spec §4.1-4.2）：全局 `autoservice/classify_intent.yaml` + tenant overlay 走 `plugins/<tid>/classify_intent.yaml` 或 `.autoservice/sandbox/<tid>/classify_intent.yaml`——admin 改关键词要走 git/file 编辑，没有 UI。
4. **Re-seed 塞 20 条原文历史**（spec §2.5）：role 切换时 prompt 前缀注入最近 20 条 public 历史。M2 加了 `tenant.history_reseed_token_limit` 截断保护，但没有摘要压缩——>20 条时后段历史直接丢掉。

### 1.2 为什么这 4 项都必须做

- **SLA**（E3.1）：生产部署没有 SLA 观测就无法定 alert policy、无法定容量、无法做 postmortem。PRD §6.1 明确验收 "pool 等待超阈值 → operator-console 告警"。
- **Handoff**（E3.2）：drift probe 只能识别"客户换话题"，不能识别"agent 自己判断该升级"。例子：customer agent 聊着聊着客户要报价，agent 应该能 `<handoff to="lead">`，而不是硬答。
- **DB 化**（E3.3）：Tenant admin 想新增关键词（比如 acme-legal 加"委托"到 purchase_intent）——M2 要求重 deploy fork，慢且危险。
- **压缩**（E3.4）：长对话里 role 切换时，20 条 tail 可能只覆盖最近 10 分钟对话。新 role 拿不到早期上下文会"失忆"。但 CON-11 严格限死：**M3 只服务 triage re-seed**，不铺到 customer / dream / translate。

### 1.3 决策优先级（PRD §5 决策 6）

> SLA 先、Handoff 后（CON-12）——SLA 是 M2 承诺项，Handoff 依赖 agent 成熟度。

本 spec 在 §6 Cross-cutting topics 中明确：**E3.2 / E3.4 代码可并行落 PR，但上线顺序是 E3.1 → E3.2 → E3.3 → E3.4**；E3.4 的 invoker 是 E3.2 的 role 切换路径，两者集成点在 §6.1。

---

## 2. Current State — 代码证据

### 2.1 E3.1 SLA 现状

- [autoservice/sla_aggregator.py:71-76](../../../autoservice/sla_aggregator.py#L71-L76) — 全局 `SLA_THRESHOLDS`，4 个 metric（first_reply_ms / accept_ms / ttfb_ms / csat_score）；**没有 pool_wait_time**。
- [autoservice/sla_aggregator.py:34-42](../../../autoservice/sla_aggregator.py#L34-L42) — `MetricType` enum 7 项（不含 pool metrics）。
- [autoservice/alert_engine.py:111-170](../../../autoservice/alert_engine.py#L111-L170) — AlertEngine + `_notify_fn` 回调已实现，window-based + per-record breach 双通道。
- [autoservice/alerts.yaml](../../../autoservice/alerts.yaml) — 4 条规则（first_reply / accept / csat / resolution_rate），**没有 pool_wait_time 规则**。
- [autoservice/web_gateway.py:285-326](../../../autoservice/web_gateway.py#L285-L326) — **AlertEngine 已接 `_push_alert_to_admins`**，推到 `_admin_connections`（admin WS），**不是 operator WS**。
- [socialware/pool.py:184-187](../../../socialware/pool.py#L184-L187) — AsyncPool 只暴露 `available_count`；**没有 busy / queue_length / wait_time_histogram**。

**关键发现**：gap-analysis 说"AlertEngine → operator-console WS push integration (connect _notify_fn to web_gateway)" 是 missing——**不准确**。`_notify_fn` 已接 `_admin_connections`，但 E3.1 的验收要求是推到 **operator-console**（PRD §6.1）。操作员和管理员是两个不同的连接池，所以 gap 仍然成立，只是性质从"线都没拉"变成"拉错目标"。

### 2.2 E3.2 Handoff 现状

- [autoservice/sentiment.py:69-73](../../../autoservice/sentiment.py#L69-L73) — `_SENTIMENT_PATTERN = re.compile(r"\[SENTIMENT:\s*(...)...\]")`——这是 inline tag parser 的现成模板。E3.2 tag 格式和解析方式应该对齐此范式。
- [autoservice/sentiment.py:76-92](../../../autoservice/sentiment.py#L76-L92) — `parse_sentiment()` 返回 `(result, cleaned_output)`——tag 从 agent 回复里抠掉。这是 agent 输出后处理的标准 hook 点。
- [autoservice/triage.py:82-229](../../../autoservice/triage.py#L82-L229) — `TriageAgent` 是入口分流器；**没有 re-triage API**，只在 `_generate_agent_reply` 前跑一次。
- [autoservice/cc_pool.py:368-387](../../../autoservice/cc_pool.py#L368-L387) — `session_query` sticky-bind 到 `chat_id`；`end_session` 可释放。E3.2 的 role 切换要走这条路径。
- [autoservice/cc_pool.py:393-454](../../../autoservice/cc_pool.py#L393-L454) — `acquire(role=..., tenant_id=...)` 已支持 role 切换；customer / dream / lead / translate / triage 全齐。

### 2.3 E3.3 DB-backed classify_intent 现状

- [autoservice/classify_intent.yaml](../../../autoservice/classify_intent.yaml) — 5 intent + keyword mapping + confidence thresholds + timeouts + model_tiers。YAML 是唯一事实源。
- [autoservice/model_router.py:60-69](../../../autoservice/model_router.py#L60-L69) — `_load_config()` 模块级 `_config` 缓存；**没有 invalidate / reload 入口**。
- [autoservice/model_router.py:91-114](../../../autoservice/model_router.py#L91-L114) — `FastClassifier.for_tenant(tenant_id)` + `clear_tenant_cache()` 已是 per-tenant 缓存，但底层走 `autoservice/tenant_triage_config.py`（YAML overlay）。
- 没有 SQLite `classify_intent_config` 表；没有 admin endpoints。

### 2.4 E3.4 History compression 现状

- [autoservice/crm.py:152-159](../../../autoservice/crm.py#L152-L159) — `get_contact_history(open_id, limit=50)` 拉原文，**无聚合**。
- [autoservice/gateway/message_router.py:905](../../../autoservice/gateway/message_router.py#L905) — `engine.get_messages(conv_id, viewer_role="operator", limit=200)`——拉原文，硬编码 limit。
- [autoservice/gateway/message_router.py:963](../../../autoservice/gateway/message_router.py#L963) — 另一处 `limit=50`。
- M2 re-seed 在 [triage spec §2.5](./2026-04-21-multi-role-triage-dispatch-design.md#L329-L361)：`_build_reseeded_prompt` 拉 20 条 public 历史塞前缀，用 token 上限截断——**没有摘要**。

---

## 3. Design per Story

### 3.1 E3.1 — SLA 精细监控

#### 3.1.1 Pool metrics surface

给 `socialware.pool.AsyncPool` 增加 snapshot API：

```python
@dataclass(frozen=True)
class PoolMetrics:
    pool_name: str                  # instance_prefix
    available_count: int            # 已有
    busy_count: int                 # 新增 = size - available_count
    total_size: int                 # 新增 = len(_all_instances)
    queue_length: int               # 新增 = 等待 acquire 的 waiter 数
    wait_time_ms_samples: list[float]  # 新增：最近 N 次 acquire 的 wait_time（ring buffer, N=256）

class AsyncPool:
    def snapshot(self) -> PoolMetrics: ...
```

实现要点：
- `queue_length`：`asyncio.Queue.qsize()` 不准（生产者端计数）——需要在 `acquire()` 里开/关 waiter counter，并用 `asyncio.Condition` 或内部 `_waiters: int` 字段维护。
- `wait_time_ms_samples`：`acquire()` 在 `await self._available.get()` 前记 `t0`、后算差值，写入 class 内 `collections.deque(maxlen=256)`。
- **不改 `acquire()` 热路径的 byte-for-byte 兼容**（M2 triage spec CON-06）：wait-time 记录可以走 `if self._metrics_enabled` flag 门控。

#### 3.1.2 Pool 等待时长 → SLAAggregator

新增 `MetricType`：
```python
class MetricType(str, Enum):
    # ... existing 7 ...
    POOL_WAIT_MS = "pool_wait_ms"    # acquire() 排队时长
    POOL_BUSY_RATIO = "pool_busy_ratio"  # busy_count / total_size, 0.0-1.0
```

接入点：
- `CCPool._acquire_role_pool()` 内 `async with pool.acquire()` 前后算 wait_time，调 `sla_aggregator.record(POOL_WAIT_MS, dt_ms, labels={"role": role, "tenant_id": tid})` —— **要求 SLAAggregator 加 `labels` 支持**（当前签名是 `record(metric, value, timestamp)`，没有 label 维度）。
- 定时器（可复用 DreamScheduler 同构 ticker，5s interval）调 `pool.snapshot()`，record `POOL_BUSY_RATIO`。

**label 扩展**：`SLAAggregator._buffers` 键从 `(metric, window)` 扩成 `(metric, window, label_key)`，`label_key` 用 `(role, tenant_id)` 序列化成 `"role=lead|tenant=acme"`。现有 4 个 metric 不传 `labels`（向后兼容），`POOL_*` 强制传。

#### 3.1.3 Per-tenant SLA 阈值

**选项 A**：DB 表 `sla_thresholds`（tenant_id, metric, limit, comparator, severity）+ admin UI；热更新。
**选项 B**：YAML 分层 — 全局 `alerts.yaml` + tenant overlay `plugins/<tid>/alerts.yaml`；重启生效。
**选项 C（推荐）**：混合——阈值默认值走 YAML（和现有 `alerts.yaml` 兼容），tenant 覆盖走 DB 表 `sla_threshold_overrides(tenant_id, rule_id, threshold, severity)`；AlertEngine `evaluate()` 时按 conversation.tenant_id 查覆盖。

选 C 的理由：
- `alerts.yaml` 是 spec §5.1 M2 已冻结的契约，不想引入向后不兼容
- tenant overrides 明显是"少数派"需求（大部分 tenant 用默认即可），DB 行数不会爆
- 只覆盖阈值不覆盖规则结构（不能 per-tenant 新增规则），减少 blast radius

**AlertEngine.evaluate() 改造**：
```python
def evaluate(self, tenant_id: str | None = None) -> list[FiredAlert]:
    for rule in self._rules:
        # 查 override
        effective_threshold = rule.threshold
        if tenant_id and (ovr := self._get_override(tenant_id, rule.id)):
            effective_threshold = ovr.threshold
        # ... 原有逻辑，用 effective_threshold
```

定时 evaluator 循环要按 tenant 分别调——目前是单租户部署（fork 模式）每个 fork 只有自己的 tenant_id；master 模式遍历 `DreamScheduler.list_active_tenants()`。

#### 3.1.4 AlertEngine → operator-console WS push

**当前状态**：[web_gateway.py:285-326](../../../autoservice/web_gateway.py#L285-L326) 把 alert 推到 `_admin_connections`（admin-portal）。

**E3.1 需求**：PRD §6.1 "Triage SLA 监控：pool 等待超阈值 → operator-console 告警"——operator-console 是另一个 WS 连接池。

**设计**：保留现有 admin push 路径；**追加** operator push 路径。
```python
async def _push_alert_to_operators(alert: FiredAlert) -> None:
    frame = build_frame("sla_alert", {...})
    for op_id, ws in list(_operator_connections.items()):
        # 按 conversation.tenant_id 过滤——operator 只看自己 tenant 的 alert
        if _operator_tenant_scope(op_id) == alert.tenant_id:
            await ws.send_json(frame)

alert_engine.set_notify(_push_alert_to_both)  # 组合 admin + operator
```

**备选事件通道**：复用 `conversation_engine.event_bus`（M2 已有 pub/sub），让 AlertEngine emit `sla.breach` event，两端都订阅。优点：通道一致性；缺点：event_bus 当前是 per-conversation scope，SLA alert 是 tenant-level，要扩 scope 支持——工作量比直接加 `_push_alert_to_operators` 大。

**选定**：直接加 `_push_alert_to_operators`（简单直接，符合 M2 现有架构风格）；未来如果 event_bus 升到 tenant scope 再收编。

#### 3.1.5 新 alert 规则

追加到 `alerts.yaml`：
```yaml
- id: alert-pool-wait
  name: "Role pool wait time breach"
  name_zh: "角色池等待时长超标"
  metric: pool_wait_ms
  window: 5m
  percentile: p95
  threshold: 2000
  severity: high
  cooldown_seconds: 300
  message_zh: "过去 5 分钟 role pool P95 等待 {value}ms，超过阈值 {threshold}ms"
  message_en: "Role pool P95 wait {value}ms exceeded {threshold}ms in last 5min"

- id: alert-pool-busy-ratio
  name: "Role pool saturation"
  metric: pool_busy_ratio
  window: 5m
  percentile: p95
  threshold: 0.9
  severity: medium
  cooldown_seconds: 600
  message_zh: "role pool 使用率 P95 达 {value:.0%}，超过阈值 {threshold:.0%}"
```

#### 3.1.6 Alternatives

- **Push vs pull metrics**：当前是 push（record at acquire time）。Pull（scraper endpoint `/metrics`）更标准但需要 Prometheus，M3 不引新依赖。选 push。
- **Per-tenant config DB vs YAML**：见 §3.1.3 选项 C。
- **Alert 内容做 i18n**：当前 alerts.yaml 有 `message_zh` / `message_en`；per-tenant 覆盖保持现有字段，不扩多语言。

### 3.2 E3.2 — Handoff 协议

#### 3.2.1 Tag 格式

```
<handoff to="lead" reason="customer requested quote">
```

必填属性：`to`（目标 role）；可选：`reason`（自由文本，log 到 TRIAGE SIDE 消息 metadata）。

**白名单**：`to ∈ {customer, lead, translate, triage}`（不能 `<handoff to="dream">`——dream 走后台链路不在对话热路径）。

#### 3.2.2 Parser 放哪

**候选位置**：
1. **Agent 输出后处理**（sentiment.py 同构）：agent 回复返回 `message_router._generate_agent_reply` 后、写入 conversation_engine 前。
2. **cc_pool 流式输出过滤器**：在 `session_query()` 的 `async for msg in instance.client.receive_response()` 里。
3. **conversation_engine.save_message() 中间件**：任何消息写入时检查。

**选定**：**选项 1**——和 `parse_sentiment` 对称；单一 hook 点；容易测试。在 `_generate_agent_reply` 最后一步把 raw agent output 传给新函数 `parse_handoff_tag(output) -> (HandoffRequest | None, cleaned_output)`，类似 `parse_sentiment` 的契约。

```python
_HANDOFF_PATTERN = re.compile(
    r'<handoff\s+to="(?P<to>customer|lead|translate|triage)"'
    r'(?:\s+reason="(?P<reason>[^"]{0,200})")?\s*/?>',
    re.IGNORECASE,
)

@dataclass(frozen=True)
class HandoffRequest:
    target_role: str
    reason: str | None

def parse_handoff(agent_output: str) -> tuple[HandoffRequest | None, str]:
    m = _HANDOFF_PATTERN.search(agent_output)
    if not m:
        return None, agent_output
    cleaned = (agent_output[:m.start()] + agent_output[m.end():]).rstrip()
    return HandoffRequest(
        target_role=m.group("to").lower(),
        reason=m.group("reason"),
    ), cleaned
```

#### 3.2.3 Re-triage trigger 契约

**流程**（eager re-triage）：
1. `_generate_agent_reply` 走完，拿到 raw agent output。
2. `parse_handoff(output) → (req, cleaned)`。
3. 若 `req is None`：走 M2 现有路径（写 cleaned 到 conversation_engine、返回）。
4. 若 `req` 有效：
   - **不发送** cleaned 文本给客户（原 agent 已经决定要 handoff，其回复内容可能半成品）
   - 写 SIDE 消息 `role=TRIAGE`，metadata：`{"type": "handoff", "from": prev_role, "to": req.target_role, "reason": req.reason}`
   - 释放旧 sticky 绑定：`cc_pool.release_sticky(conv_id)`
   - 更新 `conversation.active_role = req.target_role`
   - **同步调用** `_generate_agent_reply` 重入（一次性），新 role 走 re-seed path（M2 `_build_reseeded_prompt`，E3.4 开启时换 summary seed）
   - 新 role 生成的回复走 publish 路径

**幂等/防死循环**：
- 同一消息的 handoff 最多触发 **1 次 re-triage**（counter 存 `conversation_state.handoff_depth`）；第二次 handoff → 降级 customer role 并写 SIDE 警告 `handoff_loop_guard`。
- 目标 role 必须与当前 `active_role` 不同；相同视为 parser 失败，忽略 tag，发送 cleaned 文本。

**Alternative（lazy re-triage）**：把 cleaned 文本发给客户，下一条客户消息到达时才切 role。优点：延迟可控；缺点：客户可能看到"half-answer 再 handoff"的割裂体验。选 eager。

#### 3.2.4 Role switch 和 sticky 协议

复用 M2 triage spec §2.4 `acquire_sticky(conv_id, role, tenant_id)`：
- E3.2 的 handoff path 调 `release_sticky(conv_id)` 后 `acquire_sticky(conv_id, req.target_role, tenant_id)`——与 drift-probe-triggered switch 走同一函数，新旧 role 实例交接逻辑无分叉。

#### 3.2.5 Malformed / adversarial tag handling

| 情况 | 处理 |
|---|---|
| `<handoff to="hacker">` | regex 只匹配白名单；不命中视同无 tag |
| `<handoff to="dream">` | 同上——regex 白名单不含 dream |
| agent 输出 10 个 handoff tag | 只取第一个匹配（`re.search`）；其余留在 cleaned 里（其实 tag 已从 cleaned 删掉——选第一个就 OK） |
| 客户消息包含 `<handoff to="lead">`（注入攻击） | parser 只跑在 **agent output**——客户消息永远不过 `parse_handoff` |
| agent 在回复末尾加 `<handoff ...>` 但也产出长 PUBLIC 文本 | M2 选择"不发 cleaned"——因为 agent "决定交给别人了"，发半成品体验差。此行为进验收文档 |
| reason 超过 200 char | regex `[^"]{0,200}` 截断；parse 返 None（safer）或截前 200——**选后者**，写 SIDE metadata 不致命 |

#### 3.2.6 Alternatives

- **Inline tag vs MCP tool call**：选 tag。Tool call 要 agent SDK 支持 tool catalog + LLM function-call——M3 agent 们用 soul-prompt 驱动，加 tool 改架构大。tag 改 soul 一行"当你决定 handoff 时输出 `<handoff to="X">`"即可。
- **Eager vs lazy re-triage**：见 §3.2.3，选 eager。
- **Tag 支不支持 structured reason**（JSON）：选纯字符串。JSON 在 agent 输出里容易被 markdown code-fence 污染，regex 不好写。Metadata 需要结构化时让 reason 仍为字符串、metadata.intent 另走——E3.2 M3 版不做，Open Question 记一笔。

### 3.3 E3.3 — DB-backed classify_intent + admin UI

#### 3.3.1 SQLite 表结构

```sql
CREATE TABLE classify_intent_config (
    tenant_id TEXT NOT NULL,              -- "" 代表平台默认
    intent    TEXT NOT NULL,              -- product_inquiry / complaint / ...
    keywords  TEXT NOT NULL,              -- JSON array: ["买","购买",...]
    route_to  TEXT NOT NULL,              -- customer / lead / translate
    model_tier TEXT NOT NULL,             -- fast / slow
    priority  TEXT NOT NULL DEFAULT 'normal',
    description TEXT,
    updated_at REAL NOT NULL,             -- time.time()
    updated_by TEXT,                      -- admin_email or 'system'
    PRIMARY KEY (tenant_id, intent)
);

CREATE TABLE classify_intent_thresholds (
    tenant_id TEXT PRIMARY KEY,           -- 空字符串 = 平台默认
    high_conf  REAL NOT NULL DEFAULT 0.8,
    medium_conf REAL NOT NULL DEFAULT 0.6,
    low_conf  REAL NOT NULL DEFAULT 0.3,
    updated_at REAL NOT NULL
);
```

**存哪**：`.autoservice/database/tenant.db`（复用 tenant config 表所在库），或独立 `classify_intent.db`。选前者——减少连接、allow JOIN on tenant。

#### 3.3.2 Seed + migration

**首次启动**（startup hook）：
1. 检查 `classify_intent_config` 是否存在任何行
2. 若空：读 `autoservice/classify_intent.yaml` → 写 tenant_id="" 的 platform-default 行（5 个 intent 各一行）+ thresholds 行
3. 已有数据则跳过（idempotent）

**per-tenant seed**：tenant 首次被 Admin 打开 intent 编辑器且没有自己的 overlay 时，从 platform-default copy 5 行 + insert with `tenant_id=<tid>`。

**YAML overlay 向后兼容**（CON-03 non-breaking）：
- `FastClassifier.for_tenant(tid)` 加载逻辑：先查 DB（`tenant_id=tid`），再 fallback DB（`tenant_id=""`），最后 fallback YAML overlay（M2 现有路径）。
- YAML 路径保留至 M4（给想纯文件部署的用户）；DB 行存在就优先。

#### 3.3.3 Hot-reload 机制

**选项 A**：Polling——`FastClassifier._cache` 每 60s 查 `SELECT MAX(updated_at) FROM classify_intent_config WHERE tenant_id IN (?, '')`，变了就 invalidate。
**选项 B**：SQLite WAL notify——不跨进程，且 pysqlite 不稳定。pass。
**选项 C**：HTTP endpoint `/api/admin/classify-intent/reload` 由 admin UI 保存后显式触发，广播 `cache.invalidate` event 到 cc_pool workers。

**选定**：**A + C 组合**——UI 保存调 C 做即时生效；保留 A 做跨进程兜底（master 部署可能有多 worker，UI 保存只打到一个 worker）。Polling 间隔 60s 可调。

```python
class FastClassifier:
    _last_refresh: dict[str, float] = {}    # tenant_id → monotonic()
    _REFRESH_SEC = 60

    @classmethod
    def for_tenant(cls, tid):
        if cls._should_refresh(tid):
            cls._tenant_cache.pop(tid, None)
            cls._last_refresh[tid] = time.monotonic()
        return cls._get_or_load(tid)
```

#### 3.3.4 Admin endpoints（extension of admin-portal per CON-10）

```
GET    /api/admin/{tenant_id}/classify-intent           # list 5 intents + thresholds
PUT    /api/admin/{tenant_id}/classify-intent/{intent}  # update keywords/route_to/priority
POST   /api/admin/{tenant_id}/classify-intent/reset     # revert to platform default
POST   /api/admin/{tenant_id}/classify-intent/reload    # force cache invalidate
PUT    /api/admin/{tenant_id}/classify-intent-thresholds # update high/medium/low
```

**Auth**：复用 admin-portal magic-link session（M2 `admin_session` cookie），tenant_id 必须 = session.tenant_id（没有 cross-tenant 编辑，Epic E1 RBAC 定案后可扩 viewer/responder/admin 三级）。

**UI 形态**（admin-portal 新增 tab/panel 而非独立页——CON-10）：
- `/admin/settings` 下新增 "Intent Classifier" section
- 5 intent cards，每张：intent 名称 + keyword chip 列表（add/remove）+ route_to dropdown + priority radio
- "Reset to default" / "Save" / "Test" 按钮（"Test" 跑一条 sample message 看 FastClassifier 输出，不调 LLM）

#### 3.3.5 Alternatives

- **Per-tenant vs platform-default + override**：选后者（§3.3.1 两张表设计已体现）——减少 tenant 首次使用摩擦，只在 tenant 真正改了某个 intent 时插入行。
- **SQL schema 一张表 vs 两张**：选两张（config + thresholds）——thresholds 是全 tenant 共享一行，config 是 per-intent。合并会有大量 NULL。
- **Hot-reload：HTTP endpoint vs file watcher**：M3 不做 file watcher（yaml overlay deprecated 中）；HTTP endpoint 走 admin 手动保存，简单。

### 3.4 E3.4 — History Compression 服务

#### 3.4.1 触发时机（CON-11 限死）

**当且仅当**：`conversation.active_role` 切换（drift probe 触发 或 handoff 触发）**AND** `conversation.messages_count > 20`。

**不触发**：
- 客户消息到达不触发压缩（CON-11 明确 M3 仅 triage re-seed 用例）
- Dream 链路不使用（CON-11 留 M4+）
- customer agent 自己的多轮长对话不使用（同上）
- Takeover 模式切回 agent 时不触发（operator 已看全量历史；且切回时无 role 改变）

#### 3.4.2 Input/Output 契约

```python
@dataclass(frozen=True)
class CompressedHistory:
    conv_id: str
    summary: str                    # <= summary_max_chars（默认 2000）
    tail: list[Message]             # 最近 N 条（默认 N=5）原文
    compressed_from_seq: int        # 压缩截止 sequence_number
    compressed_to_seq: int          # 保留的最老原文的前一条
    created_at: float
    model: str                      # "haiku" | "sonnet"
    token_cost_input: int
    token_cost_output: int

async def compress_history(
    engine: ConversationEngine,
    conv_id: str,
    *,
    summary_max_chars: int = 2000,
    tail_n: int = 5,
    model_tier: ModelTier = ModelTier.FAST,  # 默认 haiku
) -> CompressedHistory: ...
```

**Re-seed 流程改造**（替换 M2 `_build_reseeded_prompt`）：
- 若 `messages_count <= 20`：保持 M2 行为（原文 20 条前缀）
- 若 `messages_count > 20`：
  1. 查缓存 `compressed_history_cache[conv_id]`（LRU, TTL=300s）
  2. 缓存 miss → 跑 `compress_history`，落 DB `conversation_summaries` 表（conv_id + summary + compressed_to_seq）
  3. 构造 prompt：
     ```
     <conversation_summary>
     {summary}
     </conversation_summary>
     <recent_messages>
     [seq={tail[0].seq}] {role}: {text}
     ...
     </recent_messages>
     Current customer message: {customer_text}
     You are now the {new_role} agent. Continue from the summary + recent messages above.
     ```

#### 3.4.3 LLM 成本预算护栏

| 护栏 | 值 | 说明 |
|---|---|---|
| 模型 | haiku（default） | triage 同款，便宜 |
| Summary max input tokens | 8k | 超出则先按 sequence DESC 截断老消息 |
| Summary max output | 512 tokens | 保证 `summary_max_chars` 不爆 |
| Per-tenant daily budget | $5/天 | 配置项，default 写死；超出后 fallback M2 原文截断 + 写 SIDE 警告 `compression_budget_exceeded` |
| Per-conversation throttle | max 1 次/30s | 防连续切 role 导致重复调用 LLM |
| Cache | in-memory LRU 500 条 + DB 持久化 | 同 conv_id 多次 role 切换复用同一 summary（直到有新消息来） |

**Budget tracking**：新表 `compression_cost_log(tenant_id, ts, conv_id, tokens_in, tokens_out, cost_usd)`；daily aggregate 查询。

#### 3.4.4 Alternatives

- **Summary only vs summary + tail**：选后者。纯 summary 丢最近细节（客户可能刚问的具体问题），tail=5 保证新 role 至少知道 immediate context。
- **Caching strategy**：per-conv_id cache（选）vs per-(conv_id, seq_cutoff) cache。后者不缓存——新消息到达后下次切 role 肯定 miss。选前者 + TTL invalidate on new message。
- **Model 选择**：默认 haiku；tenant 可配 sonnet（Open Question 1）。
- **压缩什么维度**：单一 summary（选）vs structured JSON（topics / entities / decisions）。结构化更准但 agent prompt 反而更难用。M3 简单字符串。

---

## 4. Data Model 改动

### 4.1 SQLite migrations

新 migration（追加到 M2 现有 alembic / manual migration 链）：

```sql
-- E3.1
CREATE TABLE sla_threshold_overrides (
    tenant_id TEXT NOT NULL,
    rule_id   TEXT NOT NULL,
    threshold REAL NOT NULL,
    severity  TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (tenant_id, rule_id)
);

-- E3.3
CREATE TABLE classify_intent_config (...);        -- §3.3.1
CREATE TABLE classify_intent_thresholds (...);    -- §3.3.1

-- E3.4
CREATE TABLE conversation_summaries (
    conv_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    compressed_to_seq INTEGER NOT NULL,
    created_at REAL NOT NULL,
    model TEXT NOT NULL,
    token_cost_input INTEGER,
    token_cost_output INTEGER
);
CREATE TABLE compression_cost_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    conv_id TEXT NOT NULL,
    ts REAL NOT NULL,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL
);
CREATE INDEX idx_compression_cost_ts ON compression_cost_log(tenant_id, ts);
```

### 4.2 conversation_state 新增字段（E3.2）

```python
@dataclass
class ConversationState:
    # M2 已有
    active_role: str | None
    cc_instance_id: str | None
    # E3.2 新增
    handoff_depth: int = 0           # 本次消息触发的 handoff 链深度（防循环）
    last_handoff_reason: str | None  # 审计
```

`handoff_depth` 每处理完一条客户消息 reset 为 0；re-triage 进入 +1；>1 即 loop guard。

### 4.3 TRIAGE SIDE message metadata 扩展（E3.2）

现有（M2 triage spec §2.6）：
```json
{"type":"triage_decision","intent":"...","confidence":0.xx,"route_to":"...","source":"...","previous_role":"..."}
```

新增 handoff 类型：
```json
{"type":"handoff","from":"customer","to":"lead","reason":"customer asked for quote","depth":1}
```

---

## 5. 配置 schema

### 5.1 Tenant config 新增（`plugins/<tid>/config.yaml`）

```yaml
tenant:
  # E3.1
  sla_thresholds:               # 覆盖 alerts.yaml 默认
    pool_wait_ms_p95: 1500       # 默认 2000ms
    first_reply_ms_p95: 3000
  # E3.2
  handoff_enabled: true          # false 时 parser 跳过，向后兼容
  handoff_max_depth: 1           # 单次消息最多 N 次 handoff
  # E3.4
  history_compression_enabled: true
  compression_budget_usd_per_day: 5.0
  compression_model: haiku       # haiku | sonnet
  compression_tail_n: 5
```

### 5.2 Alerts.yaml 扩展

追加 `alert-pool-wait` 和 `alert-pool-busy-ratio`（见 §3.1.5）。

### 5.3 Source of truth 纪律（跨 story）

| 配置项 | 源 | 生效机制 |
|---|---|---|
| Alert 规则定义（id、metric、window、percentile、阈值默认） | `alerts.yaml` | 启动加载 |
| Tenant 阈值覆盖 | DB `sla_threshold_overrides` | AlertEngine `evaluate(tenant_id)` 时查 |
| Classify intent keyword + route | DB `classify_intent_config`（fallback YAML） | 60s polling + HTTP reload |
| Confidence thresholds | DB `classify_intent_thresholds`（fallback YAML） | 同上 |
| Compression budget / model choice | `tenant.config.yaml` | 启动加载；改了需要 restart（M4 转 DB 再说） |

**讨论**：同一范围内出现 YAML + DB 的原因：keyword 编辑是高频 admin 操作要 DB + hot-reload；compression budget 是低频运维参数，YAML 够用。不追求"全部 DB"以保持部署可理解性。

---

## 6. Cross-cutting topics

### 6.1 E3.2 Handoff 调 E3.4 Compression

**调用契约**：E3.2 的 re-triage path 只负责"判断该切 role"；执行切换时调用 E3.4 compression service（若启用且 >20 msgs）。

```python
# message_router._generate_agent_reply 内部
handoff_req, cleaned = parse_handoff(output)
if handoff_req:
    conv_state = await engine.get_state(conv_id)
    if conv_state.handoff_depth >= tenant.handoff_max_depth:
        # loop guard
        await engine.save_message(role=TRIAGE, metadata={"type":"handoff_loop_guard",...})
        await engine.save_message(role=AGENT, text=cleaned, ...)
        return

    await cc_pool.release_sticky(conv_id)
    # E3.4 集成点
    if tenant.history_compression_enabled and conv_state.messages_count > 20:
        compressed = await compressor.get_or_build(conv_id, tail_n=tenant.compression_tail_n)
        prompt = _build_compressed_reseeded_prompt(compressed, customer_text, handoff_req.target_role)
    else:
        prompt = _build_reseeded_prompt(engine, conv_id, customer_text, prev_role, handoff_req.target_role)

    conv_state.active_role = handoff_req.target_role
    conv_state.handoff_depth += 1
    # re-enter _generate_agent_reply_inner(prompt, role=handoff_req.target_role)
```

**两个契约说清楚**：
1. Compression service **不知道** 调用方是 handoff 还是 drift probe——它只吃 conv_id，返 summary+tail。
2. Handoff path **不实现压缩**——它只判断要不要切，压缩由 compressor 决定命中缓存还是重算。

### 6.2 Metrics / alert delivery 端到端

```
AsyncPool.acquire()  ──[wait_time_ms 上报]──▶  SLAAggregator.record(POOL_WAIT_MS, dt, labels)
                                                    │
                           ┌─────── per-record breach (同步 cb) ──┐
                           ▼                                         ▼
                   _on_per_record_breach  ──▶  _admin_connections WS  ──▶  admin-portal
                                          ──▶  _operator_connections WS  ──▶  operator-console

    定时 tick (5s) ──▶  AlertEngine.evaluate(tenant_id)  ──▶  window aggregate alerts
                                                                 │
                                                                 ▼
                                                         同上两个 WS 通道
```

**关键：operator WS 按 tenant_id 过滤**（operator 只看自己 tenant）；admin WS 不过滤（platform admin 看所有）。

### 6.3 Config source-of-truth 纪律

见 §5.3 表格。**原则**：
- **启动态低频**参数（feature flag、budget 上限）→ YAML。
- **运行态高频**参数（keyword 列表、per-tenant 阈值）→ DB + hot-reload。
- **契约骨架**（alert 规则 id/metric/window） → YAML（稳定，改了要 code review）。
- YAML 和 DB 不冲突：DB 存在时 override YAML；DB 空 = 用 YAML fallback。

---

## 7. Test Strategy

### 7.1 Unit tests

| 测试文件（新增） | 覆盖点 | Story |
|---|---|---|
| `tests/pool/test_metrics_surface.py` | `snapshot()` 返回正确的 busy/queue/wait_time；wait_time ring buffer 满了后覆盖最老 | E3.1 |
| `tests/sla/test_pool_metrics_integration.py` | `CCPool._acquire_role_pool` 上报 POOL_WAIT_MS；labels 透传 | E3.1 |
| `tests/sla/test_per_tenant_thresholds.py` | Override 覆盖生效；无 override 时用 YAML 默认 | E3.1 |
| `tests/alert/test_operator_push.py` | Operator WS 收到只属于自己 tenant 的 alert；admin WS 收到全量 | E3.1 |
| `tests/handoff/test_handoff_parser.py` | 白名单命中 / 非法 target / malformed / client injection / reason 截断 | E3.2 |
| `tests/handoff/test_handoff_loop_guard.py` | handoff_depth > max → SIDE warning + cleaned 文本发出 | E3.2 |
| `tests/handoff/test_re_triage_flow.py` | release_sticky → acquire new role → re-seed → 新 role 回复流式输出 | E3.2 |
| `tests/classify_intent/test_db_backed_config.py` | Seed from YAML / tenant override / fallback 链 | E3.3 |
| `tests/classify_intent/test_hot_reload.py` | UPDATE after 60s → FastClassifier 看到新 keywords | E3.3 |
| `tests/classify_intent/test_admin_crud.py` | PUT endpoint / auth / cross-tenant 403 | E3.3 |
| `tests/compression/test_compress_history.py` | 20 条 input → summary <= max_chars；tail=5 | E3.4 |
| `tests/compression/test_budget_guardrails.py` | daily budget 超 → fallback + SIDE warning | E3.4 |
| `tests/compression/test_cache.py` | 同 conv_id 连续两次 role 切换只调 1 次 LLM | E3.4 |

### 7.2 Integration tests

| 测试 | 场景 | Stories |
|---|---|---|
| `tests/e2e/test_handoff_e2e.py::test_full_handoff_flow` | customer agent 输出 `<handoff to="lead">` → 新 role 接管 → 客户收到 lead 的回复 | E3.2 |
| `tests/e2e/test_handoff_e2e.py::test_long_conv_handoff_uses_compression` | 30 条历史 → handoff → summary prompt（非原文） | E3.2 + E3.4 |
| `tests/e2e/test_sla_alert_e2e.py::test_pool_saturation_triggers_operator_alert` | 填满 pool → wait > 阈值 → operator WS 收到 frame | E3.1 |
| `tests/e2e/test_intent_hot_reload_e2e.py` | 保存 keywords → 下一条消息分类到新 intent | E3.3 |

### 7.3 Load tests

- `tests/load/test_pool_metrics_accuracy.py`：100 并发 acquire → snapshot.busy_count == 100；wait_time_p95 < N
- `tests/load/test_sla_aggregator_perf.py`：10k record/s 下 `record()` < 0.1ms

### 7.4 回归守护

- `tests/triage/`, `tests/cc_pool/`, `tests/conversation/`, `tests/gateway/` 全绿
- M2 acceptance suite（`tests/e2e/test_m2_acceptance.py`）不 regress
- `autoservice/classify_intent.yaml` 删掉（本 spec 不删）时，FastClassifier 仍能用 DB platform-default → YAML 删不删是 M4+ 决策

---

## 8. Open Questions

1. **Per-tenant SLA 阈值在 M3 是否必须？** PRD §2 E3.1 只说 "per-tenant SLA 阈值"——没说所有 4 个 metric 都要支持 override。提案：M3 只开放 `pool_wait_ms` 和 `first_reply_ms` 两个高频的；其他 M3.5 加。
2. **Handoff tag 是否支持 structured reason？** 当前 `reason="..."` 是自由字符串。要不要 `reason_code="escalation|barrier|...."` 枚举？——便于 analytics，但 agent soul 要改。提案：M3 先字符串，M4 看 analytics 需求再加 code。
3. **E3.4 compression 的 LLM 模型**：默认 haiku（便宜、快）。会不会出现 summary 质量不够害新 role 误判？要不要给 tenant 选 sonnet？当前 §5.1 `tenant.compression_model` 已留 knob，但默认值需要定。提案：默认 haiku，tenant 可升级 sonnet，配 daily budget 保护。
4. **E3.3 keyword 编辑权限**：viewer 还是 admin 才能改？在 E1.4 RBAC 上线前走 M2 `admin_session`（任意 admin 可改）；E1.4 后降级为 `admin` tier 才能改。需要和 E1.4 设计对齐。
5. **Pool metrics label dimension 爆炸**：`(role, tenant_id)` 组合在 master 部署下可能几十个 tenant × 5 role = 几百个时间序列。SLAAggregator ring buffer 内存 OK，但 alert 评估成本线性增长。提案：AlertEngine 只 evaluate 活跃 tenant（最近 5 分钟有消息的）。
6. **Compression cache 失效策略**：§3.4.3 说"新消息到达后 invalidate TTL"——但要不要立即失效？客户说一句话就把 summary 作废重算太贵。提案：TTL 5 分钟 + 新消息数 > 10 强制失效。

---

## 9. Non-goals

- 广泛扩 compression 到 dream / customer / translate 链路（CON-11 M4+）
- Handoff 到非白名单 role（`dream`、自定义 role）
- 替换 M2 triage dispatch（本 spec 只**补丁**）
- classify_intent 版本控制 / 回滚（last-write-wins）
- SLA metrics 外部导出（Prometheus / OpenTelemetry——M4+）
- Operator 告警 mobile push / email（M3 只 WS frame；notify 渠道推 M4+）
- Compression 产物给客户可见（永远只 agent prompt 内部用；summary 不写 PUBLIC message）
- E3.1 动态扩缩容（PRD §2 E3.1 没要求，本 spec 不做）

---

## 10. 兼容性与 Rollout

### 10.1 Feature flags

| Flag | Default | 作用 |
|---|---|---|
| `tenant.handoff_enabled` | `true` | false → parse_handoff 短路，退回 M2 行为 |
| `tenant.history_compression_enabled` | `true`（长对话 >20 条时） | false → 长对话 re-seed 走 M2 原文截断 |
| `tenant.pool_metrics_enabled` | `true` | false → AsyncPool.snapshot 返空 metrics；不做 SLA 上报 |
| `tenant.intent_db_backed` | 自动检测（DB 有行即 true） | 保留 M2 YAML 路径；DB 迁移可 rollback |

### 10.2 Rollout 顺序（对齐 PRD §5 决策 6）

1. **E3.1 SLA**（M2 承诺项，先做）：AsyncPool metrics → SLAAggregator 扩展 → alert 规则 → operator WS push → per-tenant override
2. **E3.2 Handoff**（独立可并行开发；依赖 agent soul 更新 prompt）：parser → re-triage flow → loop guard → SIDE metadata
3. **E3.3 DB-backed classify_intent**（P2，不阻塞 E3.1/E3.2）：schema → seed → endpoints → admin UI → hot-reload
4. **E3.4 Compression**（P2，集成点是 E3.2）：compress_history → cache → budget → 集成到 `_build_reseeded_prompt`

**并行机会**：E3.3 / E3.4 可在 E3.1 / E3.2 开发中同时启动（无代码冲突）；但 E3.4 的集成测试要等 E3.2 落地。

---

## 附录 A · 术语

| 术语 | 定义 |
|---|---|
| Handoff | Agent 主动在回复里插 `<handoff to="X">` tag，触发 role 切换——本 spec 实装 |
| Loop guard | 同一条客户消息里 handoff 深度 ≥ `handoff_max_depth` 时的兜底 |
| Per-tenant threshold override | `sla_threshold_overrides` 表里的 tenant 维度覆盖 |
| Platform-default intent config | `classify_intent_config` 里 `tenant_id=""` 的行 |
| Compression tail | 压缩后仍以原文保留的最后 N 条消息 |
| Compression budget | 每 tenant 每天允许花在 summary LLM 调用的美元上限 |

## 附录 B · 与其他 spec 的边界

| Spec | 关系 |
|---|---|
| [2026-04-21-multi-role-triage-dispatch-design.md](./2026-04-21-multi-role-triage-dispatch-design.md) | 本 spec **直接承接**其 §0.2 四项 deferred；不改 §2.1-§2.5 的核心流程 |
| [2026-04-20-tenant-sandbox-m2-design.md](./2026-04-20-tenant-sandbox-m2-design.md) | 共享 tenant config 路径；本 spec 新增 tenant-level feature flags 和 DB 表 |
| [2026-04-18-admin-portal-web-layout-design.md](./2026-04-18-admin-portal-web-layout-design.md) | E3.3 的 keyword editor 是 admin-portal 扩展 section；非独立页面 |
| [2026-04-17-takeover-release-design.md](./2026-04-17-takeover-release-design.md) | Takeover 模式下 handoff 不触发（客户消息不过 _generate_agent_reply）——无冲突 |
| 未来 M3 E1 (Identity & RBAC) | E3.3 admin endpoint auth 当前用 M2 `admin_session`；E1.4 上线后升级为 tier-gated |

---

*v0.1 · 2026-04-21 · draft — 待 A review 后开工；对应批次 B-M3-4 (SLA + Handoff) + B-M3-6 (DB config + compression)*
