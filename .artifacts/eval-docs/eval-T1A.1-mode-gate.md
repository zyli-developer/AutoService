---
type: eval-doc
id: eval-doc-003
status: confirmed
producer: skill-5
created_at: 2026-04-16
mode: simulate
feature: "T1A.1 Mode/Gate 最小实现"
submitter: DevA
related:
  - eval-doc-001  # T0.4 LocalEngine skeleton
  - test-plan-001
---

# Eval: T1A.1 Mode/Gate 最小实现

## 基本信息
- 模式：模拟
- 提交人：DevA
- 日期：2026-04-16
- 状态：draft

## 实现范围

基于 `autoservice/conversation_engine/local_engine.py` 骨架，实现以下方法组（替换 `NotImplementedError` stub）：

1. **会话生命周期**: `create_conversation`, `get_conversation`, `list_active_conversations`, `close_conversation`, `set_csat`
2. **参与者管理**: `join`, `leave`（含 operator join → auto→copilot 自动切换）
3. **Mode 状态机**: `switch_mode`（3 态 + 串行锁 + noop 事件）
4. **Gate 可见性**: 嵌入 `send_message` 内部的降级矩阵
5. **消息 CRUD**: `send_message`, `edit_message`, `delete_message`, `get_messages`

**不包含**（属于后续任务）：Timer (T1A.2)、EventBus/subscribe/query_events (T1A.3)、handle_command (T2A.1)

## 内部存储设计（模拟）

LocalEngine 为进程内实现，使用 dict 内存存储：
- `_conversations: dict[str, Conversation]` — 会话对象
- `_messages: dict[str, list[Message]]` — per-conv 消息列表
- `_participants: dict[str, list[Participant]]` — per-conv 参与者
- `_seq_counters: dict[str, int]` — per-conv 消息序列号
- `_mode_locks: dict[str, asyncio.Lock]` — per-conv 串行锁（§7.1 #3）
- 事件暂用内部 list 缓存，T1A.3 实现 EventBus 后替换

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|---------|---------|--------|
| 1 | 创建会话 | 无已有会话 | `create_conversation(channel="web", external_id="sess_1")` | 返回 Conversation(id="web_sess_1", state=CREATED, mode=AUTO)；发 conversation.created 事件 | 可行。id 按 Q1 规则 `{channel}_{external_id}` 生成；state=CREATED, mode=AUTO。事件发送需 EventBus（T1A.3），T1A.1 内可用内部 list 暂存或 no-op。 | 事件发送依赖 T1A.3，T1A.1 内需简化处理（内部 list 或桩） | P0 |
| 2 | 创建会话幂等 | 已有 web_sess_1 且未 closed | 再次 `create_conversation(channel="web", external_id="sess_1")` | 返回现有 Conversation，不创建新的 | 可行。按 (channel, external_id) 查 _conversations，找到未 closed 则返回。 | 无 | P0 |
| 3 | 获取会话 | web_sess_1 存在 | `get_conversation("web_sess_1")` | 返回 Conversation 对象 | 可行。dict 查找。 | 无 | P0 |
| 4 | 获取不存在会话 | 无 web_sess_999 | `get_conversation("web_sess_999")` | 抛 ConversationNotFound | 可行。errors.py 已定义。 | 无 | P0 |
| 5 | 关闭会话 | web_sess_1 存在且 ACTIVE | `close_conversation("web_sess_1", outcome=RESOLVED, resolved_by="op_1")` | state→CLOSED，设置 Resolution；发 conversation.resolved + conversation.closed | 可行。需注意 frozen dataclass 不可原地改，需创建新 Conversation 替换。 | 无 | P0 |
| 6 | 关闭会话幂等 | web_sess_1 已 CLOSED | 再次 close_conversation | 返回现有对象，不报错 | 可行。检查 state==CLOSED 直接返回。 | 无 | P1 |
| 7 | operator join → auto→copilot | 会话 mode=AUTO，无 operator | `join(conv.id, Participant(id="op_1", role=OPERATOR))` | 参与者加入；mode 自动从 AUTO 切为 COPILOT；发 participant.joined + mode.changed | 可行。join 内部检测 role==OPERATOR 且当前 mode==AUTO → 调 switch_mode。需注意 switch_mode 的串行锁。 | 无 | P0 |
| 8 | operator join 幂等 | op_1 已在会话中 | 再次 `join(conv.id, op_1)` | 幂等，不报错，不重复加入 | 可行。按 participant.id 去重。 | 无 | P1 |
| 9 | 最后 operator leave → copilot→auto | mode=COPILOT，仅 op_1 一个 operator | `leave(conv.id, "op_1")` | op_1 移除；mode 自动回落 AUTO；发 participant.left + mode.changed(trigger="auto:last_operator_left") | 可行。leave 后检查剩余 OPERATOR 数量=0 → 自动 switch_mode(AUTO)。§7.1 不变量 #8。 | 无 | P0 |
| 10 | switch_mode auto→takeover | mode=AUTO，有 operator | `switch_mode(conv.id, TAKEOVER, triggered_by="op_1", trigger="/hijack")` | mode=TAKEOVER；发 mode.changed | 可行。直接 set，需 asyncio.Lock per conv。 | 无 | P0 |
| 11 | switch_mode 同态 noop (Q4) | mode=COPILOT | `switch_mode(conv.id, COPILOT, ...)` | 不抛异常；发 mode.noop 事件 | 可行。target == current → 发 mode.noop，立即返回。契约测试 test_mode.py 第 37 行已覆盖。 | 无 | P0 |
| 12 | switch_mode on closed conv | state=CLOSED | `switch_mode(conv.id, TAKEOVER, ...)` | 抛 IllegalModeTransition | 可行。检查 state==CLOSED 抛异常。 | 无 | P0 |
| 13 | 并发 switch_mode 串行化 (§7.1 #3) | mode=COPILOT，10 并发 toggle | `asyncio.gather(*(switch_mode(...) for _ in range(10)))` | 无 torn state；最终 mode 合法 | 可行。asyncio.Lock per conv 保证。测试见 test_mode.py 第 85 行。 | 无 | P1 |
| 14 | Gate: copilot + operator 发 PUBLIC | mode=COPILOT | `send_message(source=op_1, requested_visibility=PUBLIC)` | 消息 visibility=SIDE（降级）；发 message.gated | 可行。Gate 矩阵查表：(COPILOT, OPERATOR, PUBLIC) → SIDE。 | 无 | P0 |
| 15 | Gate: takeover + agent 发 PUBLIC | mode=TAKEOVER | `send_message(source=agent_1, requested_visibility=PUBLIC)` | 消息 visibility=SIDE（降级）；发 message.gated | 可行。(TAKEOVER, AGENT, PUBLIC) → SIDE。 | 无 | P0 |
| 16 | Gate: auto + agent 发 PUBLIC | mode=AUTO | `send_message(source=agent_1, requested_visibility=PUBLIC)` | 消息 visibility=PUBLIC（无降级） | 可行。(AUTO, AGENT, PUBLIC) → PUBLIC。 | 无 | P0 |
| 17 | Gate: requested=SIDE 不升级 (Q5) | 任意 mode | `send_message(source=agent, requested_visibility=SIDE)` | visibility=SIDE，不变 | 可行。只降不升规则：SIDE/SYSTEM 原样保留。 | 无 | P0 |
| 18 | Gate 降级不可逆 (§7.1 #5) | takeover 下 agent 发 PUBLIC→SIDE | `/release` 切回 auto → 重新获取该消息 | 消息 visibility 仍为 SIDE | 可行。消息是 frozen dataclass，一旦写入不可变。get_messages 返回存储的消息原样。 | 无 | P0 |
| 19 | send_message + 序列号递增 | 已有 2 条消息 | `send_message(conv.id, source=cust, content="msg3")` | 返回 Message(sequence_number=3)；per-conv 单调递增 | 可行。_seq_counters[conv_id] 递增。 | 无 | P0 |
| 20 | edit_message 占位→续写 | 消息 msg_1 存在 | `edit_message(conv.id, "msg_1", new_content="full reply", edited_by="agent")` | 返回新 Message(edit_of="msg_1", content="full reply")；发 message.edited | 可行。创建新 Message 替换。US-2.2 占位续写核心路径。 | 无 | P0 |
| 21 | get_messages 按 viewer_role 过滤 (Q9) | SIDE 消息存在 | `get_messages(conv.id, viewer_role=CUSTOMER)` | SIDE 消息不在返回列表中 | 可行。读路径按 viewer_role 过滤 visibility。 | 无 | P1 |
| 22 | get_messages since_sequence 断线重连 | 5 条消息已有 | `get_messages(conv.id, since_sequence=3)` | 返回 seq 4, 5 的消息 | 可行。列表过滤。 | 无 | P1 |
| 23 | get_messages since + before 互斥 | 同时传两个参数 | `get_messages(conv.id, since_sequence=1, before_sequence=5)` | 抛 ValidationError | 可行。参数校验即可。 | 无 | P1 |
| 24 | set_csat 有效范围 | 会话已 resolved | `set_csat(conv.id, score=4)` | Resolution.csat_score=4；发 conversation.csat_recorded | 可行。检查 1≤score≤5。 | 无 | P1 |
| 25 | set_csat 无效分数 | 同上 | `set_csat(conv.id, score=0)` | 抛 ValidationError | 可行。 | 无 | P2 |
| 26 | list_active_conversations 全部 | 3 个 active, 1 个 closed | `list_active_conversations()` | 返回 3 个 active 会话 | 可行。过滤 state != CLOSED。 | 无 | P1 |
| 27 | list_active_conversations by operator | op_1 在 2 个会话中 | `list_active_conversations(operator_id="op_1")` | 返回 op_1 参与的 2 个 | 可行。按 participants 过滤。 | 无 | P1 |

## 风险与注意事项

1. **事件发送依赖 T1A.3 EventBus**：T1A.1 的多个场景需发事件（mode.changed, message.gated 等）。契约测试 test_mode.py 第 37 行和 test_gate.py 第 84 行依赖 `subscribe()` 来验证事件。**建议**：T1A.1 实现简易内部事件缓冲（list + asyncio.Queue fan-out），T1A.3 再替换为完整 EventBus + SQLite 落盘。
2. **frozen dataclass 不可变**：Conversation/Message 均为 `frozen=True`，状态变更需创建新对象替换存储。
3. **Gate 是 send_message 内部机制**：不是独立模块，而是 send_message 方法内的查表逻辑（~20 行）。
4. **ULID 依赖**：message_id / event_id 用 ULID（Q1），需引入 `python-ulid` 或 `ulid-py` 包。
5. **~150 行预估可能偏低**：算上内存存储、Gate 矩阵、串行锁、幂等逻辑、参与者自动切换，预估 250-350 行更现实。

## 后续行动

- [ ] eval-doc 已注册到 .artifacts/eval-docs/
- [ ] 用户已确认 testcase 表格 (status: confirmed → confirmed)
