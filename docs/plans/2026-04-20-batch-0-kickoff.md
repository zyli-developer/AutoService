# Batch 0 Kickoff · Foundation

> 3 tasks · est. ~4h · parallel_capacity=2

## Pre-checks

- [ ] Design spec reviewed: [2026-04-20-tenant-sandbox-design.md](../superpowers/specs/2026-04-20-tenant-sandbox-design.md) §2 沙盒目录 schema + §3.1 /upload
- [ ] Git branch is `dev-a`
- [ ] `.autoservice/sandbox/` dir 可写（gitignored）

## Tasks

| ID | Task | Slot | Owner | Mode | Est. |
|---|---|---|---|---|---|
| T1B.1 | 沙盒目录 schema + /upload KB + souls 落盘 | A | Dev1 | solo | 4h |
| T1F.1 | useTenantId 通用 hook | B | Dev1 | parallel (subagent) | 1h |
| T1B.5 | /api/session/mode endpoint | A (after T1B.1) | Dev1 | solo | 1h |

## Execution Order

1. **并行开局**：同时启动 T1B.1（主线 focus）和 T1F.1（subagent）
2. **T1B.1 完成后**：接着做 T1B.5（同文件域，顺手）
3. **T1F.1 完成后**：subagent 空闲，等待 batch-1 任务

## Key files touched

- `autoservice/onboarding.py` — `/upload` 新增 save_drafts + KB ingest + dream_soul 模板拷贝
- `autoservice/soul_generator.py` — `save_drafts` 目标改到 `.autoservice/sandbox/<tid>/souls/`
- `autoservice/dream_soul_template.md` — 新建，静态 Dream Engine 人格模板
- `autoservice/api_routes.py` — 新增 `/api/session/mode`（返回 `{mode: "master", role: "platform_admin"}`）
- `frontend/packages/shared/useTenantId.ts` — 新 hook
- `frontend/packages/shared/useTenantId.test.ts` — 新测试

## Smoke

```bash
# T1B.1 done 后
python -c "from autoservice.onboarding import *; import json; print(json.dumps(...))"
ls .autoservice/sandbox/tenant_test/souls/   # 应有 5 个 md + _generation_meta.yaml
ls .autoservice/sandbox/tenant_test/kb/      # 应有 kb.db

# T1F.1 done 后
cd frontend && pnpm vitest packages/shared/useTenantId.test.ts

# T1B.5 done 后
curl http://localhost:8000/api/session/mode   # 应返回 {"mode":"master","role":"platform_admin"}
```

## Gate · 进 batch-1 前必过

- [ ] T1B.1 sandbox 目录产物齐全（souls/ × 5 + kb.db + config.json 骨架）
- [ ] T1F.1 vitest 全绿
- [ ] T1B.5 curl 返回正确 mode
- [ ] 一次 `git commit` 覆盖三个任务的产出
