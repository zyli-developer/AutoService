---
type: test-plan
id: test-plan-001
status: draft
producer: skill-2
created_at: "2026-04-15"
trigger: "eval-doc-001 (T0.4 LocalEngine skeleton simulate)"
related:
  - eval-doc-001
  - "protocol:autoservice/conversation_engine/protocol.py"
  - "task:T0.4"
scope_note: "骨架任务 — 所有方法体 raise NotImplementedError。测试重点：Protocol 合规、枚举/异常覆盖、hint 正确性、契约回归。不测业务逻辑。"
---

# Test Plan: T0.4 LocalEngine 骨架

## 触发原因

eval-doc-001 为 T0.4 LocalEngine 骨架定义了 14 个 testcase。本 test-plan 把这些 eval 用例转化为可执行的单测（目标：`tests/conversation_engine/test_local_engine.py`），并补充 eval-doc 未显式列出的机械化验证点（Protocol 方法逐一枚举、异常类型层级、导出完整性、tests/contract/ 回归）。

## 测试文件位置

- 主文件：`tests/conversation_engine/test_local_engine.py`（新建）
- 目录初始化：`tests/conversation_engine/__init__.py`（空文件）
- 契约回归：沿用 `tests/contract/` 现有 160 passed + 60 skipped

## 统一前置

所有 async 用例使用 `pytest-asyncio`（若尚未安装，加入 `dev-requirements`）。共享 fixtures：

```python
@pytest.fixture
def engine() -> LocalEngine:
    from autoservice.conversation_engine import LocalEngine
    return LocalEngine()

@pytest.fixture
def participant_customer() -> Participant:
    from datetime import datetime, timezone
    return Participant(
        id="u-customer-1",
        role=ParticipantRole.CUSTOMER,
        joined_at=datetime.now(timezone.utc),
    )
```

## 用例列表

### 分组 A · 导入与实例化（TC-001 ~ TC-003）

#### TC-001: LocalEngine 可从 __init__ 导入

- **来源**：eval-doc-001 TC1, 扩展
- **优先级**：P0
- **前置条件**：M0 产物齐全 + local_engine.py 已建 + `__init__.py` 末尾追加 `from .local_engine import LocalEngine`
- **操作步骤**：
  1. `from autoservice.conversation_engine import LocalEngine`
- **预期结果**：导入成功，无 ImportError / CircularImportError
- **涉及模块**：`autoservice.conversation_engine.__init__`, `autoservice.conversation_engine.local_engine`

#### TC-002: LocalEngine 可实例化

- **来源**：eval-doc-001 TC1
- **优先级**：P0
- **前置条件**：TC-001 通过
- **操作步骤**：
  1. `e = LocalEngine()`
- **预期结果**：不抛异常；返回 LocalEngine 实例
- **涉及模块**：`LocalEngine.__init__`

#### TC-003: LocalEngine 结构上满足 ConversationEngine Protocol

- **来源**：eval-doc-001 TC1, TC11 合并
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. 定义常量 `PROTOCOL_METHODS = ["create_conversation", "get_conversation", "list_active_conversations", "close_conversation", "set_csat", "join", "leave", "switch_mode", "send_message", "edit_message", "delete_message", "get_messages", "handle_command", "set_timer", "cancel_timer", "subscribe", "query_events", "register_hook"]`
  2. 对每个方法名执行 `assert hasattr(e, name) and callable(getattr(e, name))`
  3. 若 `ConversationEngine` 标注 `@runtime_checkable`，额外断言 `isinstance(e, ConversationEngine)`；否则跳过（skip + reason）
- **预期结果**：18 个方法全部存在且可调用（`register_hook` 是同步；其余 17 个 async）
- **涉及模块**：`LocalEngine`, `ConversationEngine` (Protocol)

### 分组 B · Protocol 方法抛 NotImplementedError（TC-004 ~ TC-021）

#### TC-004: create_conversation 抛 NotImplementedError 含 T1A.1 hint

- **来源**：eval-doc-001 TC2
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError) as exc: await engine.create_conversation(channel="web", external_id="c1")`
  2. 断言 `"T1A.1" in str(exc.value) and "lifecycle" in str(exc.value).lower()`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.1 (lifecycle)"`
- **涉及模块**：`LocalEngine.create_conversation`

#### TC-005: get_conversation 抛 NotImplementedError 含 T1A.1 hint

- **来源**：eval-doc-001 扩展（eval-doc 原未显式列此方法）
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError): await engine.get_conversation("conv-x")`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.1"`
- **涉及模块**：`LocalEngine.get_conversation`

#### TC-006: list_active_conversations 抛 NotImplementedError 含 T1A.1 hint

- **来源**：eval-doc-001 扩展
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError): await engine.list_active_conversations()`
  2. `with pytest.raises(NotImplementedError): await engine.list_active_conversations(operator_id="op1")`
  3. `with pytest.raises(NotImplementedError): await engine.list_active_conversations(squad_id="sq1")`
- **预期结果**：三次调用均抛 NotImplementedError，消息含 `"T1A.1"`
- **涉及模块**：`LocalEngine.list_active_conversations`

#### TC-007: close_conversation 抛 NotImplementedError 含 T1A.1 hint

- **来源**：eval-doc-001 TC6
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError): await engine.close_conversation("conv-1", outcome=Outcome.RESOLVED, resolved_by="op1")`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.1"` 和 `"lifecycle"`
- **涉及模块**：`LocalEngine.close_conversation`

#### TC-008: set_csat 抛 NotImplementedError 含 T1A.1 hint

- **来源**：eval-doc-001 扩展
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError): await engine.set_csat("conv-1", 5)`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.1"`
- **涉及模块**：`LocalEngine.set_csat`

#### TC-009: join 抛 NotImplementedError 含 T1A.1 participant hint

- **来源**：eval-doc-001 TC3
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError) as exc: await engine.join("conv-1", participant_customer)`
  2. 断言 `"T1A.1" in str(exc.value) and "participant" in str(exc.value).lower()`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.1 (participant)"`
- **涉及模块**：`LocalEngine.join`

#### TC-010: leave 抛 NotImplementedError 含 T1A.1 participant hint

- **来源**：eval-doc-001 扩展
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError): await engine.leave("conv-1", "u-customer-1")`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.1"` 和 `"participant"`
- **涉及模块**：`LocalEngine.leave`

#### TC-011: switch_mode(AUTO→COPILOT) 抛 NotImplementedError 含 T1A.1 mode hint

- **来源**：eval-doc-001 TC5
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError) as exc: await engine.switch_mode("conv-1", ConversationMode.COPILOT, triggered_by="op1", trigger="manual")`
  2. 断言 `"T1A.1" in str(exc.value) and "mode" in str(exc.value).lower()`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.1 (mode)"`
- **涉及模块**：`LocalEngine.switch_mode`

#### TC-012: send_message 抛 NotImplementedError 含 T1A.1 messages hint

- **来源**：eval-doc-001 TC4
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError) as exc: await engine.send_message("conv-1", source="u1", content="hi")`
  2. 断言 `"T1A.1" in str(exc.value) and ("message" in str(exc.value).lower() or "crud" in str(exc.value).lower())`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.1 (messages)"`
- **涉及模块**：`LocalEngine.send_message`

#### TC-013: edit_message 抛 NotImplementedError 含 T1A.1 messages hint

- **来源**：eval-doc-001 扩展
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError): await engine.edit_message("conv-1", "msg-1", new_content="edited", edited_by="u1")`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.1"` 和 `"messages"`
- **涉及模块**：`LocalEngine.edit_message`

#### TC-014: delete_message 抛 NotImplementedError 含 T1A.1 messages hint

- **来源**：eval-doc-001 扩展
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError): await engine.delete_message("conv-1", "msg-1", deleted_by="u1")`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.1"` 和 `"messages"`
- **涉及模块**：`LocalEngine.delete_message`

#### TC-015: get_messages 抛 NotImplementedError 含 T1A.1 messages hint

- **来源**：eval-doc-001 扩展
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError): await engine.get_messages("conv-1")`
  2. `with pytest.raises(NotImplementedError): await engine.get_messages("conv-1", since_sequence=10)`
  3. `with pytest.raises(NotImplementedError): await engine.get_messages("conv-1", before_sequence=10)`
- **预期结果**：三次调用均抛 NotImplementedError，消息含 `"T1A.1"`
- **涉及模块**：`LocalEngine.get_messages`

#### TC-016: handle_command 抛 NotImplementedError 含 T2A.1 hint

- **来源**：eval-doc-001 TC9
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError) as exc: await engine.handle_command("conv-1", actor_id="op1", command="/hijack")`
  2. 断言 `"T2A.1" in str(exc.value)`
- **预期结果**：抛 NotImplementedError，消息含 `"T2A.1"` 和 `"command"`
- **涉及模块**：`LocalEngine.handle_command`

#### TC-017: set_timer 抛 NotImplementedError 含 T1A.2 hint

- **来源**：eval-doc-001 TC7
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError) as exc: await engine.set_timer("conv-1", "sla_first_reply", 60000, on_expire={"action": "noop"})`
  2. 断言 `"T1A.2" in str(exc.value) and "timer" in str(exc.value).lower()`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.2"` 和 `"timer"`
- **涉及模块**：`LocalEngine.set_timer`

#### TC-018: cancel_timer 抛 NotImplementedError 含 T1A.2 hint

- **来源**：eval-doc-001 扩展
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError): await engine.cancel_timer("conv-1", "sla_first_reply")`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.2"`
- **涉及模块**：`LocalEngine.cancel_timer`

#### TC-019: subscribe 抛 NotImplementedError 含 T1A.3 hint

- **来源**：eval-doc-001 TC8
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError) as exc:` `async for _ in engine.subscribe(conversation_id="conv-1"): pass`
  2. 断言 `"T1A.3" in str(exc.value) and ("event" in str(exc.value).lower() or "bus" in str(exc.value).lower())`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.3"`。注意：若 `subscribe` 实现为 `async def -> AsyncIterator`（未 yield），直接 raise 会在 await 调用点抛出；测试需能正确捕获
- **涉及模块**：`LocalEngine.subscribe`
- **实现提示**：骨架可写为

  ```python
  async def subscribe(self, *, conversation_id=None, ...) -> AsyncIterator[Event]:
      raise NotImplementedError("T1A.3: event bus")
      yield  # 让 mypy/runtime 识别为 async generator（死代码）
  ```

  或返回一个立即 raise 的 async generator 工厂。两种都可行，TC-019 测试要点是"尝试迭代时抛错"。

#### TC-020: query_events 抛 NotImplementedError 含 T1A.3 hint

- **来源**：eval-doc-001 扩展
- **优先级**：P0
- **前置条件**：TC-002 通过
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError): await engine.query_events("conv-1")`
- **预期结果**：抛 NotImplementedError，消息含 `"T1A.3"`
- **涉及模块**：`LocalEngine.query_events`

#### TC-021: register_hook 抛 NotImplementedError 含 T1A.3 hooks hint（同步方法）

- **来源**：eval-doc-001 TC10（映射修正后从 T1A.7 改为 T1A.3）
- **优先级**：P1
- **前置条件**：TC-002 通过 + 定义 dummy hook 对象（`class DummyHook: pass`）
- **操作步骤**：
  1. `with pytest.raises(NotImplementedError) as exc: engine.register_hook(DummyHook())`（注意**无 await**）
  2. 断言 `"T1A.3" in str(exc.value) and "hook" in str(exc.value).lower()`
- **预期结果**：同步抛 NotImplementedError，消息含 `"T1A.3 (hooks)"`
- **涉及模块**：`LocalEngine.register_hook`

### 分组 C · 骨架边界（TC-022 ~ TC-024）

#### TC-022: 每个 NotImplementedError hint 至少含一个有效 T-ID

- **来源**：eval-doc-001 TC11 扩展（机械化正则）
- **优先级**：P1
- **前置条件**：TC-004 ~ TC-021 通过
- **操作步骤**：
  1. 对 18 个 Protocol 方法逐一触发（用参数化测试）
  2. 捕获每个 `NotImplementedError`
  3. 用正则 `r"T[12]A\.\d+"` 匹配消息，断言至少一命中
- **预期结果**：18 次全部匹配
- **涉及模块**：`LocalEngine.*` 全部方法
- **实现提示**：用 `pytest.mark.parametrize` 拉平

#### TC-023: `autoservice/engine/` 目录不存在（路径错误路径检测）

- **来源**：eval-doc-001 TC13
- **优先级**：P0
- **前置条件**：—
- **操作步骤**：
  1. `import pathlib; assert not (pathlib.Path("autoservice/engine").exists())`
- **预期结果**：该目录不存在
- **涉及模块**：项目结构

#### TC-024: local_engine.py 不重定义枚举

- **来源**：eval-doc-001 TC14
- **优先级**：P0
- **前置条件**：—
- **操作步骤**：
  1. 读取 `autoservice/conversation_engine/local_engine.py` 文本
  2. 断言不含 `"class Mode"`, `"class Visibility"`, `"class ConversationMode"`, `"class MessageVisibility"`, `"class EventType"`, `"class ParticipantRole"`, `"class Outcome"`, `"class ConversationState"`
- **预期结果**：零命中
- **涉及模块**：`autoservice.conversation_engine.local_engine`

### 分组 D · __init__ 导出与契约回归（TC-025 ~ TC-026）

#### TC-025: `autoservice.conversation_engine.__all__` 含 LocalEngine

- **来源**：eval-doc-001 TC12 扩展
- **优先级**：P0
- **前置条件**：`__init__.py` 已追加 `from .local_engine import LocalEngine`
- **操作步骤**：
  1. `from autoservice import conversation_engine as ce`
  2. 断言 `"LocalEngine" in ce.__all__` 或 `hasattr(ce, "LocalEngine")`（取决于是否同步加 `__all__`）
  3. 断言 T0.1 原有 export 仍在（`ConversationEngine`, `ConversationMode`, `Message`, ...）不少于 23 个名字
- **预期结果**：LocalEngine 可用；T0.1 所有原 export 保留
- **涉及模块**：`autoservice.conversation_engine.__init__`

#### TC-026: tests/contract/ 回归零

- **来源**：eval-doc-001 TC12
- **优先级**：P0（**blocking gate**）
- **前置条件**：TC-001 ~ TC-025 通过，骨架代码落地
- **操作步骤**：
  1. `pytest tests/contract/ -v`
  2. 断言 `160 passed` 不下降；skipped 数可从 60 → 更低（骨架落地后部分原 skipped 用例可能变绿）
- **预期结果**：passed ≥ 160，failed == 0
- **涉及模块**：`tests/contract/*`
- **说明**：此用例不作为 `tests/conversation_engine/test_local_engine.py` 的一部分，而是 skill-4 test-runner 的门禁步骤

## 统计

| 指标 | 值 |
|------|-----|
| 总用例数 | 26 |
| P0 | 24 |
| P1 | 2 |
| P2 | 0 |
| 来源：eval-doc-001 | 14（直接） + 11（扩展） |
| 来源：code-diff | 0（无，骨架任务） |
| 来源：coverage-gap | 0（Phase 0 无 coverage matrix） |
| 来源：bug-feedback | 0 |

## 风险标注

- **高风险**：
  - `__init__.py` 追加 export 引发循环 import（TC-001 未通过会阻断全部下游）
  - `tests/contract/ passed` 下降（TC-026 是 blocking gate，回退动作：撤销 `__init__.py` 改动）

- **回归风险**：
  - 60 skipped 契约用例中，部分可能是等待 LocalEngine 的（如 `test_protocol_signatures.py::...`），骨架落地后可能从 skipped → failed（暴露骨架不足）。预案：若出现 failed，优先读测试名判断是"骨架该抛什么"vs"骨架签名错"。

- **覆盖未知**：
  - 无 coverage-matrix artifact（Phase 0 尚未建立），本计划无法标注"已有覆盖被改动影响"。M0.5 后 skill-0 应重跑 coverage-matrix。

## 依赖 skill-3 的实现约束

1. **测试框架**：pytest + pytest-asyncio（需 dev-requirements 加入）
2. **目录新建**：`tests/conversation_engine/__init__.py`（空）+ `tests/conversation_engine/test_local_engine.py`
3. **共享 fixtures**：写在 `tests/conversation_engine/conftest.py`（engine、participant_customer 等）
4. **参数化**：TC-022 用 `pytest.mark.parametrize` 枚举 18 个方法名；TC-004-021 各自独立（便于失败定位）
5. **async 用例**：使用 `@pytest.mark.asyncio`
6. **不 import pytest 以外**：除 pytest 和 autoservice.* 外不引入新依赖

## 后续行动

- [x] test-plan 已注册到 .artifacts/test-plans/ (test-plan-001)
- [ ] 用户 review + 确认 (status: draft → confirmed)
- [ ] 流转 skill-3-test-code-writer 生成测试代码
- [ ] 流转 skill-4-test-runner 执行 + 归档
