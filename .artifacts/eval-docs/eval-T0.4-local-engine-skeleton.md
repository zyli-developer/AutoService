---
type: eval-doc
id: "eval-doc-001"
status: draft
producer: skill-5
created_at: "2026-04-15"
mode: simulate
feature: "T0.4 LocalEngine 骨架"
submitter: DevA
related:
  - "task:T0.4"
  - "contract:docs/contracts/conversation-engine.md"
  - "protocol:autoservice/conversation_engine/protocol.py"
---

# Eval: T0.4 LocalEngine 骨架

## 基本信息
- 模式：模拟（simulate）
- 提交人：DevA
- 日期：2026-04-15
- 状态：draft
- 任务类型：🟢 Green · A 线
- 依赖：T0.1（已 🟩）

## 任务范围与验收标准

**范围**：只新增 `autoservice/conversation_engine/local_engine.py` 单文件 + 在同包 `__init__.py` 末尾追加 `from .local_engine import LocalEngine`。

**不在范围内（M0 契约冻结，不得动）**：
- `protocol.py` / `types.py` / `events.py` / `errors.py`
- 新建 `autoservice/engine/` 目录（错误路径）
- 重复定义 `Mode / Visibility / EventType` 等枚举

**骨架策略**：`LocalEngine` 类结构上满足 `ConversationEngine` Protocol（duck typing），**所有方法体** `raise NotImplementedError("T1A.x: <简述>")`，按 Phase 1 任务映射：

> **映射说明（v2，修正 review 意见）**：task-status 中 T1A.1 的任务名"Mode/Gate 最小实现"范围偏窄，但 LocalEngine 能跑起来还需"对话生命周期 + 成员 + 消息 CRUD"基础设施。暂把这些基础也记到 T1A.1（实际需在 T1A.1 开工时扩任务范围或另开 T1A.0），hint 文案明示"lifecycle/participant/messages"子域以便 Phase 1 拆分。

| Protocol 方法组 | 映射 T1A.x | NotImplementedError hint |
|---|---|---|
| 对话生命周期（create/get/list/close/set_csat） | T1A.1（范围需扩）| `"T1A.1 (lifecycle): conversation lifecycle"` |
| 成员（join/leave） | T1A.1（范围需扩）| `"T1A.1 (participant): participant management"` |
| Mode 切换（switch_mode） | T1A.1 | `"T1A.1 (mode): mode transition"` |
| Messages（send/edit/delete/get） | T1A.1（范围需扩，基础 CRUD；T1A.6 负责占位续写业务逻辑）| `"T1A.1 (messages): message CRUD"` |
| handle_command | T2A.1 协议命令实现 | `"T2A.1: command dispatch"` |
| Timers（set/cancel） | T1A.2 Timer 最小实现 | `"T1A.2: timer scheduling"` |
| Events（subscribe/query） | T1A.3 EventBus 最小实现 | `"T1A.3: event bus"` |
| register_hook | **T1A.3**（hook 分发是 EventBus 基础设施，不是 T1A.7 某个具体 plugin）| `"T1A.3 (hooks): plugin hook registry"` |

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|---------|---------|--------|
| 1 | LocalEngine 可导入与实例化 | M0 产物齐全 | `from autoservice.conversation_engine import LocalEngine; e = LocalEngine()` | 无异常，`isinstance(e, ConversationEngine)` 为 True（structural typing） | 骨架下 `__init__` 为空实现（或接受 config dict），成功返回实例；Protocol 合规由 mypy/运行时 `typing.runtime_checkable` 或契约测试 `test_protocol_signatures.py` 检查 | 无 | P0 |
| 2 | create_conversation 抛 NotImplementedError | Engine 已实例化 | `await e.create_conversation(channel="web", external_id="c1")` | 抛 `NotImplementedError("T1A.1 (lifecycle): conversation lifecycle")` | 骨架按 hint 抛出，Phase 1 T1A.1 替换为内存实现 | 无 | P0 |
| 3 | join 抛 NotImplementedError | Engine 已实例化；对话 id 用 `"conv-1"` 字面量（骨架阶段两者都抛，create 顺序不影响；**Phase 1 复用此用例时需升级为先 `create_conversation` 取 id**，见"实现提示"）| `await e.join("conv-1", Participant(id="u1", role=CUSTOMER, joined_at=datetime.now(timezone.utc)))` | 抛 `NotImplementedError("T1A.1 (participant): participant management")` | 骨架抛出 | 无 | P0 |
| 4 | send_message 抛 NotImplementedError | 同 TC3（conv-1 字面量；Phase 1 需升级）| `await e.send_message("conv-1", source="u1", content="hi")` | 抛 `NotImplementedError("T1A.1 (messages): message CRUD")` | 骨架抛出 | 无 | P0 |
| 5 | switch_mode(AUTO→COPILOT) 抛 NotImplementedError | 同 TC3 | `await e.switch_mode("conv-1", ConversationMode.COPILOT, triggered_by="op1", trigger="manual")` | 抛 `NotImplementedError("T1A.1 (mode): mode transition")` | 骨架抛出 | 无 | P0 |
| 6 | close_conversation(RESOLVED) 抛 NotImplementedError | 同 TC3 | `await e.close_conversation("conv-1", outcome=Outcome.RESOLVED, resolved_by="op1")` | 抛 `NotImplementedError("T1A.1 (lifecycle): conversation lifecycle")` | 骨架抛出 | 无 | P0 |
| 7 | set_timer 抛 NotImplementedError（T1A.2） | Engine 已实例化 | `await e.set_timer("conv-1", "sla_first_reply", 60000, on_expire={...})` | 抛 `NotImplementedError("T1A.2: timer scheduling")` | 骨架抛出，hint 对应 T1A.2 | 无 | P0 |
| 8 | subscribe 抛 NotImplementedError（T1A.3） | Engine 已实例化 | `async for _ in e.subscribe(conversation_id="conv-1"): pass` | 抛 `NotImplementedError("T1A.3: event bus")` | 骨架抛出，hint 对应 T1A.3 | 无 | P0 |
| 9 | handle_command 抛 NotImplementedError（T2A.1） | Engine 已实例化 | `await e.handle_command("conv-1", actor_id="op1", command="/hijack")` | 抛 `NotImplementedError("T2A.1: command dispatch")` | 骨架抛出，hint 对应 T2A.1 | 无 | P1 |
| 10 | register_hook 抛 NotImplementedError（T1A.3 基础设施）| Engine 已实例化 | `e.register_hook(my_hook)` | 抛 `NotImplementedError("T1A.3 (hooks): plugin hook registry")` | 同步方法（非 async），骨架抛出 | 无 | P1 |
| 11 | Protocol 签名完整性 | 契约测试 | `pytest tests/contract/test_protocol_signatures.py` | LocalEngine 覆盖 Protocol 全部 23 方法 + PluginHook 6 钩子签名 | 骨架通过签名比对（参数名、类型、async/sync） | 无 | P0 |
| 12 | tests/contract/ 回归零 | 新 export 加到 `__init__.py` | `pytest tests/contract/` | 160 passed 保持不变（不因 `__init__.py` 追加 export 回退） | 追加一行 `from .local_engine import LocalEngine`，不触发循环 import | 无 | P0 |
| 13 | 错误路径：禁止新建 `autoservice/engine/` | — | 仓库扫描 | 只存在 `autoservice/conversation_engine/local_engine.py` | 不新建 engine/ 目录 | 无 | P0 |
| 14 | 错误路径：不重定义枚举 | — | grep `class Mode`, `class Visibility` 在 local_engine.py | 0 命中 | local_engine.py 只 import 复用 | 无 | P0 |

## 实现提示（给 Skill 3 test-code-writer）

- 用 `inspect.signature` 对 `LocalEngine` 每个方法与 `ConversationEngine.__annotations__` 逐一比对（Protocol 的方法在 `__annotations__` 或 `__dict__` 中可枚举）
- 对每个方法调用一次，断言 `pytest.raises(NotImplementedError) as exc` 且 `"T1A." in str(exc.value) or "T2A." in str(exc.value)`
- `isinstance(e, ConversationEngine)` 需 Protocol 带 `@runtime_checkable` 装饰器；若 T0.1 没加，改为 `hasattr(e, method_name) for method_name in PROTOCOL_METHODS`
- **TC3-6 复用为回归测试的升级路径**（Phase 1 T1A.1 落地后）：
  - 在 fixture 里先 `conv = await engine.create_conversation(channel="web", external_id="c1")`
  - 用例改写为 `await engine.join(conv.id, ...)` 等，同一断言从 `raises NotImplementedError` 改为验证实际状态（参与者加入、消息持久化等）
  - 骨架阶段保留字面量 `"conv-1"` 是权宜，test-plan 需在 Phase 1 复用时同步升级

## 风险与缓解

| 风险 | 可能性 | 缓解 |
|---|---|---|
| `__init__.py` 追加 export 引发循环 import | 低 | local_engine 只依赖同包 protocol/types/events/errors，不反向 import 上层 |
| `subscribe` 声明为 `async def` 但返回 `AsyncIterator`（生成器语义）| 中 | 骨架写成 `async def subscribe(...) -> AsyncIterator[Event]: raise NotImplementedError(...); yield`（yield 后才是生成器）。**决议**：按 T0.1 Protocol 字面，`async def ... -> AsyncIterator[...]`；骨架体直接 raise，不加 yield（mypy/Protocol 只看签名） |
| T0.3 契约测试已对 LocalEngine 有隐式断言（60 skipped 可能是等待 LocalEngine）| 高 | 测试运行后若从 60 skipped 变为 N failed，优先读失败用例判断是否需要调整骨架行为；不改 T0.1 产物 |

## 后续行动

- [x] eval-doc 已注册到 .artifacts/eval-docs/
- [ ] 用户已确认 testcase 表格 (status: draft → confirmed)
- [ ] 流转至 skill-2-test-plan-generator 产出 test-plan
