# Dream Engine UI 补强方案

> 日期：2026-04-21
> 作者：AutoService dev-a
> 状态：draft — 待评审
> 关联 PRD：[docs/prd/autoservice-full-journey.html](../prd/autoservice-full-journey.html) step 1-7 (a3 track)
> 关联规格：
> - [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §2.2-§2.6
> - [docs/superpowers/specs/2026-04-21-m3-e5-dream-extension-design.md](../superpowers/specs/2026-04-21-m3-e5-dream-extension-design.md)

---

## 1. 背景

Dream Agent 后端能力已在 M2 全量落地：

| 组件 | 位置 |
|------|------|
| 3 个 Dream 工具（emit_proposal / kb_search / list_souls） | [autoservice/dream_agent.py:129-393](../../autoservice/dream_agent.py) |
| `run_dream` tool-use 循环 | [autoservice/dream_agent.py:1036-1187](../../autoservice/dream_agent.py) |
| DreamScheduler 后台触发 | [autoservice/dream_scheduler.py](../../autoservice/dream_scheduler.py) |
| dream_runs 持久化 | [autoservice/dream_runs.py](../../autoservice/dream_runs.py) |
| HTTP API | `POST /api/dream/trigger`、`GET /api/dream/runs` [autoservice/api_routes.py:581,720](../../autoservice/api_routes.py) |
| Master-side 平台 dream（M3 E5.1） | [autoservice/master_dream_agent.py:36](../../autoservice/master_dream_agent.py) |

测试：`tests/dream_agent/ + tests/dream_scheduler/ + tests/api/test_dream_api.py + tests/dream_runs/` → **108 passed, 2 failed**（2 条失败在 dream_scheduler/test_refresh.py，`/api/management/chat` 返 422 — 管理 API 层 bug，不影响核心）。

**UI 侧 gap**：只有 Proposals 标签页统一展示各来源的 proposal，Dream 自身的「正在干活 / 运行历史 / 灰度进度」等 PRD 叙事层面完全没有。

---

## 2. PRD 原始设计 vs 当前 UI

PRD a3 track 7 步叙事（[autoservice-full-journey.html:279-321](../prd/autoservice-full-journey.html)）：

| 步骤 | PRD 视觉描述 | 当前 UI |
|------|-------------|--------|
| ① 配置规则 | IM 管理群 @Dream Engine 对话，4 个参数块（触发/覆盖/风险/灰度）`im-block` 结构 | [ManagementChat](../../frontend/apps/admin-portal/src/components/ManagementChat.tsx) 纯文本对话（Dream Engine 身份已就位） |
| ② 临时记忆池 | "白天对话写入临时记忆池" | 无 |
| ③ Dream 启动 | 夜间"Dream Engine 正在后台工作"空态提示 | 无 |
| ④ 回放整理 | Dream 后台消费对话 | 无 |
| ⑤ 沉淀经验 | 候选经验进入待审核队列 | [ProposalsTab](../../frontend/apps/admin-portal/src/components/ProposalsTab.tsx) 列表 ✅ |
| ⑥ 晨起审核 | "08:47 · 晨起推送 · 3 条提案" 聚合消息卡 + `/approve #N` | ProposalsTab ✅；ManagementChat `/approve` ✅；**缺晨起聚合消息卡** |
| ⑦ 灰度上线 | 5%→25%→100% 进度条 + CSAT/升级率"命中 vs 未命中" + `/rollback` | 无 |

---

## 3. 设计约束

- **不新增 rail 标签**：保持 spec §4.2 四格（Chat / Dashboard / Proposals / Billing），增量改造挂在现有标签内
- **红线 CON-04 不动**：任何 UI 改动都不能让 proposal 绕过 "draft → accepted → applied" 状态机
- **零后端改动优先**：四项方案中 3 项纯前端（复用已有 API）
- **i18n**：新增文案走 [packages/i18n/src/locales/](../../frontend/packages/i18n/src/locales/)，zh-CN + en 同步

---

## 4. 方案

### P0 · ProposalsTab 顶部「Dream 状态带」

**位置**：[ProposalsTab.tsx:62](../../frontend/apps/admin-portal/src/components/ProposalsTab.tsx#L62) 顶部 controls 之前新增一条状态带。

**视觉**：
```
┌─────────────────────────────────────────────────────────────┐
│ 💤 Dream Engine · 空闲中                                       │
│   距上次 2h14m · 下次 QPS<20% 持续 30min 时触发                 │
│   最近 run: 3 proposals / 7 tool_calls / 1.2s                │
│   [▶ 立即运行]  [查看历史]                                      │
└─────────────────────────────────────────────────────────────┘
```

**状态文案映射**（来自 `dream_scheduler.should_trigger` 的 reason_code）：

| reason_code | 文案 |
|-------------|------|
| `manual_off` | 🚫 已停用（管理员关闭） |
| `running` | 🔵 运行中... |
| `cool_down` | ⏸ 冷却中（还剩 Nm） |
| `never_active` | 💤 等待首次对话 |
| `idle_threshold_met` | ⚡ 即将触发 |
| `ok_scheduled` | 💤 空闲中 · 下次 ... |

**后端对接**（已就绪，0 改动）：
- `GET /api/dream/runs?tenant_id=<tid>&limit=1` → 最近 run 摘要
- `POST /api/dream/trigger` → "立即运行"按钮（返回 202 Accepted，前端轮询 runs 刷新）
- 状态 reason_code：需后端在 `GET /api/dream/status` 暴露 scheduler 计算结果 —— **需小量后端改动（~20 行）**

**工作量**：0.5 day（纯前端）+ 0.25 day（后端 status endpoint）

---

### P1 · Proposal 详情「灰度 + 指标」面板

**位置**：[ProposalsTab.tsx:128-164](../../frontend/apps/admin-portal/src/components/ProposalsTab.tsx#L128-L164) 右侧详情区，`status=accepted` 时条件渲染。

**视觉**（对齐 PRD step 5 + step 7）：
```
┌─────────────────────────────────────┐
│ 📈 灰度发布                           │
│  5% ━━━ 25% ━━━ 100%                │
│        ^已到 25%                     │
├─────────────────────────────────────┤
│ ◉ 监控指标                            │
│  CSAT           4.7 vs 4.5  ↑       │
│  升级转结案率    持平                  │
│  熔断           指标跌则自动回滚        │
├─────────────────────────────────────┤
│  [⚡ 立即回滚]   [⏩ 推进到 100%]       │
└─────────────────────────────────────┘
```

**后端对接**（已就绪，0 改动）：
- `GET /api/canary/status` [api_routes.py:793](../../autoservice/api_routes.py#L793)
- `POST /api/canary/rollback` [api_routes.py:1154](../../autoservice/api_routes.py#L1154)
- `POST /api/canary/advance` [api_routes.py:1117](../../autoservice/api_routes.py#L1117)
- **M3 T4S.3 的「Apply 按钮」并入本面板**（`status=accepted` 阶段统一操作入口）

**工作量**：1 day（纯前端）

---

### P2 · ManagementChat 富 `im-block` 消息块

**位置**：[ManagementChat.tsx](../../frontend/apps/admin-portal/src/components/ManagementChat.tsx) 消息渲染分支。

**差距**：PRD step 1 Dream 回答是 4 个结构化 `im-block`，当前只渲染纯文本。

**方案**：
1. 后端 `/api/management/chat` 响应 schema 扩展 `blocks?: Block[]` 字段（已有 InlineWidget 基础设施可复用）
2. `dream_config_dialog` 的回合输出结构化 blocks 替代纯文本
3. **同时修复现存 2 条失败测试** [tests/dream_scheduler/test_refresh.py](../../tests/dream_scheduler/test_refresh.py)（`/api/management/chat` 返 422）

**Block 类型**：
```ts
type Block =
  | { type: 'param'; title: string; status: 'done'|'pending'; meta: string }
  | { type: 'proposal-summary'; items: Array<{ id, title, risk, source }> }
  | { type: 'metric-compare'; name: string; a: string; b: string; trend: 'up'|'flat'|'down' }
```

**晨起推送（PRD step 4）** 也用 `proposal-summary` block —— Dream 早晨定时往管理群推一条聚合消息。

**工作量**：1.5 day（后端 blocks 字段 + 前端渲染 + 修 bug）

---

### P3 · Dream Runs 历史抽屉

**位置**：P0 状态带「查看历史」按钮唤起右侧抽屉。

**内容**：表格 × 最近 30 次 run
| 时间 | status | tool_calls | proposals | tokens in/out | 时长 | error |
|------|--------|-----------|-----------|---------------|-----|------|

**后端对接**（已就绪，0 改动）：
- `GET /api/dream/runs?tenant_id=<tid>&limit=30`

**工作量**：0.5 day（纯前端）

---

## 5. M3 归属 & 排期建议

### 现状对照 M3 plans

M3 Epic E5 只覆盖后端 + 一个窄 UI 任务：

| M3 任务 | 状态 | 对本方案覆盖度 |
|---------|------|--------------|
| T2S.8 Master dream skeleton | 🟡 规划中 | 后端 |
| T4S.1 apply_proposal 🔒 | 🟡 规划中 | 后端 |
| T4S.3 Admin-portal Apply button | 🟡 规划中 | **只含 Apply 按钮**，不含 P0/P1 完整叙事 |
| T4S.4 Platform dream signals | 🟡 规划中 | 后端 |

### 归属建议

| 方案 | 建议归属 | 理由 |
|------|---------|------|
| **P0 Dream 状态带** | M3 E5 增补（新增 T4S.3b） | 紧贴 Apply 按钮体验，同一批次 |
| **P1 灰度 + 指标面板** | M3 E5 增补（扩 T4S.3 范围） | T4S.3「Apply 按钮」升级为「Apply + 灰度控制面板」更完整 |
| **P2 ManagementChat 富 blocks** | 独立 hotfix（本周） | 含 422 bug 修复，阻塞 dream-config 对话；与 M3 Epic 解耦 |
| **P3 Runs 历史抽屉** | M3.5 / 或 M3 尾声 | 诊断性功能，优先级 P3 |

### 建议执行顺序

```
Week 1 (hotfix):  P2 修 422 → ManagementChat blocks schema
Week 2 (M3 E5):   P0 状态带 → P1 灰度面板（T4S.3 扩展）
Week 3 (后续):    P3 历史抽屉
```

---

## 6. 成功指标

- ✅ PRD a3 track 7 步叙事在 admin-portal 有对应可视化入口（除 ②③④ 后台步骤以状态文案呈现）
- ✅ 管理员不打开 devtools 也能看到 Dream 是否在跑、跑了多久、产了几条 proposal
- ✅ `status=accepted` 的 proposal 可以一键 Apply + 查看灰度进度 + 指标对比 + 一键 rollback
- ✅ 不违反红线 CON-04（所有 proposal 仍经 draft → accepted → applied 状态机）
- ✅ 修复 `tests/dream_scheduler/test_refresh.py` 2 条失败测试

---

## 7. 风险 & Open Questions

1. **P2 blocks schema 变更** —— 需要与 ManagementChat 现有 inline-widget 协议对齐，是否冲突？→ 需读 [InlineWidget.tsx](../../frontend/apps/admin-portal/src/components/chat/InlineWidget.tsx) 确认
2. **P0 status endpoint 权限** —— `GET /api/dream/status` 是否对所有 admin role 开放？A vs O vs S？
3. **P1 灰度控制回滚确认** —— `/rollback` 是否需要二次确认弹窗？PRD 原文是"一键撤回"，但破坏性操作建议加 confirm
4. **M3 排期是否来得及** —— M3 当前 batch-7 刚收，排 P0+P1 进 E5 会不会挤掉既有任务？需与 plans/m3/execution-plan 对齐

---

## 8. 下一步

1. 本文档评审 → 确认归属与排期
2. 若进 M3，把 P0/P1 拆为新任务 T4S.3a/b 并入 [docs/plans/m3/tasks.yaml](m3/tasks.yaml)
3. P2 hotfix 可并行启动（独立分支）
4. 走 prd2impl 流程：`/gap-scan` → `/task-gen` → `/plan-schedule`
