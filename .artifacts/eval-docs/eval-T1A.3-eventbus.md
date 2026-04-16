---
type: eval-doc
id: eval-doc-004
status: draft
producer: skill-5
created_at: 2026-04-16
mode: simulate
feature: "T1A.3 LocalEngine EventBus 最小实现"
submitter: DevA
related:
  - eval-doc-001  # T0.4 LocalEngine 骨架
  - docs/contracts/conversation-engine.md
---

# Eval: T1A.3 LocalEngine EventBus 最小实现

## 基本信息
- 模式：模拟（simulate）
- 提交人：DevA
- 日期：2026-04-16
- 状态：draft

## Feature 描述

将 LocalEngine 中现有的最小 event fan-out（`_emit` → `_subscribers` list of Queue）升级为完整 EventBus，包含：

1. **进程内 pub/sub**：Queue fan-out + scope 过滤（conversation / squad / global）
2. **SQLite 异步落盘**：event 持久化，支持 `query_events` 从 DB 查询
3. **subscribe 完整实现**：since_sequence 断点续传、squad_id scope、viewer_role 过滤
4. **Plugin Hook 分发**：`_emit` 后调用已注册 hooks 的对应方法，异常隔离（Q8c）

### 架构决策（基于契约）

| 决策点 | 选择 | 来源 |
|---|---|---|
| subscribe 对外接口 | AsyncIterator[Event] | Q6 |
| 内部实现 | Queue fan-out（O(1) per sub） | Q6 |
| event ID | ULID（字典序 = 时间序） | Q1 |
| sequence_number | per-conversation 单调递增 | Q3 |
| 跨 conv 排序 | event_id ULID 字典序 | Q3 |
| Hook 异常 | 吞掉 + 发 hook.failed 事件 | Q8c |
| SQLite | aiosqlite 异步 | NFR-2（zchat 对齐） |

### 新增 / 修改文件预估

| 文件 | 变更 |
|---|---|
| `autoservice/conversation_engine/event_bus.py` | **新建**：EventBus 类（pub/sub + SQLite） |
| `autoservice/conversation_engine/local_engine.py` | **修改**：用 EventBus 替换 `_emit` / `_subscribers` / `_events`；`subscribe` / `query_events` 委托给 EventBus；hook 分发 |
| `autoservice/conversation_engine/__init__.py` | **修改**：导出 EventBus |
| `tests/conversation_engine/test_event_bus.py` | **新建**：EventBus 单元测试 |

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|---------|---------|--------|
| 1 | 单会话 subscribe 收到事件 | engine 已创建 conv | 1. `subscribe(conversation_id=conv_id)` 2. 另一协程发消息 | subscriber 收到 `message.sent` 事件 | 当前 `_subscribers` 已能做到基本 fan-out，新 EventBus 保持此能力并增强过滤 | 无功能差异；实现层替换 | P0 |
| 2 | subscribe 过滤 event_types | engine 已创建 conv | 1. `subscribe(conversation_id=conv_id, event_types=["mode.changed"])` 2. 发消息 + 切 mode | subscriber 仅收到 `mode.changed`，不收 `message.sent` | 当前代码已有 `event_types` 过滤逻辑，新实现保持 | 无 | P0 |
| 3 | subscribe squad_id scope | engine 有 2 个 conv，conv-A squad="s1"，conv-B squad="s2" | `subscribe(squad_id="s1")` → conv-A 和 conv-B 各发事件 | subscriber 仅收到 conv-A 的事件 | **当前未实现** squad_id 过滤。新 EventBus 需在 fan-out 时检查 conv.metadata["squad_id"] | 从无到有 | P0 |
| 4 | subscribe 全局 scope | engine 有多个 conv | `subscribe()` 无任何 scope 参数 | subscriber 收到所有 conv 的所有事件 | 当前代码 `conversation_id=None` 时已接收全部事件 | 无 | P1 |
| 5 | since_sequence 断点续传（conv scope） | conv 已产生 5 个事件（seq 1-5） | `subscribe(conversation_id=conv_id, since_sequence=3)` | 先回放 seq 4, 5 的历史事件，然后继续实时流 | **当前未实现**。新 EventBus 需从 SQLite 查 seq > 3 的历史事件，注入 Queue 后切换到实时流 | 从无到有 | P0 |
| 6 | since_sequence 断点续传（squad/global scope） | 多个 conv 已产生事件 | `subscribe(squad_id="s1", since_sequence="<ulid>")` | 回放该 ULID 之后的历史事件（按 ULID 字典序），然后实时流 | **当前未实现**。需 SQLite 查询 event_id > ulid 的记录 | 从无到有 | P1 |
| 7 | viewer_role 过滤 SIDE 事件 | conv 有 SIDE 消息事件 | `subscribe(conversation_id=conv_id, viewer_role=CUSTOMER)` | customer 不收到 `message.sent(visibility=SIDE)` 相关事件 | **当前未实现**。新 EventBus 需在 fan-out 时检查 event.data 中的 visibility 字段 | 从无到有 | P1 |
| 8 | query_events 基本查询 | conv 已产生 10 个事件 | `query_events(conv_id, limit=5)` | 返回前 5 个事件 | 当前内存实现已工作。新实现从 SQLite 查询 | 实现层替换，行为不变 | P0 |
| 9 | query_events 按类型过滤 | conv 有 message.sent + mode.changed 事件 | `query_events(conv_id, types=["mode.changed"])` | 仅返回 mode.changed 事件 | 当前内存实现已工作。SQLite 加 WHERE type IN (...) | 实现层替换 | P1 |
| 10 | query_events since_sequence + until | conv 有时间跨度事件 | `query_events(conv_id, since_sequence=3, until=t1)` | 返回 seq > 3 且 timestamp <= t1 的事件 | 当前内存实现已工作 | 实现层替换 | P1 |
| 11 | SQLite 持久化 — 重启后 query | engine 发过事件 → 重建 EventBus（同 DB） | `query_events(conv_id)` | 返回之前持久化的事件 | **当前纯内存，重启丢失**。新 EventBus 用 aiosqlite 持久化 | 从无到有 | P0 |
| 12 | Plugin Hook — on_event 分发 | 注册了一个 hook 实现 on_event | engine 发消息 | hook.on_event 被调用，参数为 Event 对象 | **当前 register_hook 仅 append，未调用**。新 `_emit` 需遍历 hooks 调用 | 从无到有 | P0 |
| 13 | Plugin Hook — 特化回调分发 | hook 实现了 on_conversation_created | `create_conversation(...)` | hook.on_conversation_created 被调用 | **当前未分发**。新 `_emit` 需根据 event type 映射到特化方法 | 从无到有 | P0 |
| 14 | Plugin Hook — 异常隔离 (Q8c) | hook.on_event 抛 RuntimeError | engine 发消息 | 1. 异常被吞 2. 发 `hook.failed` 事件 3. 原始事件正常传递 | **当前未实现**。需 try/except + emit hook.failed | 从无到有 | P0 |
| 15 | 多 subscriber 并发 | 3 个 subscriber 同时监听同一 conv | 发 1 条消息 | 3 个 subscriber 各自收到同一事件（fan-out） | 当前 Queue fan-out 已支持。新实现保持 | 无 | P0 |
| 16 | subscriber 取消（finally cleanup） | subscriber 正在监听 | 取消 subscribe 的 async iterator | subscriber 从内部列表移除，不泄漏 Queue | 当前 try/finally 已清理。新实现保持 | 无 | P1 |
| 17 | SQLite 表 schema | 首次启动 | EventBus 初始化 | 自动创建 events 表（id, type, conversation_id, data JSON, timestamp, sequence_number） | **新建**。aiosqlite CREATE TABLE IF NOT EXISTS | 从无到有 | P0 |
| 18 | 高频 emit 不阻塞调用者 | 快速连续发 100 条消息 | 观察 send_message 返回延迟 | SQLite 写入异步，不阻塞 emit 返回 | 需用 asyncio.create_task 或 write-behind queue 做异步落盘 | 设计选择 | P1 |

## 风险分析

### 技术风险

1. **aiosqlite 兼容性**：项目当前未使用 aiosqlite，需新增依赖。风险低（纯 Python，无 C 扩展问题）
2. **since_sequence 回放 + 实时流衔接**：回放历史事件和实时 Queue 之间可能出现间隙或重复。需要在 EventBus 内部用锁保证：先锁定 → 查 DB → 注册 Queue → 解锁，确保不丢事件
3. **write-behind 异步落盘**：如果 emit 是 fire-and-forget 写 DB，进程崩溃时可能丢最后几条事件。M0-M4 阶段可接受（LocalEngine 本就是内存为主）

### 与现有代码的冲突

- `local_engine.py` 的 `_emit` / `_subscribers` / `_events` 会被 EventBus 替换，但对外接口不变
- 现有契约测试（tests/contract/）依赖 subscribe/query_events 行为，需保持兼容
- T1A.7-T1A.10（4 个 plugin）依赖 `register_hook` + hook 分发，T1A.3 是它们的前置

### 依赖

- **上游**：T0.4 LocalEngine 骨架 ✅
- **下游**：T1A.7 lifecycle、T1A.8 metrics、T1A.9 squad、T1A.10 cc_pool、T2A.3 SLAAggregator、T4A.1 memory_pool

## 后续行动

- [ ] eval-doc 已注册到 .artifacts/eval-docs/
- [ ] 用户已确认 testcase 表格 (status: draft → confirmed)
