# Channel-Server v1.0 — 飞书 Bridge 详细设计

> 参考实现: cc-openclaw `feishu/message_parsers.py` + `sidecar/`
> 上位文档: `03-bridge-layer.md`

---

## 1. 定位

飞书 Bridge 是 channel-server 的**渠道适配器**，负责：
1. 连接飞书 WSS（接收消息事件）
2. 解析全部飞书消息类型为统一格式
3. 通过 Bridge API 转发给 channel-server
4. 接收 channel-server 回复，通过飞书 API 发送（含消息编辑、card）
5. 管理飞书群 ↔ conversation/role 的映射

**飞书 Bridge 不包含业务逻辑**——它只做协议转换。

---

## 2. 架构

```
飞书服务器 (WSS)
     │
     ▼
┌─ feishu_bridge (独立进程) ─────────────────────────────┐
│                                                         │
│  FeishuWSClient                                         │
│  ├── lark_oapi.ws.Client (WSS 长连接)                   │
│  ├── 消息事件 → message_parsers 解析                     │
│  └── 群事件 → group_manager 处理                         │
│                                                         │
│  MessageParsers (可插拔注册表)                            │
│  ├── text, post                                         │
│  ├── image, file, audio, media (下载到本地)              │
│  ├── interactive (card 解析)                             │
│  ├── merge_forward (递归解析)                            │
│  ├── sticker, location, todo, system, share_*           │
│  └── 未知类型 → 描述性 fallback                          │
│                                                         │
│  FeishuSender                                           │
│  ├── send_text(chat_id, text)                           │
│  ├── send_card(chat_id, card_json)                      │
│  ├── update_message(message_id, text)                   │
│  ├── add_reaction(message_id, emoji)                    │
│  ├── remove_reaction(message_id, reaction_id)           │
│  └── download_file(message_id, file_key) → local_path   │
│                                                         │
│  GroupManager                                           │
│  ├── 飞书群 chat_id → role 映射                          │
│  │   customer_chats: [oc_xxx, ...] → customer           │
│  │   squad_chat: oc_yyy → operator                      │
│  │   admin_chat: oc_zzz → admin                         │
│  ├── 新群（bot 被拉入）→ 自动识别角色                    │
│  └── 群成员变动 → 通知 channel-server                    │
│                                                         │
│  BridgeAPIClient (WebSocket → channel-server :9999)     │
│  ├── register(capabilities)                             │
│  ├── customer_connect / customer_message                │
│  ├── operator_join / operator_message / operator_command│
│  ├── admin_command                                      │
│  └── 接收 reply / edit / event / csat_request           │
│                                                         │
│  VisibilityRouter                                       │
│  ├── public → 发到 customer 群                           │
│  ├── side → 发到 squad 群                                │
│  ├── system → 发到 squad 群 + admin 群                   │
│  └── csat_request → 发 card 到 customer 群               │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 消息类型解析器（message_parsers.py）

复刻 cc-openclaw 的可插拔注册表模式：

```python
# 注册表
_parsers: dict[str, Callable] = {}

def register_parser(*msg_types: str):
    def decorator(fn):
        for mt in msg_types:
            _parsers[mt] = fn
        return fn
    return decorator

def parse_message(msg_type, content, message, bridge) -> tuple[str, str]:
    """返回 (text, file_path)"""
    parser = _parsers.get(msg_type)
    if parser:
        return parser(content, message, bridge)
    return f"[{msg_type} 消息]", ""
```

### 需支持的消息类型

| 优先级 | 类型 | 解析方式 | 来源 |
|--------|------|---------|------|
| P0 | text | `content.text` | cc-openclaw |
| P0 | post | title + paragraphs | cc-openclaw |
| P0 | image/file/audio/media | 下载到本地 → `[File: path]` | cc-openclaw |
| P0 | interactive (card) | 提取 header + elements 文本 | cc-openclaw |
| P0 | merge_forward | 递归获取子消息 | cc-openclaw |
| P1 | sticker | `[表情包]` | cc-openclaw |
| P1 | share_chat / share_user | `[群名片/用户名片: id]` | cc-openclaw |
| P1 | location | `[位置: name (lat, lng)]` | cc-openclaw |
| P1 | todo | `[任务: summary]` | cc-openclaw |
| P2 | system | `[系统: 成员加入/退出/...]` | cc-openclaw |
| P2 | hongbao / vote / video_chat / calendar / folder | 描述性标签 | cc-openclaw |

---

## 4. 飞书发送能力 + 所需权限

### API 调用权限（飞书开放平台 → 权限管理）

| 操作 | API | 所需权限（任一） | 用途 |
|------|-----|----------------|------|
| 发文本/卡片 | `POST /im/v1/messages` | `im:message` 或 `im:message:send_as_bot` | agent 回复、CSAT 卡片、分队通知 |
| 编辑消息 | `PATCH /im/v1/messages/{id}` | `im:message` 或 `im:message:update` | 占位→续写替换 |
| 添加 reaction | `POST /im/v1/messages/{id}/reactions` | `im:message` 或 `im:message.reactions:write_only` | ACK 确认（OnIt） |
| 移除 reaction | `DELETE /im/v1/messages/{id}/reactions/{rid}` | `im:message` 或 `im:message.reactions:write_only` | 回复后移除 ACK |
| 下载文件 | `GET /im/v1/messages/{id}/resources/{key}` | `im:message.media` ⚠️ | 接收客户图片/文件/音频 |
| 读群消息 | `GET /im/v1/messages` | `im:message.group_msg:readonly` | E2E 测试验证 |
| 查群信息 | `GET /im/v1/chats/{id}` | `im:chat:readonly` | 群角色识别 |
| 查群成员 | `GET /im/v1/chats/{id}/members` | `im:chat.members:readonly` ⚠️ | reconciler 同步 |
| 查用户信息 | `GET /contact/v3/users/{id}` | `contact:user.base:readonly` | 显示发送者姓名 |

> ⚠️ 标注权限名称从 SDK 代码推断，未能从文档页面直接验证（页面 JS 渲染）。开通时如找不到，搜索关键词：`media`、`members`。

### 事件订阅权限（飞书开放平台 → 事件与回调）

| 事件名称 | 所需订阅权限（接收消息） | 触发场景 | 涉及角色 |
|---------|----------------------|---------|---------|
| `im.message.receive_v1` | `im:message.group_msg:readonly` | 收到任意群消息 | customer / operator / admin |
| `im.chat.member.bot.added_v1` | `im:chat` | bot 被拉入新群 | customer（动态注册） |
| `im.chat.member.user.added_v1` | `im:chat` | 用户加入群 | operator（加入 squad 群）/ admin（加入管理群）|
| `im.chat.member.user.deleted_v1` | `im:chat` | 用户退出群 | operator（撤销）/ admin（撤销）|
| `im.chat.disbanded_v1` | `im:chat` | 群解散 | 归档 conversation |

### 最小权限开通清单

```
API 权限（权限管理 tab）：
  ✅ im:message                    获取与发送单聊、群组消息
  ✅ im:message:update             更新消息
  ✅ im:message.reactions:write_only  发送、删除消息表情回复
  ✅ im:message.group_msg:readonly  获取群聊中所有用户聊天消息
  ✅ im:message.media              下载消息附件（图片/文件/音频）⚠️
  ✅ im:chat:readonly              获取群组信息
  ✅ im:chat.members:readonly      获取群成员列表 ⚠️
  ✅ contact:user.base:readonly    获取用户基本信息

事件订阅（事件与回调 tab）：
  ✅ im.message.receive_v1
  ✅ im.chat.member.bot.added_v1
  ✅ im.chat.member.user.added_v1
  ✅ im.chat.member.user.deleted_v1
  ✅ im.chat.disbanded_v1
```

### Card 消息模板

**CSAT 评分卡片**:
```json
{
  "type": "template",
  "data": {
    "template_id": "csat_rating",
    "template_variable": {
      "conversation_id": "feishu_oc_xxx"
    }
  }
}
```

或直接用 elements:
```json
{
  "header": {"title": {"content": "请为本次服务评分", "tag": "plain_text"}},
  "elements": [
    {"tag": "action", "actions": [
      {"tag": "button", "text": {"content": "⭐", "tag": "plain_text"}, "value": {"score": "1"}},
      {"tag": "button", "text": {"content": "⭐⭐", "tag": "plain_text"}, "value": {"score": "2"}},
      {"tag": "button", "text": {"content": "⭐⭐⭐", "tag": "plain_text"}, "value": {"score": "3"}},
      {"tag": "button", "text": {"content": "⭐⭐⭐⭐", "tag": "plain_text"}, "value": {"score": "4"}},
      {"tag": "button", "text": {"content": "⭐⭐⭐⭐⭐", "tag": "plain_text"}, "value": {"score": "5"}}
    ]}
  ]
}
```

**分队卡片通知**:
```json
{
  "header": {"title": {"content": "[进行中] 客户 David", "tag": "plain_text"}},
  "elements": [
    {"tag": "div", "text": {"content": "询问 B 套餐 · mode: auto", "tag": "plain_text"}},
    {"tag": "action", "actions": [
      {"tag": "button", "text": {"content": "进入对话", "tag": "plain_text"}, "value": {"action": "join", "conv_id": "feishu_oc_xxx"}}
    ]}
  ]
}
```

---

## 5. 授权模型 + 群 ↔ 角色映射（GroupManager）

### 授权模型

**飞书平台保证授权**：channel-server 不需要自己做用户鉴权。

- 飞书 WSS 只向 bot 投递**其所在群**的消息事件
- 消息发送者必须是该群的成员（飞书平台强制）
- 因此：**用户在某个群里 = 拥有该群对应角色的使用权限**

三种角色的授权来源：

| 角色 | 授权方式 | 配置方式 |
|------|---------|---------|
| **customer** | Bot 被拉入任意群 → 自动识别 | 动态：bot 收到 `im.chat.member.bot.added_v1` 时注册 |
| **operator (squad)** | 用户是指定分队群的成员 | 静态配置：`squad_chats` 列表 |
| **admin** | 用户是指定管理群的成员 | 静态配置：`admin_chat_id` |

**成员变动实时生效**：

| 飞书事件 | 角色变更 |
|---------|---------|
| `im.chat.member.user.added_v1` → squad 群 | 该用户获得 operator 权限 |
| `im.chat.member.user.deleted_v1` → squad 群 | 该用户失去 operator 权限 |
| `im.chat.member.user.added_v1` → admin 群 | 该用户获得 admin 权限 |
| `im.chat.member.user.deleted_v1` → admin 群 | 该用户失去 admin 权限 |
| `im.chat.member.bot.added_v1` → 未配置群 | 自动注册为 customer 群 |
| `im.chat.member.bot.added_v1` → 已配置群 | 跳过（已是 squad/admin） |
| `im.chat.disbanded_v1` | 清理 conversation 映射，归档 |

**customer 群持久化**：动态发现的 customer 群写入 `.feishu-bridge/customer_chats.json`，重启时加载（防止 bot 重启后遗忘已服务的客户群）。

---

### 配置

```yaml
# feishu-bridge-config.yaml
feishu:
  app_id: ${FEISHU_APP_ID}
  app_secret: ${FEISHU_APP_SECRET}

groups:
  admin_chat_id: "oc_admin_xxx"        # 管理群 → admin 角色
  squad_chats:                          # 分队群 → operator 角色
    - chat_id: "oc_squad_xiaoli"
      operator_id: "xiaoli"
    - chat_id: "oc_squad_xiaowang"
      operator_id: "xiaowang"
  # customer 群：动态，bot 被拉入时自动注册，持久化到 customer_chats.json

channel_server:
  url: "ws://localhost:9999"

storage:
  upload_dir: ".feishu-bridge/uploads"
  customer_chats_path: ".feishu-bridge/customer_chats.json"
```

### 群角色自动识别

```python
class GroupManager:
    def identify_role(self, chat_id: str) -> str:
        """根据 chat_id 判断角色"""
        if chat_id == self.admin_chat_id:
            return "admin"
        for squad in self.squad_chats:
            if chat_id == squad["chat_id"]:
                return "operator"
        if chat_id in self._dynamic_customer_chats:
            return "customer"
        return "unknown"  # 未注册的群，忽略其消息

    def register_customer_chat(self, chat_id: str) -> None:
        """bot 被拉入新群时调用，持久化"""
        self._dynamic_customer_chats.add(chat_id)
        self._save_customer_chats()

    def get_operator_id(self, chat_id: str) -> str | None:
        for squad in self.squad_chats:
            if chat_id == squad["chat_id"]:
                return squad["operator_id"]
        return None
```

### 群事件处理（EventDispatcher 注册）

```python
lark.EventDispatcherHandler.builder("", "")
    .register_p2_im_message_receive_v1(_on_message)           # 所有群消息
    .register_p2_im_chat_member_bot_added_v1(_on_bot_added)   # bot 被拉入
    .register_p2_im_chat_member_user_added_v1(_on_user_added) # 成员加入
    .register_p2_im_chat_member_user_deleted_v1(_on_user_del) # 成员退出
    .register_p2_im_chat_disbanded_v1(_on_disbanded)          # 群解散
    .build()
```

---

## 6. Visibility 路由

Bridge 从 channel-server 收到带 `visibility` 的消息后：

```python
class VisibilityRouter:
    def route(self, conversation_id: str, message: dict):
        visibility = message.get("visibility", "public")
        text = message.get("text", "")
        
        customer_chat = self.group_manager.get_customer_chat(conversation_id)
        squad_chat = self.group_manager.get_squad_chat(conversation_id)
        
        if visibility == "public":
            # 客户群 + 分队群都收到
            self.sender.send_text(customer_chat, text)
            if squad_chat:
                self.sender.send_text(squad_chat, f"[→客户] {text}")
        
        elif visibility == "side":
            # 只发到分队群
            if squad_chat:
                self.sender.send_text(squad_chat, f"[侧栏] {text}")
        
        elif visibility == "system":
            # 分队群 + 管理群
            if squad_chat:
                self.sender.send_text(squad_chat, f"[系统] {text}")
            self.sender.send_text(self.admin_chat_id, f"[系统] {text}")
        
        if message.get("type") == "csat_request":
            self.sender.send_card(customer_chat, self.csat_card(conversation_id))
```

---

## 7. E2E 测试辅助工具（feishu_test_client.py）

```python
class FeishuTestClient:
    """飞书 API 封装，用于 E2E 自动化测试"""
    
    def __init__(self, app_id: str, app_secret: str):
        self.client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
    
    def send_message(self, chat_id: str, text: str) -> str:
        """发文本消息，返回 message_id"""
        ...
    
    def send_card(self, chat_id: str, card: dict) -> str:
        """发卡片消息"""
        ...
    
    def list_messages(self, chat_id: str, start_time: str, page_size: int = 50) -> list:
        """拉取群内指定时间后的消息"""
        ...
    
    def get_message(self, message_id: str) -> dict:
        """获取单条消息详情（含 update_time，用于验证消息编辑）"""
        ...
    
    def assert_message_appears(self, chat_id: str, contains: str, timeout: int = 30):
        """轮询直到群内出现包含指定文本的消息"""
        start = time.time()
        while time.time() - start < timeout:
            messages = self.list_messages(chat_id, start_time=...)
            for m in messages:
                if contains in m.get("content", ""):
                    return m
            time.sleep(2)
        raise AssertionError(f"Message containing '{contains}' not found in {chat_id} within {timeout}s")
    
    def assert_message_absent(self, chat_id: str, contains: str, wait: int = 10):
        """等待一段时间，确认群内没有包含指定文本的消息（Gate 验证）"""
        time.sleep(wait)
        messages = self.list_messages(chat_id, start_time=...)
        for m in messages:
            if contains in m.get("content", ""):
                raise AssertionError(f"Message containing '{contains}' should NOT appear in {chat_id}")
    
    def get_chat_members(self, chat_id: str) -> list:
        """获取群成员列表"""
        ...
```

---

## 8. 文件结构

```
feishu_bridge/                    # 可以放在 channel-server submodule 内或独立仓库
├── __init__.py
├── bridge.py                     # FeishuBridge 主类（WSS + Bridge API client）
├── message_parsers.py            # 可插拔消息解析器（从 cc-openclaw 移植）
├── sender.py                     # FeishuSender（发消息/card/编辑/reaction）
├── group_manager.py              # 群角色映射 + 事件处理
├── visibility_router.py          # visibility → 飞书群 路由
├── config.py                     # 配置加载（YAML + env var）
├── test_client.py                # E2E 测试辅助工具
└── tests/
    ├── test_message_parsers.py   # 解析器单元测试
    ├── test_group_manager.py     # 群映射测试
    ├── test_visibility_router.py # visibility 路由测试
    └── test_sender.py            # 发送 mock 测试
```

---

*End of Feishu Bridge Design v1.0*
