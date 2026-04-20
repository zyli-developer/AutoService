# M1 Sandbox Provisioning · Task Status

> **Scope-specific** status table for this M1 plan. 初始化状态：全 pending。
>
> **本文件只追踪本 M1 sandbox 计划的 15 个 task**。不覆盖仓内已有的 [docs/plans/task-status.md](task-status.md)（追踪所有历史 M1-M6 工作）。
>
> Source: [2026-04-20-tasks.yaml](2026-04-20-tasks.yaml) · [2026-04-20-execution-plan.yaml](2026-04-20-execution-plan.yaml)

Last updated: 2026-04-20 (initial)

## Progress

| Milestone | Total | Pending | In Progress | Completed | Blocked |
|---|---|---|---|---|---|
| M1 Sandbox Provisioning | 15 | 15 | 0 | 0 | 0 |

---

## Batch 0 · Foundation

| ID | Task | Type | Effort | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|
| T1B.1 | 沙盒目录 schema + /upload KB + souls 落盘 | Green | M | ⏳ pending | Dev1 | — |
| T1F.1 | useTenantId 通用 hook | Green | S | ⏳ pending | Dev1 | — |
| T1B.5 | /api/session/mode endpoint (master-only) | Green | S | ⏳ pending | Dev1 | — |

**Gate**: `.autoservice/sandbox/<tid>/` 可创建产物 · useTenantId 测试通过 · /api/session/mode 返回 master

## Batch 1 · Backend fan-out + Frontend hook

| ID | Task | Type | Effort | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|
| T1B.4 | cc_pool per-tenant soul 注入 | 🟡 Yellow | M | ⏳ pending | Dev1 | — |
| T1B.2 | /activate 幂等 merge + channels 落盘 | Green | S | ⏳ pending | Dev1 | — |
| T1B.3 | /rehearsal/generate 落盘 + review 端点 | Green | S | ⏳ pending | Dev1 | — |
| T1B.6 | Dream 配置 sync 到 config.json.dream | 🟡 Yellow | S | ⏳ pending | Dev1 | — |
| T1F.2 | useSessionMode hook | Green | S | ⏳ pending | Dev1 | — |

**Gate**: cc_pool tenant-aware · rehearsal 持久化 · dream 配置落盘 · useSessionMode 可用

## Batch 2 · Publish + 三端 + Admin 骨架

| ID | Task | Type | Effort | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|
| T1B.7 | Publish gate + tarball + 归档 + ForkCreator | Green | L | ⏳ pending | Dev1 | — |
| T1F.3 | customer-chat 路由 + tenant 化 | Green | M | ⏳ pending | Dev1 | — |
| T1F.4 | operator-console 路由 + tenant 化 | Green | M | ⏳ pending | Dev1 | — |
| T1F.5 | admin-portal 双模式分发 + 布局骨架 | Green | M | ⏳ pending | Dev1 | — |

**Gate**: publish 可产 tarball + 归档 · 三端 /t/<tid>/ 可加载 · admin-portal MasterLayout

## Batch 3 · Master tabs + Wizard

| ID | Task | Type | Effort | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|
| T1F.6 | 租户列表 + 代入预览 tabs | Green | M | ⏳ pending | Dev1 | — |
| T1F.7 | WizardTab 迁移 + publish/review 接线 | Green | M | ⏳ pending | Dev1 | — |

**Gate**: /master/tenants 列表 · preview iframe · wizard 可 publish

## Batch 4 · E2E smoke

| ID | Task | Type | Effort | Status | Owner | Artifacts |
|---|---|---|---|---|---|---|
| T1S.1 | 端到端沙盒 provisioning smoke test | Green | M | ⏳ pending | Dev1 | — |

**Gate**: §10 验收 9 步全通过 · M1 可交付

---

## 状态图标

- ⏳ pending · 未开始
- 🔄 in_progress · 进行中
- ✅ completed · 已完成 + 有 verification 证据
- 🛑 blocked · 被外部/上游阻塞
- 🟡 Yellow · 需 code-reviewer 介入

## 更新规则

- 每次 task 状态变化立即更新
- `completed` 必须附 commit SHA 或 pytest 输出作为 artifact
- Batch 跨越时先跑 gate smoke，通过后再进下一 batch

## 相关文档

- [tasks.yaml](2026-04-20-tasks.yaml) · 任务定义 + 依赖
- [execution-plan.yaml](2026-04-20-execution-plan.yaml) · 批次调度
- [execution-plan.md](2026-04-20-execution-plan.md) · Gantt + 依赖图
- [tenant-sandbox-design.md](../superpowers/specs/2026-04-20-tenant-sandbox-design.md) · 设计 spec (§10 验收源)
- [gap-analysis.yaml](2026-04-20-gap-analysis.yaml) · PRD 缺口
- [task-hints.yaml](2026-04-20-task-hints.yaml) · 实施提示
