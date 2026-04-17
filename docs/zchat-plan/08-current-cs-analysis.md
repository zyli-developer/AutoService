# 08 — 当前 Channel Server 职能分析与 zchat 迁移准备

> 分析 AutoService 现有 channel_server.py 的全部职责，对照 zchat 纯路由架构，
> 识别哪些留在 router、哪些需要下沉/重构。

---

## 1. 现状：14 类职责全景

当前 `channels/feishu/channel_server.py` 约 1100+ 行，承担以下职责：

### 1.1 纯路由（可直接映射到 zchat channel-server）

| # | 职责 | 位置 | 说明 |
|---|------|------|------|
| R1 | **消息路由与分发** | L1316-1396 | 6 级优先级：exact → prefix → pool sticky → pool auto-assign → wildcard → unrouted |
| R2 | **实例注册与生命周期** | L1245-1289 | WebSocket 注册/注销、chat_id 绑定、冲突检测 |
| R3 | **Web Bridge 多路复用** | websocket.py | 单 WS 连接复用所有浏览器会话，按 chat_id demux |
| R4 | **UX 事件透传** | — | thinking、kb_searching 等事件直接转发 |
| R5 | **Plugin 工具注册** | — | `discover()` + tool/route 注册到 MCP/HTTP |

### 1.2 业务逻辑（需从 router 剥离）

| # | 职责 | 位置 | 耦合度 | 说明 |
|---|------|------|--------|------|
| B1 | **Feishu API 集成** | L898-1115 | 重 | 凭证加载、消息解析(text/post/file/image/audio)、文件下载、emoji 反应、用户查询缓存 |
| B2 | **Admin 命令系统** | L664-807 | 重 | `/status` `/inject` `/discuss` `/explain` `/help` — 拦截 + 处理 |
| B3 | **运行时模式管理** | L1010-1043 | 中 | runtime_mode (production/improve/discuss/explain) + business_mode (customer_service/sales) |
| B4 | **CRM 集成** | 散落多处 | 中 | 首次消息 → `upsert_contact`、`increment_message_count`、`log_message` |
| B5 | **Discuss 空闲检测** | L1401-1436 | 中 | 15min 超时提醒，后台 60s 轮询 |
| B6 | **ACK 反应追踪** | L541-593 | 轻 | 收到消息加 OnIt emoji，回复后移除 |
| B7 | **消息去重** | — | 轻 | `_seen` set（上限 10k） |
| B8 | **Identity & 指令** | — | 轻 | 加载 identity.yaml → 格式化 instructions |
| B9 | **上线广播** | L1118-1174 | 轻 | 启动后发全员 "AutoService 已上线 ✅" |

### 1.3 Pool 模式（并行路由路径）

| # | 职责 | 位置 | 说明 |
|---|------|------|------|
| P1 | **CCPool 初始化** | L226-274 | 按配置创建 min/max 实例池 |
| P2 | **Sticky 会话绑定** | L1355-1373 | 新 chat → 分配 pool 实例 → 持久绑定 |
| P3 | **流式更新** | L276-341 | 拦截 `content_block_delta`，500ms 节流，Feishu 消息渐进式编辑 |
| P4 | **回调链** | L395-446 | reply_callback / react_callback 路由回源 channel |

### 1.4 Web 层（FastAPI + Auth + Session）

| # | 职责 | 位置 | 说明 |
|---|------|------|------|
| W1 | **Access Code 认证** | auth.py | Admin 生成限时 code → 兑换 token → 空闲超时驱逐 |
| W2 | **Session 持久化** | session_persistence.py | 按 code 分目录存 JSON，含元数据推断 (customer_type, resolution) |
| W3 | **FastAPI 路由** | app.py | 静态文件、auth API、session API、KB API、plugin route 挂载 |
| W4 | **浏览器会话管理** | websocket.py L143-326 | Token 校验、session 创建、双向消息泵、心跳、断线恢复 |

---

## 2. zchat 纯路由架构对比

zchat channel-server（见 `02-channel-server.md`）的职责边界：

```
                zchat channel-server 只做
                ┌────────────────────────────────────┐
                │  ConversationManager  (CRUD+状态机) │
                │  ModeManager          (模式切换)     │
                │  MessageGate          (visibility)   │
                │  MessageStore         (消息历史)      │
                │  TimerManager         (超时计时)      │
                │  EventBus             (发布/订阅)     │
                │  ParticipantRegistry  (角色映射)      │
                │  SquadRegistry        (分队管理)      │
                │  Plugin 工具注册                      │
                │  Bridge API (WebSocket)               │
                │  IRC Transport                        │
                └────────────────────────────────────┘
```

关键差异：**zchat 无 Feishu/Web 直连，所有外部渠道通过 Bridge 接入**。

---

## 3. 迁移映射：每个职责的去向

### 3.1 直接映射（保留在 zchat channel-server）

| 现有 | zchat 对应 | 备注 |
|------|-----------|------|
| R1 消息路由 | ConversationManager + MessageGate | 6 级路由 → conversation-based 路由 |
| R2 实例注册 | ParticipantRegistry | WebSocket instance → IRC nick / Bridge |
| R5 Plugin 注册 | PluginManager + App tools 加载 | 机制不变，`discover()` 注入 |
| B3 模式管理 | ModeManager | auto/copilot/takeover 替代 production/improve |
| B7 消息去重 | MessageStore (id-based) | 从内存 set → 持久化 |

### 3.2 下沉到 Bridge 层

| 现有 | 目标位置 | 说明 |
|------|---------|------|
| B1 Feishu API 集成 | `feishu-bridge` | 消息解析、文件下载、emoji、用户查询全部移到飞书 Bridge |
| B6 ACK 反应追踪 | `feishu-bridge` | Bridge 自行管理 OnIt → 回复后移除 |
| B9 上线广播 | `feishu-bridge` lifecycle hook | Bridge 启动时发广播 |
| P3 流式更新 | `feishu-bridge` | Bridge 接收 `edit` 事件 → 调飞书 API 编辑消息 |
| W1 Access Code 认证 | `web-bridge` | Web Bridge 自行管理 token |
| W4 浏览器会话 | `web-bridge` | 双向消息泵、心跳、断线恢复 |
| R3 Web 多路复用 | `web-bridge` | 单 WS → channel-server，多 WS ← browsers |

### 3.3 下沉到 App 层（autoservice 业务代码）

| 现有 | 目标位置 | 说明 |
|------|---------|------|
| B2 Admin 命令 | `autoservice/admin_handler.py` | 注册为 EventBus subscriber 或 Bridge admin 消息处理器 |
| B4 CRM 集成 | `autoservice/hooks/on_message.py` | EventBus hook: `message.received` → upsert_contact |
| B5 Discuss 空闲检测 | `autoservice/discuss_manager.py` | 独立后台任务，监听 EventBus |
| B8 Identity & 指令 | `autoservice/identity_loader.py` | App 启动时加载，注入到 agent instructions |
| W2 Session 持久化 | `autoservice/session_store.py` | EventBus hook: `conversation.closed` → 持久化 |
| W3 FastAPI 路由 | 保留，但只挂 App API | 去掉 channel 相关路由 |

### 3.4 Pool 模式的演进

| 现有 | zchat 对应 | 说明 |
|------|-----------|------|
| P1 CCPool 初始化 | SquadRegistry + agent 进程管理 | Pool → Squad，每个 agent 独立进程 |
| P2 Sticky 绑定 | ConversationManager.add_participant | conversation 级别绑定替代 chat_id sticky |
| P4 回调链 | EventBus + Bridge API | reply_callback → EventBus publish → Bridge 转发 |

---

## 4. 迁移接口设计

### 4.1 Router ↔ Handler 消息信封

```python
@dataclass
class MessageEnvelope:
    chat_id: str          # 路由键（conversation_id）
    message_id: str       # 去重键
    source: str           # "feishu" | "web" | "admin"
    sender: str           # participant_id
    content: str          # 原始内容（Bridge 已解析好的纯文本/结构化）
    content_type: str     # "text" | "file" | "image" | "audio" | "command"
    metadata: dict        # 业务字段透传（mode, user_info 等）
    timestamp: float
```

**关键原则**：Router 只看 `chat_id` + `source` + `sender`，不解析 `metadata`。

### 4.2 Bridge 注册协议（已定义于 02-channel-server.md §5）

```json
{
  "type": "register",
  "bridge_type": "feishu",
  "instance_id": "feishu-bridge-1",
  "capabilities": ["customer", "operator", "admin"]
}
```

### 4.3 回复路由

```json
{
  "type": "reply",
  "conversation_id": "feishu_oc_xxx",
  "text": "...",
  "visibility": "public",
  "message_id": "cs_msg_002"
}
```

Bridge 根据 `visibility` 决定转发给谁：
- `public` → 客户 + operator + admin
- `side` → operator + admin only
- `system` → operator + admin only

---

## 5. 迁移风险与注意事项

### 5.1 高风险

| 风险 | 说明 | 缓解 |
|------|------|------|
| **Pool 流式更新** | 当前 `content_block_delta` 拦截 → 500ms 节流 → Feishu `_edit_feishu_message()` 深度耦合 | 抽象为 `StreamAdapter` 接口，Bridge 实现渠道特定的渐进式更新 |
| **Admin /inject** | 从 admin chat 注入消息到任意 conversation，当前直接操作路由表 | zchat 需提供 `admin_inject` Bridge API 消息类型 |
| **模式语义差异** | 当前 runtime_mode (production/improve/discuss/explain) ≠ zchat mode (auto/copilot/takeover) | 需要映射层或重新定义，improve/discuss/explain 可能变成 conversation metadata 而非 mode |

### 5.2 中风险

| 风险 | 说明 | 缓解 |
|------|------|------|
| **CRM 调用时序** | 当前在消息路由过程中同步调用 CRM（upsert_contact），迁移后需异步化 | EventBus hook 天然异步 |
| **Feishu 用户缓存** | 当前 channel_server 内存缓存用户信息，迁移后 Bridge 需自行管理 | feishu-bridge 内建 LRU 缓存 |
| **Startup broadcast** | 当前在 channel_server 启动 4s 后执行，直接调 Feishu API | 移到 feishu-bridge 的 `on_connected` lifecycle hook |

### 5.3 低风险

| 风险 | 说明 |
|------|------|
| **消息去重** | 从内存 `_seen` set → MessageStore id-based 去重，逻辑简单 |
| **ACK 反应** | 纯飞书 UI 行为，完全下沉到 Bridge |
| **Identity 加载** | 文件读取，与路由无关，直接移到 App 层 |

---

## 6. 建议的迁移顺序

```
Phase 0: 准备                      Phase 1: Bridge 抽象
┌────────────────────────┐        ┌────────────────────────┐
│ • 定义 MessageEnvelope │        │ • 抽取 FeishuAdapter   │
│ • 定义 Bridge 协议     │   →    │   (B1, B6, B9, P3)     │
│ • 建 EventBus 雏形     │        │ • 抽取 WebBridge       │
└────────────────────────┘        │   (W1, W4, R3)         │
                                  └────────────────────────┘
                                           │
Phase 2: 业务下沉                          ▼
┌────────────────────────┐        Phase 3: Router 瘦身
│ • Admin → handler (B2) │        ┌────────────────────────┐
│ • CRM → hook (B4)      │   →    │ • 删除所有 B/W 代码    │
│ • Discuss → manager(B5)│        │ • Router 只保留 R1-R5  │
│ • Session → store (W2) │        │ • 对接 zchat 协议      │
└────────────────────────┘        └────────────────────────┘
```

---

## 7. 附录：现有文件与 zchat 模块对照

| 现有文件 | 主要职责 | zchat 对应 |
|---------|---------|-----------|
| `channels/feishu/channel_server.py` | 路由 + Feishu + Admin + Pool | 拆分为 channel-server + feishu-bridge |
| `channels/feishu/channel.py` | Claude Code MCP stdio client | agent 进程（独立） |
| `channels/feishu/channel_tools.py` | MCP tool 工厂 | channel-server MCP tools |
| `channels/web/app.py` | FastAPI + 路由 | App HTTP server（独立） |
| `channels/web/websocket.py` | Web Bridge 多路复用 | web-bridge |
| `channels/web/auth.py` | Access Code 认证 | web-bridge 内建 |
| `channels/web/session_persistence.py` | Session 存储 | App EventBus hook |
| `autoservice/cc_pool.py` | Claude Code 实例池 | SquadRegistry + agent 管理 |

---

*End of analysis — 2026-04-17*
