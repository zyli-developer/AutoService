# M3 CC Prompt / Autorun Templates

> M3-scoped (plans_dir=`docs/plans/m3/`). Supersedes [M2 templates](../m2/cc-prompt-templates.md) for paths. Same philosophy: task-driven + state-machine-driven.
>
> Used by `/autorun`, `/batch-dispatch`, `/start-task`, `/continue-task`.
> Subagent dispatch prompts **must** reference §3 Closing before commit.

## 0. 核心原则

1. **任务驱动** — 指令以 task-id 为锚（"启动 T1S.3"），不是功能描述
2. **状态机驱动** — 每次动作序列：**读 task-status.md → 做 → 改 task-status.md → commit**
3. **task-status.md 是权威真相** — 不是 TodoWrite、不是 commit message、不是会话日志；是跨会话、跨 subagent 共享的 single source of truth
4. **CON-04 红线** — T4S.1 / T4S.8 的修改必须触发独立 code-reviewer；任何 status 写入 bypass 立即 reject
5. **E2 DEFERRED** — M3 范围内任何 subtenant / whitelabel / referral 请求一律 reject；指 [PRD §8.1 Errata](../../prd/AutoService-M3-PRD.md)

**文件位置**：

| 文件 | 角色 |
|------|------|
| [docs/plans/m3/task-status.md](task-status.md) | 权威进度 — 每批动必改 |
| [docs/plans/m3/tasks.yaml](tasks.yaml) | 任务定义（只读） |
| [docs/plans/m3/execution-plan.yaml](execution-plan.yaml) | batch 调度（只读） |
| [docs/plans/m3/2026-04-21-gap-analysis.yaml](2026-04-21-gap-analysis.yaml) | existing_code 引用 + 默认 OQ 值 |
| [docs/superpowers/specs/2026-04-21-m3-*-design.md](../../superpowers/specs/) | Epic design specs（5 份） |
| [docs/plans/project.yaml](../project.yaml) | plans_dir 指针（只读） |

---

## 1. 🚀 启动任务（Opening）

```
启动任务 {Tx.x}（{任务名}）。

自检步骤：
1. 读 docs/plans/m3/task-status.md 确认 {Tx.x} 是 ⏳ 且所有 depends_on 任务都是 ✅
2. 读 docs/plans/m3/tasks.yaml 中 {Tx.x} 条目（deliverables + verification + may_touch）
3. 读相关 Epic design spec（docs/superpowers/specs/2026-04-21-m3-e{N}-*-design.md）中本 story 的"Design Decisions"段
4. 如果 task 标 🔒（CON-04）：额外读 docs/superpowers/specs/2026-04-21-m3-e5-dream-extension-design.md §Cross-cutting RED-LINE guardrails
5. Edit task-status.md：{Tx.x} 行状态 ⏳ → 🏃 in_progress，填 owner + started_at
6. commit "chore(m3): task {Tx.x} → in_progress"

然后进入 TDD 循环（§2）。
```

---

## 2. ⚙️ 推进 dev-loop（Running）

```
针对 {Tx.x} 推进一步：
1. 如果还没测试：写 tests/... 覆盖 deliverables，先跑 red
2. 如果测试 red：实现最小代码让它 green（参考 gap-analysis.yaml existing_code 的 file:line 复用现有基础设施）
3. 如果测试 green：
   a. 跑 tasks.yaml 里 verification 字段的命令
   b. 跑相关模块回归（pytest -q tests/<module>/）
   c. M2 非回归验证（pytest tests/ 排除 e2e，必须不破 M2）
   d. Yellow task：额外跑 `/superpowers:requesting-code-review` 或 Agent subagent_type=code-reviewer
   e. 🔒 task：必须两轮 reviewer（独立 subagent + AST guardrail 测试）
   f. 全绿 + reviewer APPROVED → 进入 Closing（§3）
   g. 有 red → 进入 Debugging（§4）
```

---

## 3. ✅ 归档完成（Closing）— **每个任务完成必走**

```
{Tx.x} dev-loop 全绿 + reviewer APPROVED（如适用），归档：

1. Edit docs/plans/m3/task-status.md：
   a. {Tx.x} 所在 Phase 表：状态 🏃 → ✅ done，填 owner + commit hash
   b. Batch Progress 表：该 batch 所有任务完成时打勾 ✅ + 填 gate 结果
   c. Overall Progress：done 计数 +1，pending -1，百分比重算
   d. Session Log：追加一行 "| 日期 | batch-N | {简述} | {下一候选} |"
2. git add {产出文件} docs/plans/m3/task-status.md
3. commit "feat(m3): {Tx.x} {简述}" 或 "task(m3): {Tx.x} → completed"
   - Commit message 含：verification 结果、测试计数、reviewer 判决（Yellow 任务）
   - 🔒 task: commit body 粘贴 reviewer APPROVED 摘要 + AST guardrail run 结果
4. 输出一行：下一个可启动的 ⏳ 任务候选（依赖已满足，可从 `dependency_graph` 在 tasks.yaml 查）
```

**Batch 边界额外步骤**（该批最后一个任务完成时）：
- Batch Progress 表中该 batch 行 → ✅ + gate 结果简述
- Overall Progress 刷新
- 如果这是 milestone 最后 batch：提示 `/prd2impl:smoke-test M3-{N}`

---

## 4. 🐛 Debugging

```
{Tx.x} 出现测试 red：
1. 调用 `superpowers:systematic-debugging` skill（假设→证据→修复→验证）
2. 禁止：盲改代码、跳过测试、删测试、--no-verify 绕过 pre-commit
3. 如发现 gap-analysis.yaml 的 existing_code 描述与现实不符：
   - 更新 gap-analysis.yaml（添加 [CORRECTION yyyy-mm-dd] 备注）
   - 单独 commit "docs(m3): correct GAP-{N} existing_code"
4. 修好后回 §2 继续
```

---

## 5. 🟡 Yellow Task 额外流程

Yellow = 需要 code-reviewer 独立评审的任务。所有 P2 T2S.1/T2S.5/T2S.8、P3 T3S.1/T3S.2、P4 T4S.1/T4S.3/T4S.4/T4S.7/T4S.8、T1S.3 属此类。

```
Yellow task closing before §3:
1. 实现 + 测试全绿
2. 提 reviewer：
   - 独立 subagent（Agent subagent_type=code-reviewer），或
   - Skill `/superpowers:requesting-code-review`
3. Reviewer 检查项：
   - 契约一致（design spec + tasks.yaml）
   - 测试覆盖（NFR-05 ≥80% for new code）
   - 安全（session/auth/RBAC 相关重点）
   - M2 非回归
4. 判决：APPROVED / CHANGES_REQUESTED
   - APPROVED → 进入 §3 Closing，commit body 含判决
   - CHANGES_REQUESTED → 回 §2 改，再 reviewer
```

---

## 6. 🔒 CON-04 Security-Critical Task（T4S.1, T4S.8, 以及 master_dream_agent 相关）

```
Extra checks before §3 Closing:
1. 测试文件必须包含签名锁测试（如 test_apply_proposal_signature_has_no_dream_imports）
2. T4S.8 AST guardrail 必须跑绿 — 检查 status='applied' / 'accepted' 字符串只出现在 proposal_apply.py / proposal_pipeline.py:update_status
3. 独立 code-reviewer subagent 重点审：
   - 有没有任何 dream_agent / master_dream_agent 引入 `proposal_apply` 或反向
   - 有没有任何 status 字段的参数化通路
   - 有没有绕过 apply_proposal() 的直接 SQL
4. Reviewer 判决必须写在 commit body
5. PR 合并前：AST guardrail test 必须在 CI 绿
```

---

## 6. 🤖 Subagent Dispatch（并行批次）

在 batch-{N} 里把某任务 {Tx.x} 交给 subagent 时，prompt **必须**包含以下五条（否则破坏 task-status single-source-of-truth）：

```
你作为 subagent 执行 {Tx.x}。完成后必须：
1. 写 docs/plans/m3/task-status.md：{Tx.x} 行改 ✅，填 owner=subagent-{N}、commit hash
2. 如是 batch 最后一个任务：更新 Batch Progress + Overall Progress + Session Log
3. commit（内嵌 verification 输出 + Yellow 的 reviewer 判决）
4. 跑 M2 非回归 `pytest tests/`（排除 e2e）必须绿
5. 读 docs/plans/m3/cc-prompt-templates.md §3 Closing — 按该 checklist 逐条闭环

不得：跳过 task-status 更新；不得合并他人代码；不得 --no-verify。

上游 spec：docs/superpowers/specs/2026-04-21-m3-e{N}-*-design.md §{story subsection}
依赖已满足：{list depends_on tasks with ✅ status}
```

---

## 7. 🗓️ Batch Dispatch 开场

调用 `/prd2impl:skill-8-batch-dispatch batch-{N}` 等价于：

```
1. 读 docs/plans/m3/execution-plan.yaml 中 batch-{N} 条目
2. 验证 pre_check 所有条件满足（依赖 batches 都 ✅）
3. 对每个 task：按 mode 字段分派
   - mode: solo → main orchestrator 自己做（Opening §1 → Running §2 → Closing §3）
   - mode: parallel → Agent subagent_type=general-purpose，prompt 按 §6
   - mode: solo_after_subagents → 等 subagents 完再做
4. 全部完成 → 跑 batch gate 命令
5. 写 Session Log + 下一 batch 候选
```

---

## 8. 🏁 Milestone Smoke（M3-1 / M3-2 / M3-3 / M3-gate）

每个 milestone 最后 batch 完成后：

```
/prd2impl:skill-10-smoke-test M3-{N}

需满足：
1. execution-plan.yaml 对应 milestone.gate_checks 全绿
2. 对应 smoke_test 命令运行通过
3. 产出 .artifacts/milestones/m3-{N}-smoke.md
4. task-status.md 更新为 milestone 级进度
```

---

## 9. 默认 OQ 值提示

所有 task 实施时如遇 OQ 相关决策（无 PRD 明文），按 tasks.yaml `meta.default_oq_values` 取值。常用：

- E1: `auth_session` (admin) + `operator_session` (operator); 24h TTL + 30min idle; `auth.db`
- E3: 仅 `pool_wait_ms` + `first_reply_ms` per-tenant；free-text handoff reason；haiku 压缩默认
- E4: empty `[]` fail-closed；M4 移除 region_filter；JP/SG/AU 三国
- E5: `mark_applied` only；indefinite audit；M4+ platform-config mutation
- E6: permanent archive；chromium only
