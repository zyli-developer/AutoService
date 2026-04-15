---
version: 1.0
status: FROZEN
author: DevA
reviewer: DevB
created_at: 2026-04-15
frozen_at: 2026-04-15
supersedes: 0.2-draft
---

> **v1.0 变更**（吸收 DevB 表态 · issue #21）：
> - Q1–Q9 全部决策落定（见 §10 决策归档）
> - Q4 附加：非法 mode 转换改为 **no-op + `mode.noop` 事件**（不抛 `IllegalModeTransition`）
> - Q6 附加：`subscribe` 对外 async iterator，内部 **Queue fan-out**
> - Q7 附加：Gate 降级不可逆写入 **§7 不变量**
> - `get_messages` 加 `before_sequence` 参数（向上滚加载老消息；与 `since_sequence` 互斥）
> - `subscribe(squad_id)` 的 `since_sequence` 语义澄清为 **ULID 字典序**
> - §6 加 **handle_command 权限矩阵**
> - `get_conversation` 找不到抛 `ConversationNotFound`（显式声明）
> - 事件清单加 `mode.noop` / `hook.failed`

**v0.2 → v1.0 历史**：
- v0.1 → v0.2（响应 DevB 对齐表）：新增 `get_messages` / `handle_command` / `squad_id` filter + scope / Q9

# T0.1 · ConversationEngine 契约（v1.0 frozen）

> **path B 适配层先行**核心契约。决定后续 16 周走向。
>
> 两种实现必须同时满足：
> - **LocalEngine**（M0-M4，当前阶段）：进程内直接管理 Conversation/Mode/Gate/Timer/Event
> - **ZchatEngine**（M5 切换）：委托给 zchat channel-server（IRC transport + MCP + Bridge）

---

## 1. 背景与定位

当前 AutoService 代码中：
- `autoservice/cc_pool.py` 提供 `acquire_sticky(chat_id)` — 单维度 chat_id → CC 实例
- `channels/feishu/channel_server.py` 做路由分发（exact/prefix/pool/wildcard）
- **没有** Mode 概念、**没有** Gate、**没有** Participant 角色、**没有** Event bus、**没有** Timer 抽象

zchat 协议（见 `docs/zchat-plan/01-protocol-primitives.md`）提供上述原语，但尚未实装。

**ConversationEngine** 是前端（Web UI）和业务层（CRM、计费、分队）所依赖的**唯一契约面**。所有实现都必须是这个 Protocol 的实例，前端/业务层代码不得旁路。

---

## 2. 核心类型（值对象）

### 2.1 枚举

```python
class ConversationState(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    IDLE = "idle"
    CLOSED = "closed"

class ConversationMode(str, Enum):
    AUTO = "auto"          # Agent 自主
    COPILOT = "copilot"    # Agent 主导 + operator 旁听
    TAKEOVER = "takeover"  # operator 主导 + agent 副驾

class ParticipantRole(str, Enum):
    CUSTOMER = "customer"
    AGENT = "agent"
    OPERATOR = "operator"
    OBSERVER = "observer"

class MessageVisibility(str, Enum):
    PUBLIC = "public"
    SIDE = "side"
    SYSTEM = "system"

class Outcome(str, Enum):
    RESOLVED = "resolved"
    ABANDONED = "abandoned"
    ESCALATED = "escalated"
```

### 2.2 不可变数据类

```python
@dataclass(frozen=True)
class Participant:
    id: str
    role: ParticipantRole
    joined_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Message:
    id: str                      # ULID（见决策 Q1）
    conversation_id: str
    source: str                  # participant_id
    content: str                 # 文本载荷；二进制载荷另走 attachment url
    visibility: MessageVisibility
    timestamp: datetime
    edit_of: str | None = None
    sequence_number: int = 0     # per-conversation 单调递增（决策 Q3）
    metadata: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Conversation:
    id: str                      # 格式：{channel}_{external_id}，见决策 Q1
    state: ConversationState
    mode: ConversationMode
    participants: tuple[Participant, ...]
    created_at: datetime
    updated_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)
    resolution: "Resolution | None" = None

@dataclass(frozen=True)
class Resolution:
    outcome: Outcome
    resolved_by: str
    csat_score: int | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

@dataclass(frozen=True)
class Event:
    id: str                      # ULID
    type: str                    # EventType 字符串值，见 §5
    conversation_id: str
    data: Mapping[str, Any]
    timestamp: datetime
    sequence_number: int = 0     # 全局 OR per-conversation，见决策 Q3

@dataclass(frozen=True)
class Timer:
    conversation_id: str
    name: str                    # 7 类预设之一或 app 自定义
    duration_ms: int             # 决策 Q2：统一 ms
    started_at: datetime
    cancelled: bool = False
```

### 2.3 Timer 预设

命名与 `docs/zchat-plan/01-protocol-primitives.md §6` 对齐：

| name | 默认 | 用途 |
|------|------|------|
| `sla_onboard` | 3 s | US-2.1 首屏应答 3 s |
| `sla_placeholder` | 1 s | US-2.2 占位消息 1 s |
| `sla_slow_query` | 15 s | US-2.2 续写 15 s |
| `sla_first_reply` | 60 s | US-2.5 接管后首回 60 s |
| `takeover_wait` | 180 s | US-2.4 Agent @operator 等待 |
| `idle_timeout` | 300 s | 无活动 → idle |
| `close_timeout` | 3600 s | idle → closed |

> 每个 Timer 都会在超时时发 `timer.expired` 事件；若 `on_expire` 动作导致 mode/state 改变，也会发对应事件。

---

## 3. Protocol 定义

```python
from typing import Protocol, AsyncIterator, Mapping, Any
from datetime import datetime

class ConversationEngine(Protocol):
    """Path B 核心契约。LocalEngine 和 ZchatEngine 都必须实现。

    所有方法 async。错误语义见 §6。
    """

    # ------------ Conversation lifecycle ------------

    async def create_conversation(
        self,
        *,
        channel: str,            # "web" | "feishu"
        external_id: str,        # 渠道方 ID（web session_id / feishu chat_id）
        metadata: Mapping[str, Any] | None = None,
    ) -> Conversation:
        """返回已持久化的 Conversation；同时发 conversation.created 事件。

        id 生成规则：见决策 Q1。
        幂等：相同 (channel, external_id) 已存在且未 closed → 返回现有对象。
        """

    async def get_conversation(self, conversation_id: str) -> Conversation:
        """找不到时抛 ConversationNotFound（§6），不返回 None。"""

    async def list_active_conversations(
        self,
        *,
        operator_id: str | None = None,
        squad_id: str | None = None,
    ) -> list[Conversation]:
        """用于 operator dashboard / /status 命令。
        operator_id / squad_id 可任意组合；都为 None 返回全部 active。
        """

    async def close_conversation(
        self,
        conversation_id: str,
        *,
        outcome: Outcome,
        resolved_by: str,
        reason: str | None = None,
    ) -> Conversation:
        """幂等：已 closed 返回现有对象，不报错。发 conversation.resolved + closed。"""

    async def set_csat(self, conversation_id: str, score: int) -> None:
        """1 ≤ score ≤ 5；发 conversation.csat_recorded。"""

    # ------------ Participants ------------

    async def join(self, conversation_id: str, participant: Participant) -> None:
        """幂等。发 participant.joined。
        operator 首次 join 且当前 mode=auto → 自动切 copilot（由实现触发 switch_mode）。
        """

    async def leave(self, conversation_id: str, participant_id: str) -> None:
        """幂等。发 participant.left。
        最后一个 operator leave 且 mode=copilot → 自动回到 auto。
        """

    # ------------ Mode ------------

    async def switch_mode(
        self,
        conversation_id: str,
        target: ConversationMode,
        *,
        triggered_by: str,
        trigger: str,            # "/hijack" | "/release" | "/copilot" | "auto:operator_join"
    ) -> None:
        """Q4 决策：串行化锁（asyncio.Lock per conv）。
        **目标态 == 当前态** → **no-op，发 `mode.noop` 事件**（不抛异常）。
        其他非法转换（例如 closed 会话切 mode）仍抛 IllegalModeTransition（§6）。
        """

    # ------------ Messages ------------

    async def send_message(
        self,
        conversation_id: str,
        *,
        source: str,                        # participant_id
        content: str,
        requested_visibility: MessageVisibility = MessageVisibility.PUBLIC,
        metadata: Mapping[str, Any] | None = None,
    ) -> Message:
        """Gate 决定最终 visibility（见 §4）。
        如被 Gate 改写 → 额外发 message.gated 事件。
        决策 Q5：requested_visibility 是否可被提升（当前草案：只降不升）。
        """

    async def edit_message(
        self,
        conversation_id: str,
        message_id: str,
        *,
        new_content: str,
        edited_by: str,
    ) -> Message:
        """发 message.edited。用于占位→续写（US-2.2）。"""

    async def delete_message(
        self, conversation_id: str, message_id: str, *, deleted_by: str
    ) -> None: ...

    async def get_messages(
        self,
        conversation_id: str,
        *,
        since_sequence: int | None = None,   # 断点重连：返回 seq > since_sequence
        before_sequence: int | None = None,  # 向上滚：返回 seq < before_sequence
        until: datetime | None = None,
        viewer_role: ParticipantRole | None = None,
        limit: int = 50,
    ) -> list[Message]:
        """消息历史快照（聊天记录），区别于 query_events（状态流）。

        用途：
        - FE 断线重连（A5）：since_sequence=最后收到的 message.sequence_number
        - operator_join 拉历史（B3）：since_sequence=None + limit=N（返回最近 N 条）
        - chat UI 向上滚（DevB #1）：before_sequence=当前列表顶部 seq + limit=N
        viewer_role：决定是否过滤 SIDE 消息（Q9 决策：Engine 层过滤）。
        互斥约束：since_sequence 与 before_sequence 不可同时传；同传抛 ValidationError。
        """

    # ------------ Commands (统一入口) ------------

    async def handle_command(
        self,
        conversation_id: str,
        *,
        actor_id: str,
        command: str,            # "/hijack" | "/release" | "/copilot" | "/resolve" | "/abandon" | "/status"
        args: Mapping[str, Any] | None = None,
    ) -> None:
        """收敛 IRC CommandParser 与 Bridge operator_command 为单一 Engine 入口。

        内部派发：
        - /hijack  → switch_mode(TAKEOVER)
        - /release → switch_mode(AUTO)
        - /copilot → switch_mode(COPILOT)
        - /resolve → close_conversation(outcome=RESOLVED)
        - /abandon → close_conversation(outcome=ABANDONED)
        权限校验不通过抛 PermissionDenied（§6）。
        """

    # ------------ Timers ------------

    async def set_timer(
        self,
        conversation_id: str,
        name: str,
        duration_ms: int,
        *,
        on_expire: Mapping[str, Any],  # {"type": "mode_change"|"system_message"|"callback", "params": {...}}
    ) -> Timer: ...

    async def cancel_timer(self, conversation_id: str, name: str) -> None:
        """幂等：不存在也不报错。"""

    # ------------ Events ------------

    async def subscribe(
        self,
        *,
        conversation_id: str | None = None,
        squad_id: str | None = None,
        event_types: list[str] | None = None,
        since_sequence: int | None = None,   # conv scope: int seq；squad/global scope: event_id ULID 字典序
        viewer_role: ParticipantRole | None = None,
    ) -> AsyncIterator[Event]:
        """Q6 决策：对外 async iterator（背压自然，WS 推送友好）；
        内部实现 **Queue fan-out**（单条 Event 多订阅者共享，O(1) per sub）。

        scope 选择（三选一）：
        - conversation_id: 单会话事件流（C 端 / operator 进入某对话后）
        - squad_id: 分队级 fanout（B8 分队卡片：新对话、mode 变化、resolved）
        - 都为 None: 全局流（仅 admin / audit 用途）

        since_sequence 断点语义：
        - conv scope → int，与 Event.sequence_number 比较（per-conv 单调）
        - squad / global scope → 字符串 event_id（ULID），按字典序比较（天然时间序）
          前端只需记住最后收到的 event_id 即可续传。

        viewer_role: 与 get_messages 对称，Engine 根据 role 过滤 SIDE 事件对应的
          message.* 载荷（Q9 决策：读路径统一由 Engine 管）。
        """

    async def query_events(
        self,
        conversation_id: str,
        *,
        since_sequence: int | None = None,
        until: datetime | None = None,
        types: list[str] | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """一次性拉取，用于审计、慢查询。"""

    # ------------ Plugin hooks (registration) ------------

    def register_hook(self, hook: "PluginHook") -> None:
        """见 §7。"""


class PluginHook(Protocol):
    """App 层通过实现这些钩子扩展引擎行为。所有钩子可选实现。"""

    async def on_conversation_created(self, conv: Conversation) -> None: ...
    async def on_conversation_closed(self, conv: Conversation) -> None: ...
    async def on_mode_changed(
        self, conv: Conversation,
        old_mode: ConversationMode, new_mode: ConversationMode,
        trigger: str,
    ) -> None: ...
    async def on_participant_joined(self, conv: Conversation, p: Participant) -> None: ...
    async def on_timer_expired(self, conv: Conversation, timer: Timer) -> None: ...
    async def on_event(self, event: Event) -> None:
        """通用回调，所有事件都会到。"""
```

---

## 4. Gate 规则（强制机制）

与 zchat `§5` 完全一致。**Gate 是 mechanism 级别**：send_message 内部调用，业务层无法旁路。

| 当前 mode | 发送者 role | requested = PUBLIC 的最终 visibility |
|-----------|-------------|--------------------------------------|
| auto      | agent       | PUBLIC |
| auto      | customer    | PUBLIC |
| copilot   | agent       | PUBLIC |
| copilot   | operator    | **SIDE**（降级） |
| takeover  | agent       | **SIDE**（降级） |
| takeover  | operator    | PUBLIC |

- `requested=SIDE` / `requested=SYSTEM` 原样保留，不受 Gate 影响。
- Gate 降级后，发 `message.gated` 事件，前端 operator UI 据此显示「已降为 side」。
- **降级不可逆**（§6 决策 Q7）。

---

## 5. Event 类型（字符串常量）

```
conversation.created
conversation.activated
conversation.idled
conversation.reactivated
conversation.closed
conversation.resolved
conversation.csat_recorded

participant.joined
participant.left

mode.changed
mode.noop             # target == current mode（Q4 决策），含 trigger 便于审计

message.sent          # 真正入库后
message.gated         # visibility 被 Gate 改写
message.edited
message.deleted

timer.set
timer.expired
timer.cancelled

sla.breach            # 由 timer_expired + sla_* 聚合而来

squad.assigned        # M3 起启用
squad.reassigned

hook.failed           # PluginHook 抛异常后发此事件（Q8 决策：吞异常 + 通知）
```

每个 event 的 `data` 字段在 `test-vectors/events.json`（T0.2 产物）给出正例。

---

## 6. 错误语义

**基本原则**：Protocol 方法只抛**有限的域异常**，不让实现细节泄漏。前端/业务层对这些异常要有明确降级路径。

```python
class EngineError(Exception):
    """所有 ConversationEngine 错误的基类。"""

class ConversationNotFound(EngineError): ...
class ConversationAlreadyClosed(EngineError): ...
class IllegalModeTransition(EngineError):
    """from_mode → to_mode 不在合法转换表中。"""
class UnknownParticipant(EngineError): ...
class PermissionDenied(EngineError):
    """role 无权执行该命令（如 agent 发 /hijack）。"""
class TimerNotFound(EngineError): ...
class ValidationError(EngineError):
    """入参格式错误（score 超范围、content 空字符串等）。"""
```

**非异常错误**（如 Gate 降级、mode no-op）通过 event 表达，不抛异常。

### 6.1 handle_command 权限矩阵

| command | customer | agent | operator | admin | 备注 |
|---------|----------|-------|----------|-------|------|
| `/hijack`   | ❌ | ❌ | ✅ | ✅ | auto/copilot → takeover |
| `/release`  | ❌ | ❌ | ✅ | ✅ | takeover → auto |
| `/copilot`  | ❌ | ❌ | ✅ | ✅ | auto → copilot |
| `/resolve`  | ❌ | ❌ | ✅ | ✅ | 标记 RESOLVED |
| `/abandon`  | ❌ | ❌ | ✅ | ✅ | 标记 ABANDONED |
| `/status`   | ❌ | ❌ | ✅ | ✅ | 只读 |
| `/dispatch` | ❌ | ❌ | ❌ | ✅ | 仅 admin（M3 起） |
| `/assign`   | ❌ | ❌ | ❌ | ✅ | 仅 admin（M3 起） |

- ❌ 对应 actor_id → 抛 `PermissionDenied`
- 合法 command 但在当前 mode 下是 no-op（如 copilot 发 `/copilot`）→ 按 Q4 约定走 `mode.noop`

---

## 7. 生命周期与一致性约定

### 7.1 不变量（invariants · 实现必须满足）

1. **create_conversation 幂等**：相同 (channel, external_id) 且未 closed 返回现有对象。
2. **close_conversation 幂等**：已 closed 返回现有 Resolution。
3. **mode 切换原子**：同一 conversation 的 switch_mode 串行化（asyncio.Lock per conv）；目标态 == 当前态 → `mode.noop` 事件，不抛异常（Q4）。
4. **事件顺序**：同一 conversation 的事件按 `sequence_number` 严格递增，前端可按此判断丢失；跨 conversation / squad / global 订阅按 `event_id`（ULID）字典序单调递增。
5. **Gate 降级不可逆** ⚓：一旦 visibility 被 Gate 从 PUBLIC 降为 SIDE，后续任何 mode 切换、命令、时间流逝都不会把它升回 PUBLIC。此条是**强不变量**，不再讨论（Q7 决策）。
6. **读写路径对称**：写路径（`send_message`）由 Gate 决定最终 visibility；读路径（`get_messages` / `subscribe` / `query_events`）由 Engine 根据 `viewer_role` 过滤。App 层不应承担 visibility 授权职责（Q9 决策）。
7. **Plugin Hook 隔离**：任何 PluginHook 抛出的异常被吞并发 `hook.failed` 事件，不影响核心流程（Q8 决策）。
8. **最后一个 operator leave 回落**：mode=copilot 且最后一个 OPERATOR role 的 participant leave → 自动切回 auto。对应 mode.changed 事件的 `trigger="auto:last_operator_left"`。

---

## 8. Web 前端可暴露能力（供 DevB 对照）

供 DevB 的「前端能力 → Engine 方法 → Event」映射表使用。下表是 DevA 预期：

| 前端能力 | Engine 调用 | 触发 Event |
|---|---|---|
| 客户发消息 | `send_message(source=customer, visibility=PUBLIC)` | message.sent |
| 客户接消息 | `subscribe(conversation_id)` | message.sent(public) / message.edited |
| Operator 加入 | `join(role=operator)` | participant.joined + mode.changed(auto→copilot) |
| Operator 侧信道发言 | `send_message(source=operator, visibility=SIDE)` | message.sent(side) |
| /hijack | `switch_mode(TAKEOVER, trigger="/hijack")` | mode.changed |
| /release | `switch_mode(AUTO, trigger="/release")` | mode.changed |
| 分队卡片刷新 | `list_active_conversations(operator_id=...)` 轮询 + `subscribe(types=[squad.*, mode.*])` | squad.assigned / mode.changed |
| CSAT 请求 | （实现侧）resolve 后 set_timer(csat_wait) | conversation.resolved → 前端显示评分 |
| CSAT 响应 | `set_csat(score)` | conversation.csat_recorded |
| **断线重连**（消息快照） | `get_messages(since_sequence=N)` | — (返回列表) |
| **断线重连**（事件回放） | `subscribe(since_sequence=N)` + `query_events(since_sequence=N)` | 回放未收事件 |
| **operator_join 拉历史** | `get_messages(conversation_id, limit=N, viewer_role=OPERATOR)` | — |
| **分队卡片 fanout** | `subscribe(squad_id=..., event_types=["conversation.*", "mode.changed"])` | squad 级事件 |
| **operator 命令统一入口** | `handle_command(conv_id, actor_id, "/hijack" \| "/release" \| ...)` | mode.changed / conversation.resolved |
| 占位→续写 | `send_message(placeholder)` → `edit_message(new_content)` | message.sent + message.edited |

---

## 9. 与现有 AutoService 代码的关系

| 现有模块 | LocalEngine 实现方式 |
|---|---|
| `autoservice/cc_pool.py` (`acquire_sticky(chat_id)`) | Engine 内部保留；`conversation_id` 到 chat_id 的映射作为 engine 状态 |
| `channels/feishu/channel_server.py` 路由 | Feishu 渠道的 ingress：Feishu event → `engine.send_message(...)` |
| `autoservice/customer_manager.py` | 通过 `on_conversation_created` hook 初始化客户工作目录 |
| `autoservice/crm.py` | 通过 `on_event` hook 做审计 |
| `autoservice/rules.py` | 通过 `on_message` / `on_mode_changed` 做业务决策 |

LocalEngine 在 M0-M4 内是 **zchat 的轻量内存实现**；M5 `ZchatEngine` 替换时，前端/业务层零改动，仅更换 engine 实例。

---

## 10. 决策归档（Q1–Q9 · v1.0 frozen 2026-04-15）

所有决策 **DevA 提案 + DevB 表态同意**，冻结为 v1.0。后续变更走 RFC 流程。

| # | 决策 | 理由 / 附加条件 |
|---|---|---|
| Q1 | conversation_id = `{channel}_{external_id}`；message_id / event_id = **ULID** | 字典序天然时间序；对 reactivate 幂等友好 |
| Q2 | Timer 内部 **ms**（`duration_ms: int`），UI 转 s | 预留亚秒精度（typing / placeholder 500ms）；UI 转换零成本 |
| Q3 | `Message.sequence_number` / `Event.sequence_number` = **per-conversation 单调** | 前端 reconnect 按会话续传自然 |
| Q4 | `switch_mode` 串行化（asyncio.Lock per conv）；**目标态 == 当前态 → `mode.noop` 事件**（不抛异常） | operator 双击 / join+hijack 竞态在生产常见，no-op 对前端更友好 |
| Q5 | Gate **只降不升** | 与 zchat §5 一致 |
| Q6 | `subscribe` 对外 **async iterator**；内部 **Queue fan-out** | 多订阅者共享单条 Event，O(1) per sub |
| Q7 | Gate 降级 **不可逆**（写入 §7.1 不变量 #5） | 避免 /release 后历史消息"重新公开"破坏时序一致性 |
| Q8a | 错误处理：**抛异常**（非 Result） | Pythonic；FE WS 层捕获统一转 error |
| Q8b | 同 conv 允许多 operator | mode 切换由**首个 operator join** 触发；**最后一个 leave** 回落 auto（§7.1 不变量 #8） |
| Q8c | Plugin Hook 抛异常 → **吞掉 + `hook.failed` 事件**（§7.1 不变量 #7） | 业务插件错误不炸核心 |
| Q8d | ZchatEngine（M5）Timer 粒度映射：ms → s 除法 | M5 再处理，契约不受影响 |
| Q9 | `get_messages` / `subscribe` / `query_events` 的 visibility 过滤由 **Engine 根据 `viewer_role`** 负责 | 与 Gate 写路径对称；避免"某个 channel 忘过滤"的安全漏洞 |

---

## 11. 变更历史

| 版本 | 日期 | 变更 | 作者 |
|---|---|---|---|
| 0.1-draft | 2026-04-15 | 初稿：16 方法 Protocol + 7+1 决策题 | DevA |
| 0.2-draft | 2026-04-15 | +`get_messages` / `handle_command` / squad filter / Q9（响应 DevB 对齐表） | DevA |
| **1.0** | **2026-04-15** | **FROZEN**：Q1–Q9 定案；+`before_sequence`；+§6.1 权限矩阵；+§7.1 不变量 8 条；+`mode.noop` / `hook.failed` 事件 | DevA + DevB |

---

*End of T0.1 ConversationEngine Contract v1.0 · FROZEN 2026-04-15.*
