# M2 CC Prompt / Autorun Templates

> M2-scoped (plans_dir=`docs/plans/m2/`). Supersedes and locally overrides the
> M1 [cc-prompt-templates.md](../cc-prompt-templates.md) for paths. Same philosophy:
> task-driven + state-machine-driven.
>
> Used by `/autorun`, `/batch-dispatch`, `/start-task`, `/continue-task`.
> Subagent dispatch prompts **must** reference §3 Closing before commit.

## 0. 核心原则

1. **任务驱动** — 指令以 task-id 为锚（"启动 T1B.3"），不是功能描述
2. **状态机驱动** — 每次动作序列：**读 task-status.md → 做 → 改 task-status.md → commit**
3. **task-status.md 是权威真相** — 不是 TodoWrite、不是 commit message、不是会话日志；它是跨会话、跨 subagent 共享的 single source of truth

**文件位置**：

| 文件 | 角色 |
|------|------|
| [docs/plans/m2/task-status.md](task-status.md) | 权威进度 — 每批动必改 |
| [docs/plans/m2/2026-04-20-tasks.yaml](2026-04-20-tasks.yaml) | 任务定义（只读） |
| [docs/plans/m2/2026-04-20-execution-plan.yaml](2026-04-20-execution-plan.yaml) | batch 调度（只读） |
| [docs/plans/project.yaml](../project.yaml) | plans_dir 指针（只读） |

---

## 1. 🚀 启动任务（Opening）

```
启动任务 {Tx.x}（{任务名}）。

自检步骤：
1. 读 docs/plans/m2/task-status.md 确认 {Tx.x} 是 ⏳ 且无前置阻塞
2. 读 docs/plans/m2/2026-04-20-tasks.yaml 中 {Tx.x} 条目（deliverables + verification + depends_on）
3. 依赖的上游任务必须都是 ✅ done（对照 task-status.md）
4. 读相关 spec 节（spec_doc 路径在 project.yaml milestones.M2）
5. 把 task-status.md 里 {Tx.x} 状态改为 🔄 in_progress，填 owner + started_at
6. commit "task: {Tx.x} → in_progress"

然后进入 TDD 循环：写失败测试 → 实现 → 跑绿 → 提 verification 命令。
```

---

## 2. ⚙️ 推进 dev-loop（Running）

```
针对 {Tx.x} 推进一步：
1. 如果还没测试：写 tests/... 覆盖 deliverables，先跑 red
2. 如果测试 red：实现最小代码让它 green
3. 如果测试 green：
   a. 跑完整 verification（tasks.yaml 里 verification 字段的命令）
   b. 跑相关模块的回归测试（-q，-k 过滤）
   c. 全绿 → 进入 Closing（§3）
   d. 有 red → 进入 Debugging（§4）
```

---

## 3. ✅ 归档完成（Closing）— **每个任务完成必走**

```
{Tx.x} dev-loop 全绿，归档：

1. Edit docs/plans/m2/task-status.md：
   a. {Tx.x} 所在 Phase 表：状态 ⏳/🔄 → ✅ done，填 owner + artifact commit hash
   b. Batch 进度表：该 batch 所有任务完成时打勾 ✅ 完成 + 填 gate 结果
   c. 进度汇总：done 计数 +1，待办 -1，完成率重算
   d. 会话日志：追加一行（日期 · 事件 · commit hash）
2. git add {产出文件} docs/plans/m2/task-status.md
3. commit "feat(m2): {Tx.x} {简述}" 或 "task(m2): {Tx.x} → completed"
   - Commit message 含：verification 结果、测试计数、reviewer 判决（yellow 任务）
4. 输出一行：下一个可启动的 ⏳ 任务候选（依赖已满足）
```

**Batch 边界额外步骤**（该批最后一个任务完成时）：
- Batch 进度表中该 batch 行 → ✅ 完成 + gate 结果简述
- 总任务完成率刷新
- 如果这是 milestone 最后 batch → 提示 `/smoke-test M2`

**Yellow 任务额外步骤**（§6）— self-review 通过后才进 Closing。

---

## 4. 🔴 Debugging（测试失败）

```
{Tx.x} 测试失败。走 superpowers:systematic-debugging：

1. 隔离 failing test（单独跑 + -v 看 traceback）
2. 形成假设（什么 invariant 被破坏了）
3. 最小改动验证假设（加 log / 改 1 行）
4. 确认修复后再跑完整 verification
5. 3 次尝试仍不过 → 标 {Tx.x} 为 ⚠️ blocked in task-status，写详细 notes，跳下一批
```

---

## 5. 🟡 Yellow 任务流程

**M2 Yellow 任务**: T1B.2, T3B.4, T3B.5, T4B.1, T8B.1, T8S.3

```
Yellow 任务与 Green 唯一差别：**Closing 前必须 code-reviewer self-review**。

步骤：
1–4. 同 §1–§4（TDD + verification 绿）
5. 调用 superpowers:code-reviewer subagent：
   - 附 spec 节（Why Yellow 的原因）+ diff 文件列表 + 3-5 个 Yellow 关注点
   - subagent 返回 BLOCKING 或 non-blocking
6. BLOCKING → 修改 1 次（不无限循环）→ 重新 review
7. Approved → 继续 §3 Closing，commit message 加 "reviewer: APPROVED/summary"
```

---

## 6. 🔀 Subagent Dispatch（autorun 下）

**适用范围**：从 batch-7（P5 起）每个 subagent dispatch 必须 inline 以下约束。
**历史例外**（B 决策记录）：batch-0 ~ batch-6（17 任务）用内联 TDD 产出，未产 artifact，统一在 batch-7 dispatch 前一次性回填到 `.artifacts/`。

### 6.1 Closing 约束（task-status + commit）

```
===== Closing 约束（MUST DO）=====
完成所有任务后，**commit 前**：
1. Edit docs/plans/m2/task-status.md：
   - Phase 表中你的任务行：⏳/🔄 → ✅ done，填 owner = "Subagent <agentId>"，artifact = commit hash（你做完才知道；可先填 PENDING，commit 后再 amend / 分两个 commit）
   - Batch 进度表：该 batch 行 → ✅ 完成 + gate 结果简述
   - 进度汇总：done 计数 +N（N = 你完成的任务数）
   - 会话日志：追加一行
2. git add 代码文件 + docs/plans/m2/task-status.md（同一 commit）
3. commit 消息按 §3 格式
```

### 6.2 Artifact 产出约束（dev-loop-skills 兼容）

**每个 batch subagent 必须产出以下 artifact 并注册到 `.artifacts/registry.json`**：

| 阶段 | Artifact 类型 | 何时产 | 放在哪 |
|------|--------------|--------|--------|
| 任务开始前 | `eval-doc`（simulate 模式）| 读 spec + tasks.yaml，写"预期行为 + 验收标准" | `.artifacts/eval-docs/eval-<batch-id>-<brief>.md` |
| 测试全绿后 | `test-diff` | 从 `git diff HEAD -- tests/` 提取，markdown 摘要 | `.artifacts/test-diffs/test-diff-<batch-id>.md` |
| batch commit 后 | `e2e-report` | 跑 `python -m pytest` 对本 batch scope + regression，产结构化报告 | `.artifacts/e2e-reports/e2e-<batch-id>.md` |

**注册命令**（produce 后立即调用）：
```bash
bash scripts/artifact-register.sh \
  --project-root . \
  --type <eval-doc|test-diff|e2e-report> \
  --name "<brief>" \
  --producer "subagent-<agentId>" \
  --path .artifacts/<subdir>/<file>.md \
  --status confirmed
```

注册脚本会：生成唯一 ID（如 `eval-doc-042`）、写入 `.artifacts/registry.json`、`git add .artifacts/ && git commit -m "artifact: register <id> (<type>)"`。stdout 输出生成的 ID，记下来在 subagent 报告里。

### 6.3 Artifact 最小规范

**eval-doc** 格式（~50 行以内）:
```markdown
# Eval: <batch-id> <任务名>
## 预期行为
- 列表：spec §X.Y 说应该发生什么
## 验收标准
- 列表：测试要覆盖的场景（含 red-line）
## 关键 invariant
- 列表：不能违反的约束（CON-X 条目）
```

**test-diff** 格式：
```markdown
# Test diff: <batch-id>
新增 {N} tests across {K} files.
## 新增文件
- list
## 覆盖的场景
- list from eval-doc
## 已修 regression bug
- (if any)
```

**e2e-report** 格式：
```markdown
# E2E report: <batch-id>
Total: {N} pass / {M} fail
## New tests (from this batch)
- green: {list}
- red: {list}
## Regression (preexisting tests)
- green: {count}
- red: {list with root cause}
```

### 6.4 Subagent 报告要求

返回报告必须包含：
- 修改的代码文件列表
- **产出的 artifact 列表 + 在 registry.json 里的 id**
- 测试计数（新增 / 总数 / 回归）
- task-status.md 的具体改动（行号或段落）
- commit hash（代码 + artifact + task-status）
- 遇到的 spec 歧义和决策理由

**主控（非 subagent）执行 batch 时** — 自己就是 executor，同样要产 artifact + 注册 + 更 task-status；不要跳过直接 dispatch 下一批。

---

## 7. 🔍 Progress / Recovery

```
# 进度总览
读 docs/plans/m2/task-status.md 给我：
- 已完成 / 进行中 / 阻塞 / 待办 计数
- 当前 batch 所在 Phase + gate 检查
- 下一个可启动的 ⏳ 候选任务（依赖已满足）

# 会话恢复（fresh session）
1. 读 docs/plans/project.yaml 拿 plans_dir（= docs/plans/m2）
2. 读 docs/plans/m2/task-status.md 找最后一次会话日志条目
3. 识别 🔄 in_progress 或未 commit 的 uncommitted 改动（git status）
4. 从最后一个 ⏳ 边界继续；如果有 🔄 卡住的先解决
5. /autorun resume 或 /continue-task {Tx.x}
```

---

## 8. 应急 / 契约漂移

spec 中途改了（如 §2.4 schema 字段名变更）：
1. 读 `/contract-check` 输出评估影响面
2. 影响仅 Green 任务 → 自动 replan + 继续
3. 影响 Yellow / Red 任务或跨 batch → **halt autorun** + 报告

---

## 附：commit message 规范

```
feat(m2): {Tx.x} {简述}        # 新增功能
fix(m2):  {Tx.x} {修复}        # 修 bug
test(m2): {Tx.x} {测试相关}    # 只改测试
chore(m2): {总述}              # 文档/status 更新
```

Yellow 任务 commit 体补：`Yellow review (code-reviewer subagent): APPROVED — {summary}`
