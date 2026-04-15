# AutoService Claude Code 指令模板

> 2026-04-15 · A/B 开发者在各自 Claude Code 会话直接复制粘贴的指令库
> 配合 [`task-status.md`](task-status.md) + [`collaboration-playbook.md`](collaboration-playbook.md) 使用
>
> **使用方式**：下列模板把 `{占位符}` 替换成实际任务 ID / Owner 后粘贴给 CC

---

## 0. 两个核心原则

**原则 1 · 任务驱动**：不说"帮我写 customer-chat"，说"启动任务 T1B.1"。CC 会自动读 tasks-v3 + task-status + 契约形成完整上下文。

**原则 2 · 状态机驱动**：每次交互 CC 都应先读 `task-status.md` → 再行动 → 更新状态 → commit。状态文件是 CC 的**跨会话短期记忆**。

---

## 1. 🚀 启动任务（Opening）

```
启动任务 {Tx.x}（{任务名}）。

预期行为：
1. 先读 docs/plans/task-status.md 确认 {Tx.x} 是 ⬜ 且无前置阻塞
2. 用 Edit 把 {Tx.x} 行状态改为 🟦 in_progress，Owner 改为 {DevA|DevB}，commit "task: {Tx.x} → in_progress ({Owner})"
3. 读 docs/plans/2026-04-15-prd-gap-tasks-v3.md 中 {Tx.x} 的产出和验收标准
4. 读相关契约文件（docs/contracts/*）
5. 进入 dev-loop 第一步：skill-5-feature-eval simulate 模式，产出 eval-doc
6. eval-doc 产出后停住等我 review，不要自动进入 skill-2

按以上顺序，每步完成汇报，不要跳步。
```

**使用场景**：每个任务的第一次启动。

---

## 2. ⚙️ 推进 dev-loop（Running）

```
继续 {Tx.x}，进入 dev-loop 下一步：

1. skill-2-test-plan-generator 基于刚才的 eval-doc 产出 test-plan
2. test-plan 产出后停住等我确认
3. 确认后 skill-3-test-code-writer 写 e2e 测试
4. 测试写完进入实现阶段（业务代码）
5. skill-4-test-runner 跑测试
6. 全绿 → 改状态 🟩 completed + 填 artifact ID 到 task-status.md 关联列

每步完成汇报，允许我中断调整。
```

**使用场景**：eval-doc 审过之后继续推进。

---

## 3. ✅ 归档完成（Closing）

```
{Tx.x} dev-loop 全绿，请归档：

1. Edit task-status.md 把 {Tx.x} 状态改为 🟩 completed
2. 填"关联"列：从 .artifacts/registry.json 查 eval-doc-XXX, test-plan-XXX, test-diff-XXX, e2e-report-XXX 四个 ID
3. commit "task: {Tx.x} → completed"
4. git push 到 dev-{a|b} 分支
5. 输出一行：下一个可启动的 ⬜ 任务候选（依赖已满足 + 同工作流 + 优先 🟢 Green）
```

---

## 4. 🚧 任务阻塞（Blocked）

```
{Tx.x} 卡住：{简述原因，如 "等 T3A.5 的 16 条规则"}。

操作：
1. Edit task-status.md 把 {Tx.x} 状态改为 ⚠️ blocked
2. 在"依赖"列加 "WAITING: {阻塞的任务 ID}" 或 "BLOCKED-BY: {原因}"
3. commit "task: {Tx.x} → blocked: {原因}"
4. 从我的 ⬜ {A|B} 线任务中挑一个无阻塞的推荐给我（优先 🟢 Green）
```

---

## 5. 🔴 Red 任务（人类主导）

**适用于**: T0.1 / T0.2 / T3A.4 / T3A.5 / T3A.6 / T5A.1 / T5B.2

```
启动 Red 任务 {Tx.x}（{任务名}）。

这是人类决策任务，你是"草稿工"：
1. 读相关参考资料（我会指定，或你自己挑选并列出）
2. 起草 {产出文件路径}：内容包含 {关键字段}
3. 列 3-5 个关键设计选择题让我选（如：X 还是 Y？A 方案 vs B 方案？）
4. 不要自己拍板；产出草稿 + 选择题后停住
5. 我批准（"approved {Tx.x}"）后才 commit 并改状态 🟩
6. 不走完整 dev-loop（Red 任务不需要 test-runner）
```

**T0.1 具体版**:
```
启动 Red 任务 T0.1 ConversationEngine 设计。

1. 读 docs/zchat-plan/01-protocol-primitives.md §5-9
2. 起草 docs/contracts/conversation-engine.md：
   - Python Protocol 类定义
   - 每个方法的语义注释
   - Mode / Gate / Timer 的对齐策略（参考 zchat 命名）
3. 列关键设计选择题：
   - Mode 状态是否允许并发？
   - Timer 粒度是 ms 还是 s？
   - Gate 降级是否可逆？
   - event 订阅是 sync 还是 async？
   - 其他你发现的边界问题
4. 等我批准后 commit
```

---

## 6. 🟡 Yellow 任务（AI 主导 + 人审）

**适用于**: T1A.4 / T1A.5 / T1A.11 / T2A.2 / T2A.5 / T3A.1 / T3A.2 / T3A.7 / T4A.4 / T5A.5 / T5A.7

```
启动 Yellow 任务 {Tx.x}（{任务名}）。

步骤：
1. 读 tasks-v3 对应章节 + 相关 PRD 背景
2. 起草 {产出文件}（可能多个文件）
3. 完成后把 task-status.md 的状态标为 🟡 并在"关联"列填 "REVIEW-PENDING"
4. 输出 review checklist：我要检查的 {N} 个关键点（如 prompt 质量、边界情况、与现有代码一致性）
5. 不要 commit；等我审查
6. 我说 "approved {Tx.x}" 后 → commit + 改 🟩
7. 我说 "rejected {Tx.x}: {原因}" → 改 🟥 failed，30 分钟内重做
```

**T1A.4 具体版**:
```
启动 Yellow 任务 T1A.4 4 角色 soul.md。

1. 读 AutoService-PRD-v1.1.md §5.2 模块 B 四个角色定义
2. 读 autoservice/skills/customer-service/ 看现有 Skill 风格作为参考
3. 为 customer / translate / lead / triage 分别起草 agents/<role>/soul.md
4. 每份包含：角色定位 · 行为约束 · 反幻觉规则 · 多轮交互模式 · 升级条件 · 输出格式
5. 标 🟡 REVIEW-PENDING，输出 review checklist
6. 等我批复
```

---

## 7. 🔍 Lead / Orchestrator 视角

### 7.1 进度总览

```
读 docs/plans/task-status.md，给我：

1. 当前整体进度（x/66，各 Phase 明细百分比）
2. 进行中任务（🟦 + Owner 列表）
3. 阻塞任务（⚠️ + 阻塞原因）
4. 本 Milestone 应启动的 Red 任务（基于 task-execution-plan Batch 表）
5. 下一批可并发启动的 ⬜ 任务（依赖已满足 + 一次最多 5 个）
6. 风险提示（落后于 task-execution-plan §八 里程碑日期的任务）
```

### 7.2 批量并发派发

```
我想并发启动这 {N} 个任务：{Tx.1, Tx.2, Tx.3}。

1. 逐个确认前置依赖已满足（查 task-status.md）
2. 对每个任务，生成一个 Agent tool 的调用参数（prompt 字段用本文档 §1 启动模板）
3. 用 Agent tool 并发派发（run_in_background=true）
4. 输出一个监控表：任务 ID / Agent 名 / 预期产出 / 预期完成信号
5. 告诉我下次检查进度的时间建议
```

### 7.3 Milestone 门控

```
进入 {Mx} 联调（{Milestone 名}）：

1. 读 task-execution-plan.md §五 找 {Mx} 的联调内容和标准
2. 创建 milestone-{Mx} 分支
3. 合并 dev-a 和 dev-b 到该分支
4. 读 AutoService-UserStories-v1.1.md 相关 US 的 Gherkin
5. 运行 skill-4-test-runner 跑端到端
6. 产出 e2e-report，注册到 .artifacts/registry.json
7. 全绿 → merge 到 dev（非 main；main 由 release 流程另行管理），改 task-status.md 对应 Phase 任务状态
8. 有红 → 不 merge；输出失败清单 + 修复建议（分配给对应 Owner）
```

---

## 8. 🔀 契约漂移处理

### 8.1 发现需改契约

```
我发现 {文件:行号} 的契约需要调整：{简述问题}。

流程：
1. 读 docs/contracts/{conversation-engine.md|frontend-ws-schema.md} 确认当前版本
2. 起草变更：{新字段 / 新方法 / 删除 / 重命名}
3. 分析影响面：列出受影响的任务 ID（读 task-status.md 关联列）
4. 起草：
   - 新 schema 片段
   - 更新的 test-vectors
   - 更新的 mock 代码
5. 开 WIP 分支 contract/{简短名称}
6. 输出一段 prompt，我贴给对方线的 CC 作为 review request
7. 不要 merge 到 dev 或 main，等对方线回应
```

### 8.2 接收对方契约变更

```
对方发来契约变更：{贴入对方 prompt}

步骤：
1. 读变更描述 + 改动项
2. 基于我这条线的现有代码，分析兼容性（哪些代码会坏、需改几处）
3. 列出问题或反对意见（若有）
4. 若同意 → 在对方分支的 PR 上 approve + 更新我这条线的代码
5. 若有调整 → 起草反提议 prompt 发回对方
```

---

## 9. 🧪 Fresh Session Recovery（接续上下文）

**当 Claude Code 新开会话 / context 被压缩时**，开场用：

```
我是 {DevA|DevB}，继续 AutoService 项目的 {A|B} 线开发。

请先：
1. 读 docs/plans/collaboration-playbook.md 了解协同规则
2. 读 docs/plans/task-status.md 找所有 Owner={DevA|DevB} 且状态 🟦 的任务
3. 读这些任务对应的 .artifacts/ 中最近的 artifact（看我上次进度到哪）
4. 告诉我：
   - 我在做的任务（含状态）
   - 上次做到哪一步
   - 下一步建议行动

不要开始任何新任务，先汇报状态。
```

---

## 10. 🛠️ 应急模板

### 10.1 dev-loop 反复失败

```
{Tx.x} 的 dev-loop 已经失败 3 次，症状是 {简述}。

诊断流程：
1. 不再重跑 dev-loop
2. 读 e2e-report 最近 3 份找共同失败模式
3. 分析是否：
   a) 契约问题（schema 不一致） → 走 §8.1 流程
   b) Red 决策缺失 → 标 ⚠️ blocked 并报告
   c) 业务逻辑 bug → 定位代码位置
   d) 测试用例错 → 改 test-plan
4. 给出根因分析 + 修复建议，但不要自己改
5. 等我批准再继续
```

### 10.2 发现任务粒度不对

```
任务 {Tx.x} 实际工作量远超预期 / 远小于预期，我建议 {拆分为 a/b/c | 与 {Ty.y} 合并}。

1. 先读 tasks-v3 对应章节确认当前定义
2. 分析拆分/合并后的：
   - 新任务 ID（续编）
   - 依赖关系
   - 对关键路径影响
3. 产出：
   - tasks-v3 的 patch（diff 格式）
   - task-status.md 的 patch
4. 不要直接改文件，先给我看 patch
5. 我批准后再改两个文件并 commit "tasks: split/merge {Tx.x}"
```

### 10.3 需人工紧急介入

```
{Tx.x} 遇到无法 AI 独立解决的问题：{简述}。

流程：
1. 标 task-status.md 为 ⚠️ blocked + 在"依赖"列写 "HUMAN-REQUIRED: {简述}"
2. 起草一封 GitHub Issue 或邮件（给 Lead / 用户侧联系人）：
   - 标题：[AutoService blocker] {Tx.x} - {一句话问题}
   - 正文：背景 / 已尝试 / 卡点 / 需要的决策或资源
3. 输出 Issue 正文让我粘贴
4. 切到下一个无阻塞任务
```

---

## 11. 两人轮值时的交接

### 交接给对方线（跨 Owner）

```
我需要把 {Tx.x} 从 {DevA} 转给 {DevB}，原因：{原因}。

1. 确认 {Tx.x} 当前状态和进度
2. 起草交接备忘（writeup）：
   - 已完成步骤
   - 未完成步骤
   - 关键决策和 rationale
   - 遗留问题
3. 备忘写到 .artifacts/handoff-{Tx.x}-{date}.md
4. Edit task-status.md 把 Owner 改为 {DevB}，"关联"列加 "HANDOFF: handoff-{Tx.x}-{date}"
5. commit "task: {Tx.x} handoff DevA→DevB"
6. 输出一段 prompt 给 {DevB} 的 CC，让他快速上手
```

---

## 12. FAQ 指令

### 12.1 "我该做什么？"

```
告诉我现在应该做什么：
1. 我是 {DevA|DevB}
2. 读 task-status.md 找我的 🟦 in_progress 任务
3. 如果有 → 继续那个任务（引用 §2 或 §3）
4. 如果无 → 推荐 3 个可启动的 ⬜ 任务（优先级：Green > Yellow > Red；Phase 顺序；依赖已满足）
5. 让我选一个
```

### 12.2 "Red 决策还差多少？"

```
列出当前 Milestone 及下一 Milestone 即将需要 Red 决策的任务：

1. 读 task-execution-plan.md §五
2. 对照 task-status.md 当前进度
3. 标注每个 Red 任务的：
   - 预计启动时间
   - 是否已前置启动（如合规 T3A.4-6 需 Wed PM、zchat T5A.1 需 Thu AM）
   - 缺失的决策人 / 资料
4. 输出提醒清单
```

---

## 附：占位符速查

| 占位符 | 替换为 | 例 |
|---|---|---|
| `{Tx.x}` | 具体任务 ID | `T1A.1` |
| `{任务名}` | tasks-v3 中的任务名 | `Mode/Gate 最小实现` |
| `{DevA\|DevB}` | 当前开发者代号 | `DevA` |
| `{Mx}` | 里程碑编号 | `M1` |
| `{产出文件}` | tasks-v3 中指定的文件路径 | `autoservice/engine/local_engine.py` |

---

*v1.0 · 2026-04-15 · 配合 collaboration-playbook.md / task-status.md / tasks-v3.md 使用 · 每 Milestone 更新*
