---
type: eval-doc
id: eval-doc-T1A.2
status: confirmed
producer: skill-5
created_at: 2026-04-16
mode: simulate
feature: "T1A.2 LocalEngine Timer 最小实现"
submitter: DevA
related:
  - eval-doc-001  # T0.4 LocalEngine 骨架
  - docs/contracts/conversation-engine.md  # §2.3 Timer 预设 + §3 set_timer/cancel_timer
---

# Eval: T1A.2 LocalEngine Timer 最小实现

## 基本信息
- 模式：模拟
- 提交人：DevA
- 日期：2026-04-16
- 状态：draft

## Feature 描述

实现 ConversationEngine 契约中 `set_timer` / `cancel_timer` 两个方法，支持 7 类预设 Timer（sla_onboard / sla_placeholder / sla_slow_query / sla_first_reply / takeover_wait / idle_timeout / close_timeout）+ 自定义 Timer。超时后发 `timer.expired` 事件并执行 `on_expire` 动作。

### 核心需求
1. `set_timer(conv_id, name, duration_ms, on_expire)` → 创建定时器，返回 Timer 对象，发 `timer.set` 事件
2. `cancel_timer(conv_id, name)` → 取消定时器（幂等），发 `timer.cancelled` 事件
3. 超时触发：发 `timer.expired` 事件 + 执行 `on_expire` 动作
4. `on_expire` 动作类型：`mode_change` / `system_message` / `callback`
5. 同名 Timer 重设（set 已存在的 name）→ 取消旧的 + 创建新的

### 已有基础设施（代码分析）
- `Timer` dataclass：`types.py:100-105`（conversation_id, name, duration_ms, started_at, cancelled）
- `TIMER_DEFAULTS_MS`：`types.py:108-116`（7 类预设默认值）
- `EventType.TIMER_SET/EXPIRED/CANCELLED`：`events.py:34-36`
- `LocalEngine._emit()`：已实现事件发射 + fan-out
- `LocalEngine` 目前 `set_timer`/`cancel_timer` 抛 `NotImplementedError`

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|---------|---------|--------|
| 1 | set_timer 基本创建 | 已创建 active conversation | `set_timer(conv_id, "sla_onboard", 3000, on_expire={...})` | 返回 Timer 对象（name="sla_onboard", duration_ms=3000, cancelled=False）；发 `timer.set` 事件 | 可行。Timer dataclass 已存在，_emit 已就绪。需在 `__init__` 加 `_timers: dict[str, dict[str, tuple[Timer, asyncio.Task]]]`（conv_id → name → (Timer, Task)） | 无 | P0 |
| 2 | set_timer 超时触发 | 已设置一个短时 Timer（如 50ms） | 等待 Timer 超时 | 发 `timer.expired` 事件（data 含 name + on_expire）；执行 on_expire 动作 | 可行。用 `asyncio.create_task` + `asyncio.sleep(duration_ms / 1000)` 实现。需在 sleep 结束后检查 cancelled 标志防止竞态 | 无 | P0 |
| 3 | cancel_timer 正常取消 | 已设置一个 Timer | `cancel_timer(conv_id, "sla_onboard")` | Timer 被取消，不再触发超时；发 `timer.cancelled` 事件 | 可行。`task.cancel()` + 移除 `_timers` 条目。需 try/except CancelledError 在 timer task 中处理 | 无 | P0 |
| 4 | cancel_timer 幂等（不存在） | 无已设置 Timer | `cancel_timer(conv_id, "nonexist")` | 不报错，静默返回（契约 §3：幂等） | 可行。检查 `_timers[conv_id].get(name)` → None 则 return | 无 | P0 |
| 5 | set_timer 重设（同名覆盖） | 已存在 name="idle_timeout" 的 Timer | 再次 `set_timer(conv_id, "idle_timeout", 600000, ...)` | 旧 Timer 被取消（发 cancelled 事件？或静默）+ 新 Timer 创建（发 timer.set 事件） | 可行。内部先 cancel 旧的（静默，不发 cancelled 事件——这是重设不是用户取消）+ 创建新 Task。**设计决策点**：重设时是否发 cancelled 事件？建议不发，只发 timer.set | 需决策：重设时是否发 timer.cancelled | P0 |
| 6 | on_expire: mode_change | Timer 超时，on_expire={"type": "mode_change", "params": {"target": "takeover", "trigger": "auto:takeover_wait_expired"}} | Timer 到期 | 调用 `self.switch_mode(conv_id, TAKEOVER, ...)` | 可行。在 timer task 的 expire 回调中 dispatch on_expire.type | 无 | P0 |
| 7 | on_expire: system_message | Timer 超时，on_expire={"type": "system_message", "params": {"content": "SLA breach: onboard > 3s"}} | Timer 到期 | 调用 `self.send_message(conv_id, source="system", content=..., visibility=SYSTEM)` | 可行。需确保 "system" participant 存在或用特殊 source_id 跳过 _role_of 校验。**设计决策点**：system 消息的 source 身份处理 | 需决策：system 消息的 source 如何处理 | P1 |
| 8 | on_expire: callback | Timer 超时，on_expire={"type": "callback", "params": {"hook": "on_timer_expired"}} | Timer 到期 | 调用所有注册 PluginHook 的 `on_timer_expired(conv, timer)` | 可行。已有 `_hooks` 列表 + PluginHook.on_timer_expired 签名 | 无 | P1 |
| 9 | Timer + conversation close | 已设置多个 Timer | `close_conversation(conv_id, ...)` | 所有该会话的 Timer 被自动取消 | 需在 `close_conversation` 中添加清理逻辑：遍历 `_timers[conv_id]` 取消所有 task | 无（需修改 close_conversation） | P1 |
| 10 | set_timer 对已关闭会话 | conversation 已 CLOSED | `set_timer(conv_id, ...)` | 抛 ConversationAlreadyClosed 或 ValidationError | 可行。在 set_timer 入口 `_get_conv` + 检查 state == CLOSED | 无 | P1 |
| 11 | 并发 set/cancel 同名 Timer | 两个并发 coroutine 同时 set_timer + cancel_timer 同名 | 并发执行 | 无 race condition，最终状态一致 | 需考虑锁。可复用 per-conv lock（_mode_locks）或新增 _timer_locks。建议复用 _mode_locks 简化 | 需验证锁策略 | P2 |
| 12 | Timer SLA breach 事件 | sla_* 类 Timer 超时 | Timer 到期 | 除 `timer.expired` 外，额外发 `sla.breach` 事件（契约 §5） | 需在 expire 处理中判断 name.startswith("sla_") → 额外 emit SLA_BREACH | 无 | P1 |

## 关键设计决策

### D1: Timer 内部存储结构
**建议**: `_timers: dict[str, dict[str, _TimerEntry]]`，其中 `_TimerEntry = tuple[Timer, asyncio.Task]`。按 conv_id → name 索引，O(1) 查找/取消。

### D2: 重设时是否发 timer.cancelled 事件
**建议**: 不发。重设是内部行为，用户感知的是"Timer 被刷新"。如果发 cancelled + set 两个事件，前端处理更复杂且无收益。

### D3: system 消息的 source 身份
**建议**: 使用固定 participant_id `"__system__"`，在 `send_message` 中对 `__system__` 源跳过 `_role_of` 校验（或自动以 SYSTEM visibility 发送）。这是 Timer expire 和未来系统通知的共用路径。

### D4: 测试中的时间控制
**建议**: 测试用极短 duration（50-100ms）+ `asyncio.sleep` 等待。不引入 fake clock（YAGNI for M1）。若 CI 不稳定再引入。

## 后续行动

- [x] eval-doc 已写入 .artifacts/eval-docs/
- [ ] 用户已确认 testcase 表格 (status: confirmed → confirmed)
