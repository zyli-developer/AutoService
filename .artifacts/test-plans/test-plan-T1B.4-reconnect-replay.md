---
type: test-plan
id: test-plan-006
status: confirmed
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-doc-007 (T1B.4 断线重连 + 消息回放) — confirmed"
related:
  - eval-doc-007
  - "contract:docs/contracts/frontend-ws-schema.md §3.3 §3.4 F3 F13 S9 S12"
  - "task:T1B.4"
decisions_frozen:
  D1: "游标存 sessionStorage；try/catch 静默降级"
  D2: "消息 ID 去重（addMessageDedup）"
  D3: "每个 event 帧收到后立即发 client_ack"
  D4: "4041_REPLAY_GAP → history_request since_sequence:0 limit:50"
  D5: "wasReconnect 用 useRef 跨 onClose/onOpen 传递"
  TypeFix: "ClientHelloPayload.last_seen: string → LastSeenCursor"
---

# Test Plan: T1B.4 断线重连 + 消息回放

## 触发原因

eval-doc-007 定义了 7 个文件变更（含 ws-client 类型修正）。
本 plan 共 **24 个用例**，覆盖：游标工具函数、store 扩展、
WSClient 类型修正、hook 完整重连逻辑、ConnectionBanner 新状态、
端到端重连+回放流程。

## 测试文件规划

```
src/__tests__/
  lastSeenCursor.test.ts      新建 (TC-039~043)
  chatStore.test.ts           扩展 (TC-044~047，原有 11 个保留)
  ConnectionBanner.test.tsx   扩展 (TC-048~050，原有 2 个保留)
  useWebSocket.test.tsx       扩展 (TC-051~056，原有 8 个保留)
  integration.test.tsx        扩展 (TC-057~062，原有 8 个保留)
```

目标：原有 58 + 新增 24 = **82/82 全绿**。

---

## 用例列表

### 分组 A · lastSeenCursor 工具（TC-039 ~ TC-043）

#### TC-039: saveCursor / loadCursor 往返正确
- **文件**: `lastSeenCursor.test.ts`
- **优先级**: P0
- **步骤**:
  1. `saveCursor({ conv_seq: { 'cv1': { msg: 5, evt: 12 } } })`
  2. `const got = loadCursor()`
- **预期**: `got.conv_seq?.cv1?.msg === 5 && got.conv_seq?.cv1?.evt === 12`
- **涉及**: `src/utils/lastSeenCursor.ts`

#### TC-040: loadCursor 无数据时返回 null
- **文件**: `lastSeenCursor.test.ts`
- **优先级**: P0
- **步骤**: 清空 sessionStorage，`loadCursor()`
- **预期**: `null`

#### TC-041: updateConvCursor 单调推进 msg
- **文件**: `lastSeenCursor.test.ts`
- **优先级**: P0
- **步骤**:
  1. `let c = updateConvCursor({}, 'cv1', 'msg', 10)`
  2. `c = updateConvCursor(c, 'cv1', 'msg', 8)`（回退）
  3. `c = updateConvCursor(c, 'cv1', 'msg', 15)`（前进）
- **预期**: `c.conv_seq?.cv1?.msg === 15`（回退被忽略）

#### TC-042: updateConvCursor 不同 conv_id 独立
- **文件**: `lastSeenCursor.test.ts`
- **优先级**: P1
- **步骤**:
  1. `let c = updateConvCursor({}, 'cv1', 'msg', 5)`
  2. `c = updateConvCursor(c, 'cv2', 'msg', 3)`
- **预期**: `cv1.msg === 5 && cv2.msg === 3`（互不影响）

#### TC-043: saveCursor 在 sessionStorage 不可用时静默不抛
- **文件**: `lastSeenCursor.test.ts`
- **优先级**: P1
- **步骤**: `vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('QuotaExceeded') })`; 调 `saveCursor(...)`
- **预期**: 不抛，正常返回

### 分组 B · Store 扩展（TC-044 ~ TC-047）

#### TC-044: addMessageDedup 跳过已有 id
- **文件**: `chatStore.test.ts`
- **优先级**: P0
- **步骤**:
  1. `addMessageDedup({ id:'dup', content:'first', ... })`
  2. `addMessageDedup({ id:'dup', content:'second', ... })`
- **预期**: `messages.length === 1 && messages[0].content === 'first'`

#### TC-045: addMessageDedup 不同 id 均追加
- **文件**: `chatStore.test.ts`
- **优先级**: P0
- **步骤**: `addMessageDedup({id:'a',...})` 然后 `addMessageDedup({id:'b',...})`
- **预期**: `messages.length === 2`

#### TC-046: setReplaying / setReplayCount 更新 store
- **文件**: `chatStore.test.ts`
- **优先级**: P0
- **步骤**:
  1. `setReplaying(true)` → `isReplaying === true`
  2. `setReplayCount(7)` → `replayCount === 7`
  3. `setReplaying(false)` → `isReplaying === false`

#### TC-047: updateCursor 存入 store
- **文件**: `chatStore.test.ts`
- **优先级**: P0
- **步骤**: `updateCursor({ conv_seq: { 'cv1': { msg: 3, evt: 9 } } })`
- **预期**: `lastSeenCursor.conv_seq?.cv1?.msg === 3`

### 分组 C · ConnectionBanner 扩展（TC-048 ~ TC-050）

#### TC-048: isReplaying=true 显示"回放中"banner
- **文件**: `ConnectionBanner.test.tsx`
- **优先级**: P0
- **步骤**: `render(<ConnectionBanner status="open" isReplaying={true} replayCount={5} />)`
- **预期**: `getByTestId('connection-banner')` 存在；文本含 "5" 或 "同步" / "Sync"
- **涉及**: `src/components/ConnectionBanner.tsx`

#### TC-049: isReplaying=false + status=open → 无 banner
- **文件**: `ConnectionBanner.test.tsx`
- **优先级**: P0
- **步骤**: `render(<ConnectionBanner status="open" isReplaying={false} />)`
- **预期**: `queryByTestId('connection-banner') === null`

#### TC-050: isReplaying=true 优先于 status=closed（回放中不显示断线）
- **文件**: `ConnectionBanner.test.tsx`
- **优先级**: P1
- **步骤**: `render(<ConnectionBanner status="closed" isReplaying={true} />)`
- **预期**: banner 文本含"同步"/"回放"，不含"断线"/"lost"
- **说明**: 回放期间连接已恢复，显示"同步中"比"断线"更准确

### 分组 D · useWebSocket hook 扩展（TC-051 ~ TC-056）

#### TC-051: 收到 event 帧后自动发 client_ack
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 握手后 `pushFrame({ type:'event', payload:{ event:{ id:'evt-1', type:'conversation.created', conversation_id:'cv1', sequence_number:1 } } })`
- **预期**: `fakeInstance.sendCalls` 包含 `{ type:'client_ack', payload:{ event_id:'evt-1' } }`

#### TC-052: 收到 message 帧后游标 msg 单调推进并存 sessionStorage
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 握手后推 `type:'message'`，`payload.message.sequence_number=5`，`payload.conversation_id='cv1'`
  2. 调 `loadCursor()`（从 sessionStorage 读）
- **预期**: `cursor.conv_seq?.cv1?.msg === 5`

#### TC-053: 收到 replay_complete 帧 → isReplaying=false, replayCount 更新
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P0
- **步骤**: 先 `store.setReplaying(true)`，再 `pushFrame({ type:'replay_complete', payload:{ count:7 } })`
- **预期**: `isReplaying === false && replayCount === 7`

#### TC-054: 收到 error code=4041_REPLAY_GAP → 发 history_request
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P0
- **步骤**: 握手后 `pushFrame({ type:'error', payload:{ code:'4041_REPLAY_GAP', recoverable:true } })`
- **预期**: `fakeInstance.sendCalls` 包含 `{ type:'history_request', payload:{ conversation_id: expect.any(String), since_sequence:0, limit:50 } }`（或 conversation_id 为 null/store 中当前值）

#### TC-055: 收到 history_snapshot → addMessageDedup 批量插入（去重）
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P0
- **步骤**:
  1. store 预存 `{ id:'m-exist', ... }`
  2. `pushFrame({ type:'history_snapshot', payload:{ messages:[{id:'m-exist',...},{id:'m-new',...}] } })`
- **预期**: `messages.length === 2`（m-exist 不重复，m-new 新增）

#### TC-056: WSClient 收到结构化 lastSeen 传入 client_hello
- **文件**: `useWebSocket.test.tsx`
- **优先级**: P1
- **步骤**: 预先在 sessionStorage 存入游标 `{ conv_seq:{ cv1:{msg:3,evt:5} } }`，`renderHook(() => useWebSocket(...))`
- **预期**: `fakeInstance.opts.lastSeen` 等于该游标对象（结构化，非字符串）

### 分组 E · 端到端重连+回放（TC-057 ~ TC-062）

#### TC-057: 断线后 ConnectionBanner 显示"重连中"
- **文件**: `integration.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 握手成功后 `fakeInstance.pushClose(4499, 'server_error')`
- **预期**: `getByTestId('connection-banner')` 存在，文本含"重连"/"Reconnecting"

#### TC-058: 重连握手后 isReplaying=true，banner 变为"同步中"
- **文件**: `integration.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 断线后 `fakeInstance2.triggerOpen()`（模拟第二个 WSClient 实例握手）
- **预期**: `isReplaying === true`；banner 文本含"同步"

#### TC-059: replay_complete 后 banner 消失（实时状态）
- **文件**: `integration.test.tsx`
- **优先级**: P0
- **步骤**: 推 `replay_complete { count:3 }`
- **预期**: `queryByTestId('connection-banner') === null`

#### TC-060: 回放消息不产生重复气泡（id 去重）
- **文件**: `integration.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 推普通 message（id='m1'）→ 出现气泡
  2. 断线重连后推同一 message（id='m1'，回放）
- **预期**: 页面上"m1"内容只出现一次

#### TC-061: 4041_REPLAY_GAP 触发 history_request 并渲染历史消息
- **文件**: `integration.test.tsx`
- **优先级**: P1
- **步骤**:
  1. 推 `error { code:'4041_REPLAY_GAP' }`
  2. 确认 `sendCalls` 含 `history_request`
  3. 推 `history_snapshot { messages:[{id:'hist-1',...}] }`
- **预期**: `getByText(hist-1的内容)` 存在

#### TC-062: 正常断线（code=1000）不触发重连，无 banner
- **文件**: `integration.test.tsx`
- **优先级**: P1
- **步骤**: `fakeInstance.pushClose(1000, 'normal')`
- **预期**: `connectionStatus === 'closed'`；WSClient 未尝试重连（`sendCalls` 无新 client_hello）；banner 可见"断线"但无"重连中"

---

## 统计

| 指标 | 值 |
|---|---|
| 新增用例 | 24 |
| 原有用例（保留） | 58 |
| 目标总数 | **82/82** |
| P0 | 18 |
| P1 | 6 |
| 新建测试文件 | 1（lastSeenCursor.test.ts）|
| 扩展测试文件 | 4 |

## Skill 3 实现约束

1. **ws-client 修改范围**：仅改 `types.ts`（`LastSeenCursor` 类型 + `ClientHelloPayload.last_seen`）和 `client.ts`（`WSClientOptions.lastSeen` 类型 + 消除 TODO 注释）；不改其他逻辑
2. **FakeWSClient 扩展**：需支持捕获 `send('client_ack', ...)` 调用（已有 `sendCalls`，无需改动）
3. **TC-058 多实例问题**：断线重连时 `useWebSocket` 内部会 `new WSClient` 产生第二个实例；测试中通过 `fakeInstance` 变量更新捕获新实例，或使用 `vi.mock` 的实例数组
4. **sessionStorage 隔离**：每个测试 `beforeEach` 清空 `sessionStorage.clear()`，避免游标污染
5. **`initialState` 新增字段**：`isReplaying:false`, `replayCount:0`, `lastSeenCursor:{}`，确保 reset 有效
6. **`history_snapshot` 消息字段映射**：与 `message` 帧的 `message` 字段同格式（id/source/content/visibility/sequence_number/timestamp）；`source_display` 可能缺失，需默认值处理
7. **不得破坏原有 58 个测试**
