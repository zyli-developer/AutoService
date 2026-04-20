# M1 Sandbox Provisioning · Task Status

> **Scope-specific** status table for this M1 plan.
>
> **本文件只追踪本 M1 sandbox 计划的 15 个 task**。不覆盖仓内已有的 [docs/plans/task-status.md](task-status.md)（追踪所有历史 M1-M6 工作）。
>
> Source: [2026-04-20-tasks.yaml](2026-04-20-tasks.yaml) · [2026-04-20-execution-plan.yaml](2026-04-20-execution-plan.yaml)

Last updated: 2026-04-20 (autorun green complete)

## Progress

| Milestone | Total | Pending | Deferred 🟡 | Completed | Blocked |
|---|---|---|---|---|---|
| M1 Sandbox Provisioning | 15 | 0 | 2 | 7 | 6 |

**autorun green 终点**：7/15 完成；2 Yellow 按 green 模式规则延后；6 Green 因依赖被延后的 Yellow 而 blocked。

---

## Batch 0 · Foundation ✅

| ID | Task | Type | Effort | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|
| T1B.1 | 沙盒目录 schema + /upload KB + souls 落盘 | Green | M | ✅ completed | Dev1 | `d9e733a` · 6+56 tests |
| T1F.1 | useTenantId 通用 hook | Green | S | ✅ completed | Dev1 | `2e07a24` · 4 tests |
| T1B.5 | /api/session/mode endpoint (master-only) | Green | S | ✅ completed | Dev1 | `11bced8` · 2 tests |

**Gate**: ✅ `.autoservice/sandbox/<tid>/` 可创建产物 · useTenantId 测试通过 · /api/session/mode 返回 master

## Batch 1 · Backend fan-out + Frontend hook（部分）

| ID | Task | Type | Effort | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|
| T1B.4 | cc_pool per-tenant soul 注入 | 🟡 Yellow | M | ⏸ deferred | Dev1 | — (autorun green 不处理 Yellow) |
| T1B.2 | /activate 幂等 merge + channels 落盘 | Green | S | ✅ completed | Dev1 | `b5c669a` · 9 new + 6 regression |
| T1B.3 | /rehearsal/generate 落盘 + review 端点 | Green | S | ✅ completed | Dev1 | `819284f` · 7 + 20 sanity |
| T1B.6 | Dream 配置 sync 到 config.json.dream | 🟡 Yellow | S | ⏸ deferred | Dev1 | — (autorun green 不处理 Yellow) |
| T1F.2 | useSessionMode hook | Green | S | ✅ completed | Dev1 | `8efcb9f` · 4 tests |

**Gate (部分)**: ✅ rehearsal 持久化 ✅ /activate 幂等 ✅ useSessionMode 可用 ⏸ cc_pool / dream sync 推迟

## Batch 2 · Publish + 三端 + Admin 骨架（部分）

| ID | Task | Type | Effort | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|
| T1B.7 | Publish gate + tarball + 归档 + ForkCreator | Green | L | 🛑 blocked | Dev1 | blocked by T1B.6 |
| T1F.3 | customer-chat 路由 + tenant 化 | Green | M | 🛑 blocked | Dev1 | blocked by T1B.4 |
| T1F.4 | operator-console 路由 + tenant 化 | Green | M | 🛑 blocked | Dev1 | blocked by T1B.4 |
| T1F.5 | admin-portal 双模式分发 + 布局骨架 | Green | M | ✅ completed | Dev1 | `b2bb01a` · 4 App.test + 6 AdminWorkspace |

**Gate (部分)**: ✅ admin-portal MasterLayout 正常 · 其他项 blocked

## Batch 3 · Master tabs + Wizard

| ID | Task | Type | Effort | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|
| T1F.6 | 租户列表 + 代入预览 tabs | Green | M | 🛑 blocked | Dev1 | blocked by T1F.3 (via T1B.4) |
| T1F.7 | WizardTab 迁移 + publish/review 接线 | Green | M | 🛑 blocked | Dev1 | blocked by T1B.7 |

## Batch 4 · E2E smoke

| ID | Task | Type | Effort | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|
| T1S.1 | 端到端沙盒 provisioning smoke test | Green | M | 🛑 blocked | Dev1 | blocked by T1F.7 + T1B.7 |

---

## 状态图标

- ⏳ pending · 未开始
- 🔄 in_progress · 进行中
- ✅ completed · 已完成 + 有 verification 证据
- 🛑 blocked · 被外部/上游阻塞
- ⏸ deferred · 按 autorun level 规则暂不处理
- 🟡 Yellow · 需 code-reviewer 介入

## 解锁路径

完成 M1 剩余 8 个任务的依赖顺序：

```
step 1:  T1B.4 (Yellow) — 先做 cc_pool worker 生命周期 pre-flight review
         → 解锁 T1F.3, T1F.4
step 2:  T1B.6 (Yellow) — dream sync；完成后跑 T6C.3 回归
         → 解锁 T1B.7
step 3:  T1B.7 (Large) — publish gate + tarball
         → 解锁 T1F.7
step 4:  T1F.3, T1F.4 parallel (已由 step 1 解锁)
step 5:  T1F.6 (depends on T1F.3)
step 6:  T1F.7 (depends on T1B.7 + T1F.5 done)
step 7:  T1S.1 E2E
```

可以 `/autorun yellow` 让 autorun 带 code-reviewer 审核后自动推完两个 Yellow + 所有下游，或手工 `/start-task T1B.4` 一个个来。

## 相关文档

- [tasks.yaml](2026-04-20-tasks.yaml) · 任务定义 + 依赖
- [execution-plan.yaml](2026-04-20-execution-plan.yaml) · 批次调度
- [execution-plan.md](2026-04-20-execution-plan.md) · Gantt + 依赖图
- [tenant-sandbox-design.md](../superpowers/specs/2026-04-20-tenant-sandbox-design.md) · 设计 spec (§10 验收源)
- [gap-analysis.yaml](2026-04-20-gap-analysis.yaml) · PRD 缺口
- [task-hints.yaml](2026-04-20-task-hints.yaml) · 实施提示
