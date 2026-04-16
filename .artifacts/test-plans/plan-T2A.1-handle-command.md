---
type: test-plan
id: test-plan-T2A.1
status: confirmed
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-doc-T2A.1 confirmed — handle_command 协议命令实现"
related:
  - eval-doc-T2A.1
---

# Test Plan: T2A.1 handle_command 协议命令实现

## 触发原因

eval-doc-T2A.1 已确认，需要为 `handle_command` 实现生成可执行测试。当前方法抛 `NotImplementedError`，需覆盖 6 个命令的正常路径、权限拒绝、边界情况。

## 用例列表

### TC-001: /hijack 正常执行

- **来源**：eval-doc（#1）
- **优先级**：P0
- **前置条件**：conv active + customer + operator joined（copilot mode）
- **操作步骤**：
  1. `handle_command(conv_id, actor_id=op_id, command="/hijack")`
  2. `get_conversation(conv_id)`
- **预期结果**：mode == TAKEOVER, mode.changed 事件存在
- **涉及模块**：conversation_engine/local_engine.py

### TC-002: /release 正常执行

- **来源**：eval-doc（#2）
- **优先级**：P0
- **前置条件**：conv in TAKEOVER + operator
- **操作步骤**：
  1. 先 switch_mode 到 TAKEOVER
  2. `handle_command(..., command="/release")`
  3. `get_conversation(conv_id)`
- **预期结果**：mode == AUTO
- **涉及模块**：conversation_engine/local_engine.py

### TC-003: /copilot 正常执行

- **来源**：eval-doc（#3）
- **优先级**：P0
- **前置条件**：conv in AUTO + operator joined
- **操作步骤**：
  1. switch_mode 回 AUTO
  2. `handle_command(..., command="/copilot")`
- **预期结果**：mode == COPILOT
- **涉及模块**：conversation_engine/local_engine.py

### TC-004: /resolve 正常执行

- **来源**：eval-doc（#4）
- **优先级**：P0
- **前置条件**：conv active + operator
- **操作步骤**：
  1. `handle_command(..., command="/resolve")`
  2. `get_conversation(conv_id)`
- **预期结果**：state == CLOSED, resolution.outcome == RESOLVED
- **涉及模块**：conversation_engine/local_engine.py

### TC-005: /abandon 正常执行

- **来源**：eval-doc（#5）
- **优先级**：P0
- **前置条件**：conv active + operator
- **操作步骤**：
  1. `handle_command(..., command="/abandon")`
  2. `get_conversation(conv_id)`
- **预期结果**：state == CLOSED, resolution.outcome == ABANDONED
- **涉及模块**：conversation_engine/local_engine.py

### TC-006: /status 只读

- **来源**：eval-doc（#6）
- **优先级**：P0
- **前置条件**：conv active + operator
- **操作步骤**：
  1. `handle_command(..., command="/status")`
  2. `get_conversation(conv_id)`
- **预期结果**：不抛异常, conv state 未变
- **涉及模块**：conversation_engine/local_engine.py

### TC-007: customer → PermissionDenied

- **来源**：eval-doc（#7）
- **优先级**：P0
- **前置条件**：conv active + customer joined
- **操作步骤**：
  1. `handle_command(conv_id, actor_id=customer_id, command="/hijack")`
- **预期结果**：抛 PermissionDenied
- **涉及模块**：conversation_engine/local_engine.py

### TC-008: agent → PermissionDenied

- **来源**：eval-doc（#8）
- **优先级**：P0
- **前置条件**：conv active + agent joined
- **操作步骤**：
  1. `handle_command(conv_id, actor_id=agent_id, command="/resolve")`
- **预期结果**：抛 PermissionDenied
- **涉及模块**：conversation_engine/local_engine.py

### TC-009: mode no-op (Q4)

- **来源**：eval-doc（#9）
- **优先级**：P0
- **前置条件**：conv in copilot + operator
- **操作步骤**：
  1. `handle_command(..., command="/copilot")` (already in copilot)
  2. `query_events(conv_id, types=["mode.noop"])`
- **预期结果**：不抛异常, mode.noop 事件存在
- **涉及模块**：conversation_engine/local_engine.py

### TC-010: unknown command → ValidationError

- **来源**：eval-doc（#10）
- **优先级**：P1
- **前置条件**：conv active + operator
- **操作步骤**：
  1. `handle_command(..., command="/unknown")`
- **预期结果**：抛 ValidationError
- **涉及模块**：conversation_engine/local_engine.py

### TC-011: /resolve on already closed (幂等)

- **来源**：eval-doc（#11）
- **优先级**：P1
- **前置条件**：conv closed + operator
- **操作步骤**：
  1. Close conv first
  2. `handle_command(..., command="/resolve")`
- **预期结果**：不抛异常（close_conversation 幂等）
- **涉及模块**：conversation_engine/local_engine.py

### TC-012: /hijack on closed conv

- **来源**：eval-doc（#12）
- **优先级**：P1
- **前置条件**：conv closed + operator
- **操作步骤**：
  1. Close conv first
  2. `handle_command(..., command="/hijack")`
- **预期结果**：抛 IllegalModeTransition
- **涉及模块**：conversation_engine/local_engine.py

### TC-013: unknown participant

- **来源**：eval-doc（#13）
- **优先级**：P1
- **前置条件**：conv active
- **操作步骤**：
  1. `handle_command(conv_id, actor_id="nobody", command="/status")`
- **预期结果**：抛 UnknownParticipant
- **涉及模块**：conversation_engine/local_engine.py

### TC-014: /resolve with reason arg

- **来源**：eval-doc（#14）
- **优先级**：P1
- **前置条件**：conv active + operator
- **操作步骤**：
  1. `handle_command(..., command="/resolve", args={"reason": "customer satisfied"})`
  2. `get_conversation(conv_id)`
- **预期结果**：state == CLOSED, resolution.outcome == RESOLVED
- **涉及模块**：conversation_engine/local_engine.py

## 统计

| 指标 | 值 |
|------|-----|
| 总用例数 | 14 |
| P0 | 9 |
| P1 | 5 |
| P2 | 0 |
| 来源：eval-doc | 14 |

## 风险标注

- **回归风险**：handle_command 内部调用 switch_mode / close_conversation — 这些方法已有完整测试，风险低
- **覆盖未知**：/dispatch + /assign 暂不实现，TC-010 验证 unknown command 拒绝即可
