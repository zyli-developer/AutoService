# M2 Task Status — Tenant-side Dream Sandbox

**Milestone**：M2 · **生成时间**：2026-04-20 · **源**：[tasks.yaml](2026-04-20-tasks.yaml) · [execution-plan.yaml](2026-04-20-execution-plan.yaml)

## 进度汇总

- **总任务**：38
- **已完成**：35
- **进行中**：0
- **阻塞**：0
- **待办**：3
- **完成率**：92% (35/38)
- **最后更新**：2026-04-20

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
| 2026-04-21 | batch-5 T3B.5 完成（yellow, inline reviewer APPROVED）| `21ed7bb` |
| 2026-04-21 | batch-6 完成（P4 DreamScheduler；T4B.1 yellow reviewer APPROVED）| `5d614bc` |
| 2026-04-21 | Phase 1-4 artifact backfill (option B) | eval-doc-005/006/007/008, test-diff-004/005/006/007/008/009/010, e2e-report-003 |
| 2026-04-21 | batch-7 P5 auth core (artifact-compliant: eval-doc-009, test-diff-011, e2e-report-004) | `442c02b` |
| 2026-04-21 | batch-8 P5 auth gating (eval-doc-010, test-diff-012, e2e-report-005) | `98b21ff` |
| 2026-04-20 | batch-9 P6 frontend shell hooks — T6F.1 + T6F.2 (eval-doc-011, test-diff-013, e2e-report-006) | `ed4ec38` |
| 2026-04-21 | batch-10 P6 shell components — T6F.3 + T6F.4 (eval-doc-012, eval-doc-013, test-diff-014, e2e-report-007; subagents timed out, main orchestrator finished) | pending commit |
| 2026-04-20 | batch-11 P6 TenantLayout 4-tab + ChatTab → /api/admin/chat (eval-doc-014, test-diff-015, e2e-report-008; focused-scope vitest 4.2s — timeout mitigation effective) | pending commit |
| 2026-04-20 | batch-12 P7 TenantContext middleware + tenant_root helper (eval-doc-015, test-diff-016, e2e-report-009; 17 new tests, 0 new regression) | pending commit |
| 2026-04-20 | batch-13 T7S.4 scripts/setup.sh mode-aware + Makefile delegation (eval-doc-016, test-diff-017; 8 subprocess tests green) | pending commit |
| 2026-04-20 | batch-13 T7F.3 customer-chat + operator-console mode routing (eval-doc-017, test-diff-018; 10 frontend tests across both apps, 0 new regression) | `90cfd69` |
| 2026-04-21 | batch-13 combined e2e-report-010 + canonical T7S.4 audit commit `8bbe728`（修复 race 下的 commit subject） | e2e-report-010 registered |
| 2026-04-20 | batch-14 T7S.5 fork-mode boot smoke test (eval-doc-018, test-diff-019; 5 new tests, 0 regression on fork_runtime+bootstrap+setup scope) | pending commit |
| 2026-04-20 | batch-14 T7B.6 /api/management/chat → _master routing (eval-doc-019, test-diff-020; 7 new tests, 0 regression across api+auth+cc_pool+dream_agent+bootstrap scope; admin tool set deferred to M3) | pending commit |

## Artifact 策略 · 选项 B（2026-04-21 修订，替代先前的 C）

**现状**：Phase 1–3（14 任务，commits `178919c`..`21ed7bb`）已用内联 TDD 完成，未产任何 `.artifacts/` artifact。

**B 决策**：
1. **立即回填 Phase 1–3**：3 个汇总 eval-doc + 6 个 test-diff（每 batch 一份）+ 1 个正式 e2e-report
2. **从 batch-7 起**（batch-6 in-flight 不动，跑完后按新规）subagent dispatch prompt 强制产 artifact：
   - 任务开始前：eval-doc（simulate 模式）→ `.artifacts/eval-docs/`
   - 实现前：test-plan → `.artifacts/test-plans/`
   - 测试绿后：test-diff → `.artifacts/test-diffs/`
   - 每 batch 结束：跑 skill-4-test-runner 生成 e2e-report → `.artifacts/e2e-reports/`
   - 每个 artifact 产出必调 `bash scripts/register.sh` 注册到 `registry.json`
3. 更新 [cc-prompt-templates.md §6](cc-prompt-templates.md#6-) 把 artifact 要求 inline 到 subagent dispatch 模板

**触发点**：batch-6 subagent 完成通知 → 立即启动 Phase 1-3 回填 + 改模板 → 再 dispatch batch-7

### Backfill 完成记录 (2026-04-21)

Phase 1-4 回填已完成（option B 承诺兑现）。共 **12 artifacts 注册到 `.artifacts/registry.json`**：

| 类别 | IDs | 覆盖范围 |
|------|-----|---------|
| eval-doc (4) | `eval-doc-005`, `eval-doc-006`, `eval-doc-007`, `eval-doc-008` | 每 Phase 一份 summary (P1/P2/P3/P4) |
| test-diff (7) | `test-diff-004`..`test-diff-010` | 每 batch 一份 (batch-0..batch-6) |
| e2e-report (1) | `e2e-report-003` | Phase 1-4 整体回归 (207 pass / 0 fail) |

**双向关联**：每个 eval-doc 关联对应 batch 的 test-diff；e2e-report-003 关联 4 个 eval-doc。
**E2E 结果**：`207 passed, 0 failed` (见 `.artifacts/e2e-reports/e2e-m2-phase1-4.md`)。
**扩展**：Phase 4 (batch-6, 33 tests) 也纳入回填范围，与 batch-6 backfill 合并一次性产出。
**前向合规**：batch-7 起每个 subagent dispatch prompt 强制 inline `.artifacts/` 产出 + 注册（已在 [cc-prompt-templates.md §6.2](cc-prompt-templates.md#62-artifact-产出约束dev-loop-skills-兼容) 落实）。

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
| T3B.5 | cc_pool role='dream' support | 🟡 yellow | medium | ✅ done | Subagent T3B.5 | `21ed7bb` (9 tests + 0 regression, inline reviewer APPROVED) |
| T3B.6 | /api/dream/trigger + /api/dream/runs | green | small | ✅ done | Subagent T3B.6 | `475f32f` (15 tests, 0 regression) |

**Gate**：run_dream 产生 draft proposal；cc_pool 隔离验证。

## Phase 4 — DreamScheduler

| ID | 名称 | 类型 | 工作量 | 状态 | Owner | Artifacts |
|----|------|------|--------|------|-------|-----------|
| T4B.1 | should_trigger() logic | 🟡 yellow | medium | ✅ done | Subagent batch-6 | `5d614bc` (16 tests, inline reviewer APPROVED) |
| T4B.2 | scheduler loop + active-tenant discovery | green | medium | ✅ done | Subagent batch-6 | `5d614bc` (10 tests) |
| T4B.3 | /dream-config → scheduler.refresh() | green | small | ✅ done | Subagent batch-6 | `5d614bc` (7 tests) |

**Gate**：idle 租户自动触发；/dream-config 动态 refresh 生效。

## Phase 5 — Magic-link auth

| ID | 名称 | 类型 | 工作量 | 状态 | Owner | Artifacts |
|----|------|------|--------|------|-------|-----------|
| T5B.1 | auth DB schema + repo | green | small | ✅ done | Subagent batch-7 | `442c02b` (7 tests) |
| T5B.2 | POST /api/auth/request-login | green | small | ✅ done | Subagent batch-7 | `442c02b` (5 tests) |
| T5B.3 | GET /api/auth/verify → cookie + redirect | green | small | ✅ done | Subagent batch-7 | `442c02b` (5 tests) |
| T5B.4 | POST /api/auth/logout | green | small | ✅ done | Subagent batch-7 | `442c02b` (3 tests) |
| T5B.5 | require_tenant_access middleware | green | medium | ✅ done | Subagent batch-8 | `98b21ff` (11 tests) |
| T5B.6 | /api/session/mode auth-state extension | green | small | ✅ done | Subagent batch-8 | `98b21ff` (5 tests) |

**Gate**：request → verify → cookie → 跨 tenant 拒绝；logout 撤销。

## Phase 6 — admin-portal TenantLayout

| ID | 名称 | 类型 | 工作量 | 状态 | Owner | Artifacts |
|----|------|------|--------|------|-------|-----------|
| T6F.1 | useSessionMode + useTenantId real impl | green | small | ✅ done | Subagent batch-9 | `ed4ec38` (13 tests, all hooks green) |
| T6F.2 | AuthGate + LoginPage | green | medium | ✅ done | Subagent batch-9 | `ed4ec38` (9 tests: 5 AuthGate + 4 LoginPage; App rewrite +1) |
| T6F.3 | AdminRail variant prop | green | small | ✅ done | Subagent a68ca35d (timed out; code OK) + main orchestrator (tests + artifacts) | pending commit (10 tests, eval-doc-012, test-diff-014, e2e-report-007) |
| T6F.4 | AdminTopbar + AvatarMenu extensions | green | small | ✅ done | Subagent a56018390 (timed out; code OK) + main orchestrator (tests + artifacts) | pending commit (7 tests, eval-doc-013, test-diff-014, e2e-report-007) |
| T6F.5 | TenantLayout 4-tab component | green | medium | ✅ done | batch-11 | pending commit (7 tests, eval-doc-014, test-diff-015, e2e-report-008) |
| T6F.6 | ChatTab → /api/admin/chat | green | medium | ✅ done | batch-11 | pending commit (7 tests + backend stub in api_routes.py; wire contract stable, real `_local_admin` routing deferred to T7B.6) |

**Gate**：tenant 品牌 4 tabs 渲染；AuthGate 阻挡匿名；ChatTab 对接 /api/admin/chat。

## Phase 7 — Fork runtime

| ID | 名称 | 类型 | 工作量 | 状态 | Owner | Artifacts |
|----|------|------|--------|------|-------|-----------|
| T7B.1 | TenantContext middleware mode branching | green | medium | ✅ done | batch-12 | pending commit (7 tests, eval-doc-015, test-diff-016, e2e-report-009) |
| T7B.2 | tenant_root() path helper | green | small | ✅ done | batch-12 | pending commit (10 tests, eval-doc-015, test-diff-016, e2e-report-009) |
| T7F.3 | customer-chat + operator-console mode routing | green | small | ✅ done | batch-13 | pending commit (10 tests across both apps, eval-doc-017, test-diff-018) |
| T7S.4 | scripts/setup.sh mode-aware | green | medium | ✅ done | batch-13 | pending commit (8 tests, eval-doc-016, test-diff-017) |
| T7S.5 | Fork-mode boot smoke test | green | small | ✅ done | batch-14 | pending commit (5 tests, eval-doc-018, test-diff-019; 49 pass on fork_runtime+bootstrap+setup scope) |
| T7B.6 | /api/management/chat → _master routing | green | small | ✅ done | batch-14 | pending commit (7 tests, eval-doc-019, test-diff-020; admin tool set deferred to M3 per eval-doc-019) |

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
| batch-6 | P4 | ✅ 完成 | 3 tasks + 33 tests + 0 regression; inline reviewer APPROVED |
| batch-7 | P5 | ✅ 完成 | T5B.1-T5B.4 · 20 new tests + 0 regression; artifact-compliant (eval-doc-009 / test-diff-011 / e2e-report-004) |
| batch-8 | P5 | ✅ 完成 | T5B.5-T5B.6 · 16 new tests + 0 regression; artifact-compliant (eval-doc-010 / test-diff-012 / e2e-report-005) |
| batch-9 | P6 | ✅ 完成 | T6F.1 + T6F.2 · 22 new frontend tests + 0 regression; artifact-compliant (eval-doc-011 / test-diff-013 / e2e-report-006) |
| batch-10 | P6 | ✅ 完成 | T6F.3 + T6F.4 shell components；subagents timed out mid-task, main orchestrator finished tests + artifacts；27 tests batch-scope (+17 net new) + 0 new regression |
| batch-11 | P6 | ✅ 完成 | T6F.5 + T6F.6 · 14 new frontend tests + backend stub /api/admin/chat; artifact-compliant (eval-doc-014 / test-diff-015 / e2e-report-008); focused-scope vitest 4.2s (timeout mitigation effective) |
| batch-12 | P7 | ✅ 完成 | T7B.1 + T7B.2 · 17 new backend tests + 0 new regression; artifact-compliant (eval-doc-015 / test-diff-016 / e2e-report-009); 102 pass on fork_runtime+bootstrap+api+auth scope |
| batch-13 | P7 | ✅ 完成 | T7S.4 ✅ (8 tests) ∥ T7F.3 ✅ (10 tests); combined e2e-report-010 (18 new + 110 backend regression green, 0 new failures); artifacts linked |
| batch-14 | P7 | ⏳ pending | — |
| batch-15 | P8 | ⏳ pending | — |
| batch-16 | P8 | ⏳ pending | — |
