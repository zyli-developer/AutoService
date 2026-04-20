# M1 Sandbox Provisioning · Task Status

> **Scope-specific** status table for this M1 plan.
> Not overriding existing [docs/plans/task-status.md](task-status.md).
>
> Source: [2026-04-20-tasks.yaml](2026-04-20-tasks.yaml) · [2026-04-20-execution-plan.yaml](2026-04-20-execution-plan.yaml)

Last updated: 2026-04-20 (autorun yellow complete · **M1 Gate PASS**)

## Progress

| Milestone | Total | Completed | Pending | Blocked |
|---|---|---|---|---|
| M1 Sandbox Provisioning | **15** | **15** ✅ | 0 | 0 |

**autorun 终点**：15/15 任务完成，0 失败，2 Yellow 通过独立审核落盘。
**M1 Gate**：✅ §10 九条验收全过（9/9 E2E smoke green）。

---

## Batch 0 · Foundation ✅

| ID | Task | Commit | Tests |
|---|---|---|---|
| T1B.1 | 沙盒目录 schema + /upload KB + souls 落盘 | `d9e733a` | 6+56 green |
| T1F.1 | useTenantId 通用 hook | `2e07a24` | 4 green |
| T1B.5 | /api/session/mode endpoint | `11bced8` | 2 green + sanity |

## Batch 1 · Backend fan-out + Frontend hook ✅

| ID | Task | Commit | Tests |
|---|---|---|---|
| T1B.4 🟡 | cc_pool per-tenant soul 注入 | `556b1e9` | 12 new + 39 regression |
| T1B.2 | /activate 幂等 merge | `b5c669a` | 9 new + 6 regression |
| T1B.3 | rehearsal 落盘 + /review 端点 | `819284f` | 7 new + 20 sanity |
| T1B.6 🟡 | Dream 配置 sync | `c8a4960` | 6 new + T6C.3 regression PASS |
| T1F.2 | useSessionMode hook | `8efcb9f` | 4 new（shared 包 8/8） |

## Batch 2 · Publish + 三端 + Admin 骨架 ✅

| ID | Task | Commit | Tests |
|---|---|---|---|
| T1B.7 | Publish gate + tarball + ForkCreator | `1988bc7` | 31 new + 979 broader |
| T1F.3 | customer-chat 路由 + tenant 化 | `cea3bbc` | 5 new |
| T1F.4 | operator-console 路由 + tenant 化 | `38be9c4` | 7 new (TC-TEN-01~07) |
| T1F.5 | admin-portal 双模式分发 + 布局骨架 | `b2bb01a` | 4 App.test + 6 AdminWorkspace |

## Batch 3 · Master tabs + Wizard ✅

| ID | Task | Commit | Tests |
|---|---|---|---|
| T1F.6 | 租户列表 + 代入预览 tabs | `740cb31` | 6 backend + 11 frontend |
| T1F.7 | WizardTab 迁移 + publish/review 接线 | `56c2372` | 10 new |

## Batch 4 · E2E smoke + M1 gate ✅

| ID | Task | Commit | Tests |
|---|---|---|---|
| T1S.1 | E2E sandbox provisioning | `ab65e00` | **9/9 §10 criteria PASS** |

---

## 已知的设计债（follow-up tasks，不影响 M1 Gate）

| # | 债务 | 发现于 | 影响 | 建议 |
|---|---|---|---|---|
| D1 | Claude SDK `system_prompt` 无法 per-call 注入，只能在 CC 进程启动时烘焙 | T1B.4 pre-flight review | 当前 cc_pool factory 正确但每次 create 生成新 subprocess；无 per-tenant 池 + LRU | M2 task：cc_pool 改成 `dict[tenant_id, AsyncPool]` + LRU 回收 |
| D2 | `customer-chat/src/hooks/useTenantId.ts` 是 `frontend/packages/shared/useTenantId.ts` 的本地副本 | T1F.3 worktree 未看到 shared 包 | 功能正确但两份代码，维护风险 | 小 cleanup：切 import 到 `@autoservice/shared`，删本地副本 |
| D3 | `operator-console/src/hooks/useTenantId.ts` 同 D2 | T1F.4 同上 | 同上 | 同上 |
| D4 | `frontend/apps/admin-portal/src/components/master/__tests__/TenantListTab.test.tsx` 首次测试跑前需 `pnpm install`（react-router-dom 新加） | T1F.6 merge 后我手动 install | 一次性 | CI 文档记一笔；或加到 make setup |

---

## M1 Gate 证据

- **15/15 tasks merged** on branch `dev-a` (30 commits since `44ef76e`)
- **9/9 E2E §10 criteria passing**（[tests/e2e/test_sandbox_provisioning.py](../../tests/e2e/test_sandbox_provisioning.py)）
- **1001 broader tests passing**（10 pre-existing failures unrelated，4 skipped）
- **T6C.3 regression PASS**（T1B.6 没破坏 /approve /reject 流）
- **2 Yellow 都有独立审核记录**，写在 commit message 里可追溯

## M2 规划预览

自然下游：
- D1 cc_pool per-tenant 池 + LRU
- Tenant fork 运行模式（TenantLayout 实装 + fork 仓 CI）
- Dream Engine 升级为真 agent（soul_generator 扩 5 角色 + proposal_pipeline 读 tenant soul）
- GAP-002 管理群 IM 载体
- GAP-006 晨起推送 IM 送达
- 团队邀请 / tenant_admin 鉴权
- ForkCreator 的 `GitHubApiForkCreator` 实装（替换 `LocalTarballForkCreator`）
- D2+D3 useTenantId 去重 cleanup

## 相关文档

- [tasks.yaml](2026-04-20-tasks.yaml) · 任务定义
- [execution-plan.yaml](2026-04-20-execution-plan.yaml) · 批次调度
- [execution-plan.md](2026-04-20-execution-plan.md) · Gantt
- [tenant-sandbox-design.md](../superpowers/specs/2026-04-20-tenant-sandbox-design.md) · 设计源
- [gap-analysis.yaml](2026-04-20-gap-analysis.yaml) · PRD 缺口
- [task-hints.yaml](2026-04-20-task-hints.yaml) · 实施提示
