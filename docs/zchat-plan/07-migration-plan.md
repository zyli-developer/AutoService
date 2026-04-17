# Channel-Server v1.0 — 三层修改方案

> 对照 AutoService 现有实现，形成可执行的修改清单
> 三层：zchat CLI / channel-server / AutoService (App + Agent)

---

## 总览

```
┌─ zchat CLI (少量修改) ──────────────────────────────────┐
│  agent 模板系统 · 批量创建 · 项目配置扩展               │
└──────────────────────────────────────────────────────────┘

┌─ channel-server (核心改造) ──────────────────────────────┐
│  现有: server.py (320行) + message.py                    │
│  新增: protocol/ + engine/ + transport/ + bridge_api/    │
│  保留: MCP Server 入口 + IRC 连接基础                    │
└──────────────────────────────────────────────────────────┘

┌─ AutoService (App 层适配) ──────────────────────────────┐
│  删除: feishu/channel_server.py (1143行)                │
│        feishu/channel.py (376行)                         │
│        web/websocket.py (326行)                          │
│  保留: autoservice/ 全部业务逻辑                         │
│  新增: channel-server plugins/ + agent soul.md 模板      │
│  修改: web/app.py · Makefile · channel-instructions.md  │
└──────────────────────────────────────────────────────────┘
```

---

## Layer 1: zchat CLI 修改

### 修改 1.1: 项目配置扩展

**文件**: `zchat/cli/project.py`
**内容**: config.toml 新增 `[channel_server]` 段

```toml
# ~/.zchat/projects/{name}/config.toml 新增

[channel_server]
bridge_port = 9999
plugins_dir = "plugins"
db_path = "conversations.db"

[channel_server.timers]
takeover_wait = 180
idle_timeout = 300
close_timeout = 3600

[channel_server.participants]
operators = []
bridge_prefixes = ["feishu-bridge", "web-bridge"]
max_operator_concurrent = 5
```

**改动量**: ~20 行，在 `project.py` 的默认配置中增加 channel_server 段。

### 修改 1.2: Agent 模板系统

**文件**: 新增 `zchat/cli/templates/` 下的模板

```
templates/
├── claude-channel/          # 现有默认模板（保留）
├── autoservice-fast/        # 新增
│   ├── template.toml        # model=haiku, channels=["#general"]
│   ├── soul.md              # 快速响应 + 占位策略
│   └── start.sh
├── autoservice-deep/        # 新增
│   ├── template.toml        # model=opus, channels=["#general"]
│   ├── soul.md              # 深度分析
│   └── start.sh
├── autoservice-triage/      # 新增：智能分流
│   ├── template.toml
│   ├── soul.md              # 路由决策 + SLA 守护
│   └── start.sh
└── autoservice-admin/       # 新增：管理 Agent
    ├── template.toml
    ├── soul.md              # 管理群命令 + 仪表盘
    └── start.sh
```

**改动量**: 新建 4 组模板文件（每组 3 个文件）。`runner.py` 和 `template_loader.py` 已支持模板机制，不需要改代码。

### 修改 1.3: 批量创建命令（可选，v1.0 可跳过）

**文件**: `zchat/cli/agent_manager.py`
**内容**: 新增 `create_team` 方法

```python
def create_team(self, team_name: str, templates: list[str]):
    """批量创建一组 agent。"""
    for tmpl in templates:
        self.create(f"{team_name}-{tmpl}", agent_type=tmpl)
```

**CLI**: `zchat agent create-team autoservice --templates fast,deep,triage,admin`

**改动量**: ~30 行。v1.0 可以手动 4 次 `zchat agent create` 替代。

---

## Layer 2: channel-server 核心改造

### 现有代码分析

当前 `server.py` 的结构：

```python
# 现有 server.py (320 行) 的职责分解:

# L1-37:   配置 + 导入
# L39-60:  inject_message() — MCP notification injection
# L63-70:  poll_irc_queue() — 队列消费
# L76-180: setup_irc() — IRC 连接 + on_pubmsg/on_privmsg/on_disconnect
# L183-206: _handle_sys_message() — __zchat_sys: 处理
# L208-283: MCP Server + Tools (create_server, register_tools, reply, join_channel)
# L290-320: main() — 启动逻辑
```

### 改造策略：增量改造，不重写

不删除现有 `server.py`，而是：
1. 把 IRC 逻辑提取到 `transport/irc_transport.py`
2. 把 MCP tools 扩展（新增 tools，保留现有）
3. 新增 `protocol/` 和 `engine/` 目录
4. `server.py` 变成胶水代码（初始化 + 启动）

### 修改 2.1: protocol/ 目录（纯数据模型）

**全部新建**，无外部依赖，可 100% 单元测试。

| 文件 | 行数估算 | 内容 |
|------|---------|------|
| `protocol/conversation.py` | ~60 | Conversation + ConversationState + ConversationResolution dataclass |
| `protocol/participant.py` | ~30 | Participant + ParticipantRole enum |
| `protocol/mode.py` | ~50 | ConversationMode enum + ModeTransition + VALID_TRANSITIONS |
| `protocol/message_types.py` | ~40 | Message + MessageVisibility enum |
| `protocol/gate.py` | ~40 | gate_message() 纯函数 |
| `protocol/timer.py` | ~30 | Timer + TimerAction dataclass |
| `protocol/event.py` | ~40 | Event + EventType enum |
| `protocol/commands.py` | ~60 | 命令定义 + 解析函数 |

**合计**: ~350 行

### 修改 2.2: engine/ 目录（有状态运行时）

| 文件 | 行数估算 | 内容 | 依赖 |
|------|---------|------|------|
| `engine/conversation_manager.py` | ~150 | CRUD + 状态机 + 并发上限 + SQLite | protocol/, sqlite3 |
| `engine/mode_manager.py` | ~60 | 状态转换 + 验证 + 事件发出 | protocol/, event_bus |
| `engine/message_store.py` | ~80 | 消息存储 + edit + 查询 | protocol/, sqlite3 |
| `engine/timer_manager.py` | ~80 | asyncio 调度 + 超时回调 | protocol/, asyncio |
| `engine/event_bus.py` | ~100 | 发布/订阅 + SQLite 持久化 + 查询 | protocol/, sqlite3 |
| `engine/plugin_manager.py` | ~60 | 钩子加载 + 调用 | protocol/ |
| `engine/participant_registry.py` | ~50 | nick → role 映射 | protocol/ |
| `engine/squad_registry.py` | ~60 | agent ↔ operator 分队管理 | protocol/ |

**合计**: ~640 行

### 修改 2.3: transport/irc_transport.py

**从现有 server.py 提取**，不是新写。

```python
# 从 server.py L72-171 提取:

class IRCTransport:
    """管理 IRC 连接。从 server.py 的 setup_irc() 重构。"""
    
    def __init__(self, server, port, nick, tls=False, auth_token=""):
        ...
    
    def connect(self):
        """对应现有 setup_irc()"""
        ...
    
    # 回调注入点（由 server.py 主逻辑设置）
    self.on_pubmsg_callback = None   # 替代现有 on_pubmsg
    self.on_privmsg_callback = None  # 替代现有 on_privmsg
    self.on_join_callback = None     # 新增：检测 operator 加入
    self.on_part_callback = None     # 新增：检测参与者离开
```

**改动量**: ~120 行（主要是从 server.py 移过来 + 加回调接口）

### 修改 2.4: bridge_api/ws_server.py

**新建**。这是给 Bridge 用的 WebSocket server，替代 AutoService 的 `channel_server.py` 的 WebSocket 部分。

```python
class BridgeAPIServer:
    """WebSocket server，接受 Bridge 连接。"""
    
    def __init__(self, port=9999, conversation_manager=None, ...):
        ...
    
    async def _handle_client(self, ws):
        """处理 Bridge 的 register / customer_connect / customer_message"""
        ...
    
    async def send_reply(self, conv_id, text, message_id):
        """向 Bridge 发送 agent 的回复（只发 public）"""
        ...
    
    async def send_edit(self, conv_id, message_id, new_text):
        """向 Bridge 发送消息编辑"""
        ...
```

**改动量**: ~150 行

### 修改 2.5: server.py 改造

保留作为入口，但职责简化为胶水代码：

```python
# 改造后的 server.py 结构:

# 导入 protocol/ + engine/ + transport/ + bridge_api/
# 现有 inject_message() 保留
# 现有 create_server() 保留
# register_tools() 扩展：新增 edit_message, join_conversation, ...

# on_pubmsg 改造：
#   原来: detect_mention → inject
#   现在: participant_registry.identify → command_parser → gate → inject/bridge

# main() 改造：
#   新增: 初始化 engine 组件
#   新增: 启动 bridge_api server
#   新增: 加载 plugins
```

**改动量**: server.py 从 320 行 → ~200 行（逻辑外移到 engine/，自身变薄）

### 修改 2.6: MCP Tools 扩展

| Tool | 现有/新增 | 改动 |
|------|---------|------|
| `reply` | 现有 | 新增 `visibility` 参数 + Gate 处理 |
| `join_channel` | 现有 | 重命名为 `join_conversation` |
| `edit_message` | **新增** | 调用 message_store.update + bridge_api.send_edit |
| `leave_conversation` | **新增** | |
| `list_conversations` | **新增** | |
| `get_conversation_status` | **新增** | |
| `send_side_message` | **新增** | visibility=side 的快捷方式 |

### 修改 2.7: pyproject.toml 更新

```toml
[project]
name = "zchat-channel-server"
version = "1.0.0"              # 版本升级
dependencies = [
    "mcp[cli]>=1.2.0",
    "irc>=20.0",
    "zchat-protocol>=0.1.0",
    "websockets>=12.0",        # 新增：Bridge API
]

[tool.hatch.build.targets.wheel]
packages = ["protocol", "engine", "transport", "bridge_api", "."]
only-include = [
    "server.py", "message.py", "instructions.md",
    "protocol/", "engine/", "transport/", "bridge_api/",
]
```

### channel-server 改动汇总

| 类别 | 新增行数 | 修改行数 | 说明 |
|------|---------|---------|------|
| protocol/ | ~350 | 0 | 纯新增 |
| engine/ | ~640 | 0 | 纯新增 |
| transport/ | ~120 | 0 | 从 server.py 提取 |
| bridge_api/ | ~150 | 0 | 纯新增 |
| server.py | 0 | ~100 | 改造（变薄，逻辑外移） |
| tests/ | ~400 | 0 | protocol + engine 测试 |
| **合计** | **~1660** | **~100** | |

---

## Layer 3: AutoService App 层修改

### 删除（被 channel-server 替代）

| 文件 | 行数 | 替代方 | 原有功能 → 新位置 |
|------|------|--------|-------------------|
| `feishu/channel_server.py` | 1143 | channel-server bridge_api + Feishu Bridge | WebSocket server → `bridge_api/ws_server.py`; Feishu WSS → `feishu_bridge.py`; 路由表 → `engine/conversation_manager.py`; admin 命令 → `protocol/commands.py` |
| `feishu/channel.py` | 376 | channel-server `server.py` | ChannelClient → 不再需要（Bridge 直连 channel-server）; MCP tools → channel-server 已有; inject_message → channel-server 已有 |
| `web/websocket.py` | 326 | Web Bridge + channel-server | WebChannelBridge → `web_bridge.py`; ws_chat → Web Bridge 处理 |

**删除合计**: 1845 行

### 新增：Bridge 层

Bridge 作为独立脚本或嵌入 AutoService：

| 文件 | 行数估算 | 来源 |
|------|---------|------|
| `bridges/feishu_bridge.py` | ~250 | 从 `feishu/channel_server.py` 迁移 Feishu WSS 部分（L443-748 的 `_run_feishu` + 飞书 API 调用），去掉路由逻辑和 WebSocket server |
| `bridges/web_bridge.py` | ~150 | 从 `web/websocket.py` 迁移 `WebChannelBridge`，改为连接 channel-server Bridge API |

**具体迁移对照**:

```
feishu/channel_server.py 拆解:

L52-77:   ChannelServer.__init__      → 删除（channel-server ConversationManager 替代）
L84-125:  start/stop                  → 删除
L131-214: Feishu 凭证/用户解析/reaction → 迁移到 feishu_bridge.py
L216-270: reaction helper             → 迁移到 feishu_bridge.py
L272-337: 文件下载                     → 迁移到 feishu_bridge.py
L339-404: admin 命令处理               → 迁移到 channel-server commands (通用化)
                                         /inject → /dispatch
                                         /status → 已有
                                         /explain → 保留在 App 层
L443-748: _run_feishu (Feishu WSS)    → 迁移到 feishu_bridge.py 核心
L750-898: 路由逻辑 route_message       → 删除（channel-server 替代）
L900-953: client 消息处理              → 删除（channel-server Bridge API 替代）
```

### 新增：channel-server 插件

AutoService 的业务逻辑通过 channel-server 插件钩子注入：

```
~/.zchat/projects/{name}/plugins/
├── autoservice_lifecycle.py    # 客户生命周期管理
├── autoservice_metrics.py      # 计费 + SLA 监控
└── autoservice_squad.py        # 分队卡片推送
```

| 插件文件 | 行数估算 | 功能 | 对应现有代码 |
|---------|---------|------|------------|
| `autoservice_lifecycle.py` | ~80 | on_conversation_created → customer_manager.get_or_create; on_conversation_resolved → 更新客户记录 | `autoservice/customer_manager.py` (调用，不改) |
| `autoservice_metrics.py` | ~60 | on_mode_changed(→takeover) → 记录计费; on_event → SLA 监控 | 全新 |
| `autoservice_squad.py` | ~50 | on_conversation_created → 发卡片到 #squad; 每 3 条消息更新摘要 | 全新 |

### 修改：现有文件

| 文件 | 改动 | 行数 |
|------|------|------|
| `web/app.py` | WebSocket 路由从 `web/websocket.py` 改为指向 Web Bridge; 删除 `ws_handlers` 引用 | ~20 行修改 |
| `Makefile` | `run-server` 改为启动 channel-server（zchat 命令或直接 `zchat-channel`）; `run-channel` 改为启动 feishu_bridge | ~5 行修改 |
| `feishu/channel-instructions.md` | 更新 tools 列表（新增 edit_message/send_side_message 等）; 更新 mode 说明（删除 routed_to，改用 conversation mode 概念） | ~30 行修改 |

### 保留不动

| 文件/目录 | 行数 | 说明 |
|----------|------|------|
| `autoservice/plugin_loader.py` | 268 | 插件发现不变（channel-server 的 plugin_manager 独立于此） |
| `autoservice/customer_manager.py` | 293 | 被 autoservice_lifecycle 插件调用 |
| `autoservice/session.py` | 298 | 会话管理不变 |
| `autoservice/crm.py` | 273 | CRM 不变 |
| `autoservice/rules.py` | 78 | 规则管理不变 |
| `autoservice/config.py` | 175 | 配置不变 |
| `autoservice/database.py` | 295 | 数据库不变 |
| `autoservice/mock_db.py` | 507 | Mock 数据库不变 |
| `autoservice/permission.py` | 300 | 权限不变 |
| `plugins/` | — | 业务插件不变（MCP tools 仍然通过 channel-server register_tools 注入） |
| `skills/` | — | Claude Code skills 不变 |
| `web/app.py` | 322 | 微调 WS 路由 |
| `web/auth.py` | 285 | 认证不变 |

### Agent Soul.md 模板

每个 agent 的行为通过 soul.md 定义（App 层，不是协议层）：

**fast-agent soul.md 要点**：
```markdown
# 快速响应 Agent

你是客服团队的快速响应 Agent。

## 消息处理
- 收到客户 public 消息 → 直接回复
- 简单问题 → 立即回答（用 reply tool）
- 复杂问题 → 先发占位（reply），然后查询知识库，最后 edit_message 替换

## 占位策略
- 判断需要查询时，先发 "稍等，正在为您查询..." (visibility=public)
- 记住 message_id
- 查询完成后调用 edit_message(message_id, 完整回答)

## 能力边界
- 查不到明确答案 → 不编造，发 send_side_message 到 squad: "@operator 请协助"
- 客户要求转人工 → 发 send_side_message: "@operator 客户要求人工服务，请接管"

## Mode 感知
- 收到 system 消息 "模式切换: → takeover" → 切换为副驾驶模式
- 副驾驶模式: 只发 send_side_message（建议），不直接 reply
- 收到 system 消息 "模式切换: → auto" → 恢复正常模式
```

**关键区别**：soul.md 里的 mode 感知是**辅助性的**——即使 agent 不遵守，channel-server 的 Gate 也会物理拦截。soul.md 只是让 agent 的行为更合理（比如主动切换语气），而不是依赖它来保证安全。

---

## 执行优先级

### Day 1: channel-server 核心

```
1. protocol/ 全部 (~350 行) + 单元测试 (~200 行)
2. engine/conversation_manager.py + mode_manager.py + event_bus.py
3. server.py on_pubmsg 改造（Gate 集成）
```

### Day 2: Bridge + 集成

```
4. transport/irc_transport.py (从 server.py 提取)
5. bridge_api/ws_server.py
6. bridges/feishu_bridge.py (从 AutoService 迁移)
7. server.py 启动流程改造
```

### Day 3: AutoService 对接 + 端到端

```
8. AutoService 删除旧文件 + 修改 Makefile/app.py
9. channel-server plugins (lifecycle/metrics/squad)
10. agent soul.md 模板
11. 端到端测试: 飞书消息 → channel-server → agent → 回复 → 飞书
```

---

## 变更统计

| 层 | 新增 | 修改 | 删除 | 净变化 |
|----|------|------|------|--------|
| zchat CLI | ~100 行 | ~20 行 | 0 | +100 |
| channel-server | ~1660 行 | ~100 行 | 0 | +1660 |
| AutoService bridges | ~400 行 | 0 | 0 | +400 |
| AutoService plugins | ~190 行 | 0 | 0 | +190 |
| AutoService 删除 | 0 | ~55 行 | **1845 行** | -1845 |
| Agent 模板 | ~200 行 | 0 | 0 | +200 |
| 测试 | ~400 行 | 0 | 0 | +400 |
| **合计** | **~2950** | **~175** | **1845** | **+1105** |

净增 ~1100 行代码，但系统从"单体路由器"变为"分层协议 + 可插件扩展的架构"。

---

*End of Migration Plan v1.0*
