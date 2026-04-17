---
type: test-plan
id: test-plan-003
status: confirmed
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-doc-003 (T1A.1 Mode/Gate 最小实现)"
related:
  - eval-doc-003
  - test-plan-001  # T0.4 skeleton tests (predecessor)
---

# Test Plan: T1A.1 Mode/Gate 最小实现

## 触发原因

eval-doc-003 确认 T1A.1 实现范围：会话生命周期、参与者管理、Mode 状态机、Gate 可见性、消息 CRUD。当前 LocalEngine 全部 18 个方法为 `NotImplementedError` stub。实现后需要：

1. **契约测试通过** — `tests/contract/` 中 test_mode.py (4 cases)、test_gate.py (5 cases) 及其他相关测试注册 LocalEngine factory 后应全绿
2. **LocalEngine 单元测试** — 内存存储、幂等逻辑、边界条件
3. **T0.4 stub 测试退役** — `tests/conversation_engine/test_local_engine.py` 中 TC-001~TC-025 的 NotImplementedError 断言改为功能性断言

## 策略

- **契约测试不需要新写** — 已在 T0.3 产出，只需注册 LocalEngine factory
- **新写 LocalEngine 单元测试** — 覆盖 eval-doc-003 的 27 个 testcase 中契约测试未覆盖的场景
- **测试文件**: `tests/conversation_engine/test_local_engine.py`（替换现有 stub 测试）
- **conftest 补充**: 注册 LocalEngine 到 contract test factory

## 用例列表

### TC-001: 创建会话基本流程

- **来源**：eval-doc-003 #1
- **优先级**：P0
- **前置条件**：空 LocalEngine 实例
- **操作步骤**：
  1. `create_conversation(channel="web", external_id="sess_1")`
- **预期结果**：返回 Conversation(id="web_sess_1", state=CREATED, mode=AUTO, participants=())
- **涉及模块**：conversation_engine/local_engine.py

### TC-002: 创建会话幂等

- **来源**：eval-doc-003 #2
- **优先级**：P0
- **前置条件**：web_sess_1 已存在，state != CLOSED
- **操作步骤**：
  1. `create_conversation(channel="web", external_id="sess_1")` 再次调用
- **预期结果**：返回同一个 Conversation 对象（id 相同），不创建新的
- **涉及模块**：conversation_engine/local_engine.py

### TC-003: 获取不存在会话抛异常

- **来源**：eval-doc-003 #4
- **优先级**：P0
- **前置条件**：无 "web_nonexist" 会话
- **操作步骤**：
  1. `get_conversation("web_nonexist")`
- **预期结果**：抛 `ConversationNotFound`
- **涉及模块**：conversation_engine/local_engine.py, errors.py

### TC-004: 关闭会话 + Resolution

- **来源**：eval-doc-003 #5
- **优先级**：P0
- **前置条件**：web_sess_1 exists, state=ACTIVE
- **操作步骤**：
  1. `close_conversation("web_sess_1", outcome=RESOLVED, resolved_by="op_1")`
  2. `get_conversation("web_sess_1")`
- **预期结果**：state=CLOSED, resolution.outcome=RESOLVED, resolution.resolved_by="op_1"
- **涉及模块**：conversation_engine/local_engine.py

### TC-005: 关闭会话幂等

- **来源**：eval-doc-003 #6
- **优先级**：P1
- **前置条件**：web_sess_1 已 CLOSED
- **操作步骤**：
  1. `close_conversation("web_sess_1", outcome=RESOLVED, resolved_by="op_1")` 再次调用
- **预期结果**：返回现有 Conversation，不报错
- **涉及模块**：conversation_engine/local_engine.py

### TC-006: operator join 触发 auto→copilot

- **来源**：eval-doc-003 #7
- **优先级**：P0
- **前置条件**：会话 mode=AUTO
- **操作步骤**：
  1. `join(conv_id, Participant(id="op_1", role=OPERATOR))`
  2. `get_conversation(conv_id)`
- **预期结果**：参与者列表包含 op_1；mode=COPILOT
- **涉及模块**：conversation_engine/local_engine.py

### TC-007: join 幂等

- **来源**：eval-doc-003 #8
- **优先级**：P1
- **前置条件**：op_1 已在会话中
- **操作步骤**：
  1. `join(conv_id, op_1)` 再次调用
- **预期结果**：不报错，participants 中 op_1 仍只出现一次
- **涉及模块**：conversation_engine/local_engine.py

### TC-008: 最后 operator leave → copilot→auto

- **来源**：eval-doc-003 #9, §7.1 不变量 #8
- **优先级**：P0
- **前置条件**：mode=COPILOT, 仅 op_1 一个 OPERATOR
- **操作步骤**：
  1. `leave(conv_id, "op_1")`
  2. `get_conversation(conv_id)`
- **预期结果**：op_1 不在 participants 中；mode=AUTO
- **涉及模块**：conversation_engine/local_engine.py

### TC-009: switch_mode auto→takeover

- **来源**：eval-doc-003 #10
- **优先级**：P0
- **前置条件**：mode=AUTO, operator 已 join
- **操作步骤**：
  1. `switch_mode(conv_id, TAKEOVER, triggered_by="op_1", trigger="/hijack")`
  2. `get_conversation(conv_id)`
- **预期结果**：mode=TAKEOVER
- **涉及模块**：conversation_engine/local_engine.py

### TC-010: switch_mode 同态 noop (Q4)

- **来源**：eval-doc-003 #11, 契约 test_mode.py
- **优先级**：P0
- **前置条件**：mode=COPILOT
- **操作步骤**：
  1. `switch_mode(conv_id, COPILOT, triggered_by="op_1", trigger="/copilot")`
- **预期结果**：不抛异常；发 mode.noop 事件
- **涉及模块**：conversation_engine/local_engine.py
- **注意**：契约测试 test_mode.py:37 已覆盖此场景，需 subscribe 支持

### TC-011: switch_mode on closed → IllegalModeTransition

- **来源**：eval-doc-003 #12, 契约 test_mode.py
- **优先级**：P0
- **前置条件**：state=CLOSED
- **操作步骤**：
  1. `switch_mode(conv_id, TAKEOVER, triggered_by="op_1", trigger="/hijack")`
- **预期结果**：抛 `IllegalModeTransition`
- **涉及模块**：conversation_engine/local_engine.py, errors.py

### TC-012: 并发 switch_mode 串行化 (§7.1 #3)

- **来源**：eval-doc-003 #13, 契约 test_mode.py
- **优先级**：P1
- **前置条件**：mode=COPILOT, 10 并发请求
- **操作步骤**：
  1. `asyncio.gather(*(switch_mode(...) for _ in range(10)))` toggle TAKEOVER/COPILOT
- **预期结果**：无 torn state，final mode 是合法枚举值
- **涉及模块**：conversation_engine/local_engine.py

### TC-013: Gate — copilot + operator PUBLIC→SIDE

- **来源**：eval-doc-003 #14, 契约 test_gate.py
- **优先级**：P0
- **前置条件**：mode=COPILOT, operator + customer + agent 已 join
- **操作步骤**：
  1. `send_message(conv_id, source="op_1", content="...", requested_visibility=PUBLIC)`
- **预期结果**：返回 Message(visibility=SIDE)
- **涉及模块**：conversation_engine/local_engine.py

### TC-014: Gate — takeover + agent PUBLIC→SIDE

- **来源**：eval-doc-003 #15, 契约 test_gate.py
- **优先级**：P0
- **前置条件**：mode=TAKEOVER
- **操作步骤**：
  1. `send_message(conv_id, source="agent_1", content="...", requested_visibility=PUBLIC)`
- **预期结果**：返回 Message(visibility=SIDE)
- **涉及模块**：conversation_engine/local_engine.py

### TC-015: Gate — auto + agent PUBLIC 不降级

- **来源**：eval-doc-003 #16, 契约 test_gate.py
- **优先级**：P0
- **前置条件**：mode=AUTO
- **操作步骤**：
  1. `send_message(conv_id, source="agent_1", content="...", requested_visibility=PUBLIC)`
- **预期结果**：返回 Message(visibility=PUBLIC)
- **涉及模块**：conversation_engine/local_engine.py

### TC-016: Gate — requested=SIDE 不升级 (Q5)

- **来源**：eval-doc-003 #17, 契约 test_gate.py
- **优先级**：P0
- **前置条件**：任意 mode
- **操作步骤**：
  1. `send_message(conv_id, source="agent_1", requested_visibility=SIDE)`
- **预期结果**：visibility=SIDE（不被升级为 PUBLIC）
- **涉及模块**：conversation_engine/local_engine.py

### TC-017: Gate 降级不可逆 (§7.1 #5)

- **来源**：eval-doc-003 #18, 契约 test_gate.py
- **优先级**：P0
- **前置条件**：takeover 下 agent 发 PUBLIC→SIDE 消息已存在
- **操作步骤**：
  1. `/release` 切回 auto
  2. `get_messages(conv_id)` 查回该消息
- **预期结果**：消息 visibility 仍为 SIDE
- **涉及模块**：conversation_engine/local_engine.py

### TC-018: send_message 序列号递增

- **来源**：eval-doc-003 #19
- **优先级**：P0
- **前置条件**：已有 2 条消息
- **操作步骤**：
  1. `send_message(conv_id, source="cust_1", content="msg3")`
- **预期结果**：返回 Message(sequence_number=3)
- **涉及模块**：conversation_engine/local_engine.py

### TC-019: edit_message 占位续写

- **来源**：eval-doc-003 #20
- **优先级**：P0
- **前置条件**：msg_1 存在
- **操作步骤**：
  1. `edit_message(conv_id, msg_1.id, new_content="full reply", edited_by="agent_1")`
- **预期结果**：返回 Message(edit_of=msg_1.id, content="full reply")
- **涉及模块**：conversation_engine/local_engine.py

### TC-020: get_messages 按 viewer_role 过滤 (Q9)

- **来源**：eval-doc-003 #21
- **优先级**：P1
- **前置条件**：SIDE 消息存在
- **操作步骤**：
  1. `get_messages(conv_id, viewer_role=CUSTOMER)`
- **预期结果**：返回列表不含 SIDE 消息
- **涉及模块**：conversation_engine/local_engine.py

### TC-021: get_messages since_sequence

- **来源**：eval-doc-003 #22
- **优先级**：P1
- **前置条件**：5 条消息 (seq 1-5)
- **操作步骤**：
  1. `get_messages(conv_id, since_sequence=3)`
- **预期结果**：返回 seq=4, 5 的消息
- **涉及模块**：conversation_engine/local_engine.py

### TC-022: get_messages before_sequence

- **来源**：eval-doc-003 (补充)
- **优先级**：P1
- **前置条件**：5 条消息 (seq 1-5)
- **操作步骤**：
  1. `get_messages(conv_id, before_sequence=4, limit=2)`
- **预期结果**：返回 seq=2, 3 的消息（向上翻页）
- **涉及模块**：conversation_engine/local_engine.py

### TC-023: get_messages since + before 互斥

- **来源**：eval-doc-003 #23
- **优先级**：P1
- **前置条件**：任意
- **操作步骤**：
  1. `get_messages(conv_id, since_sequence=1, before_sequence=5)`
- **预期结果**：抛 `ValidationError`
- **涉及模块**：conversation_engine/local_engine.py, errors.py

### TC-024: set_csat 有效

- **来源**：eval-doc-003 #24
- **优先级**：P1
- **前置条件**：会话已 resolved
- **操作步骤**：
  1. `set_csat(conv_id, score=4)`
  2. `get_conversation(conv_id)`
- **预期结果**：resolution.csat_score=4
- **涉及模块**：conversation_engine/local_engine.py

### TC-025: set_csat 无效分数

- **来源**：eval-doc-003 #25
- **优先级**：P2
- **前置条件**：会话已 resolved
- **操作步骤**：
  1. `set_csat(conv_id, score=0)`
- **预期结果**：抛 `ValidationError`
- **涉及模块**：conversation_engine/local_engine.py, errors.py

### TC-026: list_active_conversations 全部

- **来源**：eval-doc-003 #26
- **优先级**：P1
- **前置条件**：3 active + 1 closed 会话
- **操作步骤**：
  1. `list_active_conversations()`
- **预期结果**：返回 3 个 active 会话（不含 closed）
- **涉及模块**：conversation_engine/local_engine.py

### TC-027: list_active_conversations by operator_id

- **来源**：eval-doc-003 #27
- **优先级**：P1
- **前置条件**：op_1 参与 2 个会话
- **操作步骤**：
  1. `list_active_conversations(operator_id="op_1")`
- **预期结果**：返回 op_1 参与的 2 个会话
- **涉及模块**：conversation_engine/local_engine.py

### TC-028: 契约测试 factory 注册

- **来源**：coverage-gap（契约测试全部 skip 因无 factory）
- **优先级**：P0
- **前置条件**：LocalEngine 实现完成
- **操作步骤**：
  1. 在 `tests/conversation_engine/conftest.py` 注册 LocalEngine factory
  2. 运行 `pytest tests/contract/ -v`
- **预期结果**：test_mode.py (4 tests) + test_gate.py (5 tests) + 其他契约测试全绿
- **涉及模块**：tests/conversation_engine/conftest.py, tests/contract/

### TC-029: 简易事件缓冲（内部）

- **来源**：eval-doc-003 风险 #1
- **优先级**：P0
- **前置条件**：LocalEngine 实例
- **操作步骤**：
  1. `subscribe(conversation_id=conv_id, event_types=["mode.changed"])`
  2. `switch_mode(conv_id, TAKEOVER, ...)`
  3. 从 subscribe iterator 读取事件
- **预期结果**：收到 mode.changed 事件（subscribe 和事件发送基础可用）
- **涉及模块**：conversation_engine/local_engine.py
- **注意**：T1A.3 会替换为完整 EventBus，但 T1A.1 需最小事件支持以通过契约测试

### TC-030: delete_message

- **来源**：补充（eval-doc 未显式列出但在实现范围内）
- **优先级**：P1
- **前置条件**：msg_1 存在
- **操作步骤**：
  1. `delete_message(conv_id, msg_1.id, deleted_by="op_1")`
  2. `get_messages(conv_id)`
- **预期结果**：msg_1 不在返回列表中
- **涉及模块**：conversation_engine/local_engine.py

## 统计

| 指标 | 值 |
|------|-----|
| 总用例数 | 30 |
| P0 | 17 |
| P1 | 11 |
| P2 | 2 |
| 来源：eval-doc | 27 |
| 来源：coverage-gap | 1 |
| 来源：补充 | 2 |

## 风险标注

- **高风险**：Gate 矩阵（TC-013~017）— 6 种 mode×role 组合必须全部正确，任何一个错误导致消息泄露给客户
- **高风险**：Mode 自动切换（TC-006, TC-008）— operator join/leave 联动 mode 切换是核心业务逻辑
- **事件依赖**：TC-010, TC-029 依赖 subscribe 基础可用。T1A.1 需实现最小事件缓冲（asyncio.Queue fan-out），否则 4 个契约测试（test_mode.py Q4 + test_gate.py message.gated）会失败
- **覆盖未知**：无 coverage-matrix artifact，所有场景视为新增覆盖
