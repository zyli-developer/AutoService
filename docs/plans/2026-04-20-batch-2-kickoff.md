# Batch 2 Kickoff · Publish gate + 三端 tenant 化 + Admin 骨架

> 4 tasks · est. ~9h · 含 1 个 Large (T1B.7 critical path)

## Pre-checks

- [ ] Batch 1 gate 通过：cc_pool tenant-aware、dream sync 落盘、rehearsal 端点可用
- [ ] Batch 1 提交已落盘
- [ ] `.autoservice/published/` 和 `.autoservice/archived/` 目录可写

## Tasks

| ID | Task | Slot | Owner | Mode | Est. |
|---|---|---|---|---|---|
| T1B.7 ★ | Publish gate + tarball + 归档 + ForkCreator | A | Dev1 | solo | 8h |
| T1F.3 | customer-chat 路由 + tenant 化 | B | Dev1 | solo | 3h |
| T1F.4 | operator-console 路由 + tenant 化 | B | Dev1 | solo | 3h |
| T1F.5 | admin-portal 双模式分发 + 布局骨架 | B | Dev1 | solo | 3h |

## Execution Order

1. **T1B.7 优先开火**（critical path，longest 任务，占 slot A 整个 batch）
2. **Slot B 串行 frontend**：T1F.3 → T1F.4 → T1F.5
3. T1B.7 允许拆成两子任务（如超时）：
   - T1B.7a：`autoservice/publish.py` 核心模块（gate / archive / runbook / ForkCreator）
   - T1B.7b：`api_routes.py` 新增 `/publish /unfreeze` 端点接线 + 集成测试

## Key files touched

- `autoservice/publish.py` — **new**
- `autoservice/api_routes.py` — 加 /publish /unfreeze 端点
- `frontend/apps/customer-chat/src/App.tsx` — 路由 + useTenantId
- `frontend/apps/operator-console/src/components/WorkspacePage.tsx` — 路由 + useTenantId
- `frontend/apps/admin-portal/src/App.tsx` — 根据 useSessionMode 分发
- `frontend/apps/admin-portal/src/layouts/MasterLayout.tsx` — **new**
- `frontend/apps/admin-portal/src/layouts/TenantLayout.tsx` — **new** (stub)

## T1B.7 深度拆解

参考 [spec §6](../superpowers/specs/2026-04-20-tenant-sandbox-design.md#6-publish-gate)：

1. `_check_publish_gate(tenant_id)` — 4 条 gate 条件
2. `_build_publish_archive(tenant_id)` → tar.gz，内容见 §6.3
3. `_write_publish_record()` → `.autoservice/published/<tid>.json`
4. `_freeze_sandbox()` → config.json.status 翻转 + 后续写入 409
5. `_write_runbook()` → 操作手册 md 自动生成
6. `_archive_sandbox()` → 物理 mv 到 `.autoservice/archived/<tid>_<ts>/`
7. `ForkCreator` 协议 + `LocalTarballForkCreator` 默认实现
8. api_routes: `/api/onboard/publish` + `/api/onboard/unfreeze`

## Smoke

```bash
# T1B.7 done 后
pytest tests/publish/test_publish_gate_checks.py -v
ls .autoservice/published/   # 应有 tarball + json record + runbook md

# T1F.3 done 后
cd frontend && pnpm dev
# 访问 http://localhost:3000/t/tenant_foo/chat → WS 连接日志含 tenant_foo

# T1F.4 done 后
# 访问 http://localhost:3000/t/tenant_foo/operator

# T1F.5 done 后
# 访问 http://localhost:3000/ → 进 MasterLayout
# curl /api/session/mode 的 mock tenant 响应 → 应切 TenantLayout stub
```

## Gate · 进 batch-3 前必过

- [ ] `pytest tests/publish/` 全绿
- [ ] 手工 publish 产出：tarball + runbook + record 三件套齐全
- [ ] 沙盒 `config.json.status = "published_pending_fork"` + 目录已 mv 到 archived/
- [ ] `/t/<tid>/*` 访问已归档租户返回 410
- [ ] 三端在 `/t/tenant_foo/*` 路由下可加载
- [ ] admin-portal 默认进 MasterLayout
- [ ] commit 覆盖所有改动
