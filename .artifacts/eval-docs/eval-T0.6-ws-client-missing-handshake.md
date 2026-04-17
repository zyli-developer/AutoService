---
type: eval-doc
id: "eval-doc-003"
status: draft
producer: skill-5
created_at: "2026-04-16"
mode: verify
feature: "T0.6 前端 ws-client 缺失握手（client_hello）"
submitter: DevA
related:
  - "task:T0.6"
  - "contract:docs/contracts/frontend-ws-schema.md#3.1"
  - "path:frontend/packages/ws-client/src/client.ts"
  - "e2e-report-002"
---

# Eval (verify): T0.6 前端 ws-client 缺失握手

## 基本信息
- 模式：验证（verify）
- 提交人：DevA
- 日期：2026-04-16
- 状态：draft
- 发现阶段：Batch 1 M0.5 联调（kickoff §5）
- 复现：100%

## 背景

按 T0.2 §3.1，前端 WebSocket 连接后必须立即发 `client_hello{protocol_version:1, ...}`，服务端返 `server_hello` 或 `error{code:"4040_VERSION_INCOMPATIBLE"}`。T0.5 后端骨架（`autoservice/web_gateway._handle_connection`）严格按此执行 —— 任何首帧非 `client_hello` 都返 `4012_VALIDATION + reason:"handshake_required"` 并 `close(1002)`。

T0.6 ws-client 骨架缺失这一步，导致前后端无法联通。

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 实际效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|---------|---------|--------|
| 1 | 连接建立后发握手 | 后端 T0.5 running on :9999；前端 customer-chat running on :5173 | 浏览器打开 http://localhost:5173 → App 触发 `useWebSocket('ws://localhost:9999/ws/customer')` → ws-client.connect() | F12 Network WS 收到 S1 `server_hello{viewer_role:"customer", session_id, ...}`；`useWebSocket` 状态 `open` | WebSocket 连接建立（TCP+Upgrade 成功），但 ws-client 未主动发任何帧；15s 后心跳 timer 触发 `send('ping', {})` 作为首帧；后端按 §3.1 返 S4 error `4012_VALIDATION` `handshake_required`；`useWebSocket.lastFrame` 显示该 error 帧 | 前端 client.ts `open` handler（client.ts:82-86）直接 `startHeartbeat()`，跳过了 `client_hello` 步骤 | P0 |
| 2 | client_hello 成功后发心跳 | TC1 已修 | 修复后连接 → 等 16s | 心跳 ping 在 server_hello 之后发出，收到 pong | 当前无法验证（被 TC1 阻塞） | — | P0 |
| 3 | 版本不兼容永久拒绝 | 后端只接受 v:1，前端声明 v:2 | 临时改 ws-client `protocolVersion: 2` | 收到 `error{code:"4040_VERSION_INCOMPATIBLE"}` → ws-client **不**触发 `scheduleReconnect()`（recoverable=false） | 当前 client.ts `close` handler `if (!this.closedByUser) this.scheduleReconnect()` 无视 close code，会无限重连 4040 | 缺少 `recoverable` 判定 | P1 |
| 4 | T1B.1 customer-chat SPA 可开工 | TC1 修复 | DevB 基于 T0.6 开始 T1B.1 | 可以在 WS `open` 后发 `customer_message` | 当前 WS 不进入 open 状态（或进入后所有业务帧都被 handshake_required 拒绝） | TC1 阻塞 | P0 |

## 证据区

### 后端收到的首帧 → 返错

收到的第一帧是 heartbeat ping（frame id `09677ec7-...`，FE→BE），而非 client_hello。后端按预期返 error：

```json
{
  "v": 1,
  "type": "error",
  "id": "1201ad15679c093f191bf81031",
  "ts": "2026-04-16T00:37:43.397Z",
  "ref": "09677ec7-26dd-4dd9-930f-ad53dad79514",
  "payload": {
    "code": "4012_VALIDATION",
    "message": "handshake required: expected client_hello",
    "recoverable": false,
    "details": { "reason": "handshake_required" }
  }
}
```

### 前端代码位置

[frontend/packages/ws-client/src/client.ts:82-86](frontend/packages/ws-client/src/client.ts#L82-L86)：

```ts
ws.addEventListener('open', () => {
  this.reconnectAttempt = 0;
  this.startHeartbeat();        // ← 应在 server_hello 收到后才起
  this.opts.onOpen?.();          // ← 应在 server_hello 收到后才触发
});
```

### 复现环境

- 后端：commit `79a295e`（origin/dev tip），uvicorn 0.x + FastAPI 0.135.3 + Python 3.14.3，端口 9999
- 前端：同 commit，vite 5.4.21 + React + ws-client v0.0.1，端口 5173
- 浏览器：用户手动 F12 观察（Chromium 系）
- OS：Windows 11

## 分流建议

**疑似 bug** —— 行为明确违反 T0.2 §3.1 冻结契约（"前端必须先发 client_hello"）。后端行为完全正确（已被 `tests/gateway/test_tc008_business_frame_before_handshake_rejected` 覆盖）。

## 修复方案（给 DevB 参考）

### 方案 A（推荐）：ws-client 接管握手，对业务透明

[client.ts](frontend/packages/ws-client/src/client.ts) 改动：

1. **新增字段**：`private handshakeComplete = false;`
2. **`open` handler 改造**：
   ```ts
   ws.addEventListener('open', () => {
     this.reconnectAttempt = 0;
     this.sendClientHello();   // 新方法：直接 ws.send，不走 send() 的 ack 链
     // 不在此处 startHeartbeat / 触发 onOpen
   });
   ```
3. **新增 `sendClientHello()`**：构造 `client_hello` 帧（带 `protocol_version: this.opts.protocolVersion ?? 1`），直接 `ws.send(raw)`。
4. **message handler 前置 handshake 分支**：
   ```ts
   if (!this.handshakeComplete) {
     if (frame.type === 'server_hello') {
       this.handshakeComplete = true;
       this.startHeartbeat();
       this.opts.onOpen?.();         // 握手完成才视为"真正的 open"
       return;
     }
     if (frame.type === 'error' && frame.payload.code === '4040_VERSION_INCOMPATIBLE') {
       this.closedByUser = true;     // 永久拒绝，阻止重连
       this.ws?.close(4040, 'version_incompatible');
       this.opts.onError?.(new Error('version_incompatible'));
       return;
     }
     // 其他握手期帧不期望出现
     this.opts.onError?.(new Error(`unexpected_pre_handshake_frame:${frame.type}`));
     return;
   }
   // ... 原 handshake 后逻辑
   ```
5. **close handler 补 4040 判定**：
   ```ts
   ws.addEventListener('close', (ev) => {
     this.stopHeartbeat();
     this.handshakeComplete = false;
     this.opts.onClose?.(ev.code, ev.reason);
     this.rejectAllPending(new Error(`ws_closed:${ev.code}`));
     if (!this.closedByUser && ev.code !== 4040) this.scheduleReconnect();
   });
   ```

### 方案 B：在 App 层显式发 client_hello

工作量小，但每个 app 都要写握手，违反骨架应提供的抽象层级。**不推荐**。

## 测试补齐建议

DevB 修复时应在 `packages/ws-client/tests/` 加单测：

- client_hello 在 `open` 事件后立即发（用 MockWebSocket 捕获首帧）
- `onOpen` 仅在 `server_hello` 收到后触发
- `4040_VERSION_INCOMPATIBLE` 时不重连
- 心跳 ping 仅在 handshake 后出现

## 后续行动

- [x] eval-doc-003 写入 `.artifacts/eval-docs/` 并注册
- [ ] 开 GitHub issue @ ezagent42/AutoService，label `bug` + `T0.6`，指派 DevB
- [ ] DevB 在 dev-b 分支修复 + 自测 + 联调复测
- [ ] 修复 PR 合入 dev 后，DevA 重跑 M0.5 smoke test

## 影响范围

- **阻塞**：T1B.1（customer-chat SPA）、T1B.2/3/4（消息流/占位/重连）均依赖 WS open
- **不阻塞**：A 线 T1A.1-3（LocalEngine Mode/Gate/Timer/EventBus 与前端解耦）
- **Batch 1 M0.5 验收**：部分达成（后端握手、envelope、错误映射、心跳 pong 机制均验证；前端 handshake 待修）
