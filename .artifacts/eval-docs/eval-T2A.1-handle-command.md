---
type: eval-doc
id: eval-doc-T2A.1
status: confirmed
producer: skill-5
created_at: 2026-04-16
mode: simulate
feature: "T2A.1 handle_command 协议命令实现"
submitter: DevA
related:
  - docs/contracts/conversation-engine.md  # §3 handle_command + §6.1 权限矩阵
  - eval-doc-003  # T1A.1 Mode/Gate
---

# Eval: T2A.1 handle_command 协议命令实现

## 基本信息
- 模式：模拟
- 提交人：DevA
- 日期：2026-04-16
- 状态：draft

## Feature 描述

实现 ConversationEngine 契约 §3 的 `handle_command` 方法 — 统一的 operator/admin 命令入口。收敛 IRC CommandParser 与 Bridge operator_command 为单一 Engine 入口。

### 支持的命令

| 命令 | 内部派发 | 参数 |
|---|---|---|
| `/hijack` | `switch_mode(TAKEOVER)` | — |
| `/release` | `switch_mode(AUTO)` | — |
| `/copilot` | `switch_mode(COPILOT)` | — |
| `/resolve` | `close_conversation(outcome=RESOLVED)` | reason（可选） |
| `/abandon` | `close_conversation(outcome=ABANDONED)` | reason（可选） |
| `/status` | 只读查询 | — |

### 权限矩阵（§6.1）

| command | customer | agent | operator | admin |
|---------|----------|-------|----------|-------|
| /hijack, /release, /copilot | ❌ | ❌ | ✅ | ✅ |
| /resolve, /abandon | ❌ | ❌ | ✅ | ✅ |
| /status | ❌ | ❌ | ✅ | ✅ |

> `/dispatch` + `/assign` 是 M3 起的 admin-only 命令，本任务暂不实现（返回 ValidationError "unknown command"）。

### 已有基础设施
- `_role_of(conv_id, participant_id)` → `ParticipantRole`（已实现）
- `switch_mode` 完整实现（含 Q4 mode.noop）
- `close_conversation` 完整实现（含幂等 + timer cleanup）
- `PermissionDenied` 异常已定义
- `handle_command` 当前抛 `NotImplementedError`

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|---------|---------|--------|
| 1 | /hijack 正常执行 | conv active + operator joined（copilot mode） | `handle_command(conv_id, actor_id=op, command="/hijack")` | mode 变为 TAKEOVER + mode.changed 事件 | 可行。内部调 `switch_mode(TAKEOVER, trigger="/hijack")` | 无 | P0 |
| 2 | /release 正常执行 | conv in TAKEOVER mode + operator | `handle_command(..., command="/release")` | mode 变为 AUTO + mode.changed 事件 | 可行。内部调 `switch_mode(AUTO, trigger="/release")` | 无 | P0 |
| 3 | /copilot 正常执行 | conv in AUTO mode + operator | `handle_command(..., command="/copilot")` | mode 变为 COPILOT + mode.changed 事件 | 可行。内部调 `switch_mode(COPILOT, trigger="/copilot")` | 无 | P0 |
| 4 | /resolve 正常执行 | conv active + operator | `handle_command(..., command="/resolve")` | conv 变为 CLOSED + RESOLVED | 可行。内部调 `close_conversation(RESOLVED, resolved_by=actor_id)` | 无 | P0 |
| 5 | /abandon 正常执行 | conv active + operator | `handle_command(..., command="/abandon")` | conv 变为 CLOSED + ABANDONED | 可行。内部调 `close_conversation(ABANDONED, resolved_by=actor_id)` | 无 | P0 |
| 6 | /status 只读查询 | conv active + operator | `handle_command(..., command="/status")` | 不修改状态，不报错（只读） | 可行。调 `get_conversation` 返回信息 | 无 | P0 |
| 7 | customer 执行命令 → PermissionDenied | conv active + customer | `handle_command(conv_id, actor_id=customer, command="/hijack")` | 抛 PermissionDenied | 可行。在入口检查 role，非 operator/admin 一律拒绝 | 无 | P0 |
| 8 | agent 执行命令 → PermissionDenied | conv active + agent | `handle_command(conv_id, actor_id=agent, command="/resolve")` | 抛 PermissionDenied | 可行 | 无 | P0 |
| 9 | mode no-op（Q4） | conv in copilot + operator | `handle_command(..., command="/copilot")` | 不抛异常，发 mode.noop 事件 | 可行。switch_mode 内部已处理 Q4 | 无 | P0 |
| 10 | unknown command | conv active + operator | `handle_command(..., command="/unknown")` | 抛 ValidationError | 可行。command 白名单检查 | 无 | P1 |
| 11 | /resolve on already closed | conv already closed + operator | `handle_command(..., command="/resolve")` | 幂等，不报错（close_conversation 幂等） | 可行。close_conversation 已有幂等逻辑 | 无 | P1 |
| 12 | /hijack on closed conv | conv closed + operator | `handle_command(..., command="/hijack")` | 抛 IllegalModeTransition | 可行。switch_mode 已有 closed 检查 | 无 | P1 |
| 13 | unknown participant | conv active | `handle_command(conv_id, actor_id="nobody", command="/status")` | 抛 UnknownParticipant | 可行。_role_of 已有此逻辑 | 无 | P1 |
| 14 | /resolve with reason arg | conv active + operator | `handle_command(..., command="/resolve", args={"reason": "solved"})` | reason 传递到 close_conversation | 可行。从 args 提取 reason | 无 | P1 |

## 设计决策

### D1: /status 返回值
`handle_command` 签名返回 `None`。/status 的查询结果不通过返回值传递（因为返回 None），而是作为 system message 发送到会话中（或未来通过 event 推送）。**本期最小实现**：/status 仅验证权限，不发消息（避免与 system message 的 source 问题耦合），后续可扩展。

### D2: /dispatch + /assign
M3 才需要，本期对未知命令返回 ValidationError，预留扩展点。

## 后续行动

- [x] eval-doc 已写入 .artifacts/eval-docs/
- [ ] 用户已确认 testcase 表格 (status: confirmed → confirmed)
