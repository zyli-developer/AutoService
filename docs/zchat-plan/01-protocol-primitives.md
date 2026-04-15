# Channel-Server Protocol — 原语定义

> 版本 v1.0 · 所有原语都是通用的，不包含业务概念

---

## §1. Conversation（对话）

一个 Conversation 代表一次人与 Agent 之间的协作对话。它是协议的核心单元。

```python
@dataclass
class Conversation:
    id: str                          # 唯一标识，格式: {source}_{external_id}
    state: ConversationState         # 生命周期状态
    mode: ConversationMode           # 当前协作模式
    participants: list[Participant]   # 参与者列表
    created_at: datetime
    updated_at: datetime
    metadata: dict                   # App 自定义数据，协议不解释
    resolution: ConversationResolution | None = None  # 结案信息
```

### 结案（Resolution）

Conversation 关闭时需要记录结案信息，用于支撑计费指标（升级转结案率、CSAT）。

```python
@dataclass
class ConversationResolution:
    outcome: str          # "resolved" | "abandoned" | "escalated"
    resolved_by: str      # participant_id（agent 或 operator）
    csat_score: int | None = None  # 1-5, 客户评分（可选）
    timestamp: datetime = field(default_factory=datetime.now)
```

| 操作 | 签名 | 触发事件 |
|------|------|---------|
| 结案 | `resolve(id, outcome, resolved_by) → void` | `conversation.resolved` |
| CSAT 记录 | `set_csat(id, score) → void` | `conversation.csat_recorded` |

### 结案命令

| 命令 | 发送者 | 效果 |
|------|--------|------|
| `/resolve` | operator 或 agent | 标记为 resolved，触发 CSAT 采集 |
| `/abandon` | system (timer) | 标记为 abandoned（长期无响应） |

### 生命周期状态

```
created → active → idle → closed
                ↑   │  ↑        │
                │   │  └────────┘  (reactivate)
                │   │
                │   └→ closed  (/resolve 或 /abandon 直接关闭)
                │
                └─────────────  (reactivate from idle)
```

| 状态 | 含义 | 触发条件 |
|------|------|---------|
| `created` | 已创建但尚未有消息交换 | conversation.create() |
| `active` | 正在进行中 | 首条消息发送，或从 idle reactivate |
| `idle` | 暂时无活动（客户离开但对话未关闭） | 可配置的无活动超时（默认 5 分钟） |
| `closed` | 对话已结束 | /resolve, /abandon, 或长期 idle 超时 |

**注意**: `active → closed` 是合法的直接转换（通过 `/resolve` 或 `/abandon`），不必经过 `idle`。

### 操作

| 操作 | 签名 | 触发事件 |
|------|------|---------|
| 创建 | `create(id, metadata) → Conversation` | `conversation.created` |
| 激活 | `activate(id) → void` | `conversation.activated` |
| 闲置 | `idle(id) → void` | `conversation.idled` |
| 重新激活 | `reactivate(id) → void` | `conversation.reactivated` |
| 关闭 | `close(id) → void` | `conversation.closed` |

### IRC 映射

- 每个 Conversation 映射到一个 IRC channel: `#conv-{conversation.id}`
- conversation.create() → IRC JOIN #conv-{id} (channel-server 的 IRC bot 加入)
- conversation.close() → IRC PART #conv-{id}

---

## §2. Participant（参与者）

```python
@dataclass
class Participant:
    id: str                    # 唯一标识（IRC nick 或 bridge 标识）
    role: ParticipantRole      # 角色
    joined_at: datetime
    metadata: dict             # App 自定义（如 agent 类型、operator 姓名）
```

### 角色

| 角色 | 含义 | 消息权限 | 可见范围 |
|------|------|---------|---------|
| `customer` | 客户（通过 Bridge 接入） | 发: public · 收: public | 只看到 public 消息 |
| `agent` | AI Agent（通过 MCP 接入） | 发: public+side · 收: public+side+system | 看到全部 |
| `operator` | 人工客服（通过 Bridge 接入） | 发: 取决于 mode · 收: public+side+system | 看到全部 |
| `observer` | 旁观者（通过 Bridge 接入） | 发: 无 · 收: public+side+system | 看到全部，不发言 |

### 如何识别角色

channel-server 通过以下方式识别参与者角色：

1. **customer**: 通过 Bridge 接入（Web 聊天窗/飞书对话群）。Bridge 在转发消息时标注 `role=customer`
2. **agent**: 通过 MCP stdio 连接到 channel-server 的 Claude Code session。创建时注册
3. **operator**: 通过 Bridge 接入（飞书分队群/Web 管理后台）。Bridge 在转发消息时标注 `role=operator` + `operator_id`
4. **observer**: 通过 Bridge 接入，显式声明为 observer 的参与者

### 参与者操作

| 操作 | 签名 | 触发事件 |
|------|------|---------|
| 加入 | `join(conversation_id, participant) → void` | `participant.joined` |
| 离开 | `leave(conversation_id, participant_id) → void` | `participant.left` |
| 查询 | `list_participants(conversation_id) → list[Participant]` | — |

---

## §3. Conversation Mode（对话模式）

Mode 是协议最核心的原语，决定了人和 Agent 之间的权力分配。

```python
class ConversationMode(Enum):
    AUTO = "auto"            # Agent 自主，无人工参与
    COPILOT = "copilot"      # Agent 主导，人工旁听+建议
    TAKEOVER = "takeover"    # 人工主导，Agent 副驾驶
```

### 模式行为矩阵

| 模式 | Agent 发 public | Agent 发 side | Operator 发 public | Operator 发 side |
|------|-----------------|---------------|--------------------|--------------------|
| `auto` | ✅ 直达客户 | ✅ | N/A (无 operator) | N/A |
| `copilot` | ✅ 直达客户 | ✅ | ❌ **被 Gate 拦截为 side** | ✅ |
| `takeover` | ❌ **被 Gate 拦截为 side** | ✅ | ✅ 直达客户 | ✅ |

### 状态转换

```
         ┌──── /copilot ────┐
         │                   │
         ▼                   │
  ┌──────────┐        ┌──────────┐
  │   auto   │◄──────►│ copilot  │
  └──────────┘        └──────────┘
       │ /hijack           │ /hijack
       │                   │
       ▼                   ▼
  ┌──────────────────────────────┐
  │          takeover            │
  └──────────────────────────────┘
       │ /release
       ▼
  ┌──────────┐
  │   auto   │
  └──────────┘
```

### 合法转换表

| From | To | 触发 | 说明 |
|------|----|------|------|
| `auto` | `copilot` | operator JOIN conversation | 自动：operator 加入即进入 copilot |
| `auto` | `takeover` | /hijack 命令 | 直接接管（跳过 copilot） |
| `copilot` | `takeover` | /hijack 命令 | 从旁听升级为接管 |
| `copilot` | `auto` | operator PART conversation | 自动：operator 离开即恢复 auto |
| `takeover` | `auto` | /release 命令 | 释放控制 |
| `takeover` | `copilot` | /copilot 命令 | 降级为旁听（继续观察但还权给 agent） |

**非法转换**：`auto → auto`、`takeover → takeover`、任何已 closed 的 conversation 的模式切换。

### 模式切换事件

每次切换产生一个 `mode.changed` 事件：
```python
Event(
    type="mode.changed",
    conversation_id="feishu_oc_xxx",
    data={
        "from": "copilot",
        "to": "takeover",
        "trigger": "/hijack",
        "triggered_by": "operator:xiaoli",
    },
    timestamp=datetime.now()
)
```

---

## §4. Message Visibility（消息可见性）

每条消息都有一个 visibility 标签，决定谁能看到它。

```python
class MessageVisibility(Enum):
    PUBLIC = "public"     # 所有参与者可见（包括 customer）
    SIDE = "side"         # 只有 agent + operator + observer 可见
    SYSTEM = "system"     # 协议控制消息（mode 切换通知等）
```

### 可见性矩阵

| Visibility | customer 可见 | agent 可见 | operator 可见 | observer 可见 |
|-----------|:------------:|:---------:|:------------:|:------------:|
| `public` | ✅ | ✅ | ✅ | ✅ |
| `side` | ❌ | ✅ | ✅ | ✅ |
| `system` | ❌ | ✅ | ✅ | ✅ |

### Bridge 层的责任

Bridge 只转发 `visibility=public` 的消息到客户端渠道（Web/Feishu）。`side` 和 `system` 消息**不出 IRC**，客户永远看不到。

---

## §5. Message（消息）

```python
@dataclass
class Message:
    id: str                          # 唯一标识
    source: str                      # 发送者 participant_id
    conversation_id: str
    content: str                     # 消息内容（协议不解释内容）
    visibility: MessageVisibility    # public / side / system
    timestamp: datetime
    edit_of: str | None = None       # 如果是编辑，指向原消息 id
    metadata: dict = field(default_factory=dict)  # App 自定义
```

### 消息操作

| 操作 | 签名 | 触发事件 | 说明 |
|------|------|---------|------|
| 发送 | `send(msg) → message_id` | `message.sent` | Gate 可能修改 visibility |
| 编辑 | `edit(message_id, new_content) → void` | `message.edited` | 替换已有消息内容 |
| 删除 | `delete(message_id) → void` | `message.deleted` | 标记删除 |

### Message Gate（消息门控）

Gate 是 channel-server 的核心机制。每条消息发送时，Gate 根据当前 mode + 发送者 role 决定最终 visibility：

```python
def gate_message(conversation: Conversation, sender: Participant, 
                 requested_visibility: MessageVisibility) -> MessageVisibility:
    """决定消息的最终可见性。这是 mechanism，不是 convention。"""
    mode = conversation.mode
    role = sender.role
    
    if requested_visibility == MessageVisibility.SYSTEM:
        return MessageVisibility.SYSTEM  # system 消息不受 gate 影响
    
    if requested_visibility == MessageVisibility.SIDE:
        return MessageVisibility.SIDE    # 显式 side 消息不升级
    
    # 以下处理 requested_visibility == PUBLIC 的情况
    if mode == ConversationMode.AUTO:
        return MessageVisibility.PUBLIC  # auto 模式：所有人正常发
    
    if mode == ConversationMode.COPILOT:
        if role == ParticipantRole.OPERATOR:
            return MessageVisibility.SIDE  # copilot: operator 消息降级为 side
        return MessageVisibility.PUBLIC    # agent 正常发
    
    if mode == ConversationMode.TAKEOVER:
        if role == ParticipantRole.AGENT:
            return MessageVisibility.SIDE  # takeover: agent 消息降级为 side
        if role == ParticipantRole.OPERATOR:
            return MessageVisibility.PUBLIC # operator 消息到客户
        return MessageVisibility.PUBLIC
    
    return requested_visibility
```

**Gate 是 mechanism 级别的保证**：agent 在 takeover 模式下无法绕过 gate 直接向客户发消息。这是和纯 prompt 约定方案的根本区别。

---

## §6. Timer（计时器）

Timer 用于实现超时逻辑（如 180s 接管等待、idle 超时等）。

```python
@dataclass
class Timer:
    conversation_id: str
    name: str                    # 计时器名称（如 "takeover_wait"）
    duration: timedelta          # 持续时间
    on_expire: TimerAction       # 超时动作
    started_at: datetime
    cancelled: bool = False

@dataclass 
class TimerAction:
    type: str                    # "mode_change" | "system_message" | "callback"
    params: dict                 # 动作参数
```

### Timer 操作

| 操作 | 签名 | 触发事件 |
|------|------|---------|
| 设置 | `set_timer(conv_id, name, duration, on_expire) → Timer` | `timer.set` |
| 取消 | `cancel_timer(conv_id, name) → void` | `timer.cancelled` |
| 超时 | (自动) | `timer.expired` → 执行 on_expire 动作 |

### 预定义 Timer 模式（App 可配置）

| Timer 名称 | 默认时长 | 超时动作 | 用途 | 设置时机 | 取消时机 |
|-----------|---------|---------|------|---------|---------|
| `takeover_wait` | 180s | mode → auto + system message | 人工接管等待 | Agent @operator 后 | operator /hijack |
| `idle_timeout` | 300s | state → idle | 对话无活动 | 最后一条消息后 | 新消息到达 |
| `close_timeout` | 3600s | state → closed | idle 后关闭 | state → idle 后 | reactivate |
| `sla_first_reply` | 60s | event: sla.breach | 人工首回 < 60s | mode → takeover 后 | operator 首条 public 消息 |
| `sla_onboard` | 3s | event: sla.breach | 首屏应答 < 3s | conversation.created | agent 首条 public 消息 |
| `sla_placeholder` | 1s | event: sla.breach | 占位消息 < 1s | 复杂查询检测后（App 插件标记） | 占位消息发出 |
| `sla_slow_query` | 15s | event: sla.breach | 慢查询续写 < 15s | 占位消息发出后 | edit_message 调用 |

**SLA 度量**：每个 SLA timer 的 set 和 cancel/expire 都记录事件。实际响应时间 = cancel_time - set_time。App 通过 EventBus.query 计算平均值。

Timer 的具体时长和动作由 App 在注册时配置，协议只提供 timer 机制。

---

## §7. Event（事件总线）

所有协议状态变化都产生事件。App 通过订阅事件实现业务逻辑。

### 事件类型

```python
class EventType(Enum):
    # Conversation 生命周期
    CONVERSATION_CREATED = "conversation.created"
    CONVERSATION_ACTIVATED = "conversation.activated"
    CONVERSATION_IDLED = "conversation.idled"
    CONVERSATION_REACTIVATED = "conversation.reactivated"
    CONVERSATION_CLOSED = "conversation.closed"
    CONVERSATION_RESOLVED = "conversation.resolved"
    CONVERSATION_CSAT_RECORDED = "conversation.csat_recorded"
    
    # Participant
    PARTICIPANT_JOINED = "participant.joined"
    PARTICIPANT_LEFT = "participant.left"
    
    # Mode
    MODE_CHANGED = "mode.changed"
    
    # Message
    MESSAGE_SENT = "message.sent"
    MESSAGE_EDITED = "message.edited"
    MESSAGE_GATED = "message.gated"   # 消息被 gate 修改了 visibility
    MESSAGE_DELETED = "message.deleted"
    
    # Timer
    TIMER_SET = "timer.set"
    TIMER_EXPIRED = "timer.expired"
    TIMER_CANCELLED = "timer.cancelled"
    
    # SLA
    SLA_BREACH = "sla.breach"
    
    # Squad
    SQUAD_ASSIGNED = "squad.assigned"
    SQUAD_REASSIGNED = "squad.reassigned"
```

### 事件结构

```python
@dataclass
class Event:
    type: EventType
    conversation_id: str
    data: dict              # 事件特定数据
    timestamp: datetime
    id: str                 # 唯一事件 ID（用于去重和审计）
```

### 事件持久化

所有事件写入 SQLite（`~/.zchat/projects/{name}/events.db`），用于：
- App 层查询统计（计费指标、SLA 监控）
- 审计追溯
- 回放调试

---

## §8. Commands（通用命令）

协议内建的命令，任何 App 都可使用。命令通过 IRC 消息发送（以 `/` 开头），channel-server 拦截并处理。

### 模式控制命令

| 命令 | 发送者 | 效果 | 产生事件 |
|------|--------|------|---------|
| `/hijack` | operator | 切换到 takeover 模式 | mode.changed |
| `/release` | operator | 从 takeover 恢复到 auto | mode.changed |
| `/copilot` | operator | 切换到 copilot（或从 takeover 降级） | mode.changed |

### 结案命令

| 命令 | 发送者 | 效果 | 产生事件 |
|------|--------|------|---------|
| `/resolve` | operator/agent | 标记 conversation 为 resolved，触发 CSAT | conversation.resolved |
| `/abandon` | system | 标记为 abandoned | conversation.resolved |

### 分队管理命令

| 命令 | 发送者 | 效果 | 产生事件 |
|------|--------|------|---------|
| `/assign {agent} {operator}` | admin | 将 agent 分配给 operator 分队 | squad.assigned |
| `/reassign {agent} {from} {to}` | admin | 转移 agent | squad.reassigned |
| `/squad` | operator | 查看自己分队的 agent 列表 | — |

### 查询命令

| 命令 | 发送者 | 效果 |
|------|--------|------|
| `/status` | operator/admin | 返回当前所有 active conversation 列表 |
| `/status #conv-{id}` | operator | 返回指定 conversation 的详细状态 |
| `/dispatch {conv_id} {agent_nick}` | admin | 将 agent 分配到指定 conversation |

### 命令解析

channel-server 在 `on_pubmsg` 和 `on_privmsg` 中检测 `/` 开头的消息：
1. 解析命令名和参数
2. 验证发送者有权执行该命令（role 检查）
3. 执行命令逻辑
4. 发出对应事件
5. 返回确认消息（system visibility）

---

## §9. Plugin Hooks（插件钩子）

App 通过注册钩子扩展协议行为。钩子是 Python 函数，channel-server 在特定时机调用。

### 钩子定义

```python
class PluginHook:
    """所有钩子的基类。"""
    
    async def on_conversation_created(self, conversation: Conversation) -> None:
        """对话创建后。App 可在此初始化客户工作目录。"""
        pass
    
    async def on_message(self, message: Message, conversation: Conversation) -> MessageAction:
        """消息发送前。App 可在此实现自定义路由逻辑。
        返回 MessageAction 可以修改消息（如追加 metadata）或阻止发送。"""
        return MessageAction.ALLOW
    
    async def on_mode_changed(self, conversation: Conversation, 
                               old_mode: ConversationMode, 
                               new_mode: ConversationMode,
                               trigger: str) -> None:
        """模式切换后。App 可在此记录计费、发送通知。"""
        pass
    
    async def on_participant_joined(self, conversation: Conversation, 
                                     participant: Participant) -> None:
        """参与者加入后。App 可在此加载客户历史上下文。"""
        pass
    
    async def on_timer_expired(self, conversation: Conversation, 
                                timer: Timer) -> None:
        """计时器超时后（在 on_expire 动作执行之后）。"""
        pass
    
    async def on_event(self, event: Event) -> None:
        """所有事件的通用监听器。App 可在此做统计、审计。"""
        pass
```

### MessageAction

```python
class MessageAction(Enum):
    ALLOW = "allow"         # 正常处理
    BLOCK = "block"         # 阻止发送（静默丢弃）
    MODIFY = "modify"       # 允许但修改内容（通过返回新 Message）
```

### 钩子加载

channel-server 启动时扫描插件目录，加载实现了 `PluginHook` 的 Python 模块：

```
~/.zchat/projects/{name}/plugins/
├── autoservice_routing.py    # AutoService 的路由策略
├── autoservice_metrics.py    # AutoService 的计费
└── another_app_plugin.py     # 另一个 App 的插件
```

---

## §10. 协议约束

### 不变量（Invariants）

1. **每个 Conversation 最多一个 mode** — 不存在"部分 takeover"
2. **Gate 是强制的** — 没有 bypass gate 的方式
3. **事件是不可变的** — 事件一旦产生不可修改或删除
4. **命令只能由有权角色执行** — /hijack 只能由 operator 执行，不能由 agent 执行
5. **visibility 降级不可逆** — 被 gate 降为 side 的消息不会在后续被升级为 public

### 并发安全

- mode 切换是原子的（通过锁保证同一时刻只有一个切换操作）
- Timer 在 asyncio 事件循环中执行，不存在线程竞争
- 事件 ID 使用 UUID，保证全局唯一

---

*End of Protocol Primitives v1.0*
