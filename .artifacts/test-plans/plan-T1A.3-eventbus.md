---
type: test-plan
id: test-plan-003
status: draft
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-doc-004 (T1A.3 EventBus simulate)"
related:
  - eval-doc-004
---

# Test Plan: T1A.3 EventBus 最小实现

## 触发原因

eval-doc-004 模拟评估了 T1A.3 EventBus 的 18 个场景。当前 LocalEngine 仅有最小 fan-out（`_subscribers` Queue 列表），缺少：
- squad_id scope 过滤
- since_sequence 断点续传
- viewer_role 事件过滤
- SQLite 异步持久化
- Plugin Hook 分发 + 异常隔离（Q8c）

本计划将 eval-doc testcase 转换为可执行的 pytest 用例，覆盖所有 P0 + P1 场景。

## 用例列表

### TC-001: EventBus 类可导入和实例化

- **来源**：eval-doc（结构验证）
- **优先级**：P0
- **前置条件**：无
- **操作步骤**：
  1. `from autoservice.conversation_engine.event_bus import EventBus`
  2. `bus = EventBus()` 或 `bus = EventBus(db_path=":memory:")`
- **预期结果**：导入成功，实例化不报错
- **涉及模块**：event_bus

### TC-002: emit 事件后 subscribe 收到（单会话 scope）

- **来源**：eval-doc #1
- **优先级**：P0
- **前置条件**：engine 已创建 conv，customer 已 join
- **操作步骤**：
  1. 启动 `subscribe(conversation_id=conv_id)` 协程
  2. 另一协程调用 `send_message`
- **预期结果**：subscriber 收到 `message.sent` 事件，event.conversation_id == conv_id
- **涉及模块**：local_engine, event_bus

### TC-003: subscribe event_types 过滤

- **来源**：eval-doc #2
- **优先级**：P0
- **前置条件**：engine 已创建 conv，customer + operator 已 join
- **操作步骤**：
  1. `subscribe(conversation_id=conv_id, event_types=["mode.changed"])`
  2. 发消息（产生 message.sent）+ 切 mode（产生 mode.changed）
- **预期结果**：subscriber 仅收到 `mode.changed`，不收到 `message.sent`
- **涉及模块**：local_engine, event_bus

### TC-004: subscribe squad_id scope 过滤

- **来源**：eval-doc #3
- **优先级**：P0
- **前置条件**：engine 有 conv-A（metadata squad_id="s1"）和 conv-B（squad_id="s2"）
- **操作步骤**：
  1. `subscribe(squad_id="s1")`
  2. conv-A 和 conv-B 各发消息
- **预期结果**：subscriber 仅收到 conv-A 的事件
- **涉及模块**：local_engine, event_bus

### TC-005: subscribe 全局 scope（无参数）

- **来源**：eval-doc #4
- **优先级**：P1
- **前置条件**：engine 有 2 个 conv
- **操作步骤**：
  1. `subscribe()` 无 scope 参数
  2. 两个 conv 各发消息
- **预期结果**：subscriber 收到所有 conv 的事件
- **涉及模块**：local_engine, event_bus

### TC-006: since_sequence 断点续传（conv scope）

- **来源**：eval-doc #5
- **优先级**：P0
- **前置条件**：conv 已产生 5 个事件（seq 1-5）
- **操作步骤**：
  1. `subscribe(conversation_id=conv_id, since_sequence=3)`
  2. 收集回放事件
  3. 在回放后再发新消息，收集实时事件
- **预期结果**：先收到 seq 4, 5 的历史事件，然后收到新的实时事件；无间隙无重复
- **涉及模块**：local_engine, event_bus

### TC-007: since_sequence 断点续传（squad/global scope, ULID）

- **来源**：eval-doc #6
- **优先级**：P1
- **前置条件**：多个 conv 已产生事件
- **操作步骤**：
  1. 记录某个事件的 event_id（ULID）
  2. `subscribe(squad_id="s1", since_sequence="<that_ulid>")`
- **预期结果**：回放该 ULID 之后的历史事件（按 ULID 字典序），然后实时流
- **涉及模块**：local_engine, event_bus

### TC-008: viewer_role 过滤 SIDE 事件

- **来源**：eval-doc #7
- **优先级**：P1
- **前置条件**：conv 处于 copilot mode，operator 发了 PUBLIC（被 Gate 降级为 SIDE）
- **操作步骤**：
  1. `subscribe(conversation_id=conv_id, viewer_role=CUSTOMER)`
  2. operator 发 PUBLIC 消息（Gate 降为 SIDE）
  3. customer 发 PUBLIC 消息
- **预期结果**：subscriber 仅收到 customer 的 message.sent，不收到 SIDE 的 message.sent
- **涉及模块**：local_engine, event_bus

### TC-009: query_events 基本查询 + limit

- **来源**：eval-doc #8
- **优先级**：P0
- **前置条件**：conv 已产生 10+ 事件
- **操作步骤**：
  1. `query_events(conv_id, limit=5)`
- **预期结果**：返回前 5 个事件，按 sequence_number 递增
- **涉及模块**：local_engine, event_bus

### TC-010: query_events 按类型过滤

- **来源**：eval-doc #9
- **优先级**：P1
- **前置条件**：conv 有 message.sent + mode.changed 事件
- **操作步骤**：
  1. `query_events(conv_id, types=["mode.changed"])`
- **预期结果**：仅返回 mode.changed 类型事件
- **涉及模块**：local_engine, event_bus

### TC-011: query_events since_sequence + until

- **来源**：eval-doc #10
- **优先级**：P1
- **前置条件**：conv 有跨时间的多个事件
- **操作步骤**：
  1. `query_events(conv_id, since_sequence=3, until=some_time)`
- **预期结果**：返回 seq > 3 且 timestamp <= until 的事件
- **涉及模块**：local_engine, event_bus

### TC-012: SQLite 持久化 — 事件写入后可查询

- **来源**：eval-doc #11
- **优先级**：P0
- **前置条件**：EventBus 使用 file-based SQLite（tmp 文件）
- **操作步骤**：
  1. engine 创建 conv + 发消息（产生事件）
  2. 创建新的 EventBus 实例（同 DB 路径）
  3. `query_events(conv_id)` 通过新实例
- **预期结果**：返回之前持久化的事件，内容一致
- **涉及模块**：event_bus

### TC-013: Plugin Hook — on_event 通用回调

- **来源**：eval-doc #12
- **优先级**：P0
- **前置条件**：注册了一个实现 `on_event` 的 hook
- **操作步骤**：
  1. `engine.register_hook(hook)`
  2. `engine.send_message(...)`
- **预期结果**：hook.on_event 被调用，参数为 Event 对象，event.type == "message.sent"
- **涉及模块**：local_engine

### TC-014: Plugin Hook — 特化回调（on_conversation_created）

- **来源**：eval-doc #13
- **优先级**：P0
- **前置条件**：注册了实现 `on_conversation_created` 的 hook
- **操作步骤**：
  1. `engine.register_hook(hook)`
  2. `engine.create_conversation(...)`
- **预期结果**：hook.on_conversation_created 被调用，参数为新建的 Conversation
- **涉及模块**：local_engine

### TC-015: Plugin Hook — on_mode_changed 回调

- **来源**：eval-doc（特化回调扩展）
- **优先级**：P0
- **前置条件**：注册了实现 `on_mode_changed` 的 hook，conv 有 customer + operator
- **操作步骤**：
  1. operator join（触发 auto→copilot）
- **预期结果**：hook.on_mode_changed 被调用，old_mode=AUTO, new_mode=COPILOT
- **涉及模块**：local_engine

### TC-016: Plugin Hook — 异常隔离（Q8c）

- **来源**：eval-doc #14
- **优先级**：P0
- **前置条件**：注册了 hook，其 on_event 抛 RuntimeError
- **操作步骤**：
  1. engine 发消息（触发 on_event → 抛异常）
- **预期结果**：
  1. 异常不传播，send_message 正常返回
  2. `query_events(types=["hook.failed"])` 返回 hook.failed 事件
  3. 原始 message.sent 事件正常存在
- **涉及模块**：local_engine, event_bus

### TC-017: 多 subscriber 并发 fan-out

- **来源**：eval-doc #15
- **优先级**：P0
- **前置条件**：3 个 subscriber 同时监听同一 conv
- **操作步骤**：
  1. 启动 3 个 `subscribe(conversation_id=conv_id)` 协程
  2. 发 1 条消息
- **预期结果**：3 个 subscriber 各自独立收到同一事件
- **涉及模块**：local_engine, event_bus

### TC-018: subscriber 取消清理（无泄漏）

- **来源**：eval-doc #16
- **优先级**：P1
- **前置条件**：subscriber 正在监听
- **操作步骤**：
  1. 启动 subscribe 协程
  2. 取消协程（cancel task）
  3. 发新事件
- **预期结果**：不报错，内部 subscriber 列表已清理
- **涉及模块**：event_bus

### TC-019: SQLite schema 自动创建

- **来源**：eval-doc #17
- **优先级**：P0
- **前置条件**：全新 DB 路径
- **操作步骤**：
  1. `EventBus(db_path=new_path)`
  2. 初始化完成后检查表是否存在
- **预期结果**：events 表已创建，包含 id/type/conversation_id/data/timestamp/sequence_number 列
- **涉及模块**：event_bus

### TC-020: 高频 emit 不阻塞调用者

- **来源**：eval-doc #18
- **优先级**：P1
- **前置条件**：engine 已创建 conv + customer join
- **操作步骤**：
  1. 连续发 50 条消息
  2. 计时总耗时
- **预期结果**：send_message 返回速度不受 SQLite 写入瓶颈影响（总耗时 < 2s）
- **涉及模块**：local_engine, event_bus

### TC-021: on_conversation_closed hook 回调

- **来源**：coverage-gap（特化 hook 补全）
- **优先级**：P1
- **前置条件**：注册了实现 `on_conversation_closed` 的 hook
- **操作步骤**：
  1. `close_conversation(...)`
- **预期结果**：hook.on_conversation_closed 被调用
- **涉及模块**：local_engine

### TC-022: on_participant_joined hook 回调

- **来源**：coverage-gap（特化 hook 补全）
- **优先级**：P1
- **前置条件**：注册了实现 `on_participant_joined` 的 hook
- **操作步骤**：
  1. `join(conv_id, participant)`
- **预期结果**：hook.on_participant_joined 被调用
- **涉及模块**：local_engine

### TC-023: 多 hook 注册，一个失败不影响其他

- **来源**：coverage-gap（Q8c 扩展）
- **优先级**：P1
- **前置条件**：注册 hook-A（正常）和 hook-B（on_event 抛异常）
- **操作步骤**：
  1. engine 发消息
- **预期结果**：hook-A.on_event 被正常调用，hook-B 的异常被隔离
- **涉及模块**：local_engine

### TC-024: 现有契约测试回归验证

- **来源**：regression
- **优先级**：P0
- **前置条件**：EventBus 替换完成
- **操作步骤**：
  1. 运行 `pytest tests/conversation_engine/test_local_engine.py`
  2. 运行 `pytest tests/contract/`
- **预期结果**：所有现有测试通过，无回归
- **涉及模块**：local_engine, event_bus

## 统计

| 指标 | 值 |
|------|-----|
| 总用例数 | 24 |
| P0 | 13 |
| P1 | 11 |
| P2 | 0 |
| 来源：eval-doc | 18 |
| 来源：coverage-gap | 3 |
| 来源：regression | 1 |
| 来源：结构验证 | 2 |

## 风险标注

- **高风险**：`_emit` 替换为 EventBus 委托 — 所有事件产生的核心路径，影响全部 T1A.1 现有测试
- **回归风险**：test_local_engine.py 的 TC-029（subscribe receives mode.changed）直接依赖 fan-out 机制
- **技术风险**：since_sequence 回放与实时流衔接（TC-006/007）需原子性保证，测试需验证无间隙

## 测试文件规划

| 文件 | 内容 |
|---|---|
| `tests/conversation_engine/test_event_bus.py` | TC-001, TC-012, TC-017, TC-018, TC-019, TC-020（EventBus 单元测试） |
| `tests/conversation_engine/test_local_engine.py` | TC-002~TC-011, TC-013~TC-016, TC-021~TC-023（追加到现有文件） |
| 现有测试 | TC-024 回归验证（运行现有 suite） |
