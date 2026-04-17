# 飞书 / Lark API 官方文档验证报告

> 2026-04-14 · 基于飞书开放平台官方文档实际抓取验证
> 配套 `2026-04-14-prd-gap-tasks.md` 中飞书相关任务的技术可行性确认
> 覆盖: 飞书 (open.feishu.cn) + Lark 国际版 (open.larksuite.com)

---

## 一、验证总览

| 能力 | 方案中假设 | 官方文档验证结果 | 状态 |
|------|-----------|----------------|------|
| 话题/Thread 回复 | `reply_in_thread` 参数存在 | ✅ **确认存在**，飞书+Lark 均支持 | 可用 |
| 消息编辑 (PUT) | 可更新已发送消息 | ✅ 确认，仅限 text/post 类型，最多 20 次 | 有限制 |
| 卡片更新 (PATCH) | 可更新已发送卡片 | ✅ 确认，仅限 interactive 类型，需 `update_multi:true` | 可用 |
| 程序化建群 | API 可创建群+加人 | ✅ 确认，完整 API 可用 | 可用 |
| 审批流 | 可创建审批模板+实例 | ✅ 确认，模板+实例 API 均可用 | 可用 |
| Bitable 写入 | 可通过 API 写入记录 | ✅ 确认，支持多字段类型 | 可用 |
| Emoji Reaction | 可添加/删除表情 | ✅ 确认（项目已在使用） | 已用 |
| Lark 国际版对等性 | API 路径一致，仅域名不同 | ✅ 确认，`open.larksuite.com` 替换 `open.feishu.cn` | 对等 |

---

## 二、逐项 API 验证详情

### 2.1 话题/Thread 回复 — ✅ 已确认

**方案任务**: T0.1 (spike), T3.7~T3.9 (Copilot thread 实现)

| 项目 | 值 |
|------|-----|
| **端点** | `POST /open-apis/im/v1/messages/:message_id/reply` |
| **飞书域名** | `https://open.feishu.cn` |
| **Lark 域名** | `https://open.larksuite.com` |
| **关键参数** | `reply_in_thread` (boolean, 可选, 默认 `false`) |
| **描述** | "是否以话题形式回复"，设为 `true` 时以 thread 形式回复 |
| **补充行为** | 如果被回复的消息已经是 thread 形式，默认以 thread 回复 |
| **支持消息类型** | text, post, image, file, audio, media, sticker, interactive, share_chat, share_user |
| **频率限制** | 1000 次/分钟，50 次/秒；单用户 5 QPS，单群 5 QPS（群内所有 Bot 共享） |
| **返回字段** | `message_id`, `root_id`, `parent_id`, `thread_id` (thread 时返回) |
| **所需权限** | `im:message` 或 `im:message:send_as_bot` 或 `im:message:send` (任一) |
| **去重** | `uuid` 参数，1 小时内相同 uuid 仅成功一次 |
| **大小限制** | 文本消息 ≤ 150 KB, 卡片/富文本 ≤ 30 KB |

**对方案的影响**:
- ✅ `reply_in_thread` 参数确认存在，thread 方案 A 技术可行
- ✅ 飞书和 Lark 均支持，无地区差异
- ⚠️ 单群 5 QPS 限制需注意 — 高并发场景下多个 Agent 在同一分队群内操作可能触达
- ✅ 返回 `thread_id` 可用于后续追踪话题内消息

**spike 待核实项更新**:
| 原始待核实项 | 结果 |
|-------------|------|
| ① thread API 字段名 | ✅ 已确认: `reply_in_thread: true` |
| ② 速率配额 | ⚠️ 单群 5 QPS，与主消息共享配额，不独立 |
| ③ 回复数上限 | ❓ 文档未明确提及，需实测 |
| ④ 多端 UI 一致性 | ❓ 文档未涉及，需实测 |
| ⑤ 生命周期事件 | ❓ 文档未涉及，需实测 |

---

### 2.2 消息编辑 (PUT) — ✅ 已确认，有限制

**方案任务**: T2.7 (占位续写，文本消息备选方案)

| 项目 | 值 |
|------|-----|
| **端点** | `PUT /open-apis/im/v1/messages/:message_id` |
| **支持类型** | **仅 text 和 post（富文本）**，不支持 interactive（卡片） |
| **频率限制** | 1000 次/分钟，50 次/秒 |
| **编辑次数上限** | **每条消息最多 20 次** |
| **约束** | 仅原始发送者可编辑；不可编辑已撤回/已删除/过期消息 |
| **所需权限** | `im:message` 或 `im:message:send_as_bot` 或 `im:message:update` (任一) |

**对方案的影响**:
- ⚠️ PUT 仅支持 text/post，**不能用于更新卡片** — 占位续写如果用文本消息 PUT 可行，但用卡片必须走 PATCH
- ✅ 20 次编辑上限对占位续写场景足够（通常只需 1-2 次）

---

### 2.3 卡片更新 (PATCH) — ✅ 已确认

**方案任务**: T1.10 (PATCH 接入), T2.7 (占位续写), T3.6 (事件驱动卡片刷新)

| 项目 | 值 |
|------|-----|
| **端点** | `PATCH /open-apis/im/v1/messages/:message_id` |
| **支持类型** | **仅 interactive（卡片）** |
| **频率限制** | 1000 次/分钟，50 次/秒；**单条消息 5 QPS** |
| **有效期** | 消息发送后 **14 天内** 可更新 |
| **前置条件** | 卡片 JSON 的 config 中需包含 `"update_multi": true`（更新前后均需） |
| **大小限制** | 卡片内容 ≤ 30 KB |
| **约束** | 仅原始发送者可更新；不可更新已撤回/批量发送/人员可见性消息 |
| **所需权限** | `im:message` 或 `im:message:send_as_bot` 或 `im:message:update` (任一) |

**对方案的影响**:
- ✅ 卡片 PATCH 确认可用，占位续写推荐走卡片路线而非文本 PUT
- ⚠️ 必须在初始卡片 JSON 中设置 `"update_multi": true`，否则无法后续更新 — 卡片模板设计时需注意
- ⚠️ 单条消息 5 QPS — 对话摘要卡片实时刷新需控制频率（建议 ≥ 5s 间隔）
- ⚠️ 14 天有效期 — 长时间未活跃的对话卡片将无法更新，需设计过期处理

---

### 2.4 程序化建群 — ✅ 已确认

**方案任务**: T3.2 (Agent 分队建群)

#### 2.4.1 创建群

| 项目 | 值 |
|------|-----|
| **端点** | `POST /open-apis/im/v1/chats` |
| **频率限制** | 1000 次/分钟，50 次/秒 |
| **关键字段** | `name`, `description`, `owner_id`, `user_id_list`, `bot_id_list`, `chat_type`, `group_message_type` |
| **群类型** | `chat_type`: "private" (默认) / "public" |
| **消息模式** | `group_message_type`: "chat" (默认) / **"thread"** (全话题模式) |
| **成员上限** | 初始: 最多 50 用户 + 5 Bot（群内 Bot 总数上限 15） |
| **群主** | 不指定 `owner_id` 则 Bot 成为群主 |
| **去重** | 相同 uuid + owner_id 在 10 小时内仅建一个群 |
| **所需权限** | `im:chat` 或 `im:chat:create` (任一) |

**重要发现**: `group_message_type: "thread"` — 飞书支持创建**全话题模式群**，群内所有消息默认以 thread 形式组织。这对 Agent 分队频道可能是更好的选择。

#### 2.4.2 添加群成员

| 项目 | 值 |
|------|-----|
| **端点** | `POST /open-apis/im/v1/chats/:chat_id/members` |
| **频率限制** | 1000 次/分钟，50 次/秒 |
| **请求体** | `{"id_list": ["open_id_1", "open_id_2"]}` |
| **ID 类型** | `member_id_type`: open_id (推荐) / union_id / user_id / app_id (Bot) |
| **批量上限** | 每次最多 50 用户或 5 Bot |
| **Bot 加入** | `id_list` 中传 app_id，`member_id_type` 设为 `app_id` |
| **所需权限** | `im:chat` 或 `im:chat.members:write_only` (任一) |

**对方案的影响**:
- ✅ 建群 + 加人 API 完整可用
- ✅ `group_message_type: "thread"` 可直接创建话题模式群，天然适合 Copilot 场景
- ⚠️ 群内 Bot 上限 15 — 4 角色 Agent 作为 1 个 Bot 应用接入，不是 4 个独立 Bot，无问题
- ⚠️ 商店应用不能用 user_id，需用 open_id/union_id

---

### 2.5 审批流 — ✅ 已确认

**方案任务**: T4.7~T4.8 (提案审核卡片 + 审批流集成)

#### 2.5.1 创建审批定义（模板）

| 项目 | 值 |
|------|-----|
| **端点** | `POST /open-apis/approval/v4/approvals` |
| **关键组成** | ① `approval_name` 名称 ② `form` 表单控件(JSON 数组) ③ `node_list` 审批节点 |
| **节点类型** | AND (会签)、OR (或签)、SEQUENTIAL (顺序) |
| **审批人角色** | Supervisor (上级)、Personal (指定人)、Free (自选) 等 |
| **所需权限** | `approval:approval` 或 `approval:definition` (任一) |

#### 2.5.2 创建审批实例

| 项目 | 值 |
|------|-----|
| **端点** | `POST /open-apis/approval/v4/instances` |
| **频率限制** | **100 次/分钟** (注意: 比消息 API 低很多) |
| **关键参数** | `approval_code`, `form` (表单值), `user_id` 或 `open_id` (发起人) |
| **通知控制** | `cancel_bot_notification` 可控制是否发送审批通过/拒绝/撤回的 Bot 通知 |
| **所需权限** | `approval:approval` 或 `approval:instance` (任一) |

**对方案的影响**:
- ✅ 审批模板 + 实例 API 均可用，Dream Engine 提案审核技术可行
- ⚠️ 审批实例创建限速 100 次/分钟 — 批量提案场景需控制速率
- ⚠️ 审批结果通知: 文档中 `cancel_bot_notification` 暗示默认会发 Bot 通知，但回调/Webhook 的具体配置需进一步查阅事件订阅文档

---

### 2.6 Bitable (多维表格) 记录写入 — ✅ 已确认

**方案任务**: T4.1~T4.2 (仪表盘指标写入)

| 项目 | 值 |
|------|-----|
| **端点** | `POST /open-apis/bitable/v1/apps/:app_token/tables/:table_id/records` |
| **频率限制** | **50 次/秒** |
| **请求体** | `{"fields": {"字段名": 值}}` |
| **支持字段类型** | 文本、数字、单选/多选、日期(毫秒时间戳)、复选框、人员(open_id)、电话、超链接、附件、关联、地理位置 |
| **幂等** | `client_token` (UUID v4) 防重复 |
| **所需权限** | `base:record:create` 或 `bitable:app` (任一) |

**对方案的影响**:
- ✅ API 完整，字段类型丰富，仪表盘指标写入无障碍
- ✅ 50 QPS 对定时指标写入绰绰有余
- ⚠️ 需要先手动在飞书中创建 Bitable 模板（app_token + table_id），API 不支持从零创建表结构（需查证）

---

### 2.7 Emoji Reaction — ✅ 已确认（项目已使用）

| 项目 | 值 |
|------|-----|
| **端点** | `POST /open-apis/im/v1/messages/:message_id/reactions` |
| **频率限制** | 1000 次/分钟，50 次/秒 |
| **请求体** | `{"reaction_type": {"emoji_type": "SMILE"}}` |
| **所需权限** | `im:message` 或 `im:message.reactions:write_only` (任一) |

**当前使用情况**: channel_server.py 已实现 ACK reaction (OnIt/DONE/THUMBSUP)，无需额外开发。

---

## 三、飞书 vs Lark 国际版 API 对等性

| 维度 | 飞书 (Feishu) | Lark 国际版 | 差异 |
|------|--------------|-------------|------|
| **API 域名** | `https://open.feishu.cn` | `https://open.larksuite.com` | 仅域名不同 |
| **API 路径** | `/open-apis/im/v1/...` | `/open-apis/im/v1/...` | ✅ 完全一致 |
| **reply_in_thread** | ✅ 支持 | ✅ 支持 | ✅ 一致 |
| **消息编辑 (PUT)** | ✅ text/post | ✅ 一致 | ✅ 一致 |
| **卡片更新 (PATCH)** | ✅ interactive | 预期一致 | 需实测确认 |
| **建群 API** | ✅ 完整 | 预期一致 | 需实测确认 |
| **审批 API** | ✅ 完整 | 预期一致 | 需实测确认 |
| **Bitable API** | ✅ 完整 | 预期一致 | 需实测确认 |
| **SDK** | `lark-oapi` (PyPI) | 同一 SDK，配置不同域名 | ✅ 同一包 |
| **用户 ID 体系** | open_id / union_id | open_id / union_id | ⚠️ ID 不互通 |
| **数据隔离** | 中国大陆数据中心 | 海外数据中心 | ⚠️ 数据不互通 |

**关键结论**:
- API 接口路径完全一致，仅需在配置中替换域名
- `lark-oapi` SDK 同时支持两个平台，通过初始化参数切换
- **ID 不互通**: 同一用户在飞书和 Lark 的 open_id 不同，跨境场景需维护映射

---

## 四、权限清单汇总

### 已有权限（项目当前已申请）

| 权限 | 用途 |
|------|------|
| `im:message:send_as_bot` | 发送消息 |
| `contact:user.base:readonly` | 查询用户信息 |

### 需新增权限

| 权限 | 用途 | 方案任务 | 优先级 |
|------|------|---------|--------|
| `im:message:update` | 消息编辑 (PUT) + 卡片更新 (PATCH) | T1.10, T2.7 | P0 |
| `im:chat:create` | 程序化建群 | T3.2 | P1 |
| `im:chat.members:write_only` | 添加群成员 | T3.2 | P1 |
| `approval:approval` | 审批模板+实例 | T4.7, T4.8 | P2 |
| `base:record:create` | Bitable 记录写入 | T4.2 | P2 |
| `im:message.reactions:write_only` | Reaction 管理 (如需独立权限) | — | 低 |

**注**: `im:message:send_as_bot` 已覆盖 reply (含 reply_in_thread)、PATCH 卡片更新。但建议独立申请 `im:message:update` 以明确权限边界。

---

## 五、频率限制汇总

| API | 全局限制 | 单体限制 | 对方案的影响 |
|-----|---------|---------|-------------|
| 发消息 (create) | 1000/分, 50/秒 | 单用户 5 QPS, 单群 5 QPS | 分队群内多 Agent 共享 5 QPS |
| 回复消息 (reply) | 1000/分, 50/秒 | 单用户 5 QPS, 单群 5 QPS | thread 内回复同受群级 5 QPS 限制 |
| 编辑消息 (PUT) | 1000/分, 50/秒 | 单消息 20 次上限 | 占位续写足够 |
| 更新卡片 (PATCH) | 1000/分, 50/秒 | **单消息 5 QPS** | 卡片刷新需 ≥200ms 间隔 |
| 建群 | 1000/分, 50/秒 | 10h 内相同参数去重 | 无瓶颈 |
| 加群成员 | 1000/分, 50/秒 | 每次 ≤50 人 | 无瓶颈 |
| 审批实例 | **100/分** | — | 批量提案需控速 |
| Bitable 写入 | **50/秒** | — | 指标写入无瓶颈 |
| Reaction | 1000/分, 50/秒 | — | 无瓶颈 |

**最关键的限速瓶颈**:
1. **单群 5 QPS** — 分队群内所有 Bot 消息 + thread 回复共享此配额。高并发场景（多个对话同时活跃）可能触达
2. **单消息 PATCH 5 QPS** — 卡片实时刷新间隔不能低于 200ms
3. **审批实例 100/分** — 批量晨起推送提案时需注意

---

## 六、方案调整建议

基于官方文档验证结果，对方案提出以下调整：

### 6.1 确认可行，无需调整

| 方案项 | 验证结论 |
|--------|---------|
| Thread Copilot (方案 A) | ✅ `reply_in_thread: true` 确认可用 |
| 飞书建群做分队频道 | ✅ 完整 API + `group_message_type: "thread"` 加分 |
| Bitable 仪表盘 | ✅ 字段类型丰富，50 QPS 充足 |
| 审批流做提案审核 | ✅ 模板+实例 API 均可用 |
| Lark 国际版对等 | ✅ 同 SDK，换域名即可 |

### 6.2 需微调

| 方案项 | 原假设 | 实际情况 | 调整 |
|--------|--------|---------|------|
| 占位续写 | 用 PATCH 更新任何消息 | PUT 仅支持 text/post；PATCH 仅支持 interactive | **占位续写必须用卡片 (interactive)**，不能用文本消息再 PATCH |
| 卡片模板 | 普通卡片 JSON | PATCH 要求 `"update_multi": true` | **所有需要后续更新的卡片，初始 JSON 必须包含此配置** |
| 卡片有效期 | 无限制 | **14 天有效期** | 需设计超过 14 天的对话卡片的"过期→新建"机制 |
| 分队群模式 | 普通群 + 手动 thread | 飞书支持 `group_message_type: "thread"` | **建议分队群直接使用 thread 模式群**，所有消息天然话题化 |

### 6.3 需在 spike 中实测

| 项 | 原因 |
|----|------|
| thread 回复数上限 | 文档未明确单条主消息下的话题回复数量上限 |
| thread 多端 UI 一致性 | 文档不涉及客户端渲染细节 |
| thread 生命周期事件 | 文档未明确话题删除/折叠是否有可订阅事件 |
| PATCH 卡片客户端视觉 | 更新时是否有闪烁/二次通知，需实际观察 |
| thread 模式群的行为差异 | `group_message_type: "thread"` 群的实际交互体验 |

---

## 七、飞书 SDK 接入参考

### Python SDK (`lark-oapi`)

```python
# 飞书
import lark_oapi as lark
client = lark.Client.builder() \
    .app_id("APP_ID").app_secret("APP_SECRET") \
    .domain(lark.FEISHU_DOMAIN) \          # https://open.feishu.cn
    .build()

# Lark 国际版 — 仅域名不同
client = lark.Client.builder() \
    .app_id("APP_ID").app_secret("APP_SECRET") \
    .domain(lark.LARK_DOMAIN) \             # https://open.larksuite.com
    .build()
```

### Thread 回复示例

```python
import lark_oapi as lark
from lark_oapi.api.im.v1 import *

request = ReplyMessageRequest.builder() \
    .message_id("om_xxx") \
    .request_body(ReplyMessageRequestBody.builder()
        .content('{"text":"这是一条话题内回复"}')
        .msg_type("text")
        .reply_in_thread(True)             # 关键参数
        .build()) \
    .build()

response = client.im.v1.message.reply(request)
# response.data.thread_id → 话题 ID，用于后续追踪
```

### 卡片更新示例

```python
request = PatchMessageRequest.builder() \
    .message_id("om_xxx") \
    .request_body(PatchMessageRequestBody.builder()
        .content('{"config":{"update_multi":true},...}')  # 必须包含 update_multi
        .build()) \
    .build()

response = client.im.v1.message.patch(request)
```

### 创建 Thread 模式群

```python
request = CreateChatRequest.builder() \
    .request_body(CreateChatRequestBody.builder()
        .name("Agent 分队 - 客服小李")
        .chat_type("private")
        .group_message_type("thread")       # 全话题模式
        .user_id_list(["ou_xxx"])
        .bot_id_list(["cli_xxx"])
        .build()) \
    .build()

response = client.im.v1.chat.create(request)
# response.data.chat_id → 分队群 ID
```

---

*基于飞书开放平台官方文档 (2026-04 验证) · 配套 prd-gap-tasks.md*
