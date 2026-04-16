# eval-doc-007 · T1B.4 断线重连 + 消息回放

> **Mode**: simulate · **Owner**: DevB · **Date**: 2026-04-16

---

## 1. 任务目标

实现客户端 WS 断线后的完整恢复流程（β1），覆盖：

| 子功能 | 说明 |
|---|---|
| **自动重连** | WSClient 已有指数退避，T1B.4 补全 `last_seen` 游标传递 |
| **消息回放** | 重连时携带游标 → BE 补发缺失帧 → UI 无缝接续 |
| **重放去重** | 回放帧与本地已有消息按 sequence_number 去重，不产生重复气泡 |
| **`client_ack`** | 收到 `event` 帧后发 `client_ack { event_id }` 推进 BE per-sub cursor |
| **4041 降级** | 游标落点外 → `history_request` 全量拉取 |
| **回放 UI** | ConnectionBanner 新增"回放中"状态；`replay_complete` 后切回"实时" |

**关联契约**：frontend-ws-schema.md §3.3 / §3.4 / F3 / F13 / S9 / S12

---

## 2. 现有代码分析

### 2.1 WSClient 已有能力

| 功能 | 状态 |
|---|---|
| 指数退避自动重连 | ✅ `scheduleReconnect()` |
| `lastSeen` 选项 | ✅ 但类型为 `string`，不符合契约 §3.3 结构化对象格式 |
| `client_hello` 含 `last_seen` | ✅ 但传递原始字符串，需改为结构化对象 |
| ack 机制 (`pendingAcks`) | ✅ |
| `client_ack` 帧类型 | ✅ 在 `FE_TO_BE_TYPES` 中，但从未自动发送 |

### 2.2 T1B.4 标记的 TODO

WSClient 中显式标注：
```typescript
// TODO(T1B.4): 断线重连时根据 `last_seen` 发 client_hello 做消息回放
// TODO(T1B.4): per-subscription cursor 推进（收到 event 后主动 client_ack）
```

### 2.3 缺失（T1B.4 新增）

| 缺口 | 位置 |
|---|---|
| `LastSeenCursor` 结构化类型 | `ws-client/src/types.ts` |
| `WSClientOptions.lastSeen` 类型修正 | `ws-client/src/client.ts` |
| 游标追踪（msg/evt sequence） | `useWebSocket.ts` |
| 游标持久化（sessionStorage） | `utils/lastSeenCursor.ts` (NEW) |
| `client_ack` 自动发送 | `useWebSocket.ts` |
| `replay_complete` 处理 | `useWebSocket.ts` + store |
| `4041_REPLAY_GAP` → `history_request` | `useWebSocket.ts` |
| `history_snapshot` → store dedup | `useWebSocket.ts` + store |
| 消息去重（sequence_number） | `store/chatStore.ts` |
| 回放 UI 状态 | `store/chatStore.ts` + `ConnectionBanner.tsx` |

---

## 3. 架构设计

### 3.1 LastSeenCursor 结构（§3.3）

```typescript
// ws-client/src/types.ts (新增)
export interface LastSeenCursor {
  conv_seq?: Record<string, { msg: number; evt: number }>;
  global_event_id?: string;  // operator/admin only
}

// ClientHelloPayload.last_seen 类型从 string → LastSeenCursor
export interface ClientHelloPayload {
  protocol_version: number;
  client_app: string;
  last_seen?: LastSeenCursor;  // ← 修正
  conversation_id?: string;
  operator_id?: string;
  squads?: string[];
}
```

WSClientOptions 同步修正：
```typescript
lastSeen?: LastSeenCursor;  // was: string
```

### 3.2 游标持久化（sessionStorage）

```typescript
// src/utils/lastSeenCursor.ts (NEW)
const STORAGE_KEY = 'as_last_seen';

export function saveCursor(cursor: LastSeenCursor): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(cursor));
  } catch { /* quota error — ignore */ }
}

export function loadCursor(): LastSeenCursor | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

export function updateConvCursor(
  cursor: LastSeenCursor,
  convId: string,
  field: 'msg' | 'evt',
  seq: number,
): LastSeenCursor {
  const prev = cursor.conv_seq?.[convId]?.[field] ?? 0;
  if (seq <= prev) return cursor;  // 仅单调推进
  return {
    ...cursor,
    conv_seq: {
      ...cursor.conv_seq,
      [convId]: { ...cursor.conv_seq?.[convId], [field]: seq },
    },
  };
}
```

### 3.3 Store 扩展

```typescript
// 新增字段
interface ChatState {
  // ...现有
  isReplaying: boolean;
  replayCount: number;       // 回放收到的消息数（UI 显示）
  lastSeenCursor: LastSeenCursor;

  // 新增 actions
  setReplaying: (v: boolean) => void;
  setReplayCount: (n: number) => void;
  updateCursor: (cursor: LastSeenCursor) => void;
  addMessageDedup: (msg: ChatMessage) => void;  // 按 id 去重的 addMessage
}
```

**`addMessageDedup`**：
```typescript
addMessageDedup: (msg) =>
  set((state) => {
    // 已有相同 id → skip
    if (state.messages.some(m => m.id === msg.id)) return state;
    return { messages: [...state.messages, msg] };
  }),
```

**`initialState` 新增**：
```typescript
isReplaying: false,
replayCount: 0,
lastSeenCursor: {},
```

### 3.4 useWebSocket.ts 扩展

重构 hook，管理完整重连生命周期：

```
mount
  → loadCursor() from sessionStorage
  → new WSClient({ lastSeen: cursor })
  → setConnectionStatus('connecting')

onOpen(hello)
  → setConnectionStatus('open')
  → if (wasReconnect) setReplaying(true)

onFrame
  → 'message'       → updateConvCursor(msg) + saveCursor + addMessageDedup
  → 'event'         → updateConvCursor(evt) + saveCursor + send client_ack
  → 'replay_complete' → setReplaying(false), setReplayCount(count)
  → 'history_snapshot' → bulk addMessageDedup (dedup by id)
  → 'error' code=4041_REPLAY_GAP
                    → setReplaying(false)
                    → send history_request { conversation_id, since_sequence: 0 }

onClose
  → setConnectionStatus('closed')
  → isReplaying stays until reconnect completes
```

**`wasReconnect` 판단**：`reconnectAttempt > 0` 시 재연결. Hook 내부에서 `const wasReconnectRef = useRef(false)` 사용.

实际实现：hook 内用 `useRef` 记录 cursor，每次 frame 到达时同步更新 ref + store + sessionStorage。

### 3.5 ConnectionBanner 扩展

```tsx
// 现有: 'closed' → "Connection lost", 'connecting' → "Reconnecting..."
// 新增: isReplaying=true → "正在恢复消息..." / "Syncing messages..."

interface ConnectionBannerProps {
  status: 'idle' | 'connecting' | 'open' | 'closed';
  isReplaying?: boolean;
  replayCount?: number;
}

// 渲染逻辑
if (isReplaying) → banner: "正在恢复消息..." (amber 色调，区别于红色断线)
if (status === 'closed') → banner: "连接中断" (red)
if (status === 'connecting') → banner: "重新连接中..." (amber)
otherwise → null
```

### 3.6 App.tsx 微调

将 `isReplaying` / `replayCount` 从 store 取出，传给 `ConnectionBanner`：
```tsx
const { messages, connectionStatus, isReplaying, replayCount } = useChatStore();
// ...
<ConnectionBanner status={connectionStatus} isReplaying={isReplaying} replayCount={replayCount} />
```

---

## 4. 关键设计决策

### D1. 游标存储位置：sessionStorage vs store-only

**决策**：**sessionStorage + store 双写**。
- sessionStorage 在同 tab 内跨重连持久（网络断开重连场景 ✓）
- 不用 localStorage，避免多 tab 间 cursor 污染
- 页面完全刷新时游标从 sessionStorage 恢复，仍可触发回放

### D2. 消息去重策略：ID 去重 vs sequence_number 去重

**决策**：**消息 ID 去重**（`addMessageDedup`）。
- sequence_number 在多对话场景下不唯一（per-conversation 单调）；用 id 更安全
- 同一消息正常推送 + 回放推送时 id 相同 → 自动跳过

### D3. client_ack 发送时机：每帧 vs 批量

**决策**：**每个 `event` 帧收到后立即发** `client_ack { event_id }`。
- 契约 F3 对应"标记前端已消费"语义
- `message` 帧不需要 client_ack（§3.2 明确 ping/pong/ack 本身不再 ack；message 帧的 sequence_number 通过 last_seen 游标推进已足够）

### D4. `4041_REPLAY_GAP` 后的 history_request 粒度

**决策**：`since_sequence: 0`（全量）+ `limit: 50`（最近 50 条）。
- 简单兜底：不知道丢了多少，拉最近 50 条足够
- 产品逻辑：用户只关心近期消息，超长历史不渲染

### D5. wasReconnect 判断

**决策**：首次连接不触发 `isReplaying` UI；重连时（onClose 后的 onOpen）才触发。
- 用 `const reconnectRef = useRef(false)` 在 `onClose` 时设为 true，在下次 `onOpen` 读取后重置

---

## 5. 与契约的对齐检查

| 契约条款 | 实现对照 |
|---|---|
| §3.3 `last_seen` 结构化对象 | `LastSeenCursor` 类型 + `ClientHelloPayload` 修正 ✓ |
| §3.3 conv scope 回放 | `conv_seq[id].{msg,evt}` 游标追踪 ✓ |
| §3.3 `4041_REPLAY_GAP` → 全量重拉 | `history_request + since_sequence:0` ✓ |
| §3.4 close code 1000 → 不重连 | WSClient 已有 `closedByUser` 判断 ✓ |
| §3.4 4499/4408 → 重连 | WSClient 已有 `scheduleReconnect` ✓ |
| F3 `client_ack { event_id }` | 每个 event 帧收到后发送 ✓ |
| F13 `history_request` | 4041 降级时发送 ✓ |
| S9 `history_snapshot` | `addMessageDedup` 批量插入 ✓ |
| S12 `replay_complete` | `setReplaying(false)` + banner 切换 ✓ |

---

## 6. 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| BE（T0.5 骨架）`replay_complete` 尚未实现 | 中 | FakeWSClient 模拟；M1 联调验证 |
| sessionStorage 在隐私模式下可能抛 SecurityError | 低 | `try/catch` 静默降级 |
| `client_ack` 发送量大（每个 event 一条） | 低 | customer 端 event 数量少；operator 端 T2 再优化 |
| `addMessageDedup` 线性扫描在大消息列表下低效 | 低 | T1B.4 消息数 < 100；T2+ 可优化为 Set<id> |

---

## 7. 不在范围

- 完整页面刷新后的历史消息渲染（T1B.4 目标是网络断线重连，不是冷启动）
- operator/admin `global_event_id` ULID 游标（T2B.1 实现）
- `history_request` 分页加载（T1B.4 用单次 limit:50 兜底）
- 重连时 token 刷新（close code 4001）

---

## 8. 产出清单

| # | 文件 | 动作 | 说明 |
|---|---|---|---|
| 1 | `packages/ws-client/src/types.ts` | **修正** | 新增 `LastSeenCursor`；`ClientHelloPayload.last_seen` 类型改为 `LastSeenCursor` |
| 2 | `packages/ws-client/src/client.ts` | **修正** | `WSClientOptions.lastSeen` 改为 `LastSeenCursor`；消除 TODO(T1B.4) 注释 |
| 3 | `src/utils/lastSeenCursor.ts` | **新建** | sessionStorage read/write + `updateConvCursor` |
| 4 | `src/store/chatStore.ts` | **扩展** | `isReplaying`、`replayCount`、`lastSeenCursor`；`addMessageDedup`；`setReplaying`、`setReplayCount`、`updateCursor` |
| 5 | `src/hooks/useWebSocket.ts` | **扩展** | 游标追踪 + `client_ack` + `replay_complete` + `history_snapshot` + `4041_REPLAY_GAP` |
| 6 | `src/components/ConnectionBanner.tsx` | **扩展** | `isReplaying` prop + "正在恢复消息..." 状态 |
| 7 | `src/App.tsx` | **微调** | 向 ConnectionBanner 传 `isReplaying` / `replayCount` |

---

*eval-doc-007 · T1B.4 · simulate · 待 review*
