# Batch 0 Kickoff · Pair Session Runbook

> 2026-04-15 · **AI 快车道：目标半天完成**（Wed AM · 09:00-12:00）
> 目标: 完成 M0 —— T0.1 ConversationEngine + T0.2 WS schema + T0.3 契约测试
> 执行方式: DevA + DevB **pair programming**（同屏或 tmux share）；两个 Claude Code 会话分别跑在 A/B 两台机器 / 两个 worktree
>
> **时间说明**：原计划 2 天，因 AI 并发执行压缩为 **3 小时**。§1 Session 结构为原文保留作参考节点，实际节奏见下：
>
> | 时段 | 实际档期 | 主要产出 |
> |---|---|---|
> | 09:00-10:00 | T0.1 起草 + DevB 并行准备能力表 | Protocol 草稿 + 能力映射 |
> | 10:00-10:30 | T0.1 决策讨论 + 终稿 | conversation-engine.md v1.0 |
> | 10:30-11:30 | T0.2 起草 + DevA 并行准备映射表 | WS schema 草稿 |
> | 11:30-12:00 | T0.2 决策 + T0.3 契约测试 + push | M0 验收 |

---

## 0. 准备（会前 15 分钟）

### 双方各自做：

```bash
# 拉最新 main
cd <AutoService repo>
git checkout main
git pull

# 创建各自的 worktree
# DevA:
git worktree add ../AutoService-dev-a -b dev-a

# DevB:
git worktree add ../AutoService-dev-b -b dev-b

# 在各自的 worktree 启动 Claude Code
cd ../AutoService-dev-{a|b}
claude  # 启动 CC 会话
```

### 准备协作频道：
- 同屏：Zoom / 腾讯会议 / tmux 共享
- 异步：GitHub Issue（可以是 "Batch 0 Kickoff" Issue 贴决策讨论）

### 确认角色：
| 任务 | Driver | Reviewer |
|---|---|---|
| T0.1 ConversationEngine | 推荐 **DevA**（后端背景更近）| DevB |
| T0.2 WS schema | 推荐 **DevB**（前端视角更关键）| DevA |
| T0.3 契约测试 | **DevA** | DevB |

也可两人同时分别 drive，再交叉 review；见 §5 替代方案。

---

## 1. Session 结构（3 小时冲刺）

| 时段 | 活动 | 主导 |
|---|---|---|
| Wed 09:00-10:00 | T0.1 ConversationEngine 设计（DevA 起草 + DevB 并行准备能力表） | DevA driver |
| Wed 10:00-10:30 | T0.1 决策讨论 + 终稿 | 双方 |
| Wed 10:30-11:30 | T0.2 WS schema 起草（DevB 起草 + DevA 并行准备映射表） | DevB driver |
| Wed 11:30-12:00 | T0.2 决策 + T0.3 契约测试 + M0 验收 commit+push | 双方 |

---

## 2. Wed 09:00-10:00 · T0.1 启动

### DevA（Driver）在自己的 CC 会话贴：

```
启动 Red 任务 T0.1 ConversationEngine 设计。

**背景**:
- 我是 DevA，正在和 DevB 做 pair session
- 这是 path B 适配层先行策略的核心契约，决定后续 3 日冲刺走向
- 输出必须同时满足 LocalEngine（现阶段）和 ZchatEngine（M5 切换）两种实现

**任务**:
1. 读 docs/zchat-plan/01-protocol-primitives.md §5-9 （Mode/Gate/Timer/Event 语义）
2. 读 channels/feishu/channel_server.py （理解现有 AutoService 的路由/生命周期）
3. 读 autoservice/cc_pool.py （理解现有 sticky session 语义）
4. 起草 docs/contracts/conversation-engine.md，包含：
   - Python Protocol 类定义（完整方法签名）
   - 每个方法的语义注释
   - Mode 枚举（auto/copilot/takeover）+ 状态转换规则
   - Gate 可见性（public/side/system）+ 决策规则
   - Timer 7 类（onboard/placeholder/slow_query/takeover_wait/idle/close/first_reply）
   - Event 类型清单（与 zchat-plan 01 §9 命名对齐）
   - 生命周期 hook 签名（on_conversation_created / on_conversation_closed / on_mode_changed / on_timer_expired）

5. 列出 5-8 个关键设计选择题让我和 DevB 决定，例如：
   - Mode 切换是否允许并发？
   - Timer 粒度 ms 还是 s？
   - Gate 降级是否可逆？
   - Event 订阅 sync vs async？
   - Conversation id 格式：UUID / 渠道前缀 / zchat 兼容？
   - error 处理：抛异常 vs Result 类型？
   - 你发现的其他边界问题

6. 不要 commit；起草完后停住等我和 DevB 讨论决策

按顺序执行，每读完一个大文件汇报关键收获。
```

### DevB（Reviewer）此时在自己的 CC 会话贴：

```
我是 DevB，正在 pair session 中 review T0.1。

DevA 正在起草 ConversationEngine 抽象。在他完成前，请我并行做准备：

1. 读 docs/prd/AutoService-UserStories-v1.1.md 所有 Epic 2 的 US
2. 读 docs/zchat-plan/02-channel-server.md §5（Bridge API）+ §3（IRC transport）
3. 读 docs/zchat-plan/05-user-journeys.md
4. 列出前端视角下 ConversationEngine 必须暴露给 Web 前端的"能力清单"：
   - 客户端发消息
   - 客户端接消息（含 edit/续写）
   - 客服端 operator_join
   - 客服端 operator_message (side visibility)
   - 客服端 /hijack
   - 分队卡片实时刷新
   - CSAT 评分请求/响应
   - 断线重连 + 消息回放（关键！）
   - ... 其他你想到的

5. 用表格形式输出：前端能力 → 对应 ConversationEngine 方法的预期调用 → 触发的 Event

这张表稍后要和 DevA 的 Protocol 对齐，找出遗漏的方法或 Event。

不要起草任何代码，只做研究笔记。
```

---

## 3. Wed 10:00-10:30 · T0.1 决策讨论

### 双方把各自产出贴在一起对照

两人合并视图：

**DevA 产出**: `docs/contracts/conversation-engine.md` 草稿 + 5-8 个选择题

**DevB 产出**: 前端能力 → Engine 方法的映射表

### 对照检查清单

| 项 | DevA 的 Protocol 是否覆盖 | DevB 能否消费 |
|---|---|---|
| US-2.1 3 秒问候 | `create_conversation` + Timer(onboard) | 前端需 WS 收 `conversation.created` + `agent.reply` |
| US-2.2 占位续写 | `send_reply(placeholder)` + `edit_message` | 前端需 WS 收 `message.edited` |
| US-2.4 Copilot | `switch_mode(copilot)` + operator_join | 前端需 WS 收 `mode.changed` + `participant.joined` |
| US-2.5 /hijack | `switch_mode(takeover)` | 前端需发 `operator_command` |
| US-2.6 角色翻转 | `mode=takeover` 下 Gate 行为 | 前端需感知 visibility 降级 |
| CSAT | `resolve()` + Timer 触发 `csat_request` | 前端需 WS 收 `csat_request` + 能发 `csat_response` |
| 断线重连 | `events.query(conversation_id, since)` | 前端需能拉历史 |

**任一行未覆盖 → DevA 补方法，或 DevB 补能力**。

### 集中决策 5-8 个设计选择题

由两人在白板 / Issue 讨论回复，每题记录：
- 结论
- 理由
- 可逆性（未来能否改）

### DevA 在 CC 会话贴：

```
决策结果汇总：

1. Mode 并发: {决策}
2. Timer 粒度: {决策}
3. Gate 降级可逆: {决策}
...

请你：
1. 基于决策更新 docs/contracts/conversation-engine.md 终稿
2. 在文件头加 YAML frontmatter:
   ```
   version: 1.0
   frozen_at: 2026-04-{Day}
   signed_off_by: [DevA, DevB]
   ```
3. Edit docs/plans/task-status.md 把 T0.1 改为 🟩 completed，Owner 填 "DevA+DevB"
4. commit "contract: T0.1 ConversationEngine frozen (v1.0)"
5. 不要 push，等 T0.2 一起 push
```

### DevB 在 CC 会话贴：

```
DevA 已完成 T0.1 ConversationEngine 终稿。请 review：

1. 读 docs/contracts/conversation-engine.md
2. 对照我之前的前端能力表，确认每项能力都有对应 Engine 方法
3. 特别检查：
   - 断线重连路径是否完整（是否有 sequence_number / last_event_id？）
   - 错误语义是否明确（Engine 抛什么 exception？前端怎么降级？）
   - 版本升级路径（未来加方法是否破坏兼容？）
4. 输出 review 清单：通过项 / 疑问项 / 强烈反对项
5. 若无强烈反对 → 在 GitHub Issue "Batch 0 Kickoff" 留言 "T0.1 approved by DevB"
```

---

## 4. Wed 10:30-11:30 · T0.2 启动

### DevB（Driver）在自己的 CC 会话贴：

```
启动 Red 任务 T0.2 WebSocket schema 冻结。

**背景**:
- T0.1 已冻结 (docs/contracts/conversation-engine.md v1.0)
- 这是前后端唯一的外部接口面，决定 3 个 Web 前端的消息消费
- 必须覆盖 17 个 User Story 的所有消息流

**任务**:
1. 读 docs/contracts/conversation-engine.md (T0.1 产物)
2. 读 docs/zchat-plan/02-channel-server.md §5 Bridge API 14 种消息类型
3. 读 docs/prd/AutoService-UserStories-v1.1.md 所有 US 的 Gherkin
4. 起草 docs/contracts/frontend-ws-schema.md，包含：
   - WebSocket 端点定义（/ws/customer / /ws/operator / /ws/admin 三路）
   - **客户端 → 服务端**消息类型（至少 10 种）：
     - customer_message, operator_join, operator_message, operator_command, 
       admin_command, csat_response, client_hello, client_ack, reconnect_request, ...
   - **服务端 → 客户端**消息类型（至少 10 种）：
     - agent_reply, message_edited, mode_changed, timer_expired, csat_request,
       conversation_closed, squad_card_update, sla_alert, error, pong, ...
   - 每种消息的 JSON Schema（字段名 / 类型 / 必填 / 示例）
   - **reconnect 协议**（last_event_id、缺失事件重放）
   - **版本协商**（client_hello 含 protocol_version）
   - **error 语义**（错误码分类 + 客户端应如何处理）

5. 列出 5-8 个关键设计选择题，例如：
   - 消息 id 格式：UUID / 服务端递增 / 混合？
   - 二进制载荷（文件/图片）走 WS 内嵌 base64 还是另走 HTTP URL？
   - 事件序列号是全局还是 per-conversation？
   - 断线后服务端缓存多久的事件用于 reconnect？
   - 心跳间隔 / 超时阈值？
   - error 是否带 retry_after？

6. 不要 commit；起草完后停住等 DevA 讨论决策

按顺序执行，每种消息类型完成一批（~5 个）就停下来让我确认格式一致性。
```

### DevA（Reviewer）此时在自己的 CC 会话贴：

```
我是 DevA，正在 pair session review T0.2。

DevB 正在起草 WS schema。在他完成前请我并行做准备：

1. 读 docs/contracts/conversation-engine.md (T0.1 产物)
2. 列出 ConversationEngine 所有方法 → 它们在 WS schema 中应有的对应消息类型
3. 列出所有 Event 类型 → 应推送到 WS 的子集（哪些对前端可见）
4. 关注点：
   - Gate 可见性如何在 WS 层体现（前端能看到 side 消息吗？）
   - Event 的 hook 是否都有对应 WS push？
   - mock 实现的难度（复杂消息类型在 mock 里怎么模拟）

5. 输出：ConversationEngine 方法 → WS 消息 映射预期表

稍后要和 DevB 的 schema 对照。
```

---

## 5. Wed 11:30-12:00 · T0.2 决策 + T0.3 契约测试

### T0.2 决策讨论

同 T0.1 流程：对照映射表 + 决策选择题 + 终稿。

### DevB 贴：

```
T0.2 WS schema 决策汇总：{贴决策}

请你：
1. 更新 docs/contracts/frontend-ws-schema.md 终稿
2. 加 YAML frontmatter (version/frozen_at/signed_off_by)
3. 生成 docs/contracts/test-vectors/ 示例数据（每种消息至少 2 个正例 + 2 个反例）
4. Edit task-status.md 把 T0.2 改为 🟩，Owner "DevA+DevB"
5. commit "contract: T0.2 WS schema frozen (v1.0)"
```

### 转入 T0.3 契约测试

### DevA 贴：

```
启动 T0.3 契约测试 suite（Green 任务，我主 drive）。

**任务**:
1. 读 docs/contracts/conversation-engine.md + frontend-ws-schema.md
2. 读 docs/contracts/test-vectors/ 示例数据
3. 创建 tests/contract/ 目录
4. 生成 3 类测试：
   a) Engine Protocol 合规测试（每个方法的入参/出参 schema 校验）
   b) WS message schema 校验测试（每种消息类型对 test-vectors 做 pytest parametrize）
   c) 状态转换测试（Mode 切换规则、Gate 降级规则、Timer 触发规则）
5. 确保测试可独立跑：`pytest tests/contract/ -v`
6. 完成后：
   - Edit task-status.md T0.3 → 🟩，Owner DevA
   - commit "test: T0.3 contract test suite passing"
   - 输出测试数量统计

**不跑 dev-loop**（这任务本身就是写测试，不需要 skill-3 再生成测试）
```

### DevB 并行做：

```
T0.3 由 DevA 主做，请我并行完成 M0 收尾：

1. 把 T0.1 / T0.2 / T0.3 的产物合并检查：
   - docs/contracts/conversation-engine.md ✓
   - docs/contracts/frontend-ws-schema.md ✓
   - docs/contracts/test-vectors/ ✓
   - tests/contract/ ✓
2. 生成 docs/contracts/README.md（三份契约文件的入口 + 变更规则）
3. 更新 docs/plans/task-status.md 的 P0 进度汇总行
4. 跑 `pytest tests/contract/` 本地验证通过
5. commit "contract: M0 documentation and index"
```

---

## 6. M0 验收与 push

### 最后联合 commit:

```bash
# 双方在各自的 worktree 都 commit 后，其中一方（通常 Lead）做联合 push:
# 注意：契约批次合入公共 `dev` 分支，**不直接进 main**（见 task-status.md §6）

git checkout dev
git merge --no-ff dev-a  # A 线改动（T0.1 + T0.3 + part of T0.2 review）
git merge --no-ff dev-b  # B 线改动（T0.2 + README）
git push origin dev

# 验收清单
pytest tests/contract/ -v                # 契约测试全绿
ls docs/contracts/                       # 4 文件齐全
grep "🟩" docs/plans/task-status.md | grep "T0\." | wc -l  # 应 = 6（P0 全绿）
```

### 开 "M0 Milestone 达成" 的 Issue 作为记录：
```markdown
# M0 Milestone · 契约冻结完成

## 产出
- [`docs/contracts/conversation-engine.md`](../../docs/contracts/conversation-engine.md) v1.0
- [`docs/contracts/frontend-ws-schema.md`](../../docs/contracts/frontend-ws-schema.md) v1.0  
- [`docs/contracts/test-vectors/`](../../docs/contracts/test-vectors/) (N 个示例)
- [`tests/contract/`](../../tests/contract/) (M 个测试通过)

## 关键决策
- 决策 1: ...
- 决策 2: ...
...

## 下一步
- DevA: 启动 T0.4 LocalEngine 骨架（用 §1 启动任务模板）
- DevB: 启动 T0.6 前端 monorepo 骨架（用 §1 启动任务模板）
- 首次 Milestone 同步: M1 完成后（Wed EOD 前）5 分钟
```

---

## 7. 替代方案：如果两人不能同时在线

### 异步 pair 流程（压缩版，总耗时 ~4h）

适用于 A/B 有 1-2h 时差但都能响应 GitHub Issue 的场景。

**步骤 1**（DevA 主导，~1h）:
- DevA 跑 T0.1 前置研究 + 起草 Protocol
- 产出发到 GitHub Issue "Batch 0 Kickoff"；@DevB

**步骤 2**（DevB 响应，30 min）:
- DevB 30 分钟内 review + 回复映射表 + 决策意见
- DevA 根据反馈更新终稿

**步骤 3**（DevB 主导，~1h）:
- DevB 主 drive T0.2，重复同步
- DevA 做 T0.3 契约测试
- 最终 push

**代价**：比同屏多 ~1h，但不要求实时同步。

---

## 8. 应急情形

### 决策无法达成

```
T0.1 选择题 3「Gate 降级是否可逆」分歧严重：
- DevA 主张: 不可逆（对应 zchat 语义）
- DevB 主张: 可逆（前端体验需要）

操作：
1. 两人各自起草 300 字方案 + 影响分析
2. 贴到 Issue，@Lead / @用户
3. 30 分钟内要求决策
4. 期间 T0.1 状态 ⚠️ blocked "HUMAN-REQUIRED: Gate 可逆性决策"
5. 双方转做无依赖任务（DevA 可提前启动 T0.4 LocalEngine 骨架，基于暂定方案；DevB 可提前做 T0.6 frontend monorepo）
```

### dev-loop 工具缺失或失败

Batch 0 本身不跑标准 dev-loop（无 skill-5/2/3/4）；这三个任务是 spec 型工作。若遇到问题直接手工修正即可。

---

## 9. Day 3+ 转入 Batch 1

M0 通过后：
- 双方在 CC 贴 `cc-prompt-templates.md §12.1` "我该做什么？"
- CC 会推荐 Batch 1 任务（T0.4 / T0.5 / T0.6）
- 贴 §1 启动任务模板依次开干

---

## 附：pair session 节奏建议

| 时间段 | 总时长 | 主要产物 |
|---|---|---|
| 会前 15 min | — | worktree / CC 启动 / 协作频道就绪 |
| Wed 09:00-10:00 | 1h | T0.1 草稿 + DevB 能力表 |
| Wed 10:00-10:30 | 30m | T0.1 决策讨论 + 终稿 |
| Wed 10:30-11:30 | 1h | T0.2 草稿 + DevA 映射表 |
| Wed 11:30-12:00 | 30m | T0.2 决策 + T0.3 测试 + push |
| **合计** | **3h 同屏** | M0 验收（Wed 12:00 前）|

---

*v1.0 · 2026-04-15 · 仅用于 Batch 0 一次性 kickoff；M0 后作废归档*
