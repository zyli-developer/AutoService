# eval-doc-006 · T1B.3 占位续写渲染

> **Mode**: simulate · **Owner**: DevB · **Date**: 2026-04-16

---

## 1. 任务目标

实现"占位态 → edit 事件原地续写替换（非新发）"（US-2.2）。

**完整流程**：
1. BE 快模型生成占位消息（"正在为您查询…"），通过 `message` 帧推送，`metadata.is_placeholder=true`
2. FE 渲染为**占位气泡**（含脉冲光标动画，区别于普通消息）
3. BE 慢模型产出真实内容，通过 `message_edited` 帧推送（`new_content` 字段）
4. FE **原地替换**气泡内容（无新气泡，有短暂高亮过渡动画）

**关联契约**：S5 `message` + S6 `message_edited`（frontend-ws-schema.md §5）

---

## 2. 现有代码分析

### 2.1 已有能力

| 模块 | 现状 |
|---|---|
| `useWebSocket.ts` | 已处理 `message_edited` 帧 → 调 `store.updateMessage(messageId, content)` |
| `store.updateMessage` | 已按 id 更新 content |
| `MessageBubble.tsx` | 已渲染文本内容；`T1B.2` 的 `typing-indicator-placeholder` 已替换 |

### 2.2 现有 Bug（T1B.3 必修）

**Bug #1 · 字段名错误**：`useWebSocket.ts` 的 `message_edited` 处理读取 `p.content`，但 WS 契约 S6 明确字段名为 **`new_content`**：

```typescript
// 当前（错误）
const content = p.content as string;

// 正确
const newContent = p.new_content as string;
```

**Bug #2 · `updateMessage` 不清除 `isStreaming`**：续写到达后气泡应退出占位动画，但当前 `updateMessage` 只更新 content，无法清除 streaming 状态（该字段尚未存在）。

### 2.3 缺失能力（T1B.3 需新增）

| 缺口 | 说明 |
|---|---|
| `ChatMessage.isStreaming` 字段 | 标识消息处于占位/流式态 |
| 占位气泡 UI | 脉冲光标动画，区别于普通消息 |
| 内容替换动画 | 续写到达时短暂高亮（~500ms） |
| `isStreaming` 生命周期管理 | 进 → 出的状态迁移 |

---

## 3. 架构设计

### 3.1 占位状态检测

BE 推送占位消息时，`metadata.is_placeholder = true`。FE 检测逻辑：

```typescript
// 在 useWebSocket.ts message 帧处理中
const isStreaming = (metadata?.is_placeholder as boolean) === true;
useChatStore.getState().addMessage({
  ...
  isStreaming,
});
```

### 3.2 ChatMessage 扩展

```typescript
interface ChatMessage {
  // ...现有字段
  isStreaming?: boolean;   // true = 占位中，等待 message_edited
  justEdited?: boolean;   // 瞬态：续写刚到达，触发高亮动画（500ms 后自动清除）
}
```

### 3.3 Store 动作扩展

```typescript
// updateMessage 增强：清除 isStreaming + 设置 justEdited
updateMessage: (messageId, newContent) =>
  set((state) => ({
    messages: state.messages.map((m) =>
      m.id === messageId
        ? { ...m, content: newContent, isStreaming: false, justEdited: true }
        : m
    ),
  })),

// 新增：clearJustEdited（500ms 后由组件 setTimeout 调用）
clearJustEdited: (messageId) =>
  set((state) => ({
    messages: state.messages.map((m) =>
      m.id === messageId ? { ...m, justEdited: false } : m
    ),
  })),
```

### 3.4 MessageBubble 视觉状态机

```
isStreaming=true   →  占位气泡（脉冲光标 + 淡蓝背景）
justEdited=true    →  高亮过渡（背景短暂变黄/蓝，500ms fade out）
otherwise          →  普通气泡（现有样式）
```

**占位光标 CSS**（Tailwind animate-pulse）：
```tsx
{message.isStreaming && (
  <span
    data-testid="streaming-cursor"
    className="inline-block w-0.5 h-4 bg-current ml-0.5 animate-pulse align-middle"
  />
)}
```

**高亮过渡**：`justEdited` 为 true 时加 `ring-2 ring-blue-300` 类，500ms 后触发 `clearJustEdited` 清除。

```tsx
// 组件内 useEffect
useEffect(() => {
  if (!message.justEdited) return;
  const timer = setTimeout(() => {
    useChatStore.getState().clearJustEdited(message.id);
  }, 500);
  return () => clearTimeout(timer);
}, [message.justEdited, message.id]);
```

### 3.5 useWebSocket.ts 修复清单

```typescript
// message_edited 帧处理（修复 new_content 字段名）
} else if (frame.type === 'message_edited') {
  const p = frame.payload as Record<string, unknown>;
  const messageId = p.message_id as string;
  const newContent = p.new_content as string;   // ← 修正
  if (messageId && newContent !== undefined) {
    useChatStore.getState().updateMessage(messageId, newContent);
  }
}
```

---

## 4. 关键设计决策

### D1. 占位检测方式：`metadata.is_placeholder` vs 内容模式匹配

**决策**：`metadata.is_placeholder === true`（显式标记）。
- 理由：内容模式匹配脆弱（真实消息也可能含"…"）；显式 flag 是 T1A.6 实现者需要遵守的约定
- 降级：若 `is_placeholder` 不存在，`isStreaming` 默认 `false`，消息正常渲染（向后兼容）

### D2. 高亮动画实现：CSS transition vs React state

**决策**：React state（`justEdited` 字段）+ Tailwind class 切换。
- 理由：无需引入额外动画库；JSDOM 测试环境下可检查 class 变化
- 实现：`justEdited=true` → 加 ring class → 500ms 后 `clearJustEdited` → class 消失

### D3. `justEdited` 清除时机：setTimeout vs CSS animation end

**决策**：`setTimeout(500ms)` 在组件内触发，受 `useEffect` 管理。
- 理由：`animationend` 事件在 JSDOM 下不触发，测试不友好

### D4. `clearJustEdited` 是 store action 还是组件本地 state

**决策**：store action。
- 理由：`justEdited` 存在 store 里（随消息列表渲染），若存在组件本地，重渲染时会重置；store 保证跨渲染一致性

---

## 5. 与契约的对齐检查

| 契约条款 | 实现对照 |
|---|---|
| S5 `message.metadata` | 读 `metadata.is_placeholder` 设置 `isStreaming` |
| S6 `message_edited.new_content` | **修复** `useWebSocket.ts` 读取字段名 |
| S6 `message_edited.message_id` | 已正确读取 |
| S6 `message_edited.sequence_number` | 存入 store（`updateMessage` 接受可选 sequenceNumber 参数；暂不强要求） |
| US-2.2 占位→续写 | 原地替换，无新气泡 ✓ |

---

## 6. 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| BE（T1A.6）尚未实现，无法端到端验证 | 中 | FakeWSClient 模拟完整流程；smoke test 等 M1 联调 |
| 500ms 高亮时间过短/过长 | 低 | 常量化，联调时调整 |
| `justEdited` 在消息列表重排时重复触发 | 低 | `useEffect` 依赖 `[message.justEdited, message.id]`，仅在 flag 变为 true 时触发 |

---

## 7. 不在范围

- 字符级流式输出（SSE / chunk 追加）→ BE 选择"占位→整体替换"模式，非逐字流
- `message_deleted`（S7）渲染 → 后续任务
- operator 发起的 `edit_request`（F14）→ T2B 阶段
- `edit_of` 字段展示"编辑历史"→ 后续

---

## 8. 产出清单

| # | 文件 | 动作 | 说明 |
|---|---|---|---|
| 1 | `src/store/chatStore.ts` | 扩展 | 加 `isStreaming`、`justEdited`；扩展 `updateMessage`；加 `clearJustEdited` action |
| 2 | `src/hooks/useWebSocket.ts` | **修复** + 扩展 | `new_content` 字段名修复；解析 `is_placeholder` |
| 3 | `src/components/MessageBubble.tsx` | 扩展 | 占位光标动画 + 高亮过渡 + `useEffect` clearJustEdited |

共 **3 个文件**，改动集中，影响范围可控。

---

*eval-doc-006 · T1B.3 · simulate · 待 review*
