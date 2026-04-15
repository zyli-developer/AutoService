---
version: 0.2-draft
status: DRAFT (awaiting DevA+DevB decisions)
author: DevA
created_at: 2026-04-15
updated_at: 2026-04-15
supersedes: 0.1-draft
---

> **v0.2 变更**（响应 DevB 对齐表 · issue #21）：
> - 新增 `get_messages(...)` — 消息历史快照（A5/B3 断线重连 + operator_join 拉历史）
> - 新增 `handle_command(...)` — 收敛 IRC `CommandParser` 与 Bridge `operator_command` 到单一入口
> - `list_active_conversations` 加 `squad_id` filter（B1）
> - `subscribe` 加 `squad_id` 参数（B8 分队卡片实时刷新）
> - 新增 Q9（get_messages 的 visibility 过滤策略）

# T0.1 · ConversationEngine 契约（草稿）

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

    async def get_conversation(self, conversation_id: str) -> Conversation: ...

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
        """非法转换抛 IllegalModeTransition（见 §6）。
        决策 Q4：是否允许并发切换（当前草案：串行化锁）。
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
        since_sequence: int | None = None,
        until: datetime | None = None,
        viewer_role: ParticipantRole | None = None,
        limit: int = 50,
    ) -> list[Message]:
        """消息历史快照（聊天记录），区别于 query_events（状态流）。

        用途：
        - FE 断线重连（A5）：since_sequence=最后收到的 message.sequence_number
        - operator_join 拉历史（B3）：since_sequence=None + limit=N
        viewer_role：决定是否过滤 SIDE 消息（见决策 Q9）。
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
        since_sequence: int | None = None,   # reconnect 断点重放
    ) -> AsyncIterator[Event]:
        """
        决策 Q6：sync vs async 订阅 —— 当前草案：async iterator（背压自然，适合 WS 推送）。
        since_sequence 用于前端 reconnect 从断点回放。

        scope 选择（三选一）：
        - conversation_id: 单会话事件流（C 端 / operator 进入某对话后）
        - squad_id: 分队级 fanout（B8 分队卡片：新对话、mode 变化、resolved）
        - 都为 None: 全局流（仅 admin / audit 用途）
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

**非异常错误**（如 Gate 降级）通过 event / 返回值里带 flag 表达，不抛异常。

---

## 7. 生命周期与一致性约定

1. **create_conversation 幂等**：相同 (channel, external_id) 且未 closed 返回现有对象。
2. **close_conversation 幂等**：已 closed 返回现有 Resolution。
3. **mode 切换原子**：同一 conversation 的 switch_mode 串行化；并发调用后到者看到新 mode 后再决定（决策 Q4）。
4. **事件顺序**：同一 conversation 的事件按 `sequence_number` 严格递增，前端可按此判断丢失。
5. **降级不可逆**：一旦 Gate 把 public 降为 side，后续不会升回（决策 Q7）。

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

## 10. 待决策选择题（§10 交给 DevA+DevB 讨论）

以下 7 题影响契约细节，需 DevB review 后决策。每题给出**草案方向**和**反方理由**，供对话。

### Q1. Conversation id / Message id / Event id 格式

- **草案**：conversation_id = `{channel}_{external_id}`（例：`feishu_oc_abc123` / `web_sess_xyz`）；message_id + event_id = **ULID**（单调时间前缀，全局唯一）。
- **反方**：zchat 原语 §7 使用 UUID；前端不关心格式，ULID 对客户端排序更友好，但要求所有实现都支持 ULID 库。
- **可逆性**：选 ULID 后可降级到 UUID（客户端只按字典序排）；反向需全库迁移，较贵。

### Q2. Timer 粒度：ms vs s

- **草案**：内部 **ms**（`duration_ms: int`），对外 UI 显示转 s。
- **反方**：SLA 场景（1s/3s）ms 过度精确；s 足够，简化类型。
- **可逆性**：高（仅字段名+除 1000）。

### Q3. sequence_number：全局 vs per-conversation

- **草案**：**per-conversation 单调**（event 和 message 各自一套），便于前端 reconnect 按 conv 续传。
- **反方**：全局序列号便于跨 conversation 的全局审计，但前端复杂。
- **可逆性**：中（前端若绑定全局序号重构成本高）。

### Q4. Mode 切换并发策略

- **草案**：同一 conversation 的 switch_mode 串行化（asyncio.Lock per conv）；并发调用 FIFO；每次切换内部做合法性校验。
- **反方**：严格禁止并发（第二个调用直接抛 ConcurrentModification），让前端显式处理。
- **可逆性**：高。

### Q5. Gate 的 requested_visibility 是否可被提升

- **草案**：**只降不升**（requested=PUBLIC 可能降 SIDE；requested=SIDE 永远保持 SIDE）。与 zchat 原语 §5 一致。
- **反方**：某些场景 operator 想发 public 但被降级后想"撤回 gate"；当前无此场景。
- **可逆性**：高。

### Q6. Event 订阅：sync 回调 vs async iterator vs pub/sub queue

- **草案**：**async iterator**（`subscribe()` 返回 AsyncIterator[Event]）；背压自然，WS 推送友好；Hook 仍用 async 回调。
- **反方**：多订阅者场景下 async iterator 要自己 fan-out；pub/sub queue (asyncio.Queue per sub) 更灵活但额外抽象。
- **可逆性**：中（一旦前端大量使用 iterator 语义，切回调需重写消费侧）。

### Q7. Gate 降级是否可逆

- **草案**：**不可逆**。一旦 PUBLIC → SIDE，后续无方式升回；与 zchat 不变量 5 一致。
- **反方**：前端 UX 希望「/release 后，takeover 期间被降级的 agent 消息重新公开」——但这破坏时序一致性（客户会突然看到过去的消息）。
- **可逆性**：**不可逆本身不可逆**（一旦允许升级，审计链就复杂）。**强烈建议草案**。

### Q9. `get_messages` 的 visibility 过滤策略（v0.2 新增）

- **草案**：Engine 根据 `viewer_role` 参数过滤 —— `CUSTOMER` 只能看 PUBLIC；`OPERATOR`/`AGENT` 看 PUBLIC+SIDE；`viewer_role=None` 不过滤（仅 admin/audit）。
- **反方**：Engine 不该承担授权职责，应由 App 层（channel handler）根据调用上下文过滤。
- **可逆性**：中（若交给 App 层后要收回到 Engine，所有 channel 都得改；反向只是 App 层多一步过滤）。
- **连带**：同样的过滤语义应否用到 `subscribe` / `query_events`？草案：是，保持一致。

### Q8. 额外边界（open）

- 错误处理：抛异常 vs Result 类型？— 草案：**抛异常**（Pythonic，前端 WS 层捕获统一转 error 消息）。反方：Result 对测试更友好。
- 同一 conversation 多 operator 参与：允许同时 N 个 operator？草案：允许，mode 由 join 顺序决定。
- ZchatEngine 实现时，本契约的 Timer 粒度能否映射到 channel-server 的 timer（后者是 s）？— 若 Q2 选 ms，ZchatEngine 做除法转换。
- Plugin Hook 抛异常的行为：吞掉 + log，还是中断流程？草案：**吞掉 + 发 `hook.failed` 事件**，避免业务错误影响核心流程。

---

*End of T0.1 draft v0.2 — 等 DevA+DevB 决策后更新为 v1.0 frozen。*
