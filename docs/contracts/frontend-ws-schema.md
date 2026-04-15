---
version: 1.0
status: FROZEN
author: DevB
reviewer: DevA
created_at: 2026-04-15
frozen_at: 2026-04-15
supersedes: 0.2-draft
upstream: docs/contracts/conversation-engine.md v1.0
---

> **v1.0 变更**（DevA second-pass sign off · issue #21）：
> - §5 标题编号修正：原 "5.2 Schema 示例" → §5.3（v0.2 新增的 "5.2 event 帧 viewer_role 过滤" 占用了 5.2）
> - frontmatter bump：0.2-draft → 1.0 FROZEN
>
> **v0.2 变更**（吸收 DevA review · issue #21）：
> - §1 修正 admin actor 模型：admin 通过 `actor_id` + Engine §6.1 admin 列识别，**不**借 OPERATOR/SYSTEM 身份
> - §3.4 `4500` → `4499`（避免与 HTTP 5xx 视觉混淆）
> - §4 F6 `subscribe.scope` 加 `global: bool`（DevA #1）
> - §4 F13 `history_request` 明示 `since_sequence` / `before_sequence` 互斥（DevA #6）
> - §5 S5 加 `source_display: {id, role, name?}`，与 `Message.source` 字符串解耦（DevA #3）
> - §5 S8 `event` 帧明确走 `viewer_role` 过滤；`hook.failed` / `message.gated` / `sla.breach` 仅推 OPERATOR/ADMIN（DevA #4）
> - §5 S11 与 §6 加 `command_response{ok:false}` vs `error` 帧边界规则（DevA #2）
> - §5 S13 `since_sequence` 标 `int | string` 联合类型（DevA #5）
> - §3.2 / §6 明确 `ping`/`pong`/`ack`/`error` 自身不再 ack（DevA D6 附加）
> - §3.3 `4041_REPLAY_GAP` 明确 ring buffer 是 **per-subscription**（DevA D3 附加）
> - §7 映射表加 `admin_command` 的 `actor_id` 列（DevA #7）

# T0.2 · Frontend WebSocket Schema (v1.0 FROZEN)

> 前后端唯一外部接口面。所有 Web 前端（C 端聊天 / Operator 工作台 / Admin 控制台）通过本契约消费 ConversationEngine。
>
> Engine 契约是**内部 Protocol**（Python 进程内）；本契约是**网络协议**（JSON over WSS）。两者一一映射，不允许 Web 前端旁路本契约直连 Engine。

---

## 1. 端点与角色

3 个独立 WebSocket 端点，**角色在端点级别分流**（避免在帧内做权限分支，简化授权模型）：

| 端点 | 视角 (`viewer_role`) | 鉴权 | 默认订阅 |
|---|---|---|---|
| `/ws/customer` | `CUSTOMER` | 短期 session token（HTTP 上行换取） | 隐式订阅自己的 `conversation_id` |
| `/ws/operator` | `OPERATOR` | OAuth/SSO bearer | 显式 `subscribe` 加入 N 个 conv + squad fanout |
| `/ws/admin` | `ADMIN`（内部，非 Engine 枚举） | OAuth/SSO bearer + RBAC | 隐式订阅全局事件流 |

> ADMIN 不在 `ParticipantRole` 枚举中（T0.1 §2.1 仅 customer/agent/operator/observer）。Admin 通过 `/ws/admin` 接入后，调用 `handle_command` 时传入自己的 admin user_id 作为 `actor_id`，由 Engine §6.1 权限矩阵的 **admin 列**识别（实现侧维护 admin id allowlist 或委托外部 IAM）。Admin **不**直接 `join` conversation，因此 `participant.joined` 等需要 `Participant` 对象的事件中不出现 admin 角色。

`viewer_role` 由端点决定，注入到 `subscribe(viewer_role=...)` / `get_messages(viewer_role=...)`，后端 Engine 据此过滤 SIDE 消息（T0.1 Q9 + 不变量 #6）。

---

## 2. 帧信封 (envelope)

所有方向的所有帧统一格式：

```json
{
  "v": 1,                            // protocol_version, 与 client_hello 协商
  "type": "<message_type>",          // 见 §4 / §5
  "id": "<frame_id>",                // FE→BE: 客户端 UUID v4（用于 ack/去重）
                                     // BE→FE: 服务端 ULID（与 Event.id 一致时复用）
  "ts": "2026-04-15T10:30:00.123Z",  // ISO 8601 UTC，毫秒精度
  "ref": "<frame_id>?",              // 可选；BE→FE 的 ack/error 用以引用 FE→BE 帧 id
  "payload": { ... }                 // 类型决定 schema
}
```

设计点：
- `v` 仅用于版本协商（§3）；不变更帧结构。
- `id` 不是消息内容的 id（如 `Message.id`），而是 **传输层帧 id**。`Message.id` 在 payload 中作为 `message_id` 字段。
- `ref` 让 FE 把 `ack`/`error` 与发出的请求帧关联。

---

## 3. 连接生命周期

### 3.1 握手 (handshake)

```
FE → BE: client_hello { protocol_version, client_app, last_seen?, conversation_id?, operator_id?, squads? }
BE → FE: server_hello { session_id, protocol_version, server_time, viewer_role, accepted_subscriptions, server_capabilities[] }
       | error { code: "VERSION_INCOMPATIBLE" | "AUTH_FAILED", ... }
```

- `client_hello.last_seen` 为断线重连续传游标（§3.3）
- `protocol_version` 协商：服务端选 `min(client.v, server.v)` 落在 `accepted_versions` 内的最大值；不交集 → `VERSION_INCOMPATIBLE`
- `accepted_subscriptions` 让 FE 知道哪些 squad/conv 没被授权（部分授权而非整连接拒绝）

### 3.2 心跳 (heartbeat)

- FE 每 20s 发 `ping`；BE 立即回 `pong`
- BE 60s 内未收到 `ping` → 主动 close（code 4408 idle）
- `ping`/`pong` payload 仅 `{server_time?}`
- **不参与 ack 链**：`ping` / `pong` / `ack` / `error` 自身不再触发 ack（避免递归）；`pong` 已是 `ping` 的天然回执

### 3.3 重连与回放 (reconnect & replay)

新连接的 `client_hello.last_seen`：

```json
"last_seen": {
  "conv_seq": {
    "feishu_oc_abc123": { "msg": 42, "evt": 87 },
    "web_sess_xyz":     { "msg": 12, "evt": 25 }
  },
  "global_event_id": "01HX..."   // 仅 operator/admin；ULID 字典序游标
}
```

服务端处理（与 T0.1 Q3/不变量 #4 对齐）：
- **conv scope**：对每个 `conversation_id`，调用 `get_messages(since_sequence=msg)` + `query_events(since_sequence=evt)`，按序补发为 `message` / `event` 帧
- **squad/global scope**：用 `global_event_id` ULID 字典序，从 **per-subscription** ring buffer 重放（保留窗口见决策 D3）
- 回放完成后发 `replay_complete { conversation_id?, count }`，FE 据此切换"实时"UI 状态

> Ring buffer 是 **per-subscription** 的（每个 `subscribe()` 调用一份独立窗口），防止单条 hot conv 挤占其他 squad 订阅的事件窗。

如果 `last_seen` 落在保留窗口外 → BE 发 `error { code: "4041_REPLAY_GAP", recoverable: true }`，FE 应做"全量重拉"（`history_request` + 重新 subscribe）。

### 3.4 关闭码 (close codes)

| code | 含义 | FE 行为 |
|---|---|---|
| 1000 | 正常关闭 | 不重连 |
| 4001 | AUTH_FAILED / TOKEN_EXPIRED | 刷新 token 后重连 |
| 4003 | PERMISSION_REVOKED | 提示用户，不自动重连 |
| 4408 | IDLE_TIMEOUT | 立即重连 |
| 4409 | CONFLICT（同 session 多连接） | 不自动重连 |
| 4499 | SERVER_ERROR | 指数退避重连 |
| 4503 | OVERLOAD | 按 `retry_after` 重连 |

---

## 4. FE → BE 消息类型（≥10 类）

每个 FE→BE 帧都期望一个 `ack` 或 `error` 回执（`ref=frame_id`）。

| # | type | 端点 | payload 关键字段 | 对应 Engine 调用 |
|---|---|---|---|---|
| F1 | `client_hello` | all | `protocol_version, last_seen?, conversation_id?, operator_id?, squads?` | (握手，无 Engine 调用) |
| F2 | `ping` | all | `{}` | — |
| F3 | `client_ack` | all | `event_id` (ULID) | 标记前端已消费，BE 用于推进 per-sub cursor |
| F4 | `customer_message` | customer | `conversation_id, content, client_msg_id?, metadata?` | `send_message(source=<customer_pid>, content, requested_visibility=PUBLIC)` |
| F5 | `csat_response` | customer | `conversation_id, score (1-5)` | `set_csat(conversation_id, score)` |
| F6 | `subscribe` | operator/admin | `scope: {conversation_id?, squad_id?, global?: bool}, event_types?, since_sequence?` | `subscribe(...)` 新建一个内部订阅；`scope.global=true` 仅 `/ws/admin` 接受 |
| F7 | `unsubscribe` | operator/admin | `subscription_id` | 关闭对应 async iterator |
| F8 | `operator_join` | operator | `conversation_id, operator: {id, name, metadata?}` | `join(conversation_id, Participant(role=OPERATOR, ...))` |
| F9 | `operator_leave` | operator | `conversation_id, operator_id` | `leave(conversation_id, operator_id)` |
| F10 | `operator_message` | operator | `conversation_id, operator_id, content, requested_visibility?` (默认 PUBLIC，Gate 在 copilot 下降级) | `send_message(source=<operator_pid>, content, requested_visibility)` |
| F11 | `operator_command` | operator | `conversation_id, operator_id, command (/hijack \| /release \| /copilot \| /resolve \| /abandon \| /status), args?` | `handle_command(conversation_id, actor_id, command, args)` |
| F12 | `admin_command` | admin | `command (/status \| /dispatch \| /assign \| ...), args` | `handle_command(<global>, actor_id, command, args)` 或方法分派 |
| F13 | `history_request` | customer/operator | `conversation_id, since_sequence?, before_sequence?, limit?` | `get_messages(conversation_id, since_sequence?, before_sequence?, viewer_role)`；**`since_sequence` 与 `before_sequence` 互斥**（同传 → `4012_VALIDATION`） |
| F14 | `edit_request` | operator | `conversation_id, message_id, new_content` | `edit_message(...)` |
| F15 | `delete_request` | operator | `conversation_id, message_id` | `delete_message(...)` |

### 4.1 Schema 示例

**F4 customer_message**:
```json
{
  "v": 1, "type": "customer_message",
  "id": "f1e2-...-uuid", "ts": "2026-04-15T10:30:00.123Z",
  "payload": {
    "conversation_id": "feishu_oc_abc123",
    "content": "B 套餐多少钱",
    "client_msg_id": "tmp_local_001",
    "metadata": {"draft_duration_ms": 4500}
  }
}
```

**F11 operator_command**:
```json
{
  "v": 1, "type": "operator_command",
  "id": "f1e2-...-uuid", "ts": "2026-04-15T10:30:05.000Z",
  "payload": {
    "conversation_id": "feishu_oc_abc123",
    "operator_id": "xiaoli",
    "command": "/hijack",
    "args": {}
  }
}
```

**F13 history_request**:
```json
{
  "v": 1, "type": "history_request",
  "id": "f1e2-...-uuid", "ts": "2026-04-15T10:30:00.000Z",
  "payload": {
    "conversation_id": "feishu_oc_abc123",
    "before_sequence": 42,
    "limit": 50
  }
}
```

---

## 5. BE → FE 消息类型（≥10 类）

BE→FE 分两类：
- **同步回执**（`ack` / `error` / `command_response`）：必带 `ref` 指向 FE 请求帧
- **异步推送**（`message` / `event` / `*_snapshot` / `csat_request` / ...）：独立帧，无 `ref`

| # | type | payload 关键字段 | 触发源 |
|---|---|---|---|
| S1 | `server_hello` | `session_id, protocol_version, server_time, viewer_role, accepted_subscriptions, server_capabilities[]` | client_hello 应答 |
| S2 | `pong` | `server_time` | ping 应答 |
| S3 | `ack` | `ref` | 任一 FE→BE 帧成功落地 |
| S4 | `error` | `code, message, recoverable, retry_after?, details?, ref?` | 任一失败 |
| S5 | `message` | `conversation_id, message: Message`（id, source, content, visibility, sequence_number, timestamp, edit_of?, metadata）, `source_display: {id, role, name?, avatar_url?}` | Engine emit `message.sent` 后，根据 visibility + viewer_role 路由；`source_display` 由 WS 层根据 `source` participant_id 查 ParticipantRegistry 注入，与 Engine `Message` 类型解耦 |
| S6 | `message_edited` | `conversation_id, message_id, new_content, edited_by, sequence_number` | Engine emit `message.edited` |
| S7 | `message_deleted` | `conversation_id, message_id, deleted_by` | Engine emit `message.deleted` |
| S8 | `event` | `event: Event`（id, type, conversation_id, data, timestamp, sequence_number） | 通用 Event 推送（mode.* / participant.* / conversation.* / timer.* / sla.* / squad.* / hook.failed / mode.noop / message.gated） |
| S9 | `history_snapshot` | `conversation_id, messages: Message[], has_more, next_before_sequence?` | history_request 应答 |
| S10 | `csat_request` | `conversation_id, prompt?, options: [1..5]` | conversation.resolved 后服务端主动推 |
| S11 | `command_response` | `command, ok, result?, error_code?, error_message?, ref` | operator_command / admin_command 应答（如 /status 的列表）。**`ok=false` 时仅含命令级业务失败（含 EngineError 子类）；协议/鉴权失败走 S4 `error` 帧** |
| S12 | `replay_complete` | `conversation_id?, count, until_sequence` | reconnect 回放完成 |
| S13 | `subscription_added` | `subscription_id, scope, since_sequence: int \| string` | subscribe 应答；`since_sequence` 类型随 scope：conv = `int`，squad/global = `string`（ULID） |
| S14 | `subscription_removed` | `subscription_id, reason` | unsubscribe 或服务端 evict |

### 5.1 设计：为什么 `event` 是单一类型而不是 22 个独立 type

- **可演进**：v1.0 §5 以后新增事件无须改 WS schema 顶层 type 集合，FE 只需识别新 `event.type` 字符串。
- **统一路由**：FE 只装一个 `event` handler，按 `event.type` 字段做内部分发；保持 1:1 与 Engine event 字符串。
- **`message` / `message_edited` / `message_deleted` 例外抽出**：因为它们携带"chat 内容载荷"且 FE UI 渲染路径强烈不同（聊天气泡 vs 状态变化提示），独立帧类型有利于压缩消息处理逻辑。`message.sent` Event 仍在 `event` 流中作为审计副本，但内容信息以 `message` 帧为准（**双发**，FE 可只取 `message` 帧）。

> **决策点 D8**：`message.sent` 是否双发（`message` 帧 + `event` 帧）？草案：是，便于 squad 监控只订阅 events 也能看到消息计数。详见 §8。

### 5.2 `event` 帧的 viewer_role 过滤（v0.2 新增）

`event` 帧亦走 Engine `subscribe(viewer_role=...)` 过滤（T0.1 不变量 #6）。除"按 visibility 过滤 `message.*` 载荷"外，**以下事件类型仅推 OPERATOR / ADMIN，不推 CUSTOMER**：

| 事件类型 | 原因 |
|---|---|
| `message.gated` | 暴露 Gate 内部规则；客户不应得知"operator 试图发 public 被降为 side" |
| `hook.failed` | 含插件类名 / 异常 trace 等内部信息 |
| `sla.breach` | 内部运维信号，客户不应自行判断"客服超时" |
| `timer.set` / `timer.expired` / `timer.cancelled` | 内部计时器；客户只感知最终结果（如"已转人工"系统消息），不感知 timer 本体 |
| `squad.assigned` / `squad.reassigned` | 分队路由元数据 |

`message` / `message_edited` / `message_deleted` 帧本身已按 `Message.visibility` 过滤（CUSTOMER 只看 PUBLIC）。`message.sent` 双发的 `event` 帧载荷遵循同一过滤规则。

### 5.3 Schema 示例

**S5 message**（push to customer）：
```json
{
  "v": 1, "type": "message",
  "id": "01HXABC...",  "ts": "2026-04-15T10:30:01.500Z",
  "payload": {
    "conversation_id": "feishu_oc_abc123",
    "message": {
      "id": "01HXABC...",
      "conversation_id": "feishu_oc_abc123",
      "source": "fast-agent",
      "content": "B 套餐每月 199 元，本月 8 折优惠...",
      "visibility": "public",
      "sequence_number": 2,
      "timestamp": "2026-04-15T10:30:01.450Z",
      "edit_of": null,
      "metadata": {}
    }
  }
}
```

**S8 event**（mode.changed）：
```json
{
  "v": 1, "type": "event",
  "id": "01HXEVT...", "ts": "2026-04-15T10:30:15.000Z",
  "payload": {
    "event": {
      "id": "01HXEVT...",
      "type": "mode.changed",
      "conversation_id": "feishu_oc_abc123",
      "data": {
        "from": "copilot",
        "to": "takeover",
        "trigger": "/hijack",
        "triggered_by": "xiaoli"
      },
      "timestamp": "2026-04-15T10:30:15.000Z",
      "sequence_number": 8
    }
  }
}
```

**S11 command_response**（/status）：
```json
{
  "v": 1, "type": "command_response",
  "id": "01HX...", "ts": "...", "ref": "client_frame_uuid",
  "payload": {
    "command": "/status",
    "ok": true,
    "result": {
      "active_count": 3,
      "conversations": [
        {"id": "feishu_oc_abc123", "customer": "David", "mode": "takeover", "operator": "xiaoli"},
        {"id": "feishu_oc_def456", "customer": "张三",  "mode": "auto",     "operator": null},
        {"id": "web_sess_789",     "customer": "匿名",  "mode": "auto",     "operator": null}
      ]
    }
  }
}
```

---

## 6. 错误码

```
分类前缀: 4xx_ 客户端可纠正 · 5xx_ 服务端问题
```

| code | 说明 | recoverable | retry_after | 建议 FE 行为 |
|---|---|---|---|---|
| `4001_AUTH_FAILED` | token 无效或过期 | true | — | 刷新 token 后重连 |
| `4003_PERMISSION_DENIED` | 角色无权执行（对应 `PermissionDenied`） | false | — | UI 灰化按钮 + 提示 |
| `4004_NOT_FOUND` | conversation/message/timer 不存在 | false | — | 提示 + 刷新列表 |
| `4009_CONFLICT` | 重复 frame_id / 重复 join | true | — | 忽略或重新生成 id |
| `4012_VALIDATION` | payload 格式错误（对应 `ValidationError`） | false | — | 修正后重发 |
| `4013_ILLEGAL_STATE` | mode 非法转换 / closed 会话写入 | false | — | 刷新状态后重试 |
| `4029_RATE_LIMIT` | 限流 | true | yes | 按 retry_after 等 |
| `4040_VERSION_INCOMPATIBLE` | 协议版本无交集 | false | — | 升级客户端 |
| `4041_REPLAY_GAP` | last_seen 落在保留窗口外 | true | — | 走"全量重拉" |
| `5000_INTERNAL` | 服务端 bug | true | yes | 指数退避 |
| `5003_OVERLOAD` | 服务端过载 | true | yes | 按 retry_after |

> Engine 的 `EngineError` 子类 → WS error code 映射在 §6.2 Bridge handler 实现表中给出（待 LocalEngine 实现）。

### 6.1 `error` 帧 vs `command_response{ok:false}` 边界（v0.2 新增）

| 失败类别 | 走哪条 | 例 |
|---|---|---|
| **协议 / 鉴权失败**（payload 格式错、帧 v 不兼容、token 过期、限流、重连游标失效） | **S4 `error` 帧**（带 `ref` 关联失败的 FE 帧） | `4001_AUTH_FAILED`、`4012_VALIDATION`、`4029_RATE_LIMIT`、`4041_REPLAY_GAP` |
| **命令级业务失败**（Engine 返回异常被 handle_command 吞下后转 `ok=false`） | **S11 `command_response{ok:false}`**（`error_code` + `error_message`） | `/hijack` `PermissionDenied`、`/dispatch` `ConversationNotFound`、`/resolve` `ConversationAlreadyClosed`、`switch_mode` `IllegalModeTransition` |
| **非命令的 Engine 调用失败**（`customer_message` 被 `ValidationError` / `send_message` 时 conv 不存在） | **S4 `error` 帧** | `4012_VALIDATION`、`4004_NOT_FOUND` |

判定法：**有命令语义的 → command_response；没有的 → error**。这样 FE 可以把"命令按钮的红色提示"和"全局 toast 错误"用两套 UI 通道区分。

---

## 7. ConversationEngine ↔ WS 映射全表

| Engine 方法 | FE→BE 帧 | BE→FE 同步 | BE→FE 异步 (Event 字符串) |
|---|---|---|---|
| `create_conversation` | （隐式：customer_connect → 服务端创建） | `event` 帧 (`conversation.created`) | `conversation.activated` |
| `get_conversation` | (内部使用，不暴露) | — | — |
| `list_active_conversations` | `admin_command /status` 或 `subscribe(squad_id=)` | `command_response` | `event` 帧（squad scope） |
| `close_conversation` | `operator_command /resolve` 或 `/abandon` | `command_response` | `conversation.resolved` + `conversation.closed` |
| `set_csat` | `csat_response` | `ack` | `conversation.csat_recorded` |
| `join` | `operator_join` | `ack` | `participant.joined` (+可能 `mode.changed`) |
| `leave` | `operator_leave` | `ack` | `participant.left` (+可能 `mode.changed` 回落 auto) |
| `switch_mode` | (通常经 `operator_command`) | — | `mode.changed` 或 `mode.noop` |
| `send_message` | `customer_message` / `operator_message` | `ack` (含 server-assigned `message_id`) | `message` 帧 + `message.sent` event (+可能 `message.gated`) |
| `edit_message` | `edit_request` | `ack` | `message_edited` 帧 + `message.edited` event |
| `delete_message` | `delete_request` | `ack` | `message_deleted` 帧 + `message.deleted` event |
| `get_messages` | `history_request` | `history_snapshot` | — |
| `handle_command` | `operator_command`（actor_id = operator_id） / `admin_command`（actor_id = admin_user_id；Engine §6.1 admin 列识别） | `command_response` | 因命令而异 |
| `set_timer` / `cancel_timer` | (内部) | — | `timer.set` / `timer.cancelled` / `timer.expired` |
| `subscribe` | `subscribe` | `subscription_added` | `event` 帧流 |
| `query_events` | (audit/admin only, 计划走 HTTP) | — | — |

`message.sent` / `message.edited` / `message.deleted` 同时走"内容帧"和"事件帧"双通道（D8）。

---

## 8. 决策选择题（请 DevA 表态）

### D1. 端点拆分：3 个 vs 1 个统一端点

- **草案**：`/ws/customer` `/ws/operator` `/ws/admin` 三端点
- **反方**：1 个 `/ws` 端点 + handshake 内 `viewer_role` —— 反向代理/负载均衡更简单
- **倾向**：草案。授权策略差异大（customer 用短 session token，operator/admin 用 SSO），端点拆分让前置网关做粗过滤更容易

### D2. 重连游标格式

- **草案**：`last_seen.conv_seq[id] = {msg, evt}` per-conv map + `global_event_id` ULID
- **反方**：单游标 `last_event_id`（ULID），服务端从全局回放表算每 conv 的差集
- **倾向**：草案。客户视角只需自己 conv 的两个数；operator 才需要 squad/global 游标。混合更经济

### D3. 服务端事件保留窗口

- **草案**：滚动窗口，**默认 15 min × 1000 条 / 订阅**，超出回 `4041_REPLAY_GAP`
- **反方**：固定 1h；或按 conv 持久（让 SQLite 兜底）
- **倾向**：草案。15min 覆盖典型刷新/网络抖动；落地全量回放走 `history_request`（有 SQLite 后盾）

### D4. 心跳间隔与超时

- **草案**：FE ping 20s · BE 60s no-ping → close
- **反方**：30s/90s（更省功耗，对移动端友好）
- **倾向**：草案。Web 端目前主战场；移动端看后续接入再调

### D5. 二进制载荷（图片/文件）

- **草案**：**HTTP URL only**，WS 帧只携带 `attachment_url`（带签名+ TTL）；不允许 inline base64
- **反方**：允许小尺寸（<256KB）inline base64
- **倾向**：草案。WS 是低延迟通道，禁止大 payload 阻塞队列；上传走 `POST /api/upload` 拿 URL

### D6. `ack` 模型

- **草案**：FE→BE 每帧都期待 `ack`（带 `ref`）；超时 5s 没 ack → FE 重发（同 `id` 幂等）
- **反方**：仅"重要"帧 ack（消息发送/命令），其他 fire-and-forget
- **倾向**：草案。统一 ack 让 FE 状态机简单（"待确认"队列），重复帧服务端按 `id` 去重即可

### D7. `client_msg_id` 回写

- **草案**：customer_message 的 `payload.client_msg_id` 在 `ack` 中回写，服务端不复用为 `Message.id`（Engine 仍生成 ULID）
- **反方**：服务端把 `client_msg_id` 当 `Message.id`（少一层映射）
- **倾向**：草案。Engine 不变量要求 `Message.id = ULID`（T0.1 Q1），不能让客户端污染 ID 空间

### D8. `message.sent` 是否双发（`message` 帧 + `event` 帧）

- **草案**：**双发**。`message` 帧用于 chat UI 渲染；`event` 帧用于 squad/audit 订阅者计数和监控
- **反方**：单发 `message` 帧；`event` 流跳过 `message.sent` 子类
- **倾向**：草案。带宽成本低（同条数据），但极大简化"分队卡片摘要每 3 条 public 消息刷新"（US-2.3）的实现——squad 订阅者不必再拉 `get_messages`

---

## 9. 不在 v1.0 范围

- **HTTP 备用通道**：`query_events` / 大文件上传 / token 刷新走 HTTP，不在本契约
- **SSE 降级**：v1.0 假定 WSS 可用；公司网代理穿透问题留 v1.1
- **服务端推 `typing_indicator`**：UX 增强项，不影响契约骨架
- **多设备会话同步**：v1.0 同 session 单连接（4009_CONFLICT）；多端共存留后续

---

## 10. 验收清单（v1.0 frozen 前）

- [ ] FE→BE ≥10 类：✅ 当前 15 类（F1-F15）
- [ ] BE→FE ≥10 类：✅ 当前 14 类（S1-S14）
- [ ] 每种类型有 JSON 示例：F4/F11/F13 + S5/S8/S11 已示例，其余在 `test-vectors/` 补齐
- [ ] reconnect 协议：✅ §3.3
- [ ] 版本协商：✅ §3.1
- [ ] error 语义：✅ §6
- [ ] Engine 方法 → WS 消息映射：✅ §7
- [ ] 决策题：✅ D1-D8
- [x] DevA review 第一轮回复：D1–D8 全过 + 7 条修订（v0.2 已吸收）
- [x] DevA second-pass：✅ SIGN OFF（issue #21 / 2026-04-15）
- [x] 终稿 frontmatter 标 FROZEN

---

## 11. 变更历史

| 版本 | 日期 | 变更 | 作者 |
|---|---|---|---|
| 0.1-draft | 2026-04-15 | 初稿：3 端点 + 信封 + 握手/重连/版本协商 + FE→BE 15 类 + BE→FE 14 类 + 错误码 + 8 决策题 | DevB |
| 0.2-draft | 2026-04-15 | 吸收 DevA review 7 条修订 + 2 小疵：admin actor 模型修正 / 4500→4499 / F6 +`global` / F13 互斥 / S5 +`source_display` / §5.2 event 过滤表 / §6.1 error vs command_response 边界 / S13 联合类型 / `ping`-`pong` 不再 ack / ring buffer per-sub | DevB |
| **1.0** | **2026-04-15** | **FROZEN**：DevA second-pass sign off；§5 章节编号修正（5.2 event 过滤 / 5.3 Schema 示例） | DevB + DevA |

---

*End of T0.2 Frontend WS Schema v1.0 · FROZEN 2026-04-15.*
