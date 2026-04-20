# M2 Task Status — Tenant-side Dream Sandbox

**Milestone**：M2 · **生成时间**：2026-04-20 · **源**：[tasks.yaml](2026-04-20-tasks.yaml) · [execution-plan.yaml](2026-04-20-execution-plan.yaml)

## 进度汇总

- **总任务**：38
- **已完成**：14
- **进行中**：0
- **阻塞**：0
- **待办**：24
- **完成率**：37% (14/38)
- **最后更新**：2026-04-21

### 会话日志

| 日期 | 事件 | Commits |
|------|------|---------|
| 2026-04-21 | batch-0 完成（T1B.1 + T1B.2 yellow） | `178919c`, `9def883` |
| 2026-04-21 | batch-1 完成（T1B.3→T1B.5）| `dc49ff0` |
| 2026-04-21 | batch-2 完成（T2B.1 ∥ T2B.2 ∥ T2B.3 · 3 个 subagent 并行）| `1f42aa4` |
| 2026-04-21 | batch-3 完成（T3B.1→T3B.3 · 1 个 subagent）| `e18b183` |
| 2026-04-21 | batch-4 完成（T3B.4 run_dream yellow + inline reviewer APPROVED）| `ec972cd` |
| 2026-04-21 | 模板修复：m2/cc-prompt-templates.md + CLAUDE.md autorun 约定 | 本次 commit |
| 2026-04-21 | batch-5 T3B.6 完成（/api/dream/* endpoints）| `475f32f` |
| 2026-04-21 | batch-5 T3B.5 完成（yellow, inline reviewer APPROVED）| PENDING |

## 更新规则

- 任务开始时：状态改为 `in_progress`，填 `owner` 和 `started_at`
- 任务完成时：状态改为 `done`，填 `completed_at` 并在 `artifacts` 列登记产出（commit hash / 测试报告 / 文件路径）
- 任务阻塞时：状态改为 `blocked`，在 `notes` 栏写原因；同步在 `.artifacts/issues/` 登记 eval-doc
- 每完成一个 batch → 运行该 batch 的 gate 检查并更新本表

---

## Phase 1 — Bootstrap + _master seed

| ID | 名称 | 类型 | 工作量 | 状态 | Owner | Artifacts |
|----|------|------|--------|------|-------|-----------|
| T1B.1 | config.local.yaml schema expectations | green | small | ✅ done | Dev1 | `178919c` (8 tests) |
| T1B.2 | soul_generator 5 roles (add dream) | 🟡 yellow | medium | ✅ done | Dev1 | `9def883` (11 tests, reviewer APPROVED) |
| T1B.3 | ensure_master_tenant() bootstrap | green | medium | ✅ done | Dev1 | `dc49ff0` (4 tests) |
| T1B.4 | ensure_local_admin() fork-side bootstrap | green | small | ✅ done | Dev1 | `dc49ff0` (4 tests) |
| T1B.5 | web_gateway lifespan mode-aware startup | green | small | ✅ done | Dev1 | `dc49ff0` (3 tests) |

**Gate**：Master + tenant boot hooks active；5-role souls 生成正确。

## Phase 2 — Schema migrations

| ID | 名称 | 类型 | 工作量 | 状态 | Owner | Artifacts |
|----|------|------|--------|------|-------|-----------|
| T2B.1 | proposals.tenant_id migration | green | small | ✅ done | Subagent a471feed | `1f42aa4` (6 tests) |
| T2B.2 | memory_pool.tenant_id migration + API | green | small | ✅ done | Subagent a5f2cbf | `1f42aa4` (9 tests) |
| T2B.3 | dream_runs.db schema + repository | green | small | ✅ done | Subagent a869663 | `1f42aa4` (12 tests) |

**Gate**：三张表 schema live；M1 数据未破坏。

## Phase 3 — Dream Agent

| ID | 名称 | 类型 | 工作量 | 状态 | Owner | Artifacts |
|----|------|------|--------|------|-------|-----------|
| T3B.1 | emit_proposal tool | green | small | ✅ done | Subagent a74376f | `e18b183` (16 tests, includes signature guard) |
| T3B.2 | kb_search tool | green | small | ✅ done | Subagent a74376f | `e18b183` (9 tests, FTS JOIN bug fixed vs soul_generator) |
| T3B.3 | list_souls tool | green | small | ✅ done | Subagent a74376f | `e18b183` (9 tests) |
| T3B.4 | run_dream() agent loop (core) | 🟡 yellow | **large** | ✅ done | Subagent af82565 | `ec972cd` (10 tests, inline reviewer APPROVED, cc_pool.acquire(role=) deferred to T3B.5) |
| T3B.5 | cc_pool role='dream' support | 🟡 yellow | medium | ✅ done | Subagent T3B.5 | PENDING (9 tests + 0 regression, inline reviewer APPROVED) |
| T3B.6 | /api/dream/trigger + /api/dream/runs | green | small | ✅ done | Subagent T3B.6 | `475f32f` (15 tests, 0 regression) |

**Gate**：run_dream 产生 draft proposal；cc_pool 隔离验证。

## Phase 4 — DreamScheduler

| ID | 名称 | 类型 | 工作量 | 状态 | Owner | Artifacts |
|----|------|------|--------|------|-------|-----------|
| T4B.1 | should_trigger() logic | 🟡 yellow | medium | ⏳ pending | — | — |
| T4B.2 | scheduler loop + active-tenant discovery | green | medium | ⏳ pending | — | — |
| T4B.3 | /dream-config → scheduler.refresh() | green | small | ⏳ pending | — | — |

**Gate**：idle 租户自动触发；/dream-config 动态 refresh 生效。

## Phase 5 — Magic-link auth

| ID | 名称 | 类型 | 工作量 | 状态 | Owner | Artifacts |
|----|------|------|--------|------|-------|-----------|
| T5B.1 | auth DB schema + repo | green | small | ⏳ pending | — | — |
| T5B.2 | POST /api/auth/request-login | green | small | ⏳ pending | — | — |
| T5B.3 | GET /api/auth/verify → cookie + redirect | green | small | ⏳ pending | — | — |
| T5B.4 | POST /api/auth/logout | green | small | ⏳ pending | — | — |
| T5B.5 | require_tenant_access middleware | green | medium | ⏳ pending | — | — |
| T5B.6 | /api/session/mode auth-state extension | green | small | ⏳ pending | — | — |

**Gate**：request → verify → cookie → 跨 tenant 拒绝；logout 撤销。

## Phase 6 — admin-portal TenantLayout

| ID | 名称 | 类型 | 工作量 | 状态 | Owner | Artifacts |
|----|------|------|--------|------|-------|-----------|
| T6F.1 | useSessionMode + useTenantId real impl | green | small | ⏳ pending | — | — |
| T6F.2 | AuthGate + LoginPage | green | medium | ⏳ pending | — | — |
| T6F.3 | AdminRail variant prop | green | small | ⏳ pending | — | — |
| T6F.4 | AdminTopbar + AvatarMenu extensions | green | small | ⏳ pending | — | — |
| T6F.5 | TenantLayout 4-tab component | green | medium | ⏳ pending | — | — |
| T6F.6 | ChatTab → /api/admin/chat | green | medium | ⏳ pending | — | — |

**Gate**：tenant 品牌 4 tabs 渲染；AuthGate 阻挡匿名；ChatTab 对接 /api/admin/chat。

## Phase 7 — Fork runtime

| ID | 名称 | 类型 | 工作量 | 状态 | Owner | Artifacts |
|----|------|------|--------|------|-------|-----------|
| T7B.1 | TenantContext middleware mode branching | green | medium | ⏳ pending | — | — |
| T7B.2 | tenant_root() path helper | green | small | ⏳ pending | — | — |
| T7F.3 | customer-chat + operator-console mode routing | green | small | ⏳ pending | — | — |
| T7S.4 | scripts/setup.sh mode-aware | green | medium | ⏳ pending | — | — |
| T7S.5 | Fork-mode boot smoke test | green | small | ⏳ pending | — | — |
| T7B.6 | /api/management/chat → _master routing | green | small | ⏳ pending | — | — |

**Gate**：全新 tenant fork 启动；前端路由正确；/api/management/chat → _master 通。

## Phase 8 — ForkCreator + E2E

| ID | 名称 | 类型 | 工作量 | 状态 | Owner | Artifacts |
|----|------|------|--------|------|-------|-----------|
| T8B.1 | GitHubApiForkCreator (gh CLI) | 🟡 yellow | **large** | ⏳ pending | — | — |
| T8B.2 | LocalTarballForkCreator runbook config step | green | small | ⏳ pending | — | — |
| T8S.3 | Full E2E acceptance (@pytest.mark.e2e) | 🟡 yellow | **large** | ⏳ pending | — | — |

**Gate**：spec §8 8-step 验收通过。

---

## Batch 进度

| Batch | 阶段 | 状态 | Gate 检查 |
|-------|------|------|-----------|
| batch-0 | P1 | ✅ 完成 | T1B.1 config schema + T1B.2 dream role ok；8+11 tests；reviewer APPROVED |
| batch-1 | P1 | ✅ 完成 | master + tenant bootstrap + lifespan ok；11 tests；uvicorn 两种模式启动 OK |
| batch-2 | P2 | ✅ 完成 | 3 张表 tenant_id 迁移完毕；27 tests + 0 regression（94 total） |
| batch-3 | P3 | ✅ 完成 | 3 个 dream 工具落盘；34 tests + 0 regression（113 total） |
| batch-4 | P3 | ✅ 完成 | T3B.4 run_dream 完成；10 tests + 99 regression；inline reviewer APPROVED |
| batch-5 | P3 | ✅ 完成 | T3B.5 ✅ done (9 tests + 0 regression, yellow) / T3B.6 ✅ done (15 tests + 0 regression) |
| batch-6 | P4 | ⏳ pending | — |
| batch-7 | P5 | ⏳ pending | — |
| batch-8 | P5 | ⏳ pending | — |
| batch-9 | P6 | ⏳ pending | — |
| batch-10 | P6 | ⏳ pending | — |
| batch-11 | P6 | ⏳ pending | — |
| batch-12 | P7 | ⏳ pending | — |
| batch-13 | P7 | ⏳ pending | — |
| batch-14 | P7 | ⏳ pending | — |
| batch-15 | P8 | ⏳ pending | — |
| batch-16 | P8 | ⏳ pending | — |
