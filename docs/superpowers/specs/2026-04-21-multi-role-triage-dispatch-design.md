# Multi-Role Triage Dispatch — Design

> 2026-04-21 · 承接 [M2 tenant-sandbox design](./2026-04-20-tenant-sandbox-m2-design.md)。
>
> **一句话**：把现有 5 个 agent role（customer / lead / translate / triage / dream）中的 translate / lead / triage 真正接入对话热路径——客户消息先经 FastClassifier 快速分流、边界情况升级到 triage agent 仲裁，按意图路由到 customer / lead / translate 之一产回复。triage 输出到 operator side channel，dream 继续走现有后台链路不受影响。

---

## 0. Scope

### 0.1 In scope

- **Triage 链路接通**：`_generate_agent_reply()` 前插入 `triage_and_route()`——FastClassifier 快路径 + 低置信升级到 triage agent
- **cc_pool 支持 5 个 role**：`customer / lead / translate / triage / dream`，非 customer/dream 的三个走**懒加载 per-(role, tenant) 子池 + reaper**
- **Sticky 绑定升级为 per-(role, conv_id)**：conversation 状态新增 `active_role` / `cc_instance_id` / `detected_language`；role 切换释放旧绑定建新绑定
- **会话级 triage 缓存 + 漂移探针**：FastClassifier 每条都跑（本来就要跑），连续 2 条与缓存不一致且新 role 高置信 → invalidate + re-triage
- **role 切换时 history re-seed**：切换后首条 prompt 前缀塞最近 20 条 public 历史（token 上限可调）
- **语言检测接入**：启发式 + langdetect 兜底，`ModelRouter.route_message()` 内部一次性搞定；barrier = detected NOT IN `tenant.supported_languages`
- **`classify_intent.yaml` 租户级 overlay**：`plugins/<tid>/classify_intent.yaml`（fork）或 `.autoservice/sandbox/<tid>/classify_intent.yaml`（master）deep-merge 全局
- **Triage 输出到 SIDE channel**：新 message role `TRIAGE`，落 conversation_engine 供 operator 订阅；低置信附带摘要
- **SLA 最小守护**：目标 pool acquire 失败 → 降级到 customer + 写一条 SIDE 警告消息
- **关键词冲突清洗**：T0 洗 `classify_intent.yaml`（价格、问题、英文补全等）

### 0.2 Out of scope（推到 M3+）

- **Path 2 summary-seeded 切换**（triage agent 产摘要喂新 role）——Q6 评估后证实比 history prefix 慢 ~1s，收益有限
- **Handoff 协议**（agent 主动 `<handoff to="lead">` 标记）——Q3 C 选项，等 agent 智能成熟后再加
- **Translate as modality wrapper**（customer 产完再过 translate 润色）——延迟翻倍、架构不符；真出现强术语一致性需求再考虑
- **DB 化配置 + admin UI 编辑关键词**——M2 yaml overlay 够用，M3/M4 升级
- **SLA 精细监控**：目标池等待时长探测、动态扩缩容、per-tenant SLA 告警——M2 只做 fallback，M3 独立设计
- **长期历史摘要服务**（超过 20 条的对话压缩）——通用问题，不在本 spec 范围
- **Dream 链路改动**——dream 现有实现不动

---

## 1. 架构总览

### 1.1 数据流（单条客户消息）

```
┌─ customer message 到达 message_router ─┐
│                                         │
│  1. FastClassifier.classify(msg, lang)  │ ~20ms
│     └─ detect_language() + keyword 打分  │
│                                         │
│  2. 取 conversation.active_role (缓存)   │ ~5ms
│                                         │
│  3. 漂移探针                             │
│     if 新决策 != 缓存                    │
│       累加 drift_counter                 │
│     else                                │
│       reset drift_counter                │
│                                         │
│  4. 分派决策                             │
│     若 confidence >= 0.6 且 (无漂移      │
│       或 drift_counter < 2) →           │
│       直接用 FastClassifier 结果          │
│     否则 →                               │
│       acquire(role="triage") 跑 triage  │ +600-1200ms
│       agent，用它的结论                   │
│                                         │
│  5. 写 SIDE message (role=TRIAGE)        │ ~5ms
│     给 operator 订阅者                   │
│                                         │
│  6. 更新 conversation.active_role       │ ~5ms
│                                         │
│  7. acquire(role=decided_role, conv_id) │
│     若新 role ≠ 旧 role：                │
│       释放旧 sticky 绑定                  │
│       history re-seed: 最近 20 条 public │
│       新 role 首次 prompt 前缀塞历史      │
│                                         │
│  8. session_query(prompt) → 流式回复     │
│                                         │
│  9. 失败降级：acquire 失败 →              │
│     SIDE 警告 + 回到 customer role       │
└─────────────────────────────────────────┘
```

### 1.2 组件图

```
                          ┌─────────────────┐
                          │  message_router │
                          │   ._generate_   │
                          │   agent_reply() │
                          └───────┬─────────┘
                                  │
                                  ▼
                       ┌──────────────────────┐
                       │  triage_and_route()  │ ← 新增
                       └──────────┬───────────┘
                                  │
          ┌───────────────────────┼────────────────────────┐
          ▼                       ▼                        ▼
┌──────────────────┐   ┌────────────────────┐   ┌────────────────────┐
│ ModelRouter      │   │ conversation_engine│   │ cc_pool            │
│ .route_message() │   │ .save_message(     │   │ .acquire(          │
│                  │   │   role=TRIAGE,     │   │   role=<decided>,  │
│ - detect_lang    │   │   visibility=SIDE) │   │   conv_id=,        │
│ - FastClassifier │   │                    │   │   tenant_id=)      │
│ - 升级到          │   │ .set_conv_state(  │   │                    │
│   cc_pool        │   │   active_role,     │   │ - customer: 主池    │
│   .acquire(      │   │   detected_lang,   │   │ - dream: _acquire_ │
│   role="triage") │   │   cc_instance_id)  │   │   dream (已有)      │
│   when conf<0.6  │   │                    │   │ - lead/translate/  │
└──────────────────┘   └────────────────────┘   │   triage: 懒子池    │
                                                 │   _acquire_role_   │
                                                 │   pool() (新)       │
                                                 └────────────────────┘
```

### 1.3 和现有代码的关系

| 模块 | 现状 | 本 spec 改动 |
|------|------|------------|
| [autoservice/cc_pool.py](../../../autoservice/cc_pool.py) | `customer` + `dream` 两个 role | 扩展 `_KNOWN_ROLES`，抽 `_acquire_role_pool(role, tenant_id)`；lead/translate/triage 走新通用路径 |
| [autoservice/model_router.py](../../../autoservice/model_router.py) | FastClassifier 完整 / 低置信硬塞 customer | 保留 FastClassifier；改 `route_message()` 低置信→触发 triage agent（不再硬塞 customer） |
| [autoservice/triage.py](../../../autoservice/triage.py) | 独立 smart triage 类，未被任何 caller 调 | 重定位为"triage agent 调用编排器"；实际语义移到 `agents/triage/soul.md` |
| [autoservice/classify_intent.yaml](../../../autoservice/classify_intent.yaml) | 全局一份 / 关键词有冲突 | 增加 overlay 加载；清洗冲突 |
| [autoservice/gateway/message_router.py](../../../autoservice/gateway/message_router.py) | `_generate_agent_reply` 直接跑默认池 | 前置 `triage_and_route()`，用返回的 role checkout |
| conversation_engine state schema | `mode / participants / messages` | 新增 `active_role` / `cc_instance_id` / `detected_language` / `drift_counter` / `triage_mode` |
| conversation_engine message role enum | CUSTOMER / AGENT / OPERATOR / SYSTEM | 新增 `TRIAGE` |
| [agents/triage/soul.md](../../../agents/triage/soul.md) | 已存在，定义 5 意图 + 输出格式 | 不改（本 spec 按此 soul 实装） |

---

## 2. 组件设计

### 2.1 ModelRouter.route_message()

**签名**（新增）：
```python
@dataclass
class TriageDecision:
    role: str                       # "customer" | "lead" | "translate"
    confidence: float               # 0.0 - 1.0
    source: Literal["fastpath", "triage_agent", "fallback"]
    intent: str                     # product_inquiry / purchase_intent / ...
    detected_language: str | None   # zh / en / ja / ...
    summary: str | None             # 低置信才填
    needs_operator_notice: bool     # confidence < 0.6 为 True

async def ModelRouter.route_message(
    self,
    message: str,
    tenant_config: TenantConfig,
    conv_id: str | None = None,   # 有 conv_id 时会查/写 drift_counter
) -> TriageDecision:
    ...
```

**流程**：
```python
1. lang = detect_language(message)                  # heuristic + langdetect
2. 若 lang NOT IN tenant_config.supported_languages:
     return TriageDecision(role="translate", confidence=0.9,
                          source="fastpath", intent="language_barrier",
                          detected_language=lang, ...)
3. fast_result = FastClassifier.classify(message, lang)
4. 若 conv_id 提供:
     cached_role = conversation.get_active_role(conv_id)
     若 fast_result.route_to != cached_role:
       drift_counter = conversation.incr_drift(conv_id)
     否则:
       conversation.reset_drift(conv_id)
5. 决策:
   - 若 fast_result.confidence >= 0.6 且 (无缓存 或 drift_counter < 2 或 drift 低置信):
       return TriageDecision(role=fast_result.route_to,
                            confidence=fast_result.confidence,
                            source="fastpath", ...)
   - 否则:
       return await self._invoke_triage_agent(
         message, tenant_id, conv_id, fast_result
       )
```

**triage agent 调用**（`_invoke_triage_agent`）：
```python
async def _invoke_triage_agent(
    self, message, tenant_id, conv_id, fast_result,
) -> TriageDecision:
    try:
        async with cc_pool.acquire(
            role="triage", tenant_id=tenant_id, timeout=2.0
        ) as instance:
            prompt = self._render_triage_prompt(message, fast_result)
            raw = await instance.one_shot_query(prompt)
            parsed = self._parse_triage_output(raw)  # 解 [分流] 格式
            return TriageDecision(
                role=parsed.route_to,
                confidence=parsed.confidence,
                source="triage_agent",
                intent=parsed.intent,
                summary=parsed.summary,
                detected_language=fast_result.detected_language,
                needs_operator_notice=parsed.confidence < 0.6,
            )
    except (asyncio.TimeoutError, PoolExhausted):
        # 降级：用 fast_result，operator 会看到 low-confidence SIDE
        return TriageDecision(
            role=fast_result.route_to, confidence=fast_result.confidence,
            source="fallback", ...,
        )
```

**Parser 约定**：triage agent 的输出必须可 regex 解析。格式（见 [agents/triage/soul.md:50-55](../../../agents/triage/soul.md#L50-L55)）：
```
[分流] 意图: {intent} | 信心: {confidence} | 路由: {role} | 原因: {reason} [| 摘要: "{summary}"]
```

Parser 容错：
- 解析失败 → 视为 fallback，用 fast_result
- confidence 解析失败 → 取 0.5
- role 不在白名单 → 强制 customer

### 2.2 detect_language()

```python
_CJK_RANGE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")
_LATIN_RANGE = re.compile(r"[a-zA-Z]")

def detect_language(message: str) -> str:
    """Return ISO code or 'unknown'."""
    if len(message.strip()) < 3:
        return "unknown"

    cjk = len(_CJK_RANGE.findall(message))
    latin = len(_LATIN_RANGE.findall(message))
    total = cjk + latin

    # 纯 CJK → 进一步区分 zh/ja
    if cjk / max(total, 1) > 0.8:
        # 启发式：有平假名/片假名 → ja
        if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", message):
            return "ja"
        return "zh"

    # 纯 Latin 且有英语常见词 → en
    if latin / max(total, 1) > 0.8:
        # 简单英语特征：常见停用词命中
        if re.search(r"\b(the|is|you|have|what|how)\b", message, re.I):
            return "en"
        # 没命中常见英语词 → 掏 langdetect
        return _langdetect_fallback(message)

    # 混合 → langdetect
    return _langdetect_fallback(message)


def _langdetect_fallback(message: str) -> str:
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0  # 确定性
        return detect(message)
    except Exception:
        return "unknown"
```

### 2.3 cc_pool：懒加载 per-(role, tenant) 子池

**新增 `_role_pools` 结构**：
```python
class CCPool(AsyncPool[CCInstance]):
    _role_pools: dict[tuple[str, str | None], AsyncPool[CCInstance]] = {}
    _role_pool_last_used: dict[tuple[str, str | None], float] = {}
    _REAP_IDLE_SEC = 600  # 10 分钟未用回收

    def acquire(self, role="customer", tenant_id=None, timeout=None, ...):
        if role == "customer":
            return super().acquire(timeout=timeout)        # 主池，不变
        if role == "dream":
            return _acquire_dream(tenant_id=tenant_id, timeout=timeout)  # 不变
        if role in ("lead", "translate", "triage"):
            return self._acquire_role_pool(role, tenant_id, timeout)
        raise NotImplementedError(
            f"cc_pool.acquire: role={role!r} not in {sorted(_KNOWN_ROLES)}"
        )

    @asynccontextmanager
    async def _acquire_role_pool(self, role, tenant_id, timeout):
        key = (role, tenant_id)
        pool = self._role_pools.get(key)
        if pool is None:
            pool = await self._create_role_pool(role, tenant_id)
            self._role_pools[key] = pool
        self._role_pool_last_used[key] = time.monotonic()
        async with pool.acquire(timeout=timeout) as inst:
            yield inst
```

**子池创建**（`_create_role_pool`）：
- size：stateful role (lead/translate) = `tenant.pool_size_per_role`（默认 2）；stateless role (triage) = 1
- warmup 策略：首次 acquire 时创建实例，不预热
- soul 注入：实例启动时按 `(role, tenant_id)` 加载对应 soul，soul 不变则实例可复用

**Reaper 协程**（全局单例，background task）：
- 每 60s 扫描 `_role_pool_last_used`
- 若某 `(role, tenant_id)` 空闲超过 `_REAP_IDLE_SEC` → 关闭子池、从字典移除
- customer 主池和 dream 池不在扫描范围内

### 2.4 Sticky 绑定升级：per-(role, conv_id)

**conversation state 新字段**（见 §3.1）：
```python
active_role: str | None           # 当前 conversation 绑定的 role
cc_instance_id: str | None        # 绑定的 CC 实例 id
detected_language: str | None     # 客户主要语言
drift_counter: int                # 连续漂移计数（reset on match）
triage_mode: Literal["drift", "sticky"]   # 租户 opt-in
```

**acquire_sticky 新签名**：
```python
async def CCPool.acquire_sticky(
    self, conv_id: str, role: str, tenant_id: str | None
) -> CCInstance:
    conv_state = await conversation.get_state(conv_id)
    # 若 role 变了，释放旧绑定
    if conv_state.active_role and conv_state.active_role != role:
        await self._release_sticky(conv_state.cc_instance_id)
    # 按 role 子池 acquire
    async with self.acquire(role=role, tenant_id=tenant_id) as inst:
        await conversation.set_active_role(conv_id, role, inst.id)
        return inst
```

### 2.5 role 切换时 history re-seed

**首次 prompt 前缀注入**：
```python
async def _build_reseeded_prompt(
    engine: ConversationEngine,
    conv_id: str,
    customer_text: str,
    previous_role: str | None,
    new_role: str,
) -> str:
    if previous_role is None or previous_role == new_role:
        return customer_text   # 无需 re-seed

    history = await engine.get_messages(
        conv_id,
        viewer_role="agent",
        visibility="public",
        limit=20,
    )
    history_block = "\n".join(
        f"[{m.role.value}] {m.text}" for m in history
    )
    return (
        "<conversation_history>\n"
        f"{history_block}\n"
        "</conversation_history>\n\n"
        f"Current customer message: {customer_text}\n\n"
        f"You are now the {new_role} agent. "
        "Continue based on the conversation history above."
    )
```

**Token 上限保护**：`history_block` 估算 token > `tenant.history_reseed_token_limit`（默认 2000）时，从后往前截断、保留最近的 N 条。

### 2.6 SIDE 消息写入 + 广播

**调用点**（在 `triage_and_route` 里）：
```python
await engine.save_message(
    conv_id=conv_id,
    role=ParticipantRole.TRIAGE,       # 新增 enum 值
    visibility=MessageVisibility.SIDE,
    text=_format_triage_text(decision),
    metadata={
        "type": "triage_decision",
        "intent": decision.intent,
        "confidence": decision.confidence,
        "route_to": decision.role,
        "source": decision.source,
        "summary": decision.summary,
        "previous_role": prev_role,
        "detected_language": decision.detected_language,
    },
)
```

**广播**：已有的 `_broadcast_to_squad` 自动把 SIDE 消息推给订阅此 conversation 的 operator WS；operator-console 前端按 `role == "triage"` 识别、按 `metadata.type == "triage_decision"` 渲染。

**文本格式**（参照 soul.md）：
```
[分流] 意图: purchase_intent | 信心: 0.85 | 路由: lead | 源: fastpath
[分流] 意图: general_question | 信心: 0.45 | 路由: customer | 源: triage_agent | 摘要: "..."
```

### 2.7 Operator UI 渲染（方向性描述，UI 实现由 admin-portal 工单完成）

- 默认折叠成一行："🔀 分流 → lead (0.85)"；点击展开完整 metadata
- `confidence < 0.6` 默认展开；高亮摘要文本
- `source == "fallback"` 标橙色警告
- SLA 警告 SIDE 消息标红色

---

## 3. 数据模型改动

### 3.1 Conversation state schema 新增字段

```python
@dataclass
class ConversationState:
    # 现有
    conv_id: str
    mode: ConversationMode
    participants: list[Participant]
    # 新增
    active_role: str | None = None            # customer/lead/translate
    cc_instance_id: str | None = None         # sticky 绑定
    detected_language: str | None = None      # zh/en/ja/...
    drift_counter: int = 0                    # 漂移累计
    triage_mode: str = "drift"                # drift | sticky
```

**持久化**：和现有 conversation 一起落 `.autoservice/database/conversations.db`。DB migration 加 5 列。

### 3.2 Message role enum 新增 TRIAGE

```python
class ParticipantRole(str, Enum):
    CUSTOMER = "customer"
    AGENT = "agent"
    OPERATOR = "operator"
    SYSTEM = "system"
    TRIAGE = "triage"      # 新增
```

Message visibility / 持久化 schema 不变——`role=triage` 的消息天然走 `visibility=SIDE` 约束，operator-console 根据 role 过滤渲染。

### 3.3 DB migration

`alembic` 或等效机制生成 migration：
- ADD COLUMN `conversations.active_role TEXT NULL`
- ADD COLUMN `conversations.cc_instance_id TEXT NULL`
- ADD COLUMN `conversations.detected_language TEXT NULL`
- ADD COLUMN `conversations.drift_counter INTEGER NOT NULL DEFAULT 0`
- ADD COLUMN `conversations.triage_mode TEXT NOT NULL DEFAULT 'drift'`
- `messages` 表的 role 字段若是 VARCHAR 无约束无需改；若是 ENUM 需扩展

---

## 4. 配置 schema

### 4.1 全局 `autoservice/classify_intent.yaml`（清洗后）

**关键词清洗清单**（T0）：
- `product_inquiry.keywords`：**移除** "价格" "price"；加 "怎么用/how to/使用/user guide"
- `complaint.keywords`：**移除** 过泛的 "问题"；加 "投诉/不满/故障/坏了/crash/broken/refuse"
- `purchase_intent.keywords`：保留 "买/购买/价格/报价/合作/试用/buy/pricing/demo/trial"；加 "quote/采购/pricing/订购"
- `language_barrier`：关键词保持空（靠语言检测）
- `general_question`：保持兜底空关键词

### 4.2 租户级 overlay

**路径约定**（和 soul 覆盖对称）：
1. `.autoservice/sandbox/<tenant_id>/classify_intent.yaml`（master 侧）
2. `plugins/<tenant_id>/classify_intent.yaml`（fork 侧）
3. Fallback 到 `autoservice/classify_intent.yaml`

**加载时机**：首次 `tenant_config` 构建时读取，deep-merge 到内存配置；`ModelRouter` 按 tenant_id cache 编译好的 `FastClassifier` 实例。

**Merge 语义**：
- `intents.<name>.keywords`：tenant 值**完全替换**全局（不 append，避免意外继承旧关键词）
- `intents.<name>.{description,route_to,model_tier,priority}`：tenant 覆盖单字段
- `confidence.{high,medium,low,uncertain}`：tenant 覆盖单字段
- `timeouts` / `model_tiers`：M2 全局唯一，不接受 tenant 覆盖（减少 blast radius）

**示例 tenant overlay**：
```yaml
# plugins/acme-legal/classify_intent.yaml
intents:
  purchase_intent:
    keywords: ["委托", "咨询费", "retainer", "订约", "聘请"]
  product_inquiry:
    keywords: ["案件", "诉讼流程", "案由", "判决", "上诉"]
# 其他字段全部继承全局
```

### 4.3 Tenant config 新增字段

`plugins/<tid>/config.yaml` 或 `.autoservice/sandbox/<tid>/config.json`：

```yaml
tenant:
  supported_languages: [zh, en]        # 语言白名单；不在此列表即触发 translate
  pool_size_per_role: 2                # lead/translate 子池实例数；triage 永远 1
  history_reseed_token_limit: 2000     # role 切换时历史 token 上限
  triage_mode: drift                    # drift | sticky
  triage_agent_timeout_ms: 2000         # triage agent 单次调用超时
```

---

## 5. 延迟与成本预算

### 5.1 单条消息延迟分布

| 场景 | 增量延迟 | 占比（估） |
|------|---------|-----------|
| FastClassifier 高置信 + 无切换 | +25ms | ~75% |
| FastClassifier 高置信 + 漂移命中 + 低 drift_counter | +25ms | ~10% |
| FastClassifier 低置信 → triage agent 仲裁 | +600-1200ms | ~10% |
| role 切换（re-seed） | +25ms + TTFT 变化 (+100-200ms) | ~5% |
| triage agent 超时降级 | +2000ms (timeout) + 0 额外（走 fast 结果） | <1% |

**加权平均延迟增量**：~150ms（对比 customer-only 的当前路径）

### 5.2 Token 成本估算

假设 tenant 每日 10000 条客户消息：
- FastClassifier：本地计算，0 API cost
- Triage agent（15% 命中）：1500 次 × 200 input + 30 output haiku → ~0.3M input + 0.05M output
- Role 切换 re-seed：1-2% 消息 × 1000 extra input → ~200K sonnet input
- 按 Haiku $0.8/M-in $4/M-out、Sonnet $3/M-in：日成本增量 **~$1.0/tenant/日**

可忽略。

---

## 6. 错误处理与降级

| 故障 | 降级策略 |
|------|---------|
| triage agent 超时（>2s） | 用 FastClassifier 结果；`source="fallback"`；SIDE 消息标警告 |
| triage agent 输出 parser 失败 | 同上 |
| 目标 role 子池 acquire 失败（池创建失败 / checkout 超时） | 降级到 customer 主池；写 SIDE 警告 `sla_warning` |
| langdetect 抛异常 | 返回 `unknown`；跳过 language_barrier 分支，走 FastClassifier 正常逻辑 |
| conversation.active_role 指向已下线的 role（tenant 改配置禁用 lead） | 视为 role 切换，re-triage |
| role 切换时 re-seed 失败（DB 挂） | 不塞历史、直接开新 session；打 warning log |
| drift_counter 跨进程不一致（多 worker 场景） | conversation state 是 DB 持久化的，不是进程内；已天然一致 |

---

## 7. 兼容性与迁移

### 7.1 现有流程不受影响

- **customer-only tenant**：不配置 `supported_languages` 和 tenant overlay 时，所有消息走 `product_inquiry/general_question/complaint` → 永远 route_to = customer → 行为与 M2 现状一致
- **dream 链路**：`cc_pool.acquire(role="dream")` 路径不变，dream_scheduler / api_routes 不动
- **现有单测**：`tests/cc_pool/`、`tests/gateway/`、`tests/api/` 等本 spec 不应破坏任何现有测试；测试期望全量回归绿

### 7.2 Rollout 顺序

1. DB migration（加 5 列 + 扩 role enum）
2. conversation_engine 新字段的 getter/setter + TRIAGE role
3. cc_pool 扩 `_acquire_role_pool()` + `_KNOWN_ROLES` 解锁
4. `classify_intent.yaml` 清洗 + overlay loader
5. `ModelRouter.route_message()` 重构（语言检测 + triage agent 调用）
6. `triage_and_route()` 顶层函数 + `_generate_agent_reply` 接入
7. SIDE 消息广播验证（operator WS）
8. Operator UI 渲染（独立工单）
9. E2E 覆盖：customer-only 回归 / lead 切换 / translate 切换 / drift 触发 / fallback 路径

### 7.3 Feature flag

`tenant.triage_dispatch_enabled: bool`（默认 true）：若 false，`_generate_agent_reply` 跳过 `triage_and_route`，直接走 customer——紧急回滚开关，无需 revert 代码。

---

## 8. 测试策略

### 8.1 单元测试

| 测试文件（新增） | 覆盖点 |
|----------------|--------|
| `tests/triage/test_model_router.py` | `route_message` 各分支：高置信 fastpath / 低置信升级 / language_barrier / tenant overlay 生效 |
| `tests/triage/test_detect_language.py` | 纯 CJK / 纯 Latin / 混合 / 短文本 / langdetect fallback |
| `tests/triage/test_drift_probe.py` | 漂移累加 / reset 逻辑 / sticky 模式禁用漂移 |
| `tests/cc_pool/test_role_pool.py` | 懒加载 / reaper / per-tenant 隔离 / NotImplementedError 不再触发 |
| `tests/cc_pool/test_sticky_role_switch.py` | role 切换释放旧绑定 + acquire 新绑定 |
| `tests/triage/test_reseed.py` | 切换时前缀注入 / token 上限截断 |
| `tests/conversation/test_active_role_state.py` | DB 持久化 / 新字段读写 |
| `tests/conversation/test_side_message_broadcast.py` | TRIAGE role SIDE 消息广播到 operator WS |

### 8.2 E2E 测试

| 测试文件 | 场景 |
|---------|------|
| `tests/e2e/test_triage_e2e.py::test_customer_only_unchanged` | 回归：不配置 triage，行为与当前一致 |
| `tests/e2e/test_triage_e2e.py::test_sales_intent_routes_to_lead` | 客户说 "你们的价格是多少" → FastClassifier 高置信 → lead 产回复 |
| `tests/e2e/test_triage_e2e.py::test_low_confidence_triage_agent_fires` | 客户说 "嗯有点事想问下" → FastClassifier 低置信 → triage agent 仲裁 → customer |
| `tests/e2e/test_triage_e2e.py::test_drift_invalidates_cache` | 同一会话，前 2 条 customer 意图，第 3/4 条 lead 意图 → drift_counter=2 → re-triage → 切 lead |
| `tests/e2e/test_triage_e2e.py::test_language_barrier_routes_to_translate` | 客户说日文，tenant.supported_languages=[zh,en] → translate |
| `tests/e2e/test_triage_e2e.py::test_role_switch_reseeds_history` | role 切换后新 role 的 prompt 包含前 20 条 public 历史 |
| `tests/e2e/test_triage_e2e.py::test_triage_agent_timeout_fallback` | triage agent 超时 → fallback 到 FastClassifier 结果 + SIDE 警告 |
| `tests/e2e/test_triage_e2e.py::test_side_message_visible_to_operator_only` | TRIAGE SIDE 消息只推 operator，不推客户 WS |

### 8.3 回归守护

本 spec 落地后，以下测试必须全绿：
- `tests/cc_pool/` 全量（customer + dream 现有）
- `tests/gateway/` 全量（websocket / takeover / participants）
- `tests/conversation/` 全量（mode 切换 / participants / message visibility）
- `tests/dream_agent/` 全量
- `tests/dream_scheduler/` 全量

---

## 9. 实现里程碑（非 task 粒度）

| 阶段 | 内容 | 依赖 |
|------|------|------|
| **T0** | 关键词清洗 + classify_intent.yaml overlay loader | 独立可并行 |
| **T1** | DB migration + conversation state 新字段 + TRIAGE role enum | 独立 |
| **T2** | `cc_pool._acquire_role_pool()` + reaper + `_KNOWN_ROLES` 扩展 | 独立 |
| **T3** | `detect_language()` + `ModelRouter.route_message()` 新签名 | 依赖 T0 |
| **T4** | Triage agent 调用编排（`_invoke_triage_agent` + parser） | 依赖 T2 + T3 |
| **T5** | `triage_and_route()` 顶层 + `_generate_agent_reply` 接入 + re-seed | 依赖 T1 + T2 + T3 + T4 |
| **T6** | SIDE 消息落库 + 广播验证 | 依赖 T1 + T5 |
| **T7** | E2E 测试套件 | 依赖 T5 + T6 |
| **T8** | Operator UI 渲染（admin-portal 独立工单） | 依赖 T6；可晚于 M2 gate |

T0/T1/T2 可并行。T3/T4 串行。T5 汇合。T6 跟在 T5 后。T7 最后。T8 是 UI 工单，不阻塞 backend M2 gate。

---

## 10. 红线与约束

- **triage 输出不给客户看**：TRIAGE role 消息 `visibility=SIDE` 强约束——任何代码路径尝试把 TRIAGE 消息标 PUBLIC 应该在 `save_message` 层报错
- **triage agent 不产客户可见回复**：soul.md 已明确"不直接回答客户问题"；parser 丢弃任何不符合 `[分流]` 格式的输出
- **Dream 红线 CON-04 不受影响**：本 spec 不触及 dream 链路、不改 proposal status 写入规则
- **Tenant 数据隔离**：`_role_pools` 按 (role, tenant_id) 键控；租户 A 的 lead 实例不会被租户 B 复用
- **Feature flag 可回滚**：`tenant.triage_dispatch_enabled=false` 立即回到 M2 现状，不需要 deploy

---

## 附录 A：术语表

| 术语 | 定义 |
|------|------|
| **FastClassifier** | [model_router.py:84](../../../autoservice/model_router.py#L84) 的关键词 + 语言检测打分器，< 20ms |
| **Triage agent** | 走 `cc_pool.acquire(role="triage")`、按 `agents/triage/soul.md` 行为的 LLM，haiku 模型 |
| **Active role** | 当前 conversation 绑定的应答 role，持久化在 conversation state |
| **Drift** | FastClassifier 当前决策与 `active_role` 不一致 |
| **Drift counter** | 连续漂移计数，≥2 且新 role 高置信 → 触发 re-triage |
| **Drift mode** | 默认模式，按漂移探针自动切 role |
| **Sticky mode** | Tenant opt-in，首次 triage 后整 conversation 不再切 role |
| **Handoff** | Agent 主动输出切换标记——本 spec 不实现 |
| **Re-seed** | role 切换时把历史打包塞新 role 首条 prompt |
| **SIDE message** | 只 operator 可见、客户看不到的消息，复用现有 visibility 机制 |

## 附录 B：与其他 spec 的边界

| 相关 spec | 边界划分 |
|----------|---------|
| [2026-04-20-tenant-sandbox-m2-design.md](./2026-04-20-tenant-sandbox-m2-design.md) | 本 spec 不改 dream / soul_generator / fork runtime，只扩 `cc_pool._KNOWN_ROLES` 和用 M2 已加的 role="dream" 的同款抽象 |
| [2026-04-18-admin-portal-web-layout-design.md](./2026-04-18-admin-portal-web-layout-design.md) | 本 spec §2.7 的 operator UI 渲染（TRIAGE 消息折叠/展开）是 admin-portal 工单，不在本 spec 实装范围 |
| [2026-04-17-takeover-release-design.md](./2026-04-17-takeover-release-design.md) | TAKEOVER 模式下 `_generate_agent_reply` 不跑；`triage_and_route` 也不跑——无冲突 |

---

**下一步**：本 spec 审阅通过后，用 `superpowers:writing-plans` 产出逐任务实现计划（预计 T0-T7 共 ~25 个任务、2-3 个 milestone gate）。
