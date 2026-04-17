# Channel-Server v1.0 — 实现设计

> channel-server 是协议原语的实现载体，独立进程运行

---

## 1. 模块职责

channel-server 是一个 Python 进程，同时扮演三个角色：

1. **MCP Server** — 对每个 Agent 的 Claude Code session 暴露 tools（reply、edit_message、join_conversation）
2. **IRC Client** — 连接 ergo IRC server，管理 channel，收发消息
3. **Bridge API Server** — 对 Bridge 层暴露 WebSocket 接口

```
┌─────────────────────────────────────────────────────────┐
│  channel-server 进程                                     │
│                                                          │
│  ┌─── MCP Server (stdio) ───┐   ┌─── Bridge API ────┐  │
│  │  Tools:                   │   │  WebSocket :9999   │  │
│  │  - reply                  │   │  register/message  │  │
│  │  - edit_message           │   │  /reply/event      │  │
│  │  - join_conversation      │   └────────┬───────────┘  │
│  │  - list_conversations     │            │              │
│  │  Notifications:           │            │              │
│  │  - channel (inject msg)   │            │              │
│  └────────────┬──────────────┘            │              │
│               │                           │              │
│  ┌────────────▼───────────────────────────▼──────────┐  │
│  │              Core Engine                           │  │
│  │                                                    │  │
│  │  ConversationManager  ──── 对话 CRUD + 状态机      │  │
│  │  ModeManager          ──── 模式切换 + 验证         │  │
│  │  MessageGate          ──── visibility 决策         │  │
│  │  MessageStore         ──── 消息历史 + edit 支持    │  │
│  │  TimerManager         ──── asyncio 计时器          │  │
│  │  EventBus             ──── 发布/订阅 + 持久化      │  │
│  │  CommandParser        ──── /hijack 等命令解析       │  │
│  │  PluginManager        ──── 钩子注册 + 调用         │  │
│  │  ParticipantRegistry  ──── 角色识别 + 映射         │  │
│  │  SquadRegistry        ──── Agent-Operator 分队管理 │  │
│  │                                                    │  │
│  └────────────┬───────────────────────────────────────┘  │
│               │                                          │
│  ┌────────────▼──────────────────────────────────────┐  │
│  │          IRC Transport                             │  │
│  │  IRC Client → ergo                                 │  │
│  │  channel 管理 (join/part)                          │  │
│  │  消息收发 (pubmsg/privmsg)                         │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## 2. 文件结构

```
zchat-channel-server/
├── server.py                    # 入口：MCP Server + main()
├── protocol/                    # 协议原语实现（纯逻辑，不含 I/O）
│   ├── __init__.py
│   ├── conversation.py          # Conversation + ConversationState + CRUD
│   ├── participant.py           # Participant + ParticipantRole
│   ├── mode.py                  # ConversationMode + 状态机 + 转换验证
│   ├── message_types.py          # Message + MessageVisibility（避免与根 message.py 冲突）
│   ├── gate.py                  # MessageGate — gate_message() 函数
│   ├── timer.py                 # Timer + TimerAction
│   ├── event.py                 # Event + EventType + EventBus
│   └── commands.py              # 命令定义 + 解析
├── engine/                      # 协议引擎（有状态，管理运行时）
│   ├── __init__.py
│   ├── conversation_manager.py  # ConversationManager（内存 + SQLite）
│   ├── mode_manager.py          # ModeManager（状态转换 + gate 调用）
│   ├── message_store.py         # MessageStore（消息历史 + edit）
│   ├── timer_manager.py         # TimerManager（asyncio 调度）
│   ├── plugin_manager.py        # PluginManager（钩子加载 + 调用）
│   ├── participant_registry.py  # ParticipantRegistry（角色映射）
│   └── squad_registry.py       # SquadRegistry（分队分配管理）
├── transport/                   # IRC transport 适配
│   ├── __init__.py
│   └── irc_transport.py         # IRC 连接、channel 管理、消息收发
├── bridge_api/                  # Bridge 层 WebSocket API
│   ├── __init__.py
│   └── ws_server.py             # WebSocket server for bridges
├── message.py                   # 现有：detect_mention, chunk_message（保留）
├── instructions.md              # 现有：Agent instructions（保留）
├── tests/
│   ├── test_gate.py             # Gate 逻辑单元测试
│   ├── test_mode.py             # 模式转换测试
│   ├── test_conversation.py     # Conversation 生命周期测试
│   ├── test_timer.py            # Timer 测试
│   └── test_commands.py         # 命令解析测试
└── plugins/                     # App 插件目录（运行时扫描）
    └── README.md
```

### 职责分离

| 目录 | 依赖 | 可测试性 | 说明 |
|------|------|---------|------|
| `protocol/` | 无外部依赖 | 纯函数，100% 单元测试 | 数据模型 + 状态机逻辑 |
| `engine/` | 依赖 protocol/ + asyncio + sqlite | 需要 mock I/O | 有状态的运行时管理 |
| `transport/` | 依赖 irc 库 | 需要 IRC server | IRC 适配层 |
| `bridge_api/` | 依赖 websockets | 需要 WS client | Bridge 通信层 |
| `server.py` | 依赖 mcp + 上述所有 | E2E 测试 | 胶水代码 |

---

## 3. 核心模块设计

### 3.1 ConversationManager

```python
class ConversationManager:
    """管理所有 conversation 的生命周期。"""
    
    def __init__(self, db_path: str):
        self._conversations: dict[str, Conversation] = {}  # 内存缓存
        self._db = sqlite3.connect(db_path)                # 持久化
        self._load_active()                                 # 启动时加载 active 的
    
    def create(self, conversation_id: str, metadata: dict = None) -> Conversation:
        """创建新 conversation，或返回已有（幂等）。"""
        ...
    
    def get(self, conversation_id: str) -> Conversation | None:
        """查询。"""
        ...
    
    def activate(self, conversation_id: str) -> None:
        """created → active。"""
        ...
    
    def idle(self, conversation_id: str) -> None:
        """active → idle。"""
        ...
    
    def reactivate(self, conversation_id: str) -> None:
        """idle → active，加载历史上下文。"""
        ...
    
    def close(self, conversation_id: str) -> None:
        """→ closed。"""
        ...
    
    def list_active(self) -> list[Conversation]:
        """列出所有 active 的 conversation。"""
        ...
    
    def add_participant(self, conversation_id: str, participant: Participant) -> None:
        """添加参与者。对 operator 做并发上限检查。"""
        if participant.role == ParticipantRole.OPERATOR:
            current = self._count_operator_conversations(participant.id)
            if current >= self.max_operator_concurrent:
                raise ConcurrencyLimitExceeded(
                    f"Operator {participant.id} 已达并发上限 ({current}/{self.max_operator_concurrent})"
                )
        ...
    
    def remove_participant(self, conversation_id: str, participant_id: str) -> None:
        ...
    
    def resolve(self, conversation_id: str, outcome: str, resolved_by: str) -> None:
        """结案。设置 resolution + 关闭 conversation。"""
        conv = self.get(conversation_id)
        conv.resolution = ConversationResolution(
            outcome=outcome, resolved_by=resolved_by
        )
        self.close(conversation_id)
        # EventBus.publish(conversation.resolved)
    
    def set_csat(self, conversation_id: str, score: int) -> None:
        """记录 CSAT 评分（1-5）。"""
        conv = self.get(conversation_id)
        if conv.resolution:
            conv.resolution.csat_score = score
        # EventBus.publish(conversation.csat_recorded)
```

**持久化 Schema**:
```sql
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'created',
    mode TEXT NOT NULL DEFAULT 'auto',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata JSON DEFAULT '{}'
);

CREATE TABLE participants (
    conversation_id TEXT NOT NULL,
    participant_id TEXT NOT NULL,
    role TEXT NOT NULL,
    joined_at TEXT NOT NULL,
    metadata JSON DEFAULT '{}',
    PRIMARY KEY (conversation_id, participant_id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

-- 消息历史（MessageStore）
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    source TEXT NOT NULL,              -- participant_id
    content TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'public',  -- public/side/system
    timestamp TEXT NOT NULL,
    edit_of TEXT,                       -- 如果是编辑，指向原消息 id
    metadata JSON DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
CREATE INDEX idx_messages_conv ON messages(conversation_id, timestamp);

-- 事件日志（EventBus）
CREATE TABLE events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,                 -- EventType 枚举值
    conversation_id TEXT,
    data JSON DEFAULT '{}',
    timestamp TEXT NOT NULL
);
CREATE INDEX idx_events_conv ON events(conversation_id, timestamp);
CREATE INDEX idx_events_type ON events(type, timestamp);

-- 结案信息（ConversationResolution）
CREATE TABLE resolutions (
    conversation_id TEXT PRIMARY KEY,
    outcome TEXT NOT NULL,             -- resolved/abandoned/escalated
    resolved_by TEXT NOT NULL,
    csat_score INTEGER,                -- 1-5, nullable
    timestamp TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
```

### 持久化与启动恢复

channel-server 启动时：
1. 从 SQLite 加载所有 `state != 'closed'` 的 conversation 到内存
2. 对每个 active conversation，重新 JOIN 对应的 IRC channel
3. 内存 dict 作为运行时路由表，SQLite 作为持久化备份
4. 所有写操作同时更新内存和 SQLite

老客户回来时：
1. Bridge 发 `customer_connect` + `conversation_id`
2. CS 查 SQLite: conversation 是否存在?
   - 存在 + state=idle → `reactivate()` + 从 messages 表加载最近 N 条历史
   - 存在 + state=closed → 创建新 conversation，但 metadata 中引用旧 conversation_id
   - 不存在 → `create()` 新 conversation
3. 历史消息通过 Bridge API 推送给客户端（如果渠道支持历史加载）

### 3.2 ModeManager

```python
class ModeManager:
    """管理 conversation 的模式切换。"""
    
    VALID_TRANSITIONS = {
        (ConversationMode.AUTO, ConversationMode.COPILOT),
        (ConversationMode.AUTO, ConversationMode.TAKEOVER),
        (ConversationMode.COPILOT, ConversationMode.TAKEOVER),
        (ConversationMode.COPILOT, ConversationMode.AUTO),
        (ConversationMode.TAKEOVER, ConversationMode.AUTO),
        (ConversationMode.TAKEOVER, ConversationMode.COPILOT),
    }
    
    def transition(self, conversation: Conversation, 
                   new_mode: ConversationMode,
                   trigger: str,
                   triggered_by: str) -> ModeTransition:
        """执行模式切换。验证合法性，更新状态，发出事件。"""
        old_mode = conversation.mode
        if (old_mode, new_mode) not in self.VALID_TRANSITIONS:
            raise InvalidModeTransition(old_mode, new_mode)
        
        conversation.mode = new_mode
        transition = ModeTransition(
            from_mode=old_mode, to_mode=new_mode,
            trigger=trigger, triggered_by=triggered_by
        )
        # EventBus.publish(mode.changed, ...)
        return transition
```

### 3.3 MessageGate

见 `01-protocol-primitives.md §5` 的 `gate_message()` 函数。Engine 层的封装：

```python
class MessageGateEngine:
    """封装 gate 逻辑 + 事件发出。"""
    
    def process(self, conversation: Conversation, sender: Participant,
                message: Message) -> Message:
        """处理消息：应用 gate → 可能修改 visibility → 返回处理后的消息。"""
        original_visibility = message.visibility
        final_visibility = gate_message(conversation, sender, message.visibility)
        
        if final_visibility != original_visibility:
            message.visibility = final_visibility
            # 发出 message.gated 事件
        
        return message
```

### 3.4 TimerManager

```python
class TimerManager:
    """基于 asyncio 的计时器管理。"""
    
    def __init__(self, event_bus: EventBus):
        self._timers: dict[tuple[str, str], asyncio.Task] = {}  # (conv_id, name) → task
        self._event_bus = event_bus
    
    def set_timer(self, conv_id: str, name: str, 
                  duration: timedelta, on_expire: TimerAction) -> Timer:
        key = (conv_id, name)
        if key in self._timers:
            self._timers[key].cancel()  # 重复设置则取消旧的
        
        timer = Timer(conversation_id=conv_id, name=name, 
                      duration=duration, on_expire=on_expire,
                      started_at=datetime.now())
        
        task = asyncio.create_task(self._wait_and_fire(timer))
        self._timers[key] = task
        return timer
    
    async def _wait_and_fire(self, timer: Timer):
        await asyncio.sleep(timer.duration.total_seconds())
        # 执行 on_expire 动作
        # 发出 timer.expired 事件
```

### 3.5 EventBus

```python
class EventBus:
    """发布/订阅 + SQLite 持久化。"""
    
    def __init__(self, db_path: str):
        self._subscribers: dict[EventType, list[Callable]] = defaultdict(list)
        self._db = sqlite3.connect(db_path)
        self._init_db()
    
    def subscribe(self, event_type: EventType, callback: Callable) -> None:
        self._subscribers[event_type].append(callback)
    
    async def publish(self, event: Event) -> None:
        # 1. 持久化到 SQLite
        self._persist(event)
        # 2. 通知订阅者
        for callback in self._subscribers.get(event.type, []):
            try:
                await callback(event)
            except Exception as e:
                log.error(f"Event subscriber error: {e}")
    
    def query(self, conversation_id: str = None, 
              event_type: EventType = None,
              since: datetime = None) -> list[Event]:
        """查询历史事件（App 用于统计）。"""
        ...
```

### 3.6 ParticipantRegistry

```python
class ParticipantRegistry:
    """维护 IRC nick → Participant 角色的映射。"""
    
    def __init__(self):
        self._agents: dict[str, Participant] = {}     # nick → participant
        self._operators: dict[str, Participant] = {}   # nick → participant
        self._bridges: dict[str, str] = {}             # bridge_nick → bridge_type
    
    def register_agent(self, nick: str, metadata: dict = None) -> Participant:
        """Agent 启动时注册。"""
        ...
    
    def register_operator(self, nick: str, metadata: dict = None) -> Participant:
        """Operator 连接时注册（或通过配置预注册）。"""
        ...
    
    def identify(self, nick: str) -> Participant | None:
        """根据 nick 识别角色。"""
        if nick in self._agents:
            return self._agents[nick]
        if nick in self._operators:
            return self._operators[nick]
        if nick in self._bridges:
            return Participant(id=nick, role=ParticipantRole.CUSTOMER)
        return None
```

---

## 4. MCP Tools

channel-server 对 Agent 暴露的 MCP tools：

| Tool | 参数 | 说明 |
|------|------|------|
| `reply` | `chat_id: str, text: str, visibility: str = "public"` | 发送消息（Gate 可能修改 visibility） |
| `edit_message` | `message_id: str, text: str` | 编辑已发送的消息 |
| `join_conversation` | `conversation_id: str` | 加入一个 conversation |
| `leave_conversation` | `conversation_id: str` | 离开一个 conversation |
| `list_conversations` | — | 列出 agent 参与的所有 active conversation |
| `get_conversation_status` | `conversation_id: str` | 获取 conversation 状态（mode、participants） |
| `send_side_message` | `conversation_id: str, text: str` | 发 side 消息（副驾驶建议） |

### App MCP Tools（业务工具注册）

channel-server 的 MCP tools 分两类：

1. **协议 tools**（上表）— channel-server 内建，所有 App 共用
2. **App tools** — App 的业务工具（知识库查询、CRM、定价引擎等），由 App 的 plugin_loader 发现并注入

**App tools 的注册流程**：

channel-server 启动时通过 `app_tools_loader` 配置项加载 App 的业务工具：

```toml
# config.toml
[channel_server]
app_tools_module = "autoservice.plugin_loader"  # App 的插件发现模块
app_tools_dir = "plugins"                        # App 的插件目录
```

```python
# server.py 启动时:
async def main():
    # ... 初始化 engine 组件 ...
    
    # 加载 App 业务工具（和协议工具并列注册到 MCP）
    app_tools = []
    if config.get("app_tools_module"):
        module = importlib.import_module(config["app_tools_module"])
        plugins = module.discover(config.get("app_tools_dir", "plugins"))
        for p in plugins:
            app_tools.extend(p.tools)
    
    # 注册所有 tools（协议 + App）
    register_tools(server, app_tools)
```

**register_tools 改造**（对应现有 AutoService `feishu/channel.py` L237-290 的模式）：

```python
def register_tools(server: Server, app_tools: list):
    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        protocol_tools = [
            Tool(name="reply", ...),
            Tool(name="edit_message", ...),
            # ... 协议 tools
        ]
        dynamic_tools = [
            Tool(name=pt.name, description=pt.description, inputSchema=pt.input_schema)
            for pt in app_tools
        ]
        return protocol_tools + dynamic_tools

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict):
        # 先查协议 tools
        if name == "reply":
            return await _handle_reply(arguments)
        # ... 其他协议 tools
        
        # 再查 App tools
        for pt in app_tools:
            if pt.name == name:
                result = pt.handler(**arguments)
                if asyncio.iscoroutine(result):
                    result = await result
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
        
        raise ValueError(f"Unknown tool: {name}")
```

这样 AutoService 的 `plugin_loader.py` 和 `plugins/` 目录完全不用改——channel-server 启动时调用 `discover()` 加载，和现有 `feishu/channel.py` 的方式一致。

### 新增 vs 现有

| Tool | 状态 | 改动 |
|------|------|------|
| `reply` | ✅ 已有 | 新增 `visibility` 参数 + Gate 处理 |
| `join_channel` | ✅ 已有 | 重命名为 `join_conversation` |
| `edit_message` | ❌ 新增 | |
| `leave_conversation` | ❌ 新增 | |
| `list_conversations` | ❌ 新增 | |
| `get_conversation_status` | ❌ 新增 | |
| `send_side_message` | ❌ 新增 | |

---

## 5. Bridge API (WebSocket)

channel-server 开启一个 WebSocket 端口（默认 9999）供 Bridge 连接。

### 设计原则：IRC 对租户不可见

**IRC 是纯内部 transport**，仅用于 channel-server ↔ agent 之间的通信。所有人类用户（客户、客服、管理员）都通过 Bridge API 接入，不直接使用 IRC/WeeChat。

```
客户 David:   Web/飞书 → Bridge → channel-server (Bridge API)
客服 小李:    飞书"分队群" → Bridge → channel-server (Bridge API)
管理员 老陈:  飞书"管理群" → Bridge → channel-server (Bridge API)
开发者:       WeeChat → IRC（可选，调试用）

channel-server ←→ agent:  IRC transport（内部）
```

Bridge 在注册时声明自己代理的角色类型，channel-server 据此应用不同的权限和 visibility 规则。

### 消息格式

#### Bridge 注册（支持多角色）

```json
{"type": "register", "bridge_type": "feishu", "instance_id": "feishu-bridge-1",
 "capabilities": ["customer", "operator", "admin"]}
```

capabilities 声明该 Bridge 可以代理哪些角色的消息。

#### 客户侧消息（Bridge → CS）

```json
{"type": "customer_connect", "conversation_id": "feishu_oc_xxx", 
 "customer": {"id": "feishu_ou_xxx", "name": "张三"}, "metadata": {}}

{"type": "customer_message", "conversation_id": "feishu_oc_xxx",
 "text": "B套餐多少钱", "message_id": "msg_001"}

{"type": "customer_disconnect", "conversation_id": "feishu_oc_xxx"}
```

#### Operator 侧消息（Bridge → CS）

```json
{"type": "operator_join", "conversation_id": "feishu_oc_xxx",
 "operator": {"id": "xiaoli", "name": "客服小李"}}

{"type": "operator_message", "conversation_id": "feishu_oc_xxx",
 "operator_id": "xiaoli", "text": "建议强调本月优惠", "message_id": "op_001"}

{"type": "operator_command", "conversation_id": "feishu_oc_xxx",
 "operator_id": "xiaoli", "command": "/hijack"}

{"type": "operator_leave", "conversation_id": "feishu_oc_xxx",
 "operator_id": "xiaoli"}
```

channel-server 收到 `operator_message` 后，根据当前 mode 应用 Gate：
- copilot → 消息降级为 side（不到客户）
- takeover → 消息保持 public（到客户）

channel-server 收到 `operator_command` 后，执行对应协议命令（/hijack, /release, /resolve 等）。

#### Admin 侧消息（Bridge → CS）

```json
{"type": "admin_command", "admin_id": "laochen",
 "command": "/status"}

{"type": "admin_command", "admin_id": "laochen",
 "command": "/dispatch feishu_oc_xxx deep-agent"}

{"type": "admin_command", "admin_id": "laochen",
 "command": "/assign fast-agent xiaoli"}
```

#### CS → Bridge 回复

```json
{"type": "registered", "instance_id": "feishu-bridge-1"}

{"type": "reply", "conversation_id": "feishu_oc_xxx", 
 "text": "B套餐每月199元...", "message_id": "cs_msg_002",
 "visibility": "public"}

{"type": "reply", "conversation_id": "feishu_oc_xxx",
 "text": "[副驾驶建议] 客户上月购买过 X 服务", "message_id": "cs_msg_003",
 "visibility": "side"}

{"type": "edit", "conversation_id": "feishu_oc_xxx",
 "message_id": "cs_msg_002", "new_text": "B套餐每月199元,本月8折优惠..."}

{"type": "event", "event_type": "mode.changed", 
 "conversation_id": "feishu_oc_xxx", "data": {...}}

{"type": "csat_request", "conversation_id": "feishu_oc_xxx"}

{"type": "command_response", "command": "/status",
 "result": "当前 active 对话 3 个:\n#1 feishu_oc_abc123 · David · takeover..."}
```

**Bridge → CS (CSAT 回传)**:
```json
{"type": "csat_response", "conversation_id": "feishu_oc_xxx", "score": 5}
```

### Visibility 路由规则

Bridge 收到 CS 的回复后，根据 `visibility` 字段决定转发给谁：

| visibility | 转发给客户端 | 转发给 operator 端 | 转发给 admin 端 |
|-----------|:-----------:|:-----------------:|:--------------:|
| `public` | ✅ | ✅ | ✅ |
| `side` | ❌ | ✅ | ✅ |
| `system` | ❌ | ✅ | ✅ |

**关键变化**：之前 spec 说 "side 和 system 不经过 Bridge"，这是错的。side 消息必须经过 Bridge 才能送达 operator（因为 operator 也通过 Bridge 接入）。正确的规则是：**Bridge 收到所有 visibility 的消息，但只把 public 转发给客户端渠道，side+system 只转发给 operator/admin 渠道**。

### 飞书 Bridge 的渠道映射

一个飞书 Bridge 实例同时代理多个飞书群：

```
飞书群                          channel-server 角色
─────────────────────────────────────────────────
客户对话群 (oc_xxx)           → customer 消息
小李的 Agent 分队群           → operator 消息 (小李看到卡片、发建议)
管理群                        → admin 消息 (/status /dispatch 命令)
```

Bridge 根据飞书群的 chat_id 判断消息属于哪个角色：
- `admin_chat_id` 配置的群 → admin
- `squad_chat_ids` 配置的群 → operator
- 其他群 → customer

---

## 6. IRC Transport 适配

### on_pubmsg 改造

```python
def on_pubmsg(conn, event):
    nick = event.source.nick
    channel = event.target  # e.g., "#conv-feishu_oc_xxx"
    body = event.arguments[0]
    
    # 1. 识别发送者角色
    participant = participant_registry.identify(nick)
    if participant is None:
        return  # 未知 nick，忽略
    
    # 2. 检查是否是命令
    if body.startswith("/"):
        command_parser.handle(body, participant, channel)
        return
    
    # 3. 提取 conversation_id
    conv_id = channel.removeprefix("#conv-")
    conversation = conversation_manager.get(conv_id)
    if conversation is None:
        return
    
    # 4. 构造 Message
    message = Message(
        id=generate_id(),
        source=participant.id,
        conversation_id=conv_id,
        content=body,
        visibility=MessageVisibility.PUBLIC,  # 请求 public
        timestamp=datetime.now()
    )
    
    # 5. Gate 处理
    message = message_gate.process(conversation, participant, message)
    
    # 6. 存储
    message_store.save(message)
    
    # 7. 分发（Bridge 收到所有 visibility 的消息，由 Bridge 按角色过滤）
    if message.visibility == MessageVisibility.PUBLIC:
        # Bridge 转发给所有端（客户 + operator + admin）
        bridge_api.send_reply(conv_id, message, visibility="public")
        inject_to_agent(message, conv_id)
    elif message.visibility == MessageVisibility.SIDE:
        # Bridge 只转发给 operator/admin 端（客户看不到）
        bridge_api.send_reply(conv_id, message, visibility="side")
        inject_to_agent(message, conv_id)
    elif message.visibility == MessageVisibility.SYSTEM:
        # Bridge 只转发给 operator/admin 端
        bridge_api.send_reply(conv_id, message, visibility="system")
        inject_to_agent(message, conv_id)
    
    # 8. 发出事件
    event_bus.publish(Event(type=EventType.MESSAGE_SENT, ...))
```

### Operator JOIN 检测

```python
def on_join(conn, event):
    nick = event.source.nick
    channel = event.target
    
    if not channel.startswith("#conv-"):
        return
    
    conv_id = channel.removeprefix("#conv-")
    participant = participant_registry.identify(nick)
    
    if participant and participant.role == ParticipantRole.OPERATOR:
        conversation = conversation_manager.get(conv_id)
        if conversation and conversation.mode == ConversationMode.AUTO:
            # Operator 加入 → 自动切换到 copilot
            mode_manager.transition(
                conversation, ConversationMode.COPILOT,
                trigger="operator_joined", triggered_by=nick
            )
        conversation_manager.add_participant(conv_id, participant)
```

---

## 7. 启动流程

```python
async def main():
    # 1. 初始化 Core Engine
    event_bus = EventBus(db_path)
    conversation_manager = ConversationManager(db_path)
    mode_manager = ModeManager(event_bus)
    message_gate = MessageGateEngine(event_bus)
    message_store = MessageStore(db_path)
    timer_manager = TimerManager(event_bus)
    participant_registry = ParticipantRegistry()
    plugin_manager = PluginManager(plugins_dir)
    command_parser = CommandParser(conversation_manager, mode_manager, timer_manager)
    
    # 2. 加载 App 插件
    plugin_manager.load_all()
    plugin_manager.register_hooks(event_bus)
    
    # 3. 启动 IRC transport
    irc_transport = IRCTransport(server, port, nick)
    irc_transport.on_pubmsg = make_pubmsg_handler(...)
    irc_transport.on_join = make_join_handler(...)
    
    # 4. 启动 Bridge API
    bridge_server = BridgeAPIServer(port=9999)
    bridge_server.on_customer_connect = make_customer_handler(...)
    
    # 5. 启动 MCP Server
    mcp_server = create_mcp_server(...)
    register_mcp_tools(mcp_server, ...)
    
    # 6. 并行运行
    async with anyio.create_task_group() as tg:
        tg.start_soon(mcp_server.run, ...)
        tg.start_soon(irc_transport.run)
        tg.start_soon(bridge_server.run)
```

---

## 8. 配置

channel-server 的配置通过环境变量 + 项目 config.toml：

```toml
# ~/.zchat/projects/{name}/config.toml 新增

[channel_server]
bridge_port = 9999              # Bridge API 端口
plugins_dir = "plugins"         # 插件目录
db_path = "conversations.db"    # SQLite 数据库路径

[channel_server.timers]
takeover_wait = 180             # 接管等待超时（秒）
idle_timeout = 300              # 对话闲置超时（秒）
close_timeout = 3600            # 闲置后自动关闭（秒）

[channel_server.participants]
# 预注册 operator nick 列表
operators = ["xiaoli", "xiaowang"]
# Bridge nick 前缀
bridge_prefixes = ["feishu-bridge", "web-bridge"]
# Operator 并发上限
max_operator_concurrent = 5
```

---

*End of Channel-Server Implementation Design v1.0*
