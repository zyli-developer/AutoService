---
type: test-plan
id: test-plan-003
status: draft
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-doc-004 (T1B.1 customer-chat SPA skeleton simulate) — confirmed"
related:
  - eval-doc-004
  - "contract:docs/contracts/frontend-ws-schema.md"
  - "task:T1B.1"
decisions_frozen:
  D1: "source_display.role 判断气泡样式，fallback 到 source 字符串含 'agent'"
  D2: "乐观发送 + client_msg_id 去重"
  D3: "conversation_id 由 server event(conversation.created) 推送获取"
  D4: "智能自动滚底：底部50px内新消息才自动滚，否则显示'新消息'按钮"
test_setup:
  framework: "Vitest 1.x + @testing-library/react 14.x"
  ws_mock: "手写 FakeWSClient stub（注入替换真实 WSClient）"
  location: "frontend/apps/customer-chat/src/__tests__/"
---

# Test Plan: T1B.1 customer-chat SPA 骨架

## 触发原因

eval-doc-004 定义了 12 个产出文件（store、7 个组件、2 个 hooks、App.tsx 重写）。
本 plan 将核心行为转为可执行单测，覆盖：状态管理、WS 帧分发、组件渲染、消息发送、
自动滚底、连接状态反馈。共计 **22 个用例**。

## 测试文件位置

```
frontend/apps/customer-chat/
  src/__tests__/
    chatStore.test.ts          # store 纯逻辑
    useWebSocket.test.tsx      # hook 帧分发
    MessageBubble.test.tsx     # 气泡渲染
    ChatInput.test.tsx         # 输入 + 发送
    MessageList.test.tsx       # 自动滚底
    ConnectionBanner.test.tsx  # 断线提示
    integration.test.tsx       # 端到端 UI 流程（FakeWS → 渲染）
  vitest.config.ts             # 新建（JSDOM 环境）
```

## 测试框架配置

```typescript
// vitest.config.ts（新建）
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
  },
});

// src/__tests__/setup.ts（新建）
import '@testing-library/jest-dom';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
```

## 新增 devDependencies（Skill 3 负责添加）

```json
"vitest": "^1.6.0",
"@testing-library/react": "^14.3.1",
"@testing-library/user-event": "^14.5.2",
"@testing-library/jest-dom": "^6.4.2",
"jsdom": "^24.1.0"
```

## FakeWSClient stub（共享）

```typescript
// src/__tests__/fakeWSClient.ts
import { vi } from 'vitest';
import type { WSClientOptions } from '@autoservice/ws-client';

export class FakeWSClient {
  public opts: WSClientOptions;
  public sendCalls: Array<{ type: string; payload: unknown }> = [];

  constructor(opts: WSClientOptions) { this.opts = opts; }

  connect() {
    // 立即触发 open（同步）
    this.opts.onOpen?.({
      session_id: 'test-session-123',
      protocol_version: 1,
      server_time: '2026-04-16T09:00:00.000Z',
      viewer_role: 'CUSTOMER',
      accepted_subscriptions: [],
      server_capabilities: ['streaming'],
    });
  }

  send(type: string, payload: unknown) {
    this.sendCalls.push({ type, payload });
    return Promise.resolve();
  }

  close() {}

  /** 测试辅助：从外部推送一帧给 onFrame handler */
  pushFrame(frame: Record<string, unknown>) {
    this.opts.onFrame?.(frame as never);
  }

  /** 测试辅助：触发连接断开 */
  pushClose(code = 1000, reason = 'test') {
    this.opts.onClose?.(code, reason);
  }
}

/** 注入 FakeWSClient 替换模块中的 WSClient */
export function mockWSClient() {
  const instance = { current: null as FakeWSClient | null };
  vi.mock('@autoservice/ws-client', async (importActual) => {
    const actual = await importActual<typeof import('@autoservice/ws-client')>();
    return {
      ...actual,
      WSClient: class {
        constructor(opts: WSClientOptions) {
          const fake = new FakeWSClient(opts);
          instance.current = fake;
          return fake;
        }
      },
    };
  });
  return instance;
}
```

---

## 用例列表

### 分组 A · chatStore 纯逻辑（TC-001 ~ TC-005）

#### TC-001: addMessage 追加到列表，status 默认 'sent'
- **文件**: `chatStore.test.ts`
- **优先级**: P0
- **步骤**:
  1. 构造 `ChatMessage` 对象（id='m1', sourceRole='customer', content='hello'）
  2. 调用 `useChatStore.getState().addMessage(msg)`
- **预期**:
  - `messages.length === 1`
  - `messages[0].content === 'hello'`
  - `messages[0].status === 'sent'`（默认）
- **涉及**: `src/store/chatStore.ts`

#### TC-002: addMessage optimistic 状态（status='sending'）
- **文件**: `chatStore.test.ts`
- **优先级**: P0
- **步骤**:
  1. `addMessage({ ..., status: 'sending', clientMsgId: 'tmp-1' })`
- **预期**: `messages[0].status === 'sending'`; `messages[0].clientMsgId === 'tmp-1'`
- **涉及**: `src/store/chatStore.ts`

#### TC-003: updateMessage 按 messageId 更新 content
- **文件**: `chatStore.test.ts`
- **优先级**: P0
- **步骤**:
  1. `addMessage({ id: 'm2', content: 'old', ... })`
  2. `updateMessage('m2', 'new content')`
- **预期**: `messages[0].content === 'new content'`
- **涉及**: `src/store/chatStore.ts`

#### TC-004: setConnectionStatus 更新状态
- **文件**: `chatStore.test.ts`
- **优先级**: P0
- **步骤**:
  1. 初始 `connectionStatus === 'idle'`
  2. `setConnectionStatus('open')`
- **预期**: `connectionStatus === 'open'`
- **涉及**: `src/store/chatStore.ts`

#### TC-005: 乐观消息去重 —— 收到服务端 message 帧时按 clientMsgId 升级而非重复
- **文件**: `chatStore.test.ts`
- **优先级**: P0
- **步骤**:
  1. `addMessage({ id: 'tmp-uuid-1', clientMsgId: 'tmp-1', status: 'sending', content: 'hi' })`
  2. 调用 `confirmOptimistic('tmp-1', { id: 'server-m1', content: 'hi', sequenceNumber: 1 })`（新 action）
- **预期**:
  - `messages.length === 1`（未重复）
  - `messages[0].id === 'server-m1'`
  - `messages[0].status === 'sent'`
  - `messages[0].sequenceNumber === 1`
- **说明**: `confirmOptimistic` 是 store 的新 action；若 Skill 3 改名，测试跟随
- **涉及**: `src/store/chatStore.ts`

### 分组 B · useWebSocket hook 帧分发（TC-006 ~ TC-010）

#### TC-006: WS open → store.connectionStatus = 'open', sessionId 更新
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P0
- **前提**: `mockWSClient()` 注入 FakeWSClient
- **步骤**:
  1. `renderHook(() => useWebSocket('ws://localhost:9999/ws/customer', 'test'))`
  2. `act(() => fakeClient.connect())`（FakeWSClient.connect 触发 onOpen）
- **预期**:
  - `useChatStore.getState().connectionStatus === 'open'`
  - hook 返回的 `sessionId === 'test-session-123'`
- **涉及**: `src/hooks/useWebSocket.ts`, `src/store/chatStore.ts`

#### TC-007: 收到 `message` 帧 → store.addMessage 被调用
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 握手完成后调用 `fakeClient.pushFrame({ type: 'message', id: 'f1', ts: '...', v:1, payload: { conversation_id: 'cv1', message: { id: 'msg-1', content: 'Hi', visibility: 'public', sequence_number: 1 }, source_display: { id: 'agent-1', role: 'agent', name: 'Bot' } } })`
- **预期**:
  - `useChatStore.getState().messages` 包含一条 `id='msg-1'`、`sourceRole='agent'`、`content='Hi'` 的消息
  - `conversationId === 'cv1'`（store 中）
- **涉及**: `src/hooks/useWebSocket.ts`

#### TC-008: 收到 `message_edited` 帧 → store.updateMessage 被调用
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 先推 message 帧建立 msg-1
  2. 推 `{ type: 'message_edited', payload: { message_id: 'msg-1', new_content: 'Edited!' } }`
- **预期**: `messages[0].content === 'Edited!'`
- **涉及**: `src/hooks/useWebSocket.ts`

#### TC-009: WS close → store.connectionStatus = 'closed'
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P0
- **步骤**: 握手后 `fakeClient.pushClose(1001, 'going_away')`
- **预期**: `connectionStatus === 'closed'`
- **涉及**: `src/hooks/useWebSocket.ts`

#### TC-010: 心跳配置 heartbeatMs=20000 传给 WSClient
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P1
- **步骤**:
  1. 捕获 FakeWSClient constructor 的 opts
  2. render hook
- **预期**: `fakeClient.opts.heartbeatMs === 20_000`（契约要求 20s，见 eval-doc-004 §5）
- **涉及**: `src/hooks/useWebSocket.ts`（需修正默认值）

### 分组 C · MessageBubble 渲染（TC-011 ~ TC-013）

#### TC-011: customer 消息右对齐，agent 消息左对齐
- **文件**: `MessageBubble.test.tsx`
- **优先级**: P0
- **步骤**:
  1. `render(<MessageBubble message={{ ..., sourceRole: 'customer', content: 'Hello' }} />)`
  2. `render(<MessageBubble message={{ ..., sourceRole: 'agent', content: 'Hi' }} />)`
- **预期**:
  - customer 气泡: 容器有 `justify-end`（或 `ml-auto`）class
  - agent 气泡: 容器有 `justify-start`（或 `mr-auto`）class
- **涉及**: `src/components/MessageBubble.tsx`

#### TC-012: status='sending' 时显示发送中指示（opacity 或 spinner）
- **文件**: `MessageBubble.test.tsx`
- **优先级**: P1
- **步骤**:
  1. `render(<MessageBubble message={{ ..., status: 'sending' }} />)`
- **预期**: 存在 `[data-testid="sending-indicator"]` 或 opacity-50 类（Skill 3 择一）
- **涉及**: `src/components/MessageBubble.tsx`

#### TC-013: source_display 缺失时 fallback 不崩溃
- **文件**: `MessageBubble.test.tsx`
- **优先级**: P1
- **步骤**:
  1. `render(<MessageBubble message={{ ..., sourceRole: undefined, source: 'agent-bot' }} />)`
- **预期**: 不抛；渲染结果含消息文本
- **说明**: 测 D1 fallback 逻辑
- **涉及**: `src/components/MessageBubble.tsx`

### 分组 D · ChatInput 输入与发送（TC-014 ~ TC-016）

#### TC-014: 点击发送按钮触发 onSend 回调
- **文件**: `ChatInput.test.tsx`
- **优先级**: P0
- **步骤**:
  1. `const onSend = vi.fn()`
  2. `render(<ChatInput onSend={onSend} />)`
  3. `userEvent.type(input, 'Hello world')`
  4. `userEvent.click(sendButton)`
- **预期**: `onSend` 被调用，参数 `'Hello world'`；输入框清空
- **涉及**: `src/components/ChatInput.tsx`

#### TC-015: Enter 键触发 onSend
- **文件**: `ChatInput.test.tsx`
- **优先级**: P0
- **步骤**:
  1. `userEvent.type(input, 'Hi{Enter}')`
- **预期**: `onSend('Hi')` 被调用；输入框清空
- **涉及**: `src/components/ChatInput.tsx`

#### TC-016: 空输入不触发 onSend
- **文件**: `ChatInput.test.tsx`
- **优先级**: P1
- **步骤**:
  1. 输入框为空，点击发送
- **预期**: `onSend` 未被调用
- **涉及**: `src/components/ChatInput.tsx`

### 分组 E · MessageList 自动滚底（TC-017 ~ TC-018）

#### TC-017: 新消息到达时（用户在底部）自动滚到底
- **文件**: `MessageList.test.tsx`
- **优先级**: P1
- **步骤**:
  1. 模拟 `scrollTop` 接近 `scrollHeight - clientHeight`（≤50px）
  2. 追加一条新消息到 `messages` prop
- **预期**: `scrollIntoView` 或 `scrollTop = scrollHeight` 被调用（spy）
- **说明**: JSDOM 不渲染真实 layout，需 spy `Element.prototype.scrollIntoView`
- **涉及**: `src/components/MessageList.tsx`, `src/hooks/useAutoScroll.ts`

#### TC-018: 用户在上方时不自动滚，显示"新消息"按钮
- **文件**: `MessageList.test.tsx`
- **优先级**: P1
- **步骤**:
  1. 模拟 `scrollTop=0`（距底>50px）
  2. 追加新消息
- **预期**: `scrollIntoView` 未被调用；出现 `[data-testid="new-msg-btn"]`
- **涉及**: `src/components/MessageList.tsx`, `src/hooks/useAutoScroll.ts`

### 分组 F · ConnectionBanner（TC-019 ~ TC-020）

#### TC-019: connectionStatus='closed' 时显示断线提示
- **文件**: `ConnectionBanner.test.tsx`
- **优先级**: P0
- **步骤**:
  1. `render(<ConnectionBanner status="closed" />)`
- **预期**: 存在断线相关文本（如"连接中断"或"Reconnecting"）；
  `[data-testid="connection-banner"]` 可见
- **涉及**: `src/components/ConnectionBanner.tsx`

#### TC-020: connectionStatus='open' 时 banner 不渲染
- **文件**: `ConnectionBanner.test.tsx`
- **优先级**: P0
- **步骤**:
  1. `render(<ConnectionBanner status="open" />)`
- **预期**: `queryByTestId("connection-banner") === null`
- **涉及**: `src/components/ConnectionBanner.tsx`

### 分组 G · 集成：WS 帧到 UI（TC-021 ~ TC-022）

#### TC-021: 完整流程——WS message 帧 → 气泡出现在页面
- **文件**: `integration.test.tsx`
- **优先级**: P0
- **步骤**:
  1. `mockWSClient()` 注入 FakeWSClient
  2. `render(<App />)`
  3. `act(() => fakeClient.connect())` → 握手完成
  4. `act(() => fakeClient.pushFrame({ type:'message', payload:{ message:{id:'m1', content:'Welcome!'}, source_display:{role:'agent'} } }))`
- **预期**: `screen.getByText('Welcome!')` 存在于 DOM
- **涉及**: `App.tsx`, `MessageBubble.tsx`, `chatStore.ts`, `useWebSocket.ts`

#### TC-022: 用户发消息——ChatInput 提交 → WSClient.send 被调用
- **文件**: `integration.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 握手完成
  2. `userEvent.type(chatInput, 'Hello agent')`
  3. `userEvent.click(sendBtn)`
- **预期**:
  - `fakeWSClient.sendCalls` 包含 `{ type: 'customer_message', payload: { content: 'Hello agent', ... } }`
  - 页面出现气泡文本 "Hello agent"（乐观渲染）
- **涉及**: `ChatInput.tsx`, `useWebSocket.ts`, `chatStore.ts`

---

## 统计

| 指标 | 值 |
|---|---|
| 总用例数 | 22 |
| P0 | 14 |
| P1 | 7 |
| P2 | 1 |
| 测试文件数 | 7 |
| 新增框架 | Vitest + @testing-library/react |

## 风险标注

- **高风险**: JSDOM 无真实 layout，TC-017/018 自动滚底需 spy，可能因 Skill 3 实现方式不同调整
- **中风险**: FakeWSClient mock 依赖 `vi.mock` 的模块路径正确；若 ws-client 用 barrel export 需调整 mock 路径
- **低风险**: TC-005 乐观去重依赖 `confirmOptimistic` action 名称；Skill 3 有命名自由但须暴露对应 action

## Skill 3 实现约束

1. **新增 devDep**: vitest、@testing-library/* 加到 `apps/customer-chat/package.json`
2. **禁区**: 不得修改 `packages/ws-client/src/`（T0.6 产物，已稳定）
3. **命名规范**: 测试函数 `it('TC-XXX: <行为描述>', ...)` 与 testid 在组件内以 `data-testid` 声明
4. **store 重置**: 每个测试前调用 `useChatStore.setState(initialState)` 避免状态污染；在 `setup.ts` 中统一处理
5. **heartbeat 修正**: `useWebSocket.ts` 须传 `heartbeatMs: 20_000` 给 WSClient（TC-010 门禁）
6. **typecheck**: Skill 4 跑测试前须先过 `pnpm typecheck`，不允许 TS 报错

## 后续行动

- [x] test-plan 已注册到 .artifacts/test-plans/ (test-plan-003, draft)
- [ ] 用户 review + 确认 (status: draft → confirmed)
- [ ] Skill 3 基于本 plan 写 22 用例 + 骨架实现（12 个文件）
- [ ] Skill 4 跑 `pnpm --filter @autoservice/customer-chat test`
