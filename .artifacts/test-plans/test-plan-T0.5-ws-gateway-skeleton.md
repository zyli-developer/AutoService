---
type: test-plan
id: test-plan-002
status: draft
producer: skill-2
created_at: "2026-04-15"
trigger: "eval-doc-002 (T0.5 WS gateway skeleton simulate) — all 4 decisions resolved"
related:
  - eval-doc-002
  - "contract:docs/contracts/frontend-ws-schema.md"
  - "contract:docs/contracts/conversation-engine.md"
  - "task:T0.5"
decisions_frozen:
  D-T0.5.1: "A — NotImplementedError → 5000_INTERNAL with details.engine_hint"
  D-T0.5.2: "Only create_app(); no __main__.py; launch via `uvicorn autoservice.web_gateway:app`"
  D-T0.5.3: "Pydantic v2 for envelope validation"
  D-T0.5.4: "starlette.testclient.TestClient (sync WebSocket API)"
---

# Test Plan: T0.5 WebSocket 服务端骨架

## 触发原因

eval-doc-002 列出 14 个 TC 覆盖路由/握手/envelope/错误映射/心跳/CORS 等骨架行为。本 plan 把它们转为可执行单测（目标：`tests/gateway/test_web_gateway.py`），并扩展 12 个边界用例（每个 FE 帧类型的"至少能被 router 识别"、ts 格式、ref 存否、/ws/operator 路径上的 NotImplementedError 行为、handshake 前发业务帧的行为等）。

## 测试文件位置

- `tests/gateway/__init__.py`（新建，空）
- `tests/gateway/conftest.py`（新建，共享 fixtures）
- `tests/gateway/test_web_gateway.py`（新建，主体用例）

## 统一前置 / 共享 fixtures

```python
# conftest.py
import pytest
from starlette.testclient import TestClient
from autoservice.web_gateway import create_app
from autoservice.conversation_engine import LocalEngine

class DummyEngine:
    """Minimal ConversationEngine-compatible stub for gateway-only tests.

    不实现全部 18 方法 —— 只实现被某些测试显式调用的。
    未实现的方法保持缺省（调用时 AttributeError），测试应避免触发。
    对 send_message / handle_command 提供可配置的返回或抛异常行为。
    """

    def __init__(self):
        self._send_message_impl = None
        self._handle_command_impl = None

    async def send_message(self, *args, **kwargs):
        if self._send_message_impl is None:
            raise AssertionError("DummyEngine.send_message not configured")
        return await self._send_message_impl(*args, **kwargs)

    async def handle_command(self, *args, **kwargs):
        if self._handle_command_impl is None:
            raise AssertionError("DummyEngine.handle_command not configured")
        return await self._handle_command_impl(*args, **kwargs)

@pytest.fixture
def local_engine_app():
    """App with default LocalEngine (all methods raise NotImplementedError)."""
    return create_app()

@pytest.fixture
def local_engine_client(local_engine_app):
    return TestClient(local_engine_app)

@pytest.fixture
def dummy_engine():
    return DummyEngine()

@pytest.fixture
def dummy_engine_client(dummy_engine):
    return TestClient(create_app(engine=dummy_engine))
```

Envelope helper（测试内用）：

```python
import uuid
from datetime import datetime, timezone

def make_frame(type_: str, payload: dict | None = None, *, v: int = 1, ref: str | None = None) -> dict:
    frame = {
        "v": v,
        "type": type_,
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now().microsecond // 1000:03d}Z",
        "payload": payload or {},
    }
    if ref is not None:
        frame["ref"] = ref
    return frame

def handshake(ws, *, viewer_role_expected: str):
    ws.send_json(make_frame("client_hello", {"protocol_version": 1, "client_app": "web"}))
    reply = ws.receive_json()
    assert reply["type"] == "server_hello"
    assert reply["payload"]["viewer_role"] == viewer_role_expected
    return reply
```

## 用例列表

### 分组 A · App 构建与路由（TC-001 ~ TC-004）

#### TC-001: create_app 可导入并返回 FastAPI 实例
- **来源**：eval-doc-002 TC1
- **优先级**：P0
- **前置**：T0.4 🟩
- **步骤**：
  1. `from autoservice.web_gateway import create_app`
  2. `app = create_app()`
- **预期**：`app` 是 FastAPI 实例；不抛
- **涉及模块**：`autoservice.web_gateway`

#### TC-002: app.routes 含 3 条 WebSocket 路由
- **来源**：eval-doc-002 TC1
- **优先级**：P0
- **步骤**：
  1. 过滤 `app.routes` 中 `path` ∈ {`/ws/customer`, `/ws/operator`, `/ws/admin`}
  2. 断言三条路径全部存在，类型为 WebSocket 路由（`APIWebSocketRoute` / `WebSocketRoute`）
- **预期**：3/3 存在
- **涉及模块**：`autoservice.web_gateway`

#### TC-003: create_app(engine=DummyEngine()) 注入生效
- **来源**：eval-doc-002 TC11
- **优先级**：P0
- **步骤**：
  1. `dummy = DummyEngine(); app = create_app(engine=dummy)`
  2. 以某种方式验证 app 内部持有 dummy（e.g. `app.state.engine is dummy`）
- **预期**：app 引用注入的 engine，而非新建 LocalEngine
- **涉及模块**：`autoservice.web_gateway`

#### TC-004: create_app() 默认注入 LocalEngine
- **来源**：eval-doc-002 扩展
- **优先级**：P1
- **步骤**：
  1. `app = create_app()`
  2. `assert isinstance(app.state.engine, LocalEngine)`
- **预期**：默认 engine 是 LocalEngine 实例
- **涉及模块**：`autoservice.web_gateway`

### 分组 B · 握手（TC-005 ~ TC-009）

#### TC-005: /ws/customer 握手返 server_hello（viewer_role=customer）
- **来源**：eval-doc-002 TC2
- **优先级**：P0
- **步骤**：
  1. 打开 `client.websocket_connect("/ws/customer")`
  2. 发 `client_hello{protocol_version:1, client_app:"web"}`
  3. 读取下一帧
- **预期**：
  - 帧 `type == "server_hello"`
  - `payload.session_id` 非空字符串（ULID 格式，~26 字符）
  - `payload.protocol_version == 1`
  - `payload.viewer_role == "customer"`
  - `payload.accepted_subscriptions == []`
  - `payload.server_capabilities` 为非空 list
  - `payload.server_time` 为 ISO8601 UTC 毫秒
  - 连接保持开启
- **涉及模块**：`gateway.connection`

#### TC-006: /ws/operator 握手 viewer_role=operator
- **来源**：eval-doc-002 TC3
- **优先级**：P0
- **步骤**：同 TC-005 但连 `/ws/operator`
- **预期**：`viewer_role == "operator"`
- **涉及模块**：同上

#### TC-007: /ws/admin 握手 viewer_role=admin
- **来源**：eval-doc-002 TC3
- **优先级**：P0
- **步骤**：同 TC-005 但连 `/ws/admin`
- **预期**：`viewer_role == "admin"`
- **涉及模块**：同上

#### TC-008: 握手前发业务帧被拒绝
- **来源**：扩展
- **优先级**：P1
- **步骤**：
  1. 连 `/ws/customer`
  2. 未发 client_hello 即发 `customer_message{...}`
- **预期**：收到 `error{code:"4012_VALIDATION", details:{reason:"handshake_required"}}`（或等价提示），连接可能被 close
- **涉及模块**：`gateway.connection`, `gateway.message_router`

#### TC-009: 握手协议版本不兼容
- **来源**：eval-doc-002 TC5 调整（版本协商发生在 client_hello 阶段而非任意帧）
- **优先级**：P1
- **步骤**：
  1. 连 `/ws/customer`
  2. 发 `client_hello{protocol_version:2}`
- **预期**：`error{code:"4040_VERSION_INCOMPATIBLE", recoverable:false}`，服务端 close(4040)
- **涉及模块**：`gateway.connection`

### 分组 C · Envelope 校验（TC-010 ~ TC-016）

#### TC-010: envelope 缺 id 返 4012
- **来源**：eval-doc-002 TC4
- **优先级**：P0
- **步骤**：握手后发 `{"v":1,"type":"ping","ts":"<valid>","payload":{}}`（缺 `id`）
- **预期**：`error{code:"4012_VALIDATION", details:{missing:["id"] or包含"id"}}`
- **涉及模块**：`gateway.envelope`

#### TC-011: envelope 缺 ts / type / payload 各返 4012
- **来源**：eval-doc-002 TC4 展开
- **优先级**：P0
- **步骤**：分别构造缺 ts / type / payload 的帧
- **预期**：三种场景均返 `4012_VALIDATION`，`details.missing` 含对应字段
- **涉及模块**：`gateway.envelope`

#### TC-012: envelope id 非 UUIDv4 返 4012
- **来源**：扩展（§2 要求 FE→BE id 为 UUIDv4）
- **优先级**：P1
- **步骤**：发 `id:"not-a-uuid"`
- **预期**：`4012_VALIDATION`，`details.reason` 含 "uuid"
- **涉及模块**：`gateway.envelope`

#### TC-013: envelope ts 非 UTC ms ISO 返 4012
- **来源**：扩展（§2 要求 ISO8601 UTC 毫秒）
- **优先级**：P1
- **步骤**：发 `ts:"2026-04-15 10:30:00"`（空格分隔无毫秒无 Z）
- **预期**：`4012_VALIDATION`
- **涉及模块**：`gateway.envelope`

#### TC-014: envelope v != 1 返 4040
- **来源**：eval-doc-002 TC5
- **优先级**：P1
- **步骤**：握手后发 `v:2` 的 ping 帧
- **预期**：`error{code:"4040_VERSION_INCOMPATIBLE"}`
- **涉及模块**：`gateway.envelope`
- **说明**：若骨架选择只在 client_hello 阶段协商 version，本 TC 与 TC-009 合并。Plan 保留两个以便 Skill 3 决定实现策略

#### TC-015: envelope ref 字段合法通过
- **来源**：扩展
- **优先级**：P2
- **步骤**：构造带合法 `ref` 的 ping 帧（`ref` 为另一 UUIDv4 字符串）
- **预期**：不被校验器拒绝（ping 的 ref 语义虽无实际用途，但不应返 validation error）
- **涉及模块**：`gateway.envelope`

#### TC-016: 未知 type 返 4012 带 unknown_type
- **来源**：eval-doc-002 TC9
- **优先级**：P1
- **步骤**：发 `type:"no_such_type"`
- **预期**：`4012_VALIDATION`，`details.unknown_type == "no_such_type"`
- **涉及模块**：`gateway.message_router`

### 分组 D · Engine 错误映射（TC-017 ~ TC-022）

#### TC-017: customer_message → NotImplementedError → 5000_INTERNAL
- **来源**：eval-doc-002 TC6（D-T0.5.1=A 落定）
- **优先级**：P0
- **步骤**：
  1. 用 `local_engine_client`（默认 LocalEngine 骨架）
  2. 握手 /ws/customer
  3. 发 F4 `customer_message{conversation_id:"c-1", content:"hi"}`
- **预期**：收到 S4 `error{code:"5000_INTERNAL", recoverable:false, ref:<frame_id>, details:{engine_hint:"T1A.1 (lifecycle): conversation lifecycle"}}`（hint 来自 `create_conversation` 的抛出，因 send_message 前通常要 create；或直接来自 `send_message` 的 hint，取决于骨架 router 策略）
- **验证**：
  - `code == "5000_INTERNAL"`
  - `ref == 发送帧的 id`
  - `details.engine_hint` 非空且匹配正则 `r"T[12]A\.\d+"`
- **涉及模块**：`gateway.message_router`, `gateway.errors`

#### TC-018: operator_command /hijack → NotImplementedError → command_response{ok:false}
- **来源**：eval-doc-002 TC7
- **优先级**：P0
- **步骤**：
  1. 用 `local_engine_client` 握手 /ws/operator
  2. 发 F11 `operator_command{command:"/hijack", conversation_id:"c-1", operator_id:"op1"}`
- **预期**：收到 S11 `command_response{command:"/hijack", ok:false, error_code:"5000_INTERNAL", error_message:..., ref:<frame_id>}`；**不**收到 S4 error 帧（§6.1 命令语义走 command_response）
- **涉及模块**：`gateway.message_router`

#### TC-019: admin_command 同样走 command_response{ok:false}
- **来源**：扩展
- **优先级**：P1
- **步骤**：连 /ws/admin，发 F12 `admin_command{command:"/status"}`
- **预期**：`command_response{ok:false, error_code:"5000_INTERNAL"}`
- **涉及模块**：`gateway.message_router`

#### TC-020: DummyEngine.send_message 返回合法 Message → S5 message + S3 ack
- **来源**：eval-doc-002 TC11 扩展
- **优先级**：P0
- **步骤**：
  1. 配置 `dummy_engine._send_message_impl` 返回构造的 `Message(id=ULID, ...)`
  2. 握手 /ws/customer
  3. 发 F4 customer_message
- **预期**：
  - 收到 S3 `ack{ref:<frame_id>}`
  - 收到 S5 `message{conversation_id, message:{id,...,visibility:"public",sequence_number:...}, source_display:{id, role}}`（骨架最小填充 source_display）
- **涉及模块**：`gateway.message_router`

#### TC-021: DummyEngine 抛 ValueError（非 NotImplementedError / 非 EngineError）→ 5000_INTERNAL
- **来源**：eval-doc-002 TC13
- **优先级**：P1
- **步骤**：
  1. `dummy_engine._send_message_impl = async raise ValueError("oops")`
  2. 握手 /ws/customer
  3. 发 customer_message
- **预期**：`error{code:"5000_INTERNAL"}`；服务端日志含 traceback；连接不中断
- **涉及模块**：`gateway.message_router`

#### TC-022: /ws/operator 上的 customer_message 被拒
- **来源**：扩展（端点粗过滤）
- **优先级**：P1
- **步骤**：握手 /ws/operator 后发 `customer_message`
- **预期**：`error{code:"4012_VALIDATION", details:{reason:"frame_not_allowed_on_endpoint"}}` 或 `4003_PERMISSION_DENIED`（Skill 3 实现择一；**推荐 4012**，因为骨架尚未做鉴权）
- **涉及模块**：`gateway.message_router`, `gateway.connection`

### 分组 E · 心跳与断开（TC-023 ~ TC-025）

#### TC-023: ping → pong
- **来源**：eval-doc-002 TC8
- **优先级**：P0
- **步骤**：握手后发 F2 `ping{}`
- **预期**：收到 S2 `pong{server_time}`；不期望 ack 帧
- **涉及模块**：`gateway.message_router`

#### TC-024: pong/ack/error 不触发 ack 链
- **来源**：扩展（§3.2 明示）
- **优先级**：P2
- **步骤**：假设骨架不会主动发 pong 以外的"需要 ack"的帧；本 TC 通过 code inspection 而非运行时验证
- **预期**：`message_router` 代码中不对 ping/pong/ack/error 调用 ack helper
- **涉及模块**：`gateway.message_router`
- **说明**：若 Skill 3 觉得 code inspection 太费力，允许降级为"发 pong 帧给服务端（客户端不应发 pong，但骨架应容错），断言不收到 ack"

#### TC-025: 客户端主动断开，服务端干净退出
- **来源**：eval-doc-002 TC10
- **优先级**：P1
- **步骤**：
  1. 握手
  2. 退出 `with websocket_connect(...)` 上下文
- **预期**：无 pytest warning / 无 unclosed resource；TestClient 可继续复用
- **涉及模块**：`gateway.connection`

### 分组 F · CORS 与契约回归（TC-026 ~ TC-027）

#### TC-026: CORS 允许 5173/5174/5175
- **来源**：eval-doc-002 TC12
- **优先级**：P1
- **步骤**：对每个 origin 发 HTTP OPTIONS `/ws/customer`
- **预期**：200；`Access-Control-Allow-Origin` 回显对应 origin
- **涉及模块**：`autoservice.web_gateway`（CORSMiddleware 配置）

#### TC-027: tests/contract/ 回归零（blocking gate）
- **来源**：eval-doc-002 TC14
- **优先级**：P0
- **步骤**：`pytest tests/contract/`（独立调用，skill-4 门禁）
- **预期**：160 passed / 60 skipped，未变化
- **涉及模块**：`tests/contract/*`
- **说明**：不写入 `tests/gateway/test_web_gateway.py`；由 skill-4 test-runner 单独执行

## 统计

| 指标 | 值 |
|---|---|
| 总用例数 | 27 |
| P0 | 12 |
| P1 | 11 |
| P2 | 2 |
| 来源：eval-doc-002 | 14（直接） + 12（扩展） + 1（回归门禁） |

## 风险标注

- **高风险**：
  - `D-T0.5.1` 假定 `5000_INTERNAL` 被 FE 按"服务器错误"处理，联调时若 DevB 的前端对 5xxx 默认指数退避重连，会放大"骨架期感知到的错误"噪声；缓解：骨架期 FE 可在 dev 模式对 `details.engine_hint` 非空的 5000 打"未实现"提示而非重连
  - `TC-020` 的 source_display 由骨架填充（源于 Engine Message 无此字段），若 Phase 1 实装 ParticipantRegistry 后骨架 stub 漏删，将产生脏数据
- **回归风险**：
  - TC-027：仅靠 skill-4 门禁，若 Skill 3 不慎改到 `autoservice/conversation_engine/__init__.py`，契约测试会回退
- **覆盖未知**：
  - 无 coverage-matrix（Phase 0 尚未建立）；本计划依赖人审

## 依赖 skill-3 的实现约束

1. **依赖新增**：FastAPI、uvicorn、Pydantic v2、starlette 已随 FastAPI 带；确认 `.venv` 已安装，否则 Skill 3 需更新 `dev-requirements`
2. **文件清单**：
   - `autoservice/web_gateway.py`
   - `autoservice/gateway/__init__.py` `envelope.py` `connection.py` `message_router.py` `errors.py`
   - `tests/gateway/__init__.py` `conftest.py` `test_web_gateway.py`
3. **测试框架**：pytest + starlette.testclient（同步）；不使用 pytest-asyncio（骨架 gateway 虽然是 async，但 TestClient 对外是同步 API）
4. **禁区**：不得修改 `autoservice/conversation_engine/` 下任何文件（M0 契约），不得修改 T0.4 产物
5. **路径哨兵**：Skill 3 验收时执行 `grep -l "class.*Engine" autoservice/gateway/` 应为空（gateway 不能定义 Engine）
6. **命名**：测试函数名 `test_tc{三位}_{动作}_{目标}`，例如 `test_tc001_create_app_returns_fastapi`

## 后续行动

- [x] test-plan 已注册到 .artifacts/test-plans/ (test-plan-002, draft)
- [ ] 用户 review + 确认 (status: draft → confirmed)
- [ ] Skill 3 基于本 plan 写 27 用例 + 骨架实现
- [ ] Skill 4 跑 `tests/gateway/ + tests/contract/` 归档
