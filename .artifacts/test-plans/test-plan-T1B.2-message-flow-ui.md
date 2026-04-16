---
type: test-plan
id: test-plan-004
status: confirmed
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-doc-005 (T1B.2 消息流 UI) — confirmed"
related:
  - eval-doc-005
  - "contract:docs/contracts/frontend-ws-schema.md"
  - "task:T1B.2"
decisions_frozen:
  D1: "打字指示：客户端推断（发送→显示，收回复→隐藏，30s超时）"
  D2: "消息分组：同 source + 5min 时间窗口断组"
  D3: "时间戳：仅组尾最后一条显示"
  D4: "图片加载失败：onError → 灰色占位"
test_setup:
  framework: "Vitest 1.x + @testing-library/react 14.x（已有）"
  location: "frontend/apps/customer-chat/src/__tests__/"
---

# Test Plan: T1B.2 消息流 UI

## 触发原因

eval-doc-005 定义了 9 个产出文件（4 个新建组件 + 5 个增强）。
本 plan 覆盖：时间戳格式化、消息分组、打字指示、图片渲染、头像、store 扩展。
共计 **21 个用例**，新增 3 个测试文件，扩展 3 个已有测试文件。

## 测试文件规划

```
src/__tests__/
  formatTimestamp.test.ts       # 新建 (TC-001~005)
  TypingIndicator.test.tsx      # 新建 (TC-006~008)
  MessageGroup.test.tsx         # 新建 (TC-009~013)
  MessageBubble.test.tsx        # 扩展 (TC-014~016，原有3个保留)
  MessageList.test.tsx          # 扩展 (TC-017~018，原有2个保留)
  chatStore.test.ts             # 扩展 (TC-019~020，原有5个保留)
  integration.test.tsx          # 扩展 (TC-021，原有2个保留)
```

---

## 用例列表

### 分组 A · formatTimestamp 工具（TC-001 ~ TC-005）

#### TC-001: 今天的时间戳只显示 HH:MM
- **文件**: `formatTimestamp.test.ts`
- **优先级**: P0
- **步骤**:
  1. `const ts = new Date(); ts.setHours(14, 32, 0)`（今天 14:32）
  2. `formatTimestamp(ts.toISOString())`
- **预期**: `"14:32"`（24h 格式）
- **涉及**: `src/utils/formatTimestamp.ts`

#### TC-002: 昨天的时间戳显示 "昨天 HH:MM"
- **文件**: `formatTimestamp.test.ts`
- **优先级**: P0
- **步骤**:
  1. 构造昨天 09:15 的 ISO 字符串
  2. `formatTimestamp(ts)`
- **预期**: `"昨天 09:15"` 或语言无关的 `"Yesterday 09:15"`（Skill 3 可选；统一即可）
- **涉及**: `src/utils/formatTimestamp.ts`

#### TC-003: 更早日期显示 "M/D HH:MM"
- **文件**: `formatTimestamp.test.ts`
- **优先级**: P0
- **步骤**: 构造 4 月 10 日 16:00
- **预期**: `"4/10 16:00"`
- **涉及**: `src/utils/formatTimestamp.ts`

#### TC-004: 无效时间戳返回空字符串而非崩溃
- **文件**: `formatTimestamp.test.ts`
- **优先级**: P1
- **步骤**: `formatTimestamp('')` 和 `formatTimestamp('not-a-date')`
- **预期**: 返回 `""` 或 `"--:--"`；不抛异常
- **涉及**: `src/utils/formatTimestamp.ts`

#### TC-005: 零点边界——今天 00:00 vs 昨天 23:59
- **文件**: `formatTimestamp.test.ts`
- **优先级**: P1
- **步骤**: 分别构造今天 00:00:01 和昨天 23:59:59
- **预期**: 今天显示 `HH:MM`，昨天显示含 "昨天"/"Yesterday"
- **涉及**: `src/utils/formatTimestamp.ts`

### 分组 B · TypingIndicator 组件（TC-006 ~ TC-008）

#### TC-006: visible=true 时渲染三点动画
- **文件**: `TypingIndicator.test.tsx`
- **优先级**: P0
- **步骤**: `render(<TypingIndicator visible={true} />)`
- **预期**:
  - `screen.getByTestId('typing-indicator')` 存在
  - 找到 3 个 `animate-bounce` 元素
- **涉及**: `src/components/TypingIndicator.tsx`

#### TC-007: visible=false 时不渲染
- **文件**: `TypingIndicator.test.tsx`
- **优先级**: P0
- **步骤**: `render(<TypingIndicator visible={false} />)`
- **预期**: `queryByTestId('typing-indicator') === null`
- **涉及**: `src/components/TypingIndicator.tsx`

#### TC-008: store isAgentTyping=true → MessageList 显示 typing-indicator
- **文件**: `TypingIndicator.test.tsx`
- **优先级**: P0
- **步骤**:
  1. `useChatStore.setState({ ...initialState, isAgentTyping: true })`
  2. `render(<MessageList messages={[]} />)`
- **预期**: `screen.getByTestId('typing-indicator')` 存在
- **涉及**: `src/components/MessageList.tsx`, `src/store/chatStore.ts`

### 分组 C · MessageGroup 分组逻辑（TC-009 ~ TC-013）

#### TC-009: 相邻同 source 消息合并为一组
- **文件**: `MessageGroup.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 构造 3 条 `source='agent-1'` 的相邻消息（时间间隔 < 5min）
  2. `render(<MessageList messages={msgs} />)`
- **预期**:
  - 只有 **1 个** `[data-testid="sender-avatar"]`（头像不重复）
  - 只有 **1 个** 发送者名字文本
  - 3 条气泡内容都在页面
- **涉及**: `src/components/MessageGroup.tsx`, `src/components/MessageList.tsx`

#### TC-010: 不同 source 消息各自独立头像
- **文件**: `MessageGroup.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 消息 A: `source='agent-1'`，消息 B: `source='agent-2'`
  2. `render(<MessageList messages={[A, B]} />)`
- **预期**: 2 个 `[data-testid="sender-avatar"]`
- **涉及**: `src/components/MessageGroup.tsx`

#### TC-011: 时间间隔 > 5min 强制断组
- **文件**: `MessageGroup.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 消息 A: `source='agent-1'`, `timestamp=T`
  2. 消息 B: `source='agent-1'`, `timestamp=T+6min`
- **预期**: 2 个 `[data-testid="sender-avatar"]`（断组了）
- **涉及**: `src/components/MessageGroup.tsx`（groupMessages 函数）

#### TC-012: customer 消息不显示头像（右对齐，自己就是用户）
- **文件**: `MessageGroup.test.tsx`
- **优先级**: P1
- **步骤**:
  1. 1 条 `sourceRole='customer'` 消息
  2. `render(<MessageList messages={[msg]} />)`
- **预期**: `queryByTestId('sender-avatar') === null`
- **涉及**: `src/components/MessageGroup.tsx`

#### TC-013: 组尾最后一条显示时间戳，组内前面的不显示
- **文件**: `MessageGroup.test.tsx`
- **优先级**: P1
- **步骤**:
  1. 3 条同 source 消息（timestamps: T, T+1min, T+2min）
  2. `render(<MessageList messages={msgs} />)`
- **预期**:
  - `queryAllByTestId('message-timestamp')` 长度为 1
  - 该时间戳对应最后一条消息的时间
- **涉及**: `src/components/MessageBubble.tsx`（条件渲染 timestamp）

### 分组 D · MessageBubble 增强（TC-014 ~ TC-016）

#### TC-014: 图片消息渲染 img 元素
- **文件**: `MessageBubble.test.tsx`（扩展）
- **优先级**: P0
- **步骤**:
  1. `render(<MessageBubble message={{ ..., metadata: { attachment_url: 'https://example.com/img.jpg' } }} showTimestamp={false} />)`
- **预期**:
  - `getByTestId('image-attachment')` 存在
  - `src === 'https://example.com/img.jpg'`
  - 无 `<p>` 文本段落
- **涉及**: `src/components/MessageBubble.tsx`

#### TC-015: 图片加载失败显示占位
- **文件**: `MessageBubble.test.tsx`（扩展）
- **优先级**: P1
- **步骤**:
  1. render 图片消息
  2. `fireEvent.error(screen.getByTestId('image-attachment'))`
- **预期**: img 被替换为 `[data-testid="image-error-placeholder"]`（或 img `src` 变为占位）
- **涉及**: `src/components/MessageBubble.tsx`

#### TC-016: showTimestamp=true 时渲染时间戳
- **文件**: `MessageBubble.test.tsx`（扩展）
- **优先级**: P0
- **步骤**:
  1. `render(<MessageBubble message={{ ..., timestamp: '2026-04-16T06:32:00.000Z' }} showTimestamp={true} />)`
- **预期**: `getByTestId('message-timestamp')` 存在，文本含 `14:32`（本地时间，依测试时区；或检查格式正则 `\d{1,2}:\d{2}`）
- **涉及**: `src/components/MessageBubble.tsx`, `src/utils/formatTimestamp.ts`

### 分组 E · MessageList 集成（TC-017 ~ TC-018）

#### TC-017: isAgentTyping=false 时 typing-indicator 不存在
- **文件**: `MessageList.test.tsx`（扩展）
- **优先级**: P0
- **步骤**:
  1. `useChatStore.setState({ ...initialState, isAgentTyping: false })`
  2. `render(<MessageList messages={[]} />)`
- **预期**: `queryByTestId('typing-indicator') === null`
- **涉及**: `src/components/MessageList.tsx`

#### TC-018: SenderAvatar 有 avatarUrl 时渲染 img；无时渲染首字母
- **文件**: `MessageList.test.tsx`（扩展）
- **优先级**: P1
- **步骤**:
  1. 渲染含 `avatarUrl='https://example.com/a.png'` 的 agent 消息
  2. 渲染含 `senderName='Alice'` 无 avatarUrl 的 agent 消息
- **预期**:
  - 情况 1: `[data-testid="sender-avatar"] img` 存在
  - 情况 2: `[data-testid="sender-avatar"]` 文本含 `"A"`
- **涉及**: `src/components/SenderAvatar.tsx`

### 分组 F · Store 扩展（TC-019 ~ TC-020）

#### TC-019: setAgentTyping 更新 isAgentTyping
- **文件**: `chatStore.test.ts`（扩展）
- **优先级**: P0
- **步骤**:
  1. 初始 `isAgentTyping === false`
  2. `useChatStore.getState().setAgentTyping(true)`
- **预期**: `isAgentTyping === true`
- **涉及**: `src/store/chatStore.ts`

#### TC-020: addMessage 时如果 sourceRole 为 agent → setAgentTyping(false)
- **文件**: `chatStore.test.ts`（扩展）
- **优先级**: P0
- **步骤**:
  1. `setAgentTyping(true)`
  2. `addMessage({ ..., sourceRole: 'agent', status: 'sent' })`
- **预期**: `isAgentTyping === false`（收到 agent 回复自动关闭打字指示）
- **说明**: 此逻辑可在 store `addMessage` 内实现，或在 `useWebSocket.ts` 的 onFrame 里实现；测试验证结果即可
- **涉及**: `src/store/chatStore.ts` 或 `src/hooks/useWebSocket.ts`

### 分组 G · 集成（TC-021）

#### TC-021: 发送消息后出现 typing-indicator；收到 agent 回复后消失
- **文件**: `integration.test.tsx`（扩展）
- **优先级**: P0
- **步骤**:
  1. FakeWSClient 注入，握手完成
  2. 输入并发送 "Hello"
  3. 断言 `typing-indicator` 出现
  4. `fakeInstance.pushFrame({ type:'message', ..., source_display:{ role:'agent' }, ... })`
  5. 断言 `typing-indicator` 消失
- **涉及**: `App.tsx`, `useWebSocket.ts`, `chatStore.ts`, `TypingIndicator.tsx`

---

## 统计

| 指标 | 值 |
|---|---|
| 新增用例数 | 21 |
| 原有用例（T1B.1，不重跑，保留） | 22 |
| P0 | 15 |
| P1 | 6 |
| 新建测试文件 | 3 |
| 扩展测试文件 | 4 |

## Skill 3 实现约束

1. **`MessageBubble` 新 prop**: 加 `showTimestamp?: boolean`（组件本身不判断是否组尾，由 MessageGroup 决定传 true/false）
2. **`groupMessages` 纯函数**：导出为 `export function groupMessages(messages: ChatMessage[]): MessageGroup[]`，方便单独测试
3. **`isAgentTyping` 初始值** = `false`，加入 `initialState` 对象（确保测试 reset 有效）
4. **打字超时**：使用 `useRef` 存 timer id，组件 unmount 清除；App.tsx 传 `onSend` 时 `setAgentTyping(true)` + 启动 30s 定时器
5. **不得破坏 T1B.1 原有 22 个测试**：运行 `pnpm test` 要求 43/43（22 旧 + 21 新）全绿
6. **时区处理**：`formatTimestamp` 使用本地时区比较日期（`new Date().toLocaleDateString()` 比较），不用 UTC

## 后续行动

- [x] test-plan 已注册 (test-plan-004, confirmed)
- [ ] Skill 3 写 21 用例 + 9 文件实现
- [ ] Skill 4 跑 `pnpm test`，目标 43/43 全绿
