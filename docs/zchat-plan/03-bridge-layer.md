# Channel-Server v1.0 — Bridge 层设计

> Bridge 是渠道协议和 channel-server 之间的适配器

---

## 1. Bridge 架构

Bridge 是一个独立进程（或嵌入到 channel-server），负责：
1. 连接外部渠道（Feishu WSS、Web WebSocket、未来的 WhatsApp/PSTN）
2. 将渠道消息转为 channel-server Bridge API 消息
3. 将 channel-server 的回复/事件转回渠道消息
4. **只转发 visibility=public 的消息给客户**

```
┌─ Feishu Bridge (独立进程) ──────────────────────────────┐
│                                                          │
│  Feishu WSS ◄──── lark_oapi SDK ────► Feishu 服务器     │
│       │                                                  │
│       ▼                                                  │
│  feishu_bridge.py                                        │
│  ├── 消息格式转换 (Feishu JSON → Bridge API JSON)       │
│  ├── 用户识别 (open_id → customer participant)           │
│  ├── 消息发送 (reply → Feishu send API)                 │
│  ├── 消息编辑 (edit → Feishu update API)                │
│  ├── 文件处理 (image/file → 下载 + 转发)                │
│  └── reaction (emoji → Feishu reaction API)              │
│       │                                                  │
│       ▼                                                  │
│  WebSocket Client → channel-server :9999                │
└──────────────────────────────────────────────────────────┘

┌─ Web Bridge (嵌入 FastAPI) ─────────────────────────────┐
│                                                          │
│  Browser WebSocket ◄────────────► FastAPI /ws/chat      │
│       │                                                  │
│       ▼                                                  │
│  web_bridge.py                                           │
│  ├── 认证 (access code → session token)                 │
│  ├── 消息格式转换 (browser JSON → Bridge API JSON)      │
│  ├── 消息推送 (reply → WebSocket push)                  │
│  ├── 消息编辑 (edit → WebSocket push "update" type)     │
│  └── 会话管理 (session_id → conversation_id 映射)       │
│       │                                                  │
│       ▼                                                  │
│  WebSocket Client → channel-server :9999                │
└──────────────────────────────────────────────────────────┘
```

---

## 2. Feishu Bridge

### 来源

从 AutoService `feishu/channel_server.py` 迁移以下逻辑：
- Feishu WSS 长连接（`_run_feishu()`，第 443-748 行）
- 飞书 API 调用（发消息、reaction、文件下载、用户查找）
- 管理员消息处理（admin_chat_id 的 /help /status 等命令）

### 迁移后不再需要的部分

| AutoService 原有 | 迁移去向 | 说明 |
|-----------------|---------|------|
| `ChannelServer` 类的 WebSocket 服务 | channel-server Bridge API | 不再自建 WS server |
| `route_message()` 路由逻辑 | channel-server ConversationManager | 不再自己路由 |
| `exact_routes / prefix_routes` | channel-server ConversationManager | 不再自己维护路由表 |
| `Instance` 注册机制 | channel-server ParticipantRegistry | |

### Feishu Bridge 核心流程

```python
class FeishuBridge:
    def __init__(self, channel_server_url: str, credentials_path: str):
        self.cs_url = channel_server_url   # ws://localhost:9999
        self.cs_ws = None                  # channel-server WebSocket
        self.feishu_client = None          # lark_oapi.Client
        self.admin_chat_id = None
    
    async def start(self):
        # 1. 连接 channel-server
        self.cs_ws = await websockets.connect(self.cs_url)
        await self.cs_ws.send(json.dumps({
            "type": "register",
            "bridge_type": "feishu",
            "instance_id": "feishu-bridge-1",
            "capabilities": ["customer", "operator", "admin"]
        }))
        
        # 2. 连接 Feishu
        self.feishu_client = self._init_feishu_client()
        
        # 3. 并行运行
        async with anyio.create_task_group() as tg:
            tg.start_soon(self._feishu_message_loop)   # 飞书 → channel-server
            tg.start_soon(self._cs_reply_loop)          # channel-server → 飞书
    
    async def _feishu_message_loop(self):
        """监听飞书消息，转发到 channel-server。"""
        # 从 AutoService channel_server.py 迁移 Feishu WSS 消费逻辑
        async for feishu_event in self.feishu_ws:
            message = self._parse_feishu_event(feishu_event)
            if message is None:
                continue
            
            # 转为 Bridge API 格式
            conv_id = f"feishu_{message['chat_id']}"
            
            # 首次出现的 chat_id → customer_connect
            if not self._known_conversations.get(conv_id):
                await self.cs_ws.send(json.dumps({
                    "type": "customer_connect",
                    "conversation_id": conv_id,
                    "customer": {
                        "id": f"feishu_{message['open_id']}",
                        "name": self._resolve_user(message['open_id']),
                    },
                    "metadata": {"source": "feishu", "chat_id": message['chat_id']}
                }))
                self._known_conversations[conv_id] = True
            
            # 发送消息
            await self.cs_ws.send(json.dumps({
                "type": "customer_message",
                "conversation_id": conv_id,
                "text": message['text'],
                "message_id": message['message_id'],
                "metadata": {
                    "user_id": message['open_id'],
                    "message_type": message.get('message_type', 'text'),
                }
            }))
    
    async def _cs_reply_loop(self):
        """监听 channel-server 回复，转发到飞书。"""
        async for raw in self.cs_ws:
            msg = json.loads(raw)
            
            if msg['type'] == 'reply':
                chat_id = msg['conversation_id'].removeprefix('feishu_')
                await self._send_feishu_message(chat_id, msg['text'])
                
            elif msg['type'] == 'edit':
                await self._update_feishu_message(msg['message_id'], msg['new_text'])
                
            elif msg['type'] == 'event':
                # 某些事件可能需要通知管理员
                if msg['event_type'] == 'mode.changed' and self.admin_chat_id:
                    await self._notify_admin(msg)
```

### 飞书特有功能

| 功能 | 实现位置 | 说明 |
|------|---------|------|
| ACK reaction (OnIt) | feishu_bridge | 收到消息后立即加 reaction，回复后移除 |
| 文件下载 | feishu_bridge | 图片/文件/音频通过飞书 API 下载到本地 |
| 用户名解析 | feishu_bridge | open_id → 姓名（缓存 + 飞书 API） |
| 管理群命令 | feishu_bridge → channel-server | /status 等命令转发给 channel-server |
| 消息编辑 | feishu_bridge | channel-server edit → 飞书 update message API |

---

## 3. Web Bridge

### 来源

从 AutoService `web/websocket.py` 迁移 `WebChannelBridge` 逻辑。

### Web Bridge 核心流程

```python
class WebBridge:
    """嵌入 FastAPI 的 Web Bridge。"""
    
    def __init__(self, channel_server_url: str):
        self.cs_url = channel_server_url
        self.cs_ws = None
        self._reply_queues: dict[str, asyncio.Queue] = {}  # conv_id → queue
    
    async def ensure_connected(self):
        """连接 channel-server（懒初始化）。"""
        if self.cs_ws is not None:
            return
        self.cs_ws = await websockets.connect(self.cs_url)
        await self.cs_ws.send(json.dumps({
            "type": "register",
            "bridge_type": "web",
            "instance_id": "web-bridge-1"
        }))
        asyncio.create_task(self._receive_loop())
    
    async def handle_browser_session(self, browser_ws: WebSocket, session_id: str):
        """处理一个浏览器 WebSocket 会话。"""
        conv_id = f"web_{session_id}"
        
        # 通知 channel-server
        await self.cs_ws.send(json.dumps({
            "type": "customer_connect",
            "conversation_id": conv_id,
            "customer": {"id": f"web_{session_id}", "name": "Web User"},
            "metadata": {"source": "web"}
        }))
        
        reply_queue = asyncio.Queue()
        self._reply_queues[conv_id] = reply_queue
        
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(self._browser_to_cs, browser_ws, conv_id)
                tg.start_soon(self._cs_to_browser, browser_ws, conv_id, reply_queue)
        finally:
            self._reply_queues.pop(conv_id, None)
    
    async def _browser_to_cs(self, browser_ws, conv_id):
        async for raw in browser_ws.iter_text():
            msg = json.loads(raw)
            await self.cs_ws.send(json.dumps({
                "type": "customer_message",
                "conversation_id": conv_id,
                "text": msg.get("content", ""),
                "message_id": f"web_{uuid4().hex[:8]}"
            }))
    
    async def _cs_to_browser(self, browser_ws, conv_id, reply_queue):
        while True:
            msg = await reply_queue.get()
            if msg['type'] == 'reply':
                await browser_ws.send_json({
                    "type": "bot_text_delta",
                    "content": msg['text'],
                    "message_id": msg.get('message_id', '')
                })
                await browser_ws.send_json({"type": "done"})
            elif msg['type'] == 'edit':
                await browser_ws.send_json({
                    "type": "message_update",
                    "message_id": msg['message_id'],
                    "content": msg['new_text']
                })
    
    async def _receive_loop(self):
        """从 channel-server 接收消息，分发到对应的 reply_queue。"""
        async for raw in self.cs_ws:
            msg = json.loads(raw)
            conv_id = msg.get('conversation_id', '')
            if conv_id in self._reply_queues:
                await self._reply_queues[conv_id].put(msg)
```

---

## 4. Bridge 层的 Visibility 路由

### 核心原则：IRC 对租户不可见

所有人类用户（客户、客服、管理员）都通过 Bridge 接入。IRC 仅是 channel-server ↔ agent 之间的内部 transport。

### Visibility 路由规则

channel-server 向 Bridge 发送**所有 visibility 的消息**（public + side + system），但每条消息都带有 `visibility` 字段。**Bridge 根据 visibility 决定转发给哪个渠道端**：

```
Agent 发消息
  → channel-server Gate 判定 visibility
    → public: Bridge 转发给 客户端 + operator 端 + admin 端
    → side: Bridge 只转发给 operator 端 + admin 端（客户看不到）
    → system: Bridge 只转发给 operator 端 + admin 端（客户看不到）
```

### 飞书 Bridge 的渠道分流

一个飞书 Bridge 实例连接多个飞书群，每个群映射到不同角色：

| 飞书群 | 角色 | 收到的消息 |
|--------|------|-----------|
| 客户对话群 (oc_xxx) | customer | 只收 `visibility=public` |
| 小李的 Agent 分队群 | operator | 收 public + side + system |
| 管理群 | admin | 收 public + side + system + command_response |

**安全保证仍然成立**：客户端渠道（对话群/Web 聊天窗）永远只收到 public 消息。side 消息只会出现在 operator/admin 的渠道（分队群/管理群）中。

### Operator 通过 Bridge 发送命令

operator 不需要 WeeChat。所有命令通过飞书群发送：

```
小李在"Agent 分队群"中:
  看到卡片: "[进行中] David · 询问套餐"
  → 回复: "进入 feishu_oc_abc123"
  → Bridge 发送: {"type": "operator_join", "conversation_id": "feishu_oc_abc123", ...}
  → CS 自动切换 mode=copilot

  看到 agent 和客户的对话（public 消息自动转发到分队群）
  → 输入: "建议强调本月优惠"
  → Bridge 发送: {"type": "operator_message", ...}
  → CS Gate: copilot + operator → side（不到客户）
  → agent 收到 side 建议

  判断需要接管:
  → 输入: "/hijack"
  → Bridge 发送: {"type": "operator_command", "command": "/hijack"}
  → CS 执行模式切换

  问题解决:
  → 输入: "/resolve"
  → Bridge 发送: {"type": "operator_command", "command": "/resolve"}
  → CS 触发 CSAT 采集
```

**operator 全程在飞书操作，不接触 IRC/WeeChat。**

---

## 5. 消息编辑处理

### 协议层

```
Agent 调用 edit_message(message_id, new_text)
  → channel-server MessageStore 更新消息内容
  → channel-server 发 message.edited 事件
  → channel-server 通过 Bridge API 发 edit 消息给 Bridge
```

### Feishu Bridge

飞书支持消息更新 API：
```python
async def _update_feishu_message(self, message_id: str, new_text: str):
    """调用飞书 update message API 替换消息内容。"""
    import lark_oapi as lark
    req = (
        lark.BaseRequest.builder()
        .http_method(lark.HttpMethod.PATCH)
        .uri(f"/open-apis/im/v1/messages/{message_id}")
        .token_types({lark.AccessTokenType.TENANT})
        .body({"msg_type": "text", "content": json.dumps({"text": new_text})})
        .build()
    )
    self.feishu_client.request(req)
```

### Web Bridge

Web 通过 WebSocket push `message_update` 事件：
```json
{"type": "message_update", "message_id": "cs_msg_002", "content": "更新后的内容"}
```

前端 JS 收到后替换对应消息的 innerHTML。

### IRC 层

IRC 不支持消息编辑。对于 IRC 上的 operator/observer，edit 表现为一条新消息：
```
[编辑] cs_msg_002: 更新后的内容
```

这是可接受的，因为 operator 在 IRC 中主要关注消息流而非精确的消息版本。

---

## 6. 新增 Bridge vs 扩展

添加新渠道（如 WhatsApp）只需要：

1. 实现一个新的 `whatsapp_bridge.py`
2. 连接 channel-server Bridge API（相同的 WebSocket 协议）
3. 处理 WhatsApp 特有的消息格式转换
4. 不需要改 channel-server 的任何代码

这是协议和 Bridge 分离的核心价值。

---

*End of Bridge Layer Design v1.0*
