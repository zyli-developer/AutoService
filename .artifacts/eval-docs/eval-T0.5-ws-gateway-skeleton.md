---
type: eval-doc
id: "eval-doc-002"
status: confirmed
producer: skill-5
created_at: "2026-04-15"
mode: simulate
feature: "T0.5 WebSocket 服务端骨架"
submitter: DevA
related:
  - "task:T0.5"
  - "contract:docs/contracts/frontend-ws-schema.md"
  - "contract:docs/contracts/conversation-engine.md"
  - "eval-doc-001"
---

# Eval: T0.5 WebSocket 服务端骨架

## 基本信息
- 模式：模拟（simulate）
- 提交人：DevA
- 日期：2026-04-15
- 状态：draft
- 任务类型：🟢 Green · A 线
- 依赖：T0.2（schema 🟩）+ T0.4（LocalEngine 🟩）

## 任务范围与验收标准

**范围（骨架三件事）**：
1. **路由**：FastAPI app + 3 WS 端点 `/ws/customer` `/ws/operator` `/ws/admin`，各自注入 `viewer_role`
2. **Envelope 校验**：`v / type / id / ts / payload` 基本字段 + FE→BE `id` 为 UUIDv4 + `ts` 是带毫秒的 UTC ISO8601；违规返 S4 `error{code: 4012_VALIDATION}`
3. **Engine 调用与错误映射**：Engine 抛 `NotImplementedError` → S4 `error` 帧；Engine 抛 `EngineError` 子类（Phase 1 才会出现）按 §6.1 映射到 `error` 或 `command_response{ok:false}`

**不在范围内（留后续任务）**：
- ACK 链超时 + 幂等去重（T1A.3 EventBus）
- 重连回放 `replay_complete` + ring buffer（T1B.4 前端断线重连对应）
- Heartbeat 超时 close（可加个简易定时器，但 close code 4408 的灰度等 T1A.2 Timer）
- 订阅 fanout `event` 帧（T1A.3）
- `source_display` 的 ParticipantRegistry（T1A.1）
- `participant.joined` 等事件的具体推送（依赖 T1A.3）
- 鉴权（4001/4003）— 骨架接受任何 token，Phase 2/3 接入

**目录结构**：

```
autoservice/
  web_gateway.py           # FastAPI app factory: create_app(engine=None) -> FastAPI
  gateway/
    __init__.py            # export Router, Connection, validate_envelope, handle_frame
    envelope.py            # Pydantic model + validator（v/type/id/ts/payload + uuid/ISO 校验）
    connection.py          # Connection class（封装 WebSocket + session_id + viewer_role + conversation_id? map）
    message_router.py      # 按 §7 映射表把 FE 帧分派到 Engine 方法；NotImplementedError/EngineError → error 帧
    errors.py              # WS 错误码常量 + ErrorCode enum；EngineError → WS code 映射表
```

**测试入口**：`autoservice/web_gateway.py` 的 `app` 对象可被 uvicorn 载入；pytest 用 `httpx.AsyncClient` + `httpx_ws`（或 `starlette.testclient.TestClient`）。

## 关键决策点（请 review）

### D-T0.5.1 · NotImplementedError → 哪个错误码？

骨架阶段 Engine 方法全部抛 `NotImplementedError`。WS 骨架需把它转成 S4 error 帧。但 T0.2 §6 现有错误码表里**没有**"未实现"这一类。三个选项：

| 选项 | 映射 | 优点 | 缺点 |
|---|---|---|---|
| **A. 复用 `5000_INTERNAL`** | `NotImplementedError → 5000_INTERNAL recoverable:false` | 无需改契约；Phase 1 落地后错误码自然消失 | FE 收到会指数退避重连，掩盖"未实现"的真实原因；日志需带 hint 才能分辨 |
| **B. 新增 `5001_NOT_IMPLEMENTED`** | 走契约漂移流程，T0.2 schema 加一码 | 语义清晰；FE 可显式 "coming soon" 提示 | M0.5 要改 schema + tests/contract/ 测试表 + DevB 重新 sign off；仅服务于"骨架阶段"的临时码，Phase 1 后即死码 |
| **C. 本地映射为 `4012_VALIDATION` + `details.reason="not_implemented"`** | 骨架期把"未实现"视为"客户端发了当前版本不支持的操作" | 不改契约；`details` 字段已存在 | 语义牵强，4012 本意是 payload 格式错；日后 audit 看日志混淆 |

**DevA 倾向 A（`5000_INTERNAL`）**：
- 契约已冻结，改动成本大
- 骨架只活到 Phase 1 开工（几小时），Phase 1 T1A.1 落地后这个映射自然失效
- 服务端日志里打 `extra={"engine_hint": "T1A.1 (lifecycle): ..."}` 足以 audit
- Phase 1 完工后此映射代码删除，不遗留死码

**问题**：请裁决。

### D-T0.5.2 · Engine 注入方式

骨架期 `LocalEngine` 是唯一实现，但 M5 需切 `ZchatEngine`。骨架给 `create_app` 留参数：

```python
def create_app(engine: ConversationEngine | None = None) -> FastAPI:
    engine = engine or LocalEngine()
    ...
```

生产代码另提一个 `autoservice/main.py`（或 `__main__.py`）读 config 决定实例。骨架阶段无需实装 config，但需预留参数位。

**问题**：骨架要不要同时加一个最小 `__main__.py` 让 `python -m autoservice` 能启 uvicorn？还是只留 `create_app()` 让 uvicorn CLI 调用（`uvicorn autoservice.web_gateway:app`）？我倾向后者（更少代码）。

### D-T0.5.3 · Pydantic 版本

T0.2 §2 envelope 需要 JSON schema 校验。项目是否已有 Pydantic？若无，骨架要不要直接用 Pydantic v2？替代是手写 validator（更轻但麻烦）。**我倾向 Pydantic v2**（事实标准 + 后续 T0.6 前端 TS 类型也可从 Pydantic 生成）。

### D-T0.5.4 · 测试框架

`tests/gateway/` 新建。跑 WS 需要 async 测试客户端。候选：

- `starlette.testclient.TestClient` — 同步 API，启动 TestClient 后 `.websocket_connect()`
- `httpx + httpx_ws` — async API
- `websockets` — async 但非 ASGI-aware

**我倾向 starlette TestClient**：骨架不追求异步测试，同步 API 够用且零依赖新增。

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|---------|---------|--------|
| 1 | FastAPI app 可被导入并注册 3 个 WS 路由 | T0.4 LocalEngine 已 🟩 | `from autoservice.web_gateway import create_app; app = create_app()` | app 成功返回；`app.routes` 含 `/ws/customer` `/ws/operator` `/ws/admin` 三条 WebSocket 路由 | FastAPI `add_api_websocket_route` 注册 3 个 handler；骨架 handler 体只做"accept + handshake + 分派循环 + 关闭清理" | 无 | P0 |
| 2 | /ws/customer 握手返 server_hello | app 运行中 | TestClient 连 `/ws/customer`；发 `client_hello{protocol_version:1, client_app:"web"}`；读取一帧 | 收到 `server_hello{session_id, protocol_version:1, server_time, viewer_role:"customer", accepted_subscriptions:[], server_capabilities:[]}`；不 close | 骨架生成 ULID session_id、UTC ts、固定 `server_capabilities=["v1"]`；`accepted_subscriptions` 骨架始终空数组（无鉴权 + 无 subscribe 落地） | 无 | P0 |
| 3 | /ws/operator /ws/admin 握手同样工作，`viewer_role` 随端点正确 | 同上 | 分别连两个端点 + client_hello | `viewer_role=operator` 或 `admin` | 三个 handler 共享同一 handshake helper，仅 `viewer_role` 参数不同 | 无 | P0 |
| 4 | Envelope 缺字段返 4012_VALIDATION error 帧 | handshake 完成 | 发 `{"v":1,"type":"customer_message"}`（缺 `id/ts/payload`） | 收到 S4 `error{code:"4012_VALIDATION", recoverable:false, ref:null, details:{missing:["id","ts","payload"]}}`；连接不断 | 骨架 envelope 校验器用 Pydantic v2；校验失败直接回 error 帧；不 raise 到 handler | 无 | P0 |
| 5 | Envelope `v` 非 1 返 4040_VERSION_INCOMPATIBLE | 同上 | 发完整帧但 `v:2` | 收到 `error{code:"4040_VERSION_INCOMPATIBLE", recoverable:false}`，随后服务端 close(4040) | 骨架硬编码 accepted=[1] | 无 | P1 |
| 6 | customer_message → LocalEngine.send_message 抛 NotImplementedError → error 帧 | handshake 完成 | 发 F4 `customer_message{conversation_id:"test-1", content:"hi"}` | 收到 S4 `error{code:"<D-T0.5.1 裁决>", message:"...", recoverable:false, ref:<frame_id>, details:{engine_hint:"T1A.1 (lifecycle): conversation lifecycle" or similar}}` | 骨架捕获 `NotImplementedError`，从 `str(exc)` 提取 T1A.x hint 放 `details`；不抛到 uvicorn loop | **依赖 D-T0.5.1** | P0 |
| 7 | operator_command /hijack → handle_command 抛 NotImplementedError → **command_response{ok:false}** 而非 error 帧（§6.1） | handshake 完成 | 发 F11 `operator_command{command:"/hijack", conversation_id:"t", operator_id:"op1"}` | 收到 S11 `command_response{command:"/hijack", ok:false, error_code:"<D-T0.5.1 裁决>", error_message, ref:<frame_id>}` | 骨架在 router 里按"命令语义"分派到 command_response；非命令语义走 error 帧 | 无 | P0 |
| 8 | ping → pong（heartbeat） | handshake 完成 | 发 F2 `ping{}` | 收到 S2 `pong{server_time}`；不期待 ack | 骨架 router 对 ping 直连 pong helper，不走 Engine | 无 | P0 |
| 9 | 未知 type 返 4012_VALIDATION error 帧 | 同上 | 发 `{..., "type":"unknown_frame"}` | error{code:"4012_VALIDATION", details:{unknown_type:"unknown_frame"}} | router 找不到 handler 时默认 4012 | 无 | P1 |
| 10 | 连接在客户端主动断开时，服务端 handler 干净退出 | 同上 | TestClient 关闭上下文 | 服务端循环 break；无未关闭资源警告 | FastAPI WebSocketDisconnect 被 except 捕获 + finally 清理 Connection 对象 | 无 | P1 |
| 11 | Engine 通过 Protocol 注入，非 LocalEngine 专属 | — | 自定义一个 `DummyEngine` 只实现 `send_message` 返回固定 Message；create_app(engine=DummyEngine()) | customer_message 正常回 S5 message + ack | 骨架只引 `ConversationEngine` Protocol 类型；不 import LocalEngine 为默认需要时再 import | 无 | P0 |
| 12 | CORS 允许 5173/5174/5175 | app 创建 | 发 HTTP OPTIONS `/ws/customer` with `Origin: http://localhost:5173` | 200 + `Access-Control-Allow-Origin: http://localhost:5173` | starlette CORSMiddleware 白名单 | 无 | P1 |
| 13 | 骨架不吞业务异常（只吞 NotImplementedError）| app 创建；DummyEngine 在 send_message 抛 `ValueError` | 发 customer_message | 测试期望服务端返 `error{code:"5000_INTERNAL"}` 而非崩；日志含 traceback | 骨架全局 try/except 对未知异常统一走 5000 | 无 | P1 |
| 14 | `tests/contract/` 回归零 | T0.5 文件落地 | `pytest tests/contract/` | 仍 160 passed / 60 skipped | T0.5 只新增文件，不改 autoservice/conversation_engine/ | 无 | P0 |

## 关键非功能点

- **并发模型**：每个 WebSocket 一个 asyncio 协程；骨架阶段**不**起后台 fanout 任务（留 T1A.3 EventBus）
- **日志**：骨架用 `logging.getLogger("autoservice.gateway")`，关键事件 info 级（handshake 成功/失败、NotImplementedError 转 error 帧）
- **关闭清理**：Connection 对象用 async context manager，finally 块中注销 `session_id → conversation_id` 映射
- **无 Rate Limit**：4029 不在骨架范围，Phase 2+ 实装

## 风险

| 风险 | 可能性 | 缓解 |
|---|---|---|
| Pydantic v2 未安装 | 中 | 先 `pip install pydantic` 然后加到 `dev-requirements` |
| starlette TestClient 对 WS 的 mock 与真实 uvicorn 不一致 | 低 | 骨架期信任 TestClient；联调（kickoff §5）时 DevB 真连 uvicorn 再验 |
| 心跳超时 close（4408）未实装 → 联调时前端等不到 close | 中 | 骨架文档明示"heartbeat 只回 pong，不执行超时 close"；前端联调时避免长期空闲 |
| `source_display` 字段因无 ParticipantRegistry 骨架没填 → S5 message 帧 schema 检查失败 | 中 | 骨架暂不触发 S5 message 推送（Engine 全部抛 NotImplementedError），因此不会出现 schema 不全的 S5；测试 11 用 DummyEngine 时临时填 `source_display={id:source, role:"agent"}` |

## 实现提示（给 Skill 3）

- **Envelope Pydantic 模型**示意：

  ```python
  from datetime import datetime
  from pydantic import BaseModel, Field, UUID4, field_validator

  class Envelope(BaseModel):
      v: int = Field(ge=1, le=1)
      type: str
      id: str  # FE→BE: UUIDv4; BE→FE: ULID — 骨架只校 FE→BE
      ts: str
      ref: str | None = None
      payload: dict

      @field_validator("ts")
      def _ts_utc_ms(cls, v): ...  # 必须含 .mmm 且以 Z 结尾
  ```

- **错误帧 helper**：`def make_error(code: str, message: str, *, ref: str | None = None, recoverable: bool = False, details: dict | None = None) -> dict`
- **NotImplementedError 拦截位置**：`message_router.dispatch` 内，围绕 Engine 方法调用；只捕获 `NotImplementedError`，其他异常交由上层 handler 处理（测试 13）
- **命令语义判定**：FE 帧 `type in {"operator_command", "admin_command"}` → `command_response` 路径；其他 → `error` 帧路径
- **TestClient 用法**：
  ```python
  from starlette.testclient import TestClient
  with TestClient(app).websocket_connect("/ws/customer") as ws:
      ws.send_json({...})
      data = ws.receive_json()
  ```

## 后续行动

- [ ] DevA 裁决 D-T0.5.1（错误码选 A/B/C）
- [ ] DevA 裁决 D-T0.5.2（是否加 `__main__.py`）
- [ ] DevA 确认 D-T0.5.3（Pydantic v2）+ D-T0.5.4（starlette TestClient）
- [ ] 用户调整 testcase / 优先级
- [ ] 确认后 status: draft → confirmed，进 skill-2 test-plan
