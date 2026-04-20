# Takeover Release Design — Manual & Automatic AI Restore

**Date:** 2026-04-17
**Author:** brainstorming session
**Status:** approved — ready for implementation plan

## 1. Overview & Scope

Operator 通过 `/hijack` 命令接管对话后，当前没有把对话交回 AI 的路径，容易让对话卡在 TAKEOVER 模式。本设计提供一条**手动**和两条**自动**的释放路径。

### In scope

1. **手动释放**：Hijack 按钮变成双态——空闲时显示"抢单"（发 `/hijack`），接管中显示"释放回 AI"（发 `/release`）。
2. **静默自动释放**：TAKEOVER 期间，归属 operator 连续 N 秒（默认 30s）未发 message → 切回 **COPILOT**，trigger=`auto:idle_timeout`。
3. **离线自动释放**：归属 operator 的 WS 断开超过 M 秒（默认 30s 宽限期）→ 切回 **AUTO**，trigger=`auto:operator_offline`。
4. **静默预警**：自动释放前 5s 发 `takeover_warning` 帧。归属 operator 点「继续接管」或发消息 → 重置 timer、发 `takeover_warning_cancelled`。
5. **配置化**：idle 超时、预警时长、offline 宽限期从 `.autoservice/config.local.yaml` 读取，缺失时回落到硬编码默认。

### Out of scope（另起 feature）

- **对话排他锁**：engine 当前不校验"认领人"，多 operator 同时 `/hijack` 的冲突处理留待后续。
- **客户侧通知**：自动释放时给客户发"正在回到 AI"系统消息。
- **Dashboard 埋点**：auto-release 次数/原因统计。
- **Timer 跨重启持久化**：gateway 重启后进行中的 TAKEOVER 对话其 idle timer 丢失，operator 可手动释放。

### 成功标准

- Hijack 后静默 30s → 25s 时收到 `takeover_warning` → 不响应再 5s → 对话模式变 COPILOT，`mode.changed` 事件 `trigger=auto:idle_timeout`。
- Hijack 后关闭 operator 标签页 → WS 断开 30s 后，对话模式变 AUTO，`trigger=auto:operator_offline`。
- Operator 点"释放回 AI"按钮 → 立即切 AUTO，`trigger=/release`。
- 所有释放路径都能被 `/hijack` 再次逆转（reversible）。

## 2. Backend Architecture

### 2.1 核心变更点

| 位置 | 内容 |
|---|---|
| `autoservice/conversation_engine/types.py` Conversation dataclass | 新增 `takeover_operator_id: str \| None = None` |
| `autoservice/conversation_engine/local_engine.py` `switch_mode` | 新增 kwarg `takeover_operator_id: str \| None = None`；锁内原子更新 conv.mode + conv.takeover_operator_id（进入 TAKEOVER 时赋值 actor，离开 TAKEOVER 时清零）；在 emit `mode.changed` 事件 data 中包含 `takeover_operator_id`（takeover 时 = 归属人，其他 mode = null） |
| `local_engine.py` `handle_command("/hijack")` | 调 `switch_mode(TAKEOVER, takeover_operator_id=actor_id)`；switch_mode 返回后 arm idle timer |
| `local_engine.py` `handle_command("/release" \| "/copilot")` 与 `close_conversation` | 调 switch_mode 前先 `_cancel_idle_release_timer`（switch_mode 自动清零 `takeover_operator_id`） |
| `local_engine.py` `send_message` | 若 `conv.mode == TAKEOVER` 且 `source == conv.takeover_operator_id`，调 `_reset_idle_release_timer` |
| `autoservice/gateway/message_router.py` `_process_frame` | 新增 `client_ack` 的 `action="continue"` 分支：调 engine 的 reset API |
| `local_engine.py` LocalEngine `__init__` | 接收 `takeover_config: dict` 参数（idle_timeout_ms, warning_ms） |
| **新增** `autoservice/gateway/offline_watcher.py` | 跟踪 operator 在线/离线；per-operator 宽限期 timer；离线到期时调 engine.switch_mode(AUTO) |
| `autoservice/web_gateway.py` create_app | 加载 config.local.yaml 的 `takeover` 段；实例化 OfflineWatcher 并挂到 app.state |
| `web_gateway.py` `_handle_connection` finally | operator 断开时调 `offline_watcher.on_disconnect(operator_id)`；开始时（client_hello 带 operator_id）调 `on_connect` |

### 2.2 Idle release timer（静默超时）

复用 engine 现有 `Timer` + `_dispatch_on_expire` 框架。进入 TAKEOVER 时注册两个级联 timer：

```
Timer(name="takeover_warning_<conv>", duration=idle_timeout_ms - warning_ms=25000ms)
  on_expire:
    1. push BE→FE "takeover_warning" 帧到归属 operator 的 WS
    2. arm 下一个 timer
Timer(name="takeover_release_<conv>", duration=warning_ms=5000ms)
  on_expire: switch_mode(conv, COPILOT, trigger="auto:idle_timeout")
```

重置逻辑（`_reset_idle_release_timer`）：
- cancel 两个 timer
- 若刚才 warning 已 push → 再 push `takeover_warning_cancelled` 帧
- 重新 arm

触发重置的事件：
- 归属 operator 发 message（`send_message` 里判断）
- 归属 operator 发 `client_ack(action=continue)`
- 再次 `/hijack` 同一对话

### 2.3 Offline watcher

独立模块（非 engine Timer），因为离线检测是 gateway 层关心的事；一个 operator 可能盯多个对话，应 per-operator 统一管理。

```python
# autoservice/gateway/offline_watcher.py (skeleton)
class OfflineWatcher:
    def __init__(self, engine, grace_ms: int):
        self._engine = engine
        self._grace_ms = grace_ms
        self._online: set[str] = set()            # operator_id
        self._pending: dict[str, asyncio.Task] = {}  # operator_id → grace task

    def on_connect(self, operator_id: str):
        self._online.add(operator_id)
        task = self._pending.pop(operator_id, None)
        if task and not task.done():
            task.cancel()

    def on_disconnect(self, operator_id: str):
        self._online.discard(operator_id)
        self._pending[operator_id] = asyncio.create_task(
            self._grace(operator_id), name=f"offline-grace-{operator_id}")

    async def _grace(self, operator_id: str):
        try:
            await asyncio.sleep(self._grace_ms / 1000)
        except asyncio.CancelledError:
            return
        if operator_id in self._online:
            return  # reconnected
        # find all conversations where this operator is the takeover_operator_id
        for conv in self._engine.list_conversations_in_takeover_by(operator_id):
            await self._engine.switch_mode(
                conv.id, ConversationMode.AUTO,
                triggered_by="__system__",
                trigger="auto:operator_offline",
            )
```

Engine 需新增辅助方法 `list_conversations_in_takeover_by(operator_id)` 扫描 `_conversations`。

### 2.4 新增 BE→FE 帧

```json
// takeover 即将自动释放时推送给归属 operator
{
  "v": 1,
  "type": "takeover_warning",
  "id": "<frame_id>",
  "ts": "<iso>",
  "payload": {
    "conversation_id": "web_cust_xxx",
    "remaining_ms": 5000,
    "reason": "idle"
  }
}

// 重置后清除 UI 横幅
{
  "v": 1,
  "type": "takeover_warning_cancelled",
  "id": "<frame_id>",
  "ts": "<iso>",
  "payload": {
    "conversation_id": "web_cust_xxx"
  }
}
```

### 2.5 FE→BE 帧复用

使用已有 `client_ack` 帧：
```json
{
  "v": 1,
  "type": "client_ack",
  "id": "...",
  "payload": {
    "ref_frame_id": "<takeover_warning 的 id>",
    "action": "continue",
    "conversation_id": "web_cust_xxx"
  }
}
```
`message_router._process_frame` 新增分支识别 `payload.action == "continue"`，调 engine 重置 timer。

### 2.6 Config

在 `.autoservice/config.local.yaml.example` 增加：

```yaml
# ─── Takeover（接管/释放）配置 ─────────────────────────
takeover:
  idle_timeout_ms: 30000      # /hijack 后静默多久触发自动释放
  warning_ms: 5000            # 预警阶段长度（warning → release 缓冲）
  offline_grace_ms: 30000     # operator WS 断开多久算真正离线
```

**加载路径**：`web_gateway.create_app` 用 `socialware.config.load_config(Path(".autoservice/config.local.yaml"))`。文件不存在或字段缺失 → 回落到硬编码默认（和 example 一致）。

**传递路径**：
- LocalEngine `__init__` 新增 `takeover_config: dict` 参数 → idle timer 使用
- OfflineWatcher `__init__` 收 `grace_ms: int`

## 3. Frontend Architecture

### 3.1 HijackButton 双态

`frontend/apps/operator-console/src/components/HijackButton.tsx`：

```tsx
const mode = useOperatorStore((s) => s.conversations[conversationId]?.mode);

if (mode === 'takeover') {
  // 释放按钮
  text = '释放回 AI';
  testId = `btn-release-${conversationId}`;
  command = '/release';
  variant = 'default'; // 非 danger
} else {
  // 抢单按钮
  text = '抢单';
  testId = `btn-hijack-${conversationId}`;
  command = '/hijack';
  variant = 'primary danger';
}
```

保留原文件名 `HijackButton.tsx`（逻辑内分支），避免引用面大改动。

### 3.2 TakeoverWarning 组件（新增）

`frontend/apps/operator-console/src/components/TakeoverWarning.tsx`：
- 订阅 `useOperatorStore` 中当前对话的 `takeoverWarning` 字段
- 仅在 `takeover_operator_id === 当前 operatorId`（store 推导）且 `takeoverWarning` 不为空时渲染
- 样式：inline 顶部横幅（参考 `ConnectionBanner`），**不用 modal**（避免打断正在打字）
- 倒计时显示剩余秒数（client-side setInterval 从 remaining_ms 递减）
- 两个 action：
  - **继续接管**：发 `client_ack(action="continue", ref_frame_id=warning_frame_id)`
  - **释放**：发 `operator_command /release`

Operator 在 IMInput 发任意消息 → 前端无需额外处理；后端 `send_message` 触发 timer reset，主动 push `takeover_warning_cancelled`，组件订阅后自动隐藏。

### 3.3 useOperatorWS 帧处理追加

`hooks/useOperatorWS.ts` 的 `onFrame` 回调：
```typescript
if (frame.type === 'takeover_warning') {
  const p = frame.payload as any;
  useOperatorStore.getState().setTakeoverWarning(p.conversation_id, {
    remainingMs: p.remaining_ms,
    reason: p.reason,
    warningFrameId: frame.id,
    armedAt: new Date().toISOString(),
  });
}
if (frame.type === 'takeover_warning_cancelled') {
  const p = frame.payload as any;
  useOperatorStore.getState().clearTakeoverWarning(p.conversation_id);
}
```

### 3.4 Store 变更

`operatorStore.ts`：

```typescript
interface TakeoverWarning {
  remainingMs: number;
  reason: 'idle';
  warningFrameId: string;
  armedAt: string;
}
interface Conversation {
  // existing...
  mode: 'auto' | 'copilot' | 'takeover';  // 已有
  takeoverOperatorId?: string;             // 新增（从 mode.changed 事件 data 里吸收）
  takeoverWarning?: TakeoverWarning;       // 新增
}
// actions
setTakeoverWarning(convId, warning): void
clearTakeoverWarning(convId): void
```

`handleEventFrame` 中 `mode.changed` 的分支：从 `event.data.takeover_operator_id`（backend 在事件 data 里显式带出）读取并写入 store。新 mode != takeover 时后端会送 null，store 记录 null。

### 3.5 ws-client schema

`frontend/packages/ws-client/src/types.ts`：
- `BeToFeType` 加 `'takeover_warning'`, `'takeover_warning_cancelled'`
- `FeToBeType` 不变（复用 `client_ack`）

### 3.6 mode 同步

已有 `mode.changed` 事件经订阅 fan-out 更新 store — 这部分**不用改**。双态按钮随 `conversation.mode` 切换。

## 4. Edge Cases & Testing

### 4.1 状态机

```
           /hijack                     /release (manual)
AUTO  ───────────────▶  TAKEOVER  ──────────────────▶  AUTO
  ▲          ▲     │                                     ▲
  │          │     │ idle 25s ─▶ takeover_warning 帧    │
  │          │     │                                     │
  │ offline  │     │ idle +5s ─▶ COPILOT                │
  │ grace    │     │ (auto:idle_timeout)                 │
  │          │     │                                     │
  │          │     └─▶ operator disconnect +30s ─▶ AUTO
  │          │                      (auto:operator_offline)
  │          │
  │     operator join + msg
COPILOT ───────────────── (existing, 不改)
```

所有 TAKEOVER 出口都要 cancel idle timer 和 offline watcher 的 per-conv 追踪（实际上 watcher 按 operator 管理，自动会跳过已不在 TAKEOVER 的对话）。

### 4.2 边界场景

| # | 场景 | 预期行为 |
|---|---|---|
| 1 | hijack 后 operator 持续发消息 | timer 滚动重置，永不自动释放 |
| 2 | hijack 后收到 warning，点"继续" | `client_ack(action=continue)` → 重置 timer → `takeover_warning_cancelled` |
| 3 | hijack 后收到 warning，operator 无视 5s | 切 COPILOT，operator 仍在 participant 列表 |
| 4 | hijack 后 operator 关闭标签页 | WS close → 30s 宽限期 → 切 AUTO |
| 5 | 关标签页 20s 内重新打开 | WS reconnect → watcher cancel 宽限 task → 对话保持 TAKEOVER |
| 6 | hijack 期间对话 `/resolve` | close 前 cancel idle timer（避免 resolved 后 timer 触发非法 mode 切换） |
| 7 | A `/hijack`，B 也加入并发消息，A 静默 30s | B 的消息**不**重置 A 的 timer（`source != takeover_operator_id`）；A 超时 → 对话 COPILOT，`takeover_operator_id` 清零 |
| 8 | gateway 重启 | 内存 timer 丢失；重启后 TAKEOVER 对话不会自动释放。Operator 可手动释放（MVP 范围接受） |
| 9 | config 文件不存在 / 字段缺失 | 回落硬编码默认（30s/5s/30s），启动不报错 |
| 10 | warning 帧发送失败（WS 已断） | 不影响后端流程；5s 后仍触发释放。同时 offline_watcher 也会起作用 |
| 11 | operator 同时是多个对话的接管人 | 每对话独立 idle timer；多个 warning 帧并发是可能的 |

### 4.3 测试策略

**后端（pytest）**：`tests/gateway/test_takeover_release.py`
- `/release` 切回 AUTO，emit `mode.changed(trigger=/release)`
- hijack 后静默（fake clock）→ warning 帧 → COPILOT
- hijack 后 25s 发消息 → 无 warning → 再 30s（累计滚动）→ warning → 5s → COPILOT
- operator disconnect → 宽限期 → AUTO
- disconnect 20s 内 reconnect → 不触发 AUTO
- A hijack，B 发消息，A 静默 30s → 对话 COPILOT（归属判定）
- config 覆盖：用 5s idle 跑测试
- `takeover_operator_id` 在各 mode 出口正确清零

用 `asyncio.sleep` monkey-patch 或 `asyncio.get_event_loop().time()` 替换做假 clock，避免真等 30s。

**前端（vitest）**：
- `HijackButton.test.tsx`
  - mode=takeover → text "释放回 AI"，dispatch `/release`
  - mode=auto|copilot → text "抢单"，dispatch `/hijack`
- `TakeoverWarning.test.tsx`
  - store 有 warning 时渲染，点"继续"发 `client_ack`
  - 收到 `takeover_warning_cancelled` 后从 store 清除
  - 非归属 operator 不渲染
- `useOperatorWS.test.tsx`
  - 新帧写入/清除 store

**E2E**（`tests/e2e/` 新增 `test_takeover_auto_release.py`）：
- customer 连接 → operator hijack → idle 30s (用小一点的 config，比如 3s + 1s warn) → 验证 mode=COPILOT 且 customer 继续收到 AI 回复

### 4.4 实现顺序（由 writing-plans 细化）

1. 后端 config 加载 + Conversation.takeover_operator_id 字段 + engine 构造函数参数
2. 后端 idle timer（含 warning 帧 + reset API）
3. 后端 client_ack action=continue 分支
4. 后端 offline_watcher 模块 + web_gateway 接线
5. 前端 ws-client schema 扩展
6. 前端 store 字段 + actions
7. 前端 HijackButton 双态
8. 前端 TakeoverWarning 组件 + useOperatorWS 帧处理
9. 后端单测 + 前端单测
10. E2E 接线
