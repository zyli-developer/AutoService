# eval-doc-005 · T1B.2 消息流 UI

> **Mode**: simulate · **Owner**: DevB · **Date**: 2026-04-16

---

## 1. 任务目标

在 T1B.1 骨架基础上，将消息流提升为完整的产品级 UI，覆盖：
- **时间戳**：每条气泡显示格式化发送时间
- **打字指示**：客户发送后，等待 Agent 回复期间显示"正在输入"动画
- **多消息类型**：文本（已有）+ 图片（`metadata.attachment_url`）
- **气泡增强**：发送者名称（agent/operator 显示 name）、头像占位、消息分组（连续同源消息合并头像）

**关联 PRD**：β1 · US-2.1（客户看到 Agent 问候）  
**前置**：T1B.1 🟩（骨架组件已完整）

---

## 2. 现有代码分析

### 2.1 T1B.1 已有

| 模块 | 状态 | T1B.2 需做什么 |
|---|---|---|
| `MessageBubble.tsx` | 文本渲染、左右对齐、sending/failed 状态 | 加时间戳、发送者名、头像、图片类型 |
| `MessageList.tsx` | 滚动容器 + `typing-indicator-placeholder` | 替换占位为真实 `TypingIndicator` |
| `chatStore.ts` | `ChatMessage` 含 `timestamp`、无 `metadata`/`senderName`/`avatarUrl` | 扩展类型 + 加 typing 状态 |
| `useWebSocket.ts` | 解析 `source_display.role` | 补充解析 `name`、`avatar_url`、`metadata` |

### 2.2 ChatMessage 当前类型缺口

```typescript
// 缺失字段（T1B.2 需补）：
senderName?: string;      // from source_display.name
avatarUrl?: string;       // from source_display.avatar_url
metadata?: {
  attachment_url?: string;  // D5: 图片/文件 URL（HTTP only）
  [key: string]: unknown;
};
contentType?: 'text' | 'image';  // 推断：有 attachment_url → image
```

---

## 3. 架构设计

### 3.1 组件变化

```
MessageList
  ├── MessageGroup          ← NEW：相邻同源消息分组（共享头像 + 名字）
  │     ├── SenderAvatar    ← NEW：圆形头像（有 avatarUrl → img，否则首字母占位）
  │     └── MessageBubble   ← ENHANCE：加时间戳 + 图片类型
  └── TypingIndicator       ← NEW：替换 placeholder（三点动画）
```

### 3.2 消息分组逻辑

连续来自同一 `source` 的消息合并为一个 `MessageGroup`：
- 第一条：显示头像 + 发送者名
- 后续条：缩进对齐，不重复头像
- 分组分隔：时间间隔 > 5 分钟，或来源不同

```typescript
function groupMessages(messages: ChatMessage[]): MessageGroup[] {
  // 按相邻同 source 聚合
  // 时间差 > 5min 则强制断组
}
interface MessageGroup {
  source: string;
  sourceRole: ChatMessage['sourceRole'];
  senderName?: string;
  avatarUrl?: string;
  messages: ChatMessage[];
}
```

### 3.3 时间戳格式

| 场景 | 格式 | 示例 |
|---|---|---|
| 今天 | `HH:MM` | `14:32` |
| 昨天 | `昨天 HH:MM` | `昨天 09:15` |
| 更早 | `M/D HH:MM` | `4/10 16:00` |

- 每条消息气泡下方显示（小字、灰色）
- 分组内：仅最后一条显示时间戳（减少视觉噪声）

### 3.4 打字指示（Typing Indicator）

**触发机制（客户端推断，无需 BE 推送）**：
- 客户发送消息后，`typingActive = true`
- 收到任何新的 agent/operator 消息后，`typingActive = false`
- 超时 30s 自动关闭（防止 BE 无响应时永久显示）
- WS 断开时自动关闭

**Store 扩展**：
```typescript
interface ChatState {
  // ...现有字段
  isAgentTyping: boolean;
  setAgentTyping: (v: boolean) => void;
}
```

**组件**：
```tsx
// TypingIndicator.tsx
export function TypingIndicator({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <div data-testid="typing-indicator" className="flex px-4 py-1 justify-start">
      <div className="bg-slate-100 rounded-2xl rounded-bl-sm px-4 py-3 flex gap-1">
        <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce [animation-delay:0ms]" />
        <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce [animation-delay:150ms]" />
        <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce [animation-delay:300ms]" />
      </div>
    </div>
  );
}
```

### 3.5 图片消息渲染

判断逻辑（在 `MessageBubble` 内）：
```typescript
const isImage = !!message.metadata?.attachment_url;
```

渲染：
```tsx
{isImage ? (
  <img
    src={message.metadata!.attachment_url}
    alt="image attachment"
    className="max-w-[240px] rounded-lg"
    data-testid="image-attachment"
    loading="lazy"
  />
) : (
  <p className="whitespace-pre-wrap break-words">{message.content}</p>
)}
```

### 3.6 SenderAvatar

```tsx
function SenderAvatar({ name, avatarUrl }: { name?: string; avatarUrl?: string }) {
  if (avatarUrl) {
    return <img src={avatarUrl} className="w-8 h-8 rounded-full" alt={name} />;
  }
  const initial = (name ?? '?')[0].toUpperCase();
  return (
    <div className="w-8 h-8 rounded-full bg-slate-300 flex items-center justify-center text-xs font-medium text-slate-600">
      {initial}
    </div>
  );
}
```

---

## 4. 关键设计决策

### D1. 打字指示触发：客户端推断 vs 契约扩展

**背景**：WS 契约 v1.0 §9 明确将 `typing_indicator` 列为"不在范围"。

**决策**：**客户端推断**。
- 客户发消息 → `setAgentTyping(true)` + 启动 30s 超时
- 收到 agent 消息 → `setAgentTyping(false)` + 清除超时
- 实现简单，无需 BE 配合；T2 阶段如需真实指示，只需改触发点

### D2. 消息分组粒度：同 source vs 同 role

**决策**：**同 source**（participant_id）。
- 理由：两个不同 operator 发消息，role 相同但 source 不同，应各自显示头像和名字
- 5 分钟时间间隔强制断组，增强可读性

### D3. 时间戳显示位置：每条 vs 仅组尾

**决策**：**仅组尾最后一条显示**。
- 减少视觉干扰；用户关注"这组消息是什么时间发的"
- 对比：iMessage、微信均采用类似策略（间隔较大才显示新时间戳）

### D4. 图片加载失败处理

**决策**：显示 broken-image 占位（`alt` 文字 + 灰色背景）。
- `onError` 事件替换 img src 为内联 SVG 占位

---

## 5. 与契约的对齐检查

| 契约条款 | 实现对照 |
|---|---|
| S5 `message.metadata` 为 flexible dict | `ChatMessage.metadata?: Record<string,unknown>` |
| S5 `source_display.name?` / `avatar_url?` | 解析后存入 `senderName` / `avatarUrl` |
| D5 图片 HTTP URL only，WS 携带 `attachment_url` | 读 `metadata.attachment_url`，`<img>` 渲染 |
| §9 `typing_indicator` 不在 v1.0 WS 范围 | 客户端推断，无需新帧类型 ✓ |
| S5 `message.timestamp` ISO8601 UTC | `formatTimestamp()` 格式化显示 |

---

## 6. 风险与边界

| 风险 | 等级 | 缓解 |
|---|---|---|
| 图片 URL 跨域（CORS） | 中 | 渲染 `<img>` 自然支持；签名 URL 由 BE 控制 TTL |
| `metadata.attachment_url` 字段名未在契约 JSON 示例中出现 | 低 | D5 明确命名；useWebSocket 解析时 optional chaining |
| 打字指示 30s 超时过长/过短 | 低 | 可配置常量，联调时调整 |
| 消息分组算法在大量历史消息时性能 | 低 | `useMemo` 包裹分组计算 |

---

## 7. 不在 T1B.2 范围

- 占位续写（streaming text）→ T1B.3
- 历史消息拉取 → T1B.4
- 文件（非图片）附件 → 后续
- 服务端推 `typing_indicator` 帧 → WS v1.1
- 表情回应（reaction） → 后续

---

## 8. 产出清单

| # | 文件 | 动作 | 说明 |
|---|---|---|---|
| 1 | `src/store/chatStore.ts` | 扩展 | 加 `senderName`、`avatarUrl`、`metadata`、`isAgentTyping` |
| 2 | `src/components/TypingIndicator.tsx` | 新建 | 三点动画 |
| 3 | `src/components/SenderAvatar.tsx` | 新建 | 头像（img or 首字母） |
| 4 | `src/components/MessageGroup.tsx` | 新建 | 分组容器 |
| 5 | `src/components/MessageBubble.tsx` | 增强 | 时间戳 + 图片 + 图片加载失败 |
| 6 | `src/components/MessageList.tsx` | 增强 | 分组渲染 + TypingIndicator 替换 placeholder |
| 7 | `src/hooks/useWebSocket.ts` | 增强 | 解析 `senderName`/`avatarUrl`/`metadata`；触发 typing |
| 8 | `src/utils/formatTimestamp.ts` | 新建 | 时间格式化工具 |
| 9 | `src/App.tsx` | 微调 | handleSend 后 setAgentTyping(true) |

---

*eval-doc-005 · T1B.2 · simulate · 待 review*
