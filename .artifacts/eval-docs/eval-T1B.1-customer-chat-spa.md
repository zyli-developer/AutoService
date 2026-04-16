# eval-doc-004 · T1B.1 customer-chat SPA 骨架

> **Mode**: simulate · **Owner**: DevB · **Date**: 2026-04-16

---

## 1. 任务目标

将 T0.6 产出的 `frontend/apps/customer-chat/` 占位页面扩展为功能完整的客户聊天 SPA 骨架，支撑 US-2.1（客户访问即获 Agent 问候）。

**验收标准**（来自 tasks-v3 + kickoff Batch 2 smoke）：
- 浏览器打开 customer-chat，F12 看 WS 握手成功
- 页面有完整聊天 UI 布局（输入框、消息区、标题栏）
- WS 连接 `web_gateway` 的 `/ws/customer` 端点
- 消息能发送（`customer_message` 帧）并显示在 UI 上
- 收到 `message` 帧能渲染为聊天气泡

---

## 2. 现有代码分析

### 2.1 已有（T0.6 产出）

| 模块 | 文件 | 状态 |
|---|---|---|
| WSClient | `packages/ws-client/src/client.ts` | 完整：握手、心跳、重连、ack |
| WS 类型 | `packages/ws-client/src/types.ts` | 完整：F1-F15 + S1-S14 + 枚举 |
| Envelope 解析 | `packages/ws-client/src/envelope.ts` | 完整：Zod schema |
| useWebSocket hook | `apps/customer-chat/src/hooks/useWebSocket.ts` | 骨架：只暴露 status/lastFrame/sessionId |
| App.tsx | `apps/customer-chat/src/App.tsx` | 占位：显示 WS 状态 + JSON dump |
| main.tsx | `apps/customer-chat/src/main.tsx` | 完整：I18nProvider 包裹 |
| 依赖 | package.json | React 18 + Tailwind + Radix + Zustand + ws-client + i18n |

### 2.2 缺失（T1B.1 需产出）

| 需求 | 说明 |
|---|---|
| 聊天布局组件 | 标题栏 + 消息列表 + 输入区的三段式布局 |
| 消息气泡组件 | 区分 customer / agent / system 来源的气泡样式 |
| 消息输入组件 | 输入框 + 发送按钮 + Enter 发送 |
| 消息状态管理 | Zustand store 管理消息列表 + 会话状态 |
| WS 消息分发 | 将 `message` / `message_edited` / `event` 帧分发到 store |
| 发送消息 | 构造 `customer_message` 帧通过 WSClient.send() |
| 连接状态 UI | 断线/重连中的视觉反馈 |
| 打字指示占位 | 为 T1B.3（占位续写渲染）预留 typing indicator 位置 |

---

## 3. 架构设计

### 3.1 组件树

```
<App>
  <ChatLayout>
    <ChatHeader />           -- 标题 + 连接状态指示
    <MessageList>             -- 滚动消息容器
      <MessageBubble />       -- 单条消息（气泡样式）
      <SystemMessage />       -- 系统消息（居中小字）
      <TypingIndicator />     -- T1B.3 预留
    </MessageList>
    <ChatInput />             -- 输入框 + 发送
  </ChatLayout>
```

### 3.2 状态管理（Zustand）

```typescript
interface ChatStore {
  // Connection
  connectionStatus: 'idle' | 'connecting' | 'open' | 'closed';
  sessionId: string | null;
  conversationId: string | null;

  // Messages
  messages: ChatMessage[];
  
  // Actions
  addMessage: (msg: ChatMessage) => void;
  updateMessage: (messageId: string, content: string) => void;
  setConnectionStatus: (status: ConnectionStatus) => void;
  setConversationId: (id: string) => void;
}

interface ChatMessage {
  id: string;
  source: string;
  sourceRole: 'customer' | 'agent' | 'operator' | 'system';
  content: string;
  visibility: Visibility;
  timestamp: string;
  sequenceNumber: number;
  status: 'sending' | 'sent' | 'failed';  // optimistic UI
  clientMsgId?: string;                    // 乐观发送的临时 ID
}
```

### 3.3 WS 消息流

```
用户输入 → ChatInput.onSubmit()
  → store.addMessage(optimistic, status='sending')
  → wsClient.send('customer_message', payload)
  → ack 回来 → store.updateStatus(clientMsgId, 'sent')
  → error 回来 → store.updateStatus(clientMsgId, 'failed')

服务端推送 → useWebSocket.onFrame
  → frame.type === 'message' → store.addMessage(fromServer)
  → frame.type === 'message_edited' → store.updateMessage(id, newContent)
  → frame.type === 'event' → 按 event.type 分发（mode.changed 等暂不处理，T2B 实现）
```

### 3.4 文件结构规划

```
apps/customer-chat/src/
  main.tsx                    (已有，不改)
  App.tsx                     (重写：挂载 ChatLayout)
  index.css                   (扩展 Tailwind 样式)
  store/
    chatStore.ts              (新建：Zustand store)
  hooks/
    useWebSocket.ts           (重构：增加消息分发到 store)
    useAutoScroll.ts          (新建：消息列表自动滚底)
  components/
    ChatLayout.tsx            (新建：三段式布局容器)
    ChatHeader.tsx            (新建：标题 + 状态)
    MessageList.tsx           (新建：消息滚动列表)
    MessageBubble.tsx         (新建：消息气泡)
    SystemMessage.tsx         (新建：系统消息)
    ChatInput.tsx             (新建：输入框)
    ConnectionBanner.tsx      (新建：断线提示条)
```

---

## 4. 关键设计决策

### D1. 消息来源角色判断

**问题**: `Message.source` 是 participant_id 字符串，不是 role。BE→FE 的 `message` 帧有 `source_display: {id, role, name?}`（T0.2 §5 S5），可直接用。

**决策**: 用 `payload.source_display.role` 判断气泡样式。若 `source_display` 不存在（兼容），fallback 到 `source` 字符串含 "agent" → agent，否则 customer。

### D2. 乐观发送

**决策**: 用户发送消息时立即渲染（status='sending'），收到 ack 后改 'sent'。服务端推回的 `message` 帧与本地乐观消息通过 `client_msg_id` 去重（不重复渲染）。

### D3. conversation_id 获取时机

**决策**: customer 端隐式订阅（T0.2 §1）。`server_hello` 返回后，等待第一个 `event(conversation.created/activated)` 获取 conversation_id。或者，如果 `client_hello` 携带 `conversation_id`（重连场景），直接用。首次访问时 conversation_id 由服务端创建后通过 event 推送。

### D4. 滚动行为

**决策**: 新消息到达时，如果用户已在底部（或接近底部 50px），自动滚到底。如果用户正在翻阅历史，不自动滚动，改为显示"有新消息"按钮。

---

## 5. 与契约的对齐检查

| T0.2 条款 | 实现对照 |
|---|---|
| §1 `/ws/customer` 端点 | WSClient URL 指向 `/ws/customer` |
| §2 帧信封 `{v, type, id, ts, ref, payload}` | 复用 `packages/ws-client/envelope.ts` Zod schema |
| §3.1 `client_hello` → `server_hello` | WSClient 已实现 |
| §3.2 心跳 20s ping | WSClient 已实现（默认 15s，需调为 20s） |
| §4 F4 `customer_message` | ChatInput → wsClient.send('customer_message', ...) |
| §5 S5 `message` + `source_display` | MessageBubble 渲染 |
| §5 S6 `message_edited` | store.updateMessage() |
| §5 S10 `csat_request` | 预留，T1B.1 不实现 CSAT UI |
| §6 错误码 | ConnectionBanner 显示 4001 刷新提示等 |

**心跳间隔偏差**: WSClient 默认 15s，契约要求 20s（§3.2）。需在 useWebSocket 传 `heartbeatMs: 20_000`。

---

## 6. 风险与边界

| 风险 | 等级 | 缓解 |
|---|---|---|
| web_gateway 尚未实现 `message` 帧推送 | 中 | T1B.1 只做 UI 骨架；用 mock WS server 或 T0.5 已有的骨架验证握手 |
| source_display 字段尚未在 BE 实现 | 低 | fallback 逻辑已设计 |
| conversation_id 创建流程依赖 A 线 T1A.1-3 | 低 | 本任务 UI 可用硬编码 conv_id 测试 |

---

## 7. 不在 T1B.1 范围

- 占位续写渲染 → T1B.3
- 断线重连 + 消息回放 → T1B.4
- 浮动按钮 SDK → T1B.5
- i18n 22 语种填充 → T1B.6
- 消息气泡的图片/附件类型 → 后续
- CSAT 评分 UI → 后续
- 历史消息拉取（history_request）→ T1B.4

---

## 8. 产出清单

| # | 文件 | 动作 | 说明 |
|---|---|---|---|
| 1 | `src/store/chatStore.ts` | 新建 | Zustand 消息 + 连接状态 |
| 2 | `src/components/ChatLayout.tsx` | 新建 | 三段式布局 |
| 3 | `src/components/ChatHeader.tsx` | 新建 | 标题 + 连接状态 |
| 4 | `src/components/MessageList.tsx` | 新建 | 消息滚动容器 |
| 5 | `src/components/MessageBubble.tsx` | 新建 | 聊天气泡 |
| 6 | `src/components/SystemMessage.tsx` | 新建 | 系统消息 |
| 7 | `src/components/ChatInput.tsx` | 新建 | 输入框 + 发送 |
| 8 | `src/components/ConnectionBanner.tsx` | 新建 | 断线提示 |
| 9 | `src/hooks/useWebSocket.ts` | 重构 | 消息分发到 store |
| 10 | `src/hooks/useAutoScroll.ts` | 新建 | 自动滚底逻辑 |
| 11 | `src/App.tsx` | 重写 | 挂载 ChatLayout |
| 12 | `src/index.css` | 扩展 | 聊天相关 Tailwind |

---

*eval-doc-004 · T1B.1 · simulate · 待 review*
