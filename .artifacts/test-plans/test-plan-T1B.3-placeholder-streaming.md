---
type: test-plan
id: test-plan-005
status: confirmed
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-doc-006 (T1B.3 占位续写渲染) — confirmed"
related:
  - eval-doc-006
  - "contract:docs/contracts/frontend-ws-schema.md §5 S6"
  - "task:T1B.3"
decisions_frozen:
  D1: "占位检测：metadata.is_placeholder===true；缺省→isStreaming=false（向后兼容）"
  D2: "高亮动画：justEdited React state + Tailwind ring class"
  D3: "clearJustEdited 由组件内 setTimeout(500ms) 触发"
  D4: "clearJustEdited 是 store action（跨渲染一致）"
  BugFix: "message_edited 帧字段名：p.content → p.new_content"
---

# Test Plan: T1B.3 占位续写渲染

## 触发原因

eval-doc-006 确定 3 个文件变更（store + hook + bubble）及 1 个 Bug 修复。
本 plan 共 **16 个用例**，覆盖：bug 修复验证、store 新动作、占位气泡视觉、
高亮动画生命周期、及端到端占位→续写流程。

## 测试文件规划

```
src/__tests__/
  chatStore.test.ts        扩展（TC-023~026，原有 7 个保留）
  MessageBubble.test.tsx   扩展（TC-027~030，原有 6 个保留）
  useWebSocket.test.tsx    扩展（TC-031~033，原有 5 个保留）
  integration.test.tsx     扩展（TC-034~038，原有 3 个保留）
```

目标：原有 42 + 新增 16 = **58/58 全绿**。

---

## 用例列表

### 分组 A · Store 新动作（TC-023 ~ TC-026）

#### TC-023: updateMessage 清除 isStreaming，设置 justEdited
- **文件**: `chatStore.test.ts`
- **优先级**: P0
- **步骤**:
  1. `addMessage({ id:'m1', isStreaming: true, content:'占位中…', ... })`
  2. `updateMessage('m1', '真实内容')`
- **预期**:
  - `messages[0].content === '真实内容'`
  - `messages[0].isStreaming === false`
  - `messages[0].justEdited === true`
- **涉及**: `src/store/chatStore.ts`

#### TC-024: clearJustEdited 将指定消息 justEdited 设回 false
- **文件**: `chatStore.test.ts`
- **优先级**: P0
- **步骤**:
  1. `addMessage({ id:'m2', justEdited: true, ... })`
  2. `clearJustEdited('m2')`
- **预期**: `messages[0].justEdited === false`
- **涉及**: `src/store/chatStore.ts`

#### TC-025: clearJustEdited 只影响目标消息，不影响其他
- **文件**: `chatStore.test.ts`
- **优先级**: P1
- **步骤**:
  1. addMessage m1(`justEdited:true`) + m2(`justEdited:true`)
  2. `clearJustEdited('m1')`
- **预期**: `m1.justEdited===false`, `m2.justEdited===true`
- **涉及**: `src/store/chatStore.ts`

#### TC-026: addMessage 含 isStreaming=true 正常存入 store
- **文件**: `chatStore.test.ts`
- **优先级**: P0
- **步骤**: `addMessage({ id:'m3', isStreaming: true, content:'…', ... })`
- **预期**: `messages[0].isStreaming === true`
- **涉及**: `src/store/chatStore.ts`

### 分组 B · MessageBubble 占位视觉（TC-027 ~ TC-030）

#### TC-027: isStreaming=true 时渲染 streaming-cursor
- **文件**: `MessageBubble.test.tsx`
- **优先级**: P0
- **步骤**: `render(<MessageBubble message={{ ..., isStreaming: true, content:'…' }} />)`
- **预期**: `getByTestId('streaming-cursor')` 存在
- **涉及**: `src/components/MessageBubble.tsx`

#### TC-028: isStreaming=false 时不渲染 streaming-cursor
- **文件**: `MessageBubble.test.tsx`
- **优先级**: P0
- **步骤**: `render(<MessageBubble message={{ ..., isStreaming: false }} />)`
- **预期**: `queryByTestId('streaming-cursor') === null`
- **涉及**: `src/components/MessageBubble.tsx`

#### TC-029: justEdited=true 时气泡含高亮 class（ring-2）
- **文件**: `MessageBubble.test.tsx`
- **优先级**: P0
- **步骤**: `render(<MessageBubble message={{ ..., justEdited: true }} />)`
- **预期**: 内层气泡 div 含 `ring-2` class（或 `data-testid="bubble-highlight"` 存在）
- **涉及**: `src/components/MessageBubble.tsx`

#### TC-030: justEdited=true 时 500ms 后 clearJustEdited 被调用
- **文件**: `MessageBubble.test.tsx`
- **优先级**: P0
- **步骤**:
  1. `vi.useFakeTimers()`
  2. 向 store 加入 `{ id:'m4', justEdited: true }` 的消息
  3. `render(<MessageBubble message={...} />)`
  4. `vi.advanceTimersByTime(500)`
- **预期**: `useChatStore.getState().messages[0].justEdited === false`
- **说明**: 用 fake timers 控制 setTimeout
- **涉及**: `src/components/MessageBubble.tsx`（useEffect + setTimeout）

### 分组 C · useWebSocket Bug 修复（TC-031 ~ TC-033）

#### TC-031: message_edited 帧读取 new_content（Bug 修复验证）
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P0（回归门禁）
- **步骤**:
  1. 连接并握手
  2. addMessage `{ id:'orig', content:'占位' }`
  3. `pushFrame({ type:'message_edited', payload:{ message_id:'orig', new_content:'真实内容', sequence_number:2 } })`
- **预期**: `messages[0].content === '真实内容'`（而非空/undefined）
- **说明**: 此 TC 在修复前会失败，修复后通过
- **涉及**: `src/hooks/useWebSocket.ts`

#### TC-032: message 帧含 is_placeholder=true → addMessage isStreaming=true
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 握手后推送 `{ type:'message', payload:{ message:{ id:'ph1', content:'…', metadata:{ is_placeholder:true }, ... }, source_display:{role:'agent'} } }`
- **预期**: `messages[0].isStreaming === true`
- **涉及**: `src/hooks/useWebSocket.ts`

#### TC-033: message 帧不含 is_placeholder → isStreaming=false（默认）
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P1
- **步骤**: 推正常 message 帧（无 metadata 或 `is_placeholder:false`）
- **预期**: `messages[0].isStreaming === false`（或 `undefined`，视实现）
- **涉及**: `src/hooks/useWebSocket.ts`

### 分组 D · 端到端占位→续写流程（TC-034 ~ TC-038）

#### TC-034: 占位消息到达 → 光标动画可见
- **文件**: `integration.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 握手后 pushFrame 占位 message（`is_placeholder:true`，content:'正在查询…'）
  2. render App
- **预期**: `getByTestId('streaming-cursor')` 存在；`getByText('正在查询…')` 存在
- **涉及**: `App.tsx` → `MessageBubble`

#### TC-035: message_edited 到达 → 光标消失，内容原地更新
- **文件**: `integration.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 推占位 message（id='ph1'）
  2. 推 `message_edited`（message_id='ph1', new_content='套餐价格是 199 元'）
- **预期**:
  - `queryByTestId('streaming-cursor') === null`
  - `getByText('套餐价格是 199 元')` 存在
  - `queryByText('正在查询…') === null`（旧内容消失）
- **涉及**: `useWebSocket.ts`（分发）→ `store.updateMessage`

#### TC-036: message_edited 到达 → 短暂出现高亮 class
- **文件**: `integration.test.tsx`
- **优先级**: P1
- **步骤**:
  1. 推占位 → 推 edited
  2. 立即断言（不推进 timer）
- **预期**: 含 `ring-2` class 的元素存在
- **涉及**: `MessageBubble.tsx`

#### TC-037: 500ms 后高亮 class 消失
- **文件**: `integration.test.tsx`
- **优先级**: P1
- **步骤**:
  1. `vi.useFakeTimers()`
  2. 推占位 → 推 edited
  3. `vi.advanceTimersByTime(500)`
- **预期**: `queryAllByText` 中不含 `ring-2` class
- **涉及**: `MessageBubble.tsx`（clearJustEdited）

#### TC-038: 无占位标记的普通消息不触发 streaming 状态
- **文件**: `integration.test.tsx`
- **优先级**: P1
- **步骤**: 推普通 agent message（无 metadata）
- **预期**: `queryByTestId('streaming-cursor') === null`；消息正常渲染
- **涉及**: `useWebSocket.ts`

---

## 统计

| 指标 | 值 |
|---|---|
| 新增用例 | 16 |
| 原有用例（保留） | 42 |
| 目标总数 | **58/58** |
| P0 | 12 |
| P1 | 4 |
| Bug 修复 gate | TC-031（`new_content` 字段名） |

## Skill 3 实现约束

1. **`initialState` 必须包含新字段默认值**（否则测试 reset 不完整）：`isStreaming` 和 `justEdited` 不在 initialState（它们是 per-message 字段，在 ChatMessage interface 中可选）
2. **fake timer 隔离**：TC-030 / TC-037 用 `vi.useFakeTimers()` + `afterEach(() => vi.useRealTimers())`；不影响其他 TC
3. **TC-031 是 Bug 修复回归 gate**：若修复未完成，此 TC 必失败 → 不允许跳过
4. **不得破坏原有 42 个测试**
5. **MessageBubble 中 useEffect 依赖数组**必须是 `[message.justEdited, message.id]`，防止过度触发
