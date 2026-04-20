# Batch 3 Kickoff · Master tabs + Wizard 迁移（真并行）

> 2 tasks · est. ~4h · 推荐 `superpowers:dispatching-parallel-agents` 真并行

## Pre-checks

- [ ] Batch 2 gate 通过：publish 端点可用、三端 tenant 化、admin MasterLayout 就绪
- [ ] Batch 2 提交已落盘

## Tasks

| ID | Task | Slot | Owner | Mode | Est. |
|---|---|---|---|---|---|
| T1F.6 | 租户列表 + 代入预览 tabs | A | Dev1 | parallel (subagent) | 3h |
| T1F.7 | WizardTab 迁移 + publish/review 接线 | B | Dev1 | parallel (subagent) | 3h |

## Execution Order — 真并行

T1F.6 和 T1F.7 修改不同文件、不同路由，**可用 subagent 同时开工**：

```
dispatch parallel:
  subagent-A → T1F.6 (TenantListTab + TenantPreviewTab)
  subagent-B → T1F.7 (WizardTab 迁移 + 接线)
```

## Key files touched

### T1F.6
- `frontend/apps/admin-portal/src/components/master/TenantListTab.tsx` — **new**
- `frontend/apps/admin-portal/src/components/master/TenantPreviewTab.tsx` — **new**
- `frontend/apps/admin-portal/src/layouts/MasterLayout.tsx` — 注册 `/master/tenants` 和 `/master/tenants/:id/preview` 路由

### T1F.7
- `frontend/apps/admin-portal/src/components/wizard/WizardTab.tsx` — 路由迁 `/master/tenants/new` + Step 4 publish 按钮 + Step 2 review 按钮接线
- `frontend/apps/admin-portal/src/components/wizard/SandboxReady.tsx` — publish onClick
- `frontend/apps/admin-portal/src/components/wizard/VirtualRehearsalStep.tsx` — review onClick

## Smoke

```bash
# 启 backend + 前端
cd frontend && pnpm dev &

# T1F.6 smoke
# 访问 http://localhost:3000/master/tenants → 列出 .autoservice/sandbox/ 下所有租户
# 点击进入 /master/tenants/:id/preview → iframe 内嵌 /t/<tid>/chat，可对话

# T1F.7 smoke
# 访问 http://localhost:3000/master/tenants/new → 走完向导
# Step 4 点"一键对外" → 成功调 /api/onboard/publish → 看到 tarball 下载或路径展示
# Step 2 每条对话点 approve/flag → rehearsal.json 更新
```

## Gate · 进 batch-4 前必过

- [ ] `/master/tenants` 列表能读 `.autoservice/sandbox/` 下真实租户
- [ ] `/master/tenants/:id/preview` iframe 能嵌入对话
- [ ] `/master/tenants/new` 向导全流程 + Step 4 publish 成功
- [ ] Step 2 审核按钮持久化到 rehearsal.json
- [ ] commit 覆盖两个任务的改动
