---
type: test-plan
id: test-plan-T1A.2
status: draft
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-doc-T1A.2 confirmed — Timer 最小实现"
related:
  - eval-doc-T1A.2
---

# Test Plan: T1A.2 LocalEngine Timer 最小实现

## 触发原因

eval-doc-T1A.2 已确认，需要为 `set_timer` / `cancel_timer` 实现生成可执行的 E2E 测试。当前 LocalEngine 两个方法抛 `NotImplementedError`，需要覆盖 7 类预设 Timer 的创建、取消、超时触发、on_expire 动作分发及边界情况。

## 用例列表

### TC-001: set_timer 基本创建 + timer.set 事件

- **来源**：eval-doc（#1）
- **优先级**：P0
- **前置条件**：已创建 active conversation + customer participant 已 join
- **操作步骤**：
  1. `engine.set_timer(conv_id, "sla_onboard", 3000, on_expire={"type": "callback", "params": {}})`
  2. 检查返回值
  3. `engine.query_events(conv_id, types=["timer.set"])`
- **预期结果**：
  - 返回 `Timer` 对象：name="sla_onboard", duration_ms=3000, cancelled=False
  - conversation_id 匹配
  - 存在 `timer.set` 事件，data 含 name + duration_ms
- **涉及模块**：conversation_engine/local_engine.py

### TC-002: set_timer 超时触发 timer.expired 事件

- **来源**：eval-doc（#2）
- **优先级**：P0
- **前置条件**：已创建 active conversation + customer participant 已 join
- **操作步骤**：
  1. `engine.set_timer(conv_id, "test_timer", 50, on_expire={"type": "callback", "params": {}})`
  2. `await asyncio.sleep(0.15)` — 等待超时（含裕量）
  3. `engine.query_events(conv_id, types=["timer.expired"])`
- **预期结果**：
  - 存在 `timer.expired` 事件
  - 事件 data 含 name="test_timer"
- **涉及模块**：conversation_engine/local_engine.py

### TC-003: cancel_timer 正常取消

- **来源**：eval-doc（#3）
- **优先级**：P0
- **前置条件**：已设置一个长时 Timer（如 5000ms，确保不会在测试中超时）
- **操作步骤**：
  1. `engine.set_timer(conv_id, "idle_timeout", 5000, on_expire=...)`
  2. `engine.cancel_timer(conv_id, "idle_timeout")`
  3. `await asyncio.sleep(0.1)` — 短暂等待确认无 expired 事件
  4. `engine.query_events(conv_id, types=["timer.cancelled"])`
  5. `engine.query_events(conv_id, types=["timer.expired"])`
- **预期结果**：
  - 存在 `timer.cancelled` 事件
  - 不存在 `timer.expired` 事件
- **涉及模块**：conversation_engine/local_engine.py

### TC-004: cancel_timer 幂等（不存在的 Timer）

- **来源**：eval-doc（#4）
- **优先级**：P0
- **前置条件**：已创建 conversation，无 Timer 设置
- **操作步骤**：
  1. `engine.cancel_timer(conv_id, "nonexistent")` — 不应抛异常
- **预期结果**：
  - 无异常抛出
  - 无 `timer.cancelled` 事件（没有什么被取消）
- **涉及模块**：conversation_engine/local_engine.py

### TC-005: set_timer 同名重设（覆盖旧 Timer）

- **来源**：eval-doc（#5）
- **优先级**：P0
- **前置条件**：已创建 conversation + participant
- **操作步骤**：
  1. `engine.set_timer(conv_id, "idle_timeout", 5000, on_expire=...)` — 旧
  2. `engine.set_timer(conv_id, "idle_timeout", 80, on_expire=...)` — 新（短时）
  3. `await asyncio.sleep(0.2)` — 等待新 Timer 超时
  4. 检查事件
- **预期结果**：
  - 存在 2 个 `timer.set` 事件（旧 + 新）
  - 只有 1 个 `timer.expired` 事件（新 Timer 触发的）
  - 无 `timer.cancelled` 事件（重设不发 cancelled，设计决策 D2）
- **涉及模块**：conversation_engine/local_engine.py

### TC-006: on_expire mode_change 动作

- **来源**：eval-doc（#6）
- **优先级**：P0
- **前置条件**：conversation 在 AUTO mode + customer + operator 已 join（切到 COPILOT）
- **操作步骤**：
  1. `engine.set_timer(conv_id, "takeover_wait", 50, on_expire={"type": "mode_change", "params": {"target": "takeover", "triggered_by": "system", "trigger": "auto:takeover_wait_expired"}})`
  2. `await asyncio.sleep(0.15)`
  3. `engine.get_conversation(conv_id)`
- **预期结果**：
  - conversation mode 变为 TAKEOVER
  - 存在 `timer.expired` 事件
  - 存在 `mode.changed` 事件（copilot → takeover）
- **涉及模块**：conversation_engine/local_engine.py

### TC-007: on_expire system_message 动作

- **来源**：eval-doc（#7）
- **优先级**：P1
- **前置条件**：conversation active + customer participant
- **操作步骤**：
  1. `engine.set_timer(conv_id, "sla_onboard", 50, on_expire={"type": "system_message", "params": {"content": "SLA breach: onboard > 3s"}})`
  2. `await asyncio.sleep(0.15)`
  3. `engine.get_messages(conv_id)`
- **预期结果**：
  - 存在 SYSTEM visibility 消息，content = "SLA breach: onboard > 3s"
  - 存在 `timer.expired` 事件
- **涉及模块**：conversation_engine/local_engine.py

### TC-008: on_expire callback 动作（PluginHook）

- **来源**：eval-doc（#8）
- **优先级**：P1
- **前置条件**：conversation active + 已注册 PluginHook（mock）
- **操作步骤**：
  1. 创建 mock PluginHook，记录 `on_timer_expired` 调用
  2. `engine.register_hook(mock_hook)`
  3. `engine.set_timer(conv_id, "test_cb", 50, on_expire={"type": "callback", "params": {}})`
  4. `await asyncio.sleep(0.15)`
- **预期结果**：
  - mock_hook.on_timer_expired 被调用一次
  - 调用参数包含正确的 conversation 和 timer 对象
- **涉及模块**：conversation_engine/local_engine.py

### TC-009: close_conversation 自动清理 Timer

- **来源**：eval-doc（#9）
- **优先级**：P1
- **前置条件**：conversation active + 设置了 2 个长时 Timer
- **操作步骤**：
  1. `engine.set_timer(conv_id, "idle_timeout", 5000, ...)`
  2. `engine.set_timer(conv_id, "close_timeout", 10000, ...)`
  3. `engine.close_conversation(conv_id, outcome=RESOLVED, resolved_by="op")`
  4. `await asyncio.sleep(0.1)`
  5. 检查 expired 事件
- **预期结果**：
  - 无 `timer.expired` 事件（Timer 被清理，不再触发）
  - conversation 正常关闭
- **涉及模块**：conversation_engine/local_engine.py

### TC-010: set_timer 对已关闭会话报错

- **来源**：eval-doc（#10）
- **优先级**：P1
- **前置条件**：conversation 已 CLOSED
- **操作步骤**：
  1. 创建并关闭 conversation
  2. `engine.set_timer(conv_id, "test", 1000, on_expire=...)`
- **预期结果**：
  - 抛出 `ConversationAlreadyClosed` 或 `ValidationError`
- **涉及模块**：conversation_engine/local_engine.py

### TC-011: sla_* Timer 超时发 sla.breach 事件

- **来源**：eval-doc（#12）
- **优先级**：P1
- **前置条件**：conversation active + customer participant
- **操作步骤**：
  1. `engine.set_timer(conv_id, "sla_onboard", 50, on_expire={"type": "callback", "params": {}})`
  2. `await asyncio.sleep(0.15)`
  3. `engine.query_events(conv_id, types=["sla.breach"])`
- **预期结果**：
  - 存在 `sla.breach` 事件
  - 事件 data 含 timer name
- **涉及模块**：conversation_engine/local_engine.py

### TC-012: 取消后的 Timer 不触发超时

- **来源**：eval-doc（#3 扩展 — 验证无残留）
- **优先级**：P1
- **前置条件**：conversation active
- **操作步骤**：
  1. `engine.set_timer(conv_id, "short", 80, on_expire=...)`
  2. `engine.cancel_timer(conv_id, "short")` — 立即取消
  3. `await asyncio.sleep(0.2)` — 等待超过原 duration
  4. 检查 expired 事件
- **预期结果**：
  - 无 `timer.expired` 事件
- **涉及模块**：conversation_engine/local_engine.py

## 统计

| 指标 | 值 |
|------|-----|
| 总用例数 | 12 |
| P0 | 6 |
| P1 | 6 |
| P2 | 0 |
| 来源：eval-doc | 12 |
| 来源：code-diff | 0 |
| 来源：coverage-gap | 0 |
| 来源：bug-feedback | 0 |

## 风险标注

- **高风险**：TC-002/TC-005/TC-006 涉及 asyncio timer 精度 — 测试用短 duration (50-80ms) + 宽裕等待 (150-200ms) 降低 CI 抖动风险
- **回归风险**：TC-009 修改 close_conversation 逻辑 — 需确保现有 close 测试（TC-004/005 in test_local_engine.py）仍通过
- **覆盖未知**：无 coverage-matrix，并发场景（eval-doc #11）降级为实现阶段手动验证，不列入本轮自动化测试
