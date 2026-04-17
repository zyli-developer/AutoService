# AutoService 双人协同 Playbook

> 2026-04-15 · A/B 两线并行开发的操作手册
> 入职必读 · 配合 [`task-status.md`](task-status.md) + [`2026-04-15-prd-gap-tasks-v3.md`](2026-04-15-prd-gap-tasks-v3.md) + [`2026-04-15-task-execution-plan.md`](2026-04-15-task-execution-plan.md) 使用

## ⚡ AI 快车道时间表（2026-04-15 调整）

全程 AI 执行，目标 **2026-04-17（Fri）前完成 M5**。本 playbook 中"周 X"、"Milestone 时长"等时间引用按以下表换算：

| 里程碑 | 档期 | 时长 |
|---|---|---|
| **M0** 契约 | Wed 04-15 AM | 半天 |
| **M1** 客户端端到端 | Wed 04-15 PM | 半天 |
| **M2** 工作台 | Thu 04-16 AM | 半天 |
| **M3** 管理+合规 | Thu 04-16 PM | 半天 |
| **M4** Dream+计费 | Fri 04-17 AM | 半天 |
| **M5** zchat 切换+验收 | Fri 04-17 PM | 半天 |

**节奏调整**:
- 周同步 → **每 Milestone 结束时 5 分钟同步**（而非每周一次）
- Red 决策响应 → **30 分钟内**（而非 48 小时）
- Yellow 评审 → **30 分钟内**（而非 3 天）
- 里程碑联调 → **压缩到 30 分钟 smoke test**（而非 2-3 天）
- Red 前置启动 → 合规 T3A.4-6 在 Wed PM 启动；zchat T5A.1 在 Thu AM 启动

---

---

## 0. 谁读这份文档

- **A 线开发者** (后端 / 引擎 / 业务)：43 任务
- **B 线开发者** (Web 前端 / 交付)：29 任务
- **Lead / PM**（可能是其中一人兼）：跨线协调、Red 决策、里程碑门控

所有人在**首次上手**和**每个 Milestone 前**都应快速过一遍本文档。

---

## 1. 项目文档地图

| 角色 | 必读 |
|---|---|
| **入职第 1 小时** | 本文档 + [`AutoService-PRD-v1.1.md`](../prd/AutoService-PRD-v1.1.md) |
| **A 线日常** | [`AutoService-PRD-v1.1.md`](../prd/AutoService-PRD-v1.1.md) / [`2026-04-15-prd-gap-tasks-v3.md`](2026-04-15-prd-gap-tasks-v3.md) 的 A 线 · [`task-status.md`](task-status.md) · `docs/contracts/*`（契约） · [`zchat-plan/`](../zchat-plan/)（参考） |
| **B 线日常** | [`AutoService-PRD-v1.1.md`](../prd/AutoService-PRD-v1.1.md) / [`AutoService-UserStories-v1.1.md`](../prd/AutoService-UserStories-v1.1.md) · [`2026-04-15-prd-gap-tasks-v3.md`](2026-04-15-prd-gap-tasks-v3.md) 的 B 线 · [`task-status.md`](task-status.md) · `docs/contracts/frontend-ws-schema.md` |
| **Milestone 前** | [`2026-04-15-task-execution-plan.md`](2026-04-15-task-execution-plan.md) §四 §五 |

---

## 2. 三层协同模型

### Layer 1 · 独立开发（90% 时间）

**目标**：两人彼此不打扰；仅通过 `task-status.md` 和 git 可见对方进度。

**日常循环**（每日）:

```
┌─ 早 ────────────────────────────────────┐
│ 1. git fetch && git pull main             │
│ 2. 打开 task-status.md                    │
│ 3. 挑一个自己线的 ⬜ pending 任务         │
│ 4. Edit 改状态 ⬜ → 🟦 填 Owner          │
│ 5. commit "task: Tx.x → in_progress (..)"│
│ 6. git push                               │
└───────────────────────────────────────────┘
              ↓
┌─ 日中 ─────────────────────────────────┐
│ 在自己 worktree / 分支开发              │
│ 跑 dev-loop（skill-5 → 2 → 3 → 4）     │
│ 产出的 artifact 自动进 registry.json    │
└─────────────────────────────────────────┘
              ↓
┌─ 晚 ────────────────────────────────────┐
│ 1. 任务完成 → 改 🟦 → 🟩                │
│ 2. 把 artifact ID 填"关联"列             │
│ 3. commit "task: Tx.x → completed"       │
│ 4. git push                              │
│ 5. 若卡住 → 改 🟦 → ⚠️ 填 blocker 原因  │
└──────────────────────────────────────────┘
```

**独立性保证**：
- A/B 的任务在不同文件夹（`autoservice/` vs `frontend/`），代码合并冲突概率接近零
- `task-status.md` 改动行不同，合并冲突概率接近零
- 通过 **WebSocket schema**（`docs/contracts/frontend-ws-schema.md`）交互，不共享代码

### Layer 2 · Milestone 同步（每 M 结束 5 分钟）

**时机**：每个 Milestone（M0/M0.5/M1/M2/M3/M4）完成后立即 5 分钟；**不再按周**

**异步亦可**：GitHub Issue / Slack 线程，不强制视频

**4 个固定议题**:

| # | 议题 | 产出 |
|---|---|---|
| 1 | 进度对齐（看 task-status.md 进度汇总）| 是否有落后任务？ |
| 2 | 契约漂移预警（本 M 是否需改 WS schema？）| 若是，立即 30 分钟内 pair 改 |
| 3 | 下一 Milestone 批次预告（各自启动哪些任务）| 确认 handoff 时间 |
| 4 | Yellow 评审排期（有哪些 🟡 需对方/用户审？）| 约 30 分钟评审窗口 |

**5 分钟硬上限**。超时 → 列问题单，单独 30 分钟短会处理。

### Layer 3 · 里程碑联调（6 次，每次 30 分钟 smoke test）

| 里程碑 | 档期 | 时长 | 联调内容 | 产出 |
|---|---|---|---|---|
| **M0** | Wed 11:30-12:00 | 30 min | T0.1 ConversationEngine + T0.2 WS schema 冻结 | `docs/contracts/*` + 签字 |
| **M1** | Wed EOD | 30 min | customer-chat × LocalEngine：US-2.1 问候 / US-2.2 占位续写 / CSAT | e2e-report |
| **M2** | Thu 13:00 | 30 min | operator-console × 协议命令：Copilot / /hijack / 角色翻转 | e2e-report |
| **M3** | Thu EOD | 30 min | admin-portal × 合规 / soul 生成 / 预演 | e2e-report |
| **M4** | Fri 14:00 | 30 min | 提案 UI × Dream Engine 闭环：灰度 / 回滚 / 账单 | e2e-report |
| **M5** | Fri EOD | 60 min | ZchatEngine 切换 × AB 测试 × 17 story E2E | e2e-report + 切换决策 |

**联调期工作方式**：
- 两人坐一起（或长 pair 视频）
- 主分支开 `milestone-Mx` 临时分支；各自 push 到这个分支
- 每个 Milestone 跑一次 skill-4 test-runner，产出 e2e-report
- **门控规则**：e2e-report 失败 → 修 → 再跑；不通过不得进入下一 Phase

---

## 3. Git / Worktree 约定

### 分支策略

```
main                       ← 集成主干（Milestone 通过后合入）
├── dev-a                  ← A 线开发主分支
│   ├── task/T1A.1         ← 每任务一个子分支（推荐但非强制）
│   ├── task/T1A.2
│   └── ...
├── dev-b                  ← B 线开发主分支
│   ├── task/T1B.1
│   └── ...
└── milestone-M1           ← 临时联调分支
```

### Commit message 约定

| 场景 | 格式 | 示例 |
|---|---|---|
| 任务状态变更 | `task: Tx.x → {status} ({Owner})` | `task: T1A.1 → in_progress (DevA)` |
| 任务完成 | `task: Tx.x → completed` | `task: T0.4 → completed` |
| 任务阻塞 | `task: Tx.x → blocked: {原因}` | `task: T3A.7 → blocked: waiting T3A.5` |
| 代码提交 | `feat(Tx.x): {描述}` | `feat(T1A.1): implement Mode state machine` |
| 契约变更 | `contract: {描述}` | `contract: add csat_response schema` |
| Milestone 合并 | `milestone: Mx ({date})` | `milestone: M1 (2026-05-14)` |

### Worktree 使用（可选）

若用多 worktree 并行跑多个任务:
```bash
git worktree add ../AutoService-T1A.1 -b task/T1A.1
git worktree add ../AutoService-T1A.4 -b task/T1A.4
```

每个 worktree 跑一个 AI Agent，互不干扰。完成后 merge 回 `dev-a`。

---

## 4. task-status.md 维护铁律

| # | 规则 | 违反后果 |
|---|---|---|
| 1 | 只有 task owner 能改自己任务的状态 | 违反者的 commit 会被 revert |
| 2 | 改状态用 **Edit 单行**，**禁止整表重写** | 会导致合并冲突爆炸 |
| 3 | Owner 字段只在 🟦 `in_progress` 时填，`🟩 completed` 后可选保留 | 保持视觉干净 |
| 4 | 关联 artifact 字段只填 skill-6 registry 里的合法 ID | 便于交叉引用 |
| 5 | 卡住超过 1 天必须改 ⚠️ `blocked` 并在"依赖"列写原因 | Milestone 同步才能发现阻塞 |
| 6 | 改 WS schema = 改 T0.2 产物 → **必须双方同意** | 否则 revert 并回滚 |

---

## 5. 契约协同

### 契约文件（不可单边修改）

```
docs/contracts/
├── conversation-engine.md       ← T0.1 产物（Python Protocol 签名）
├── frontend-ws-schema.md        ← T0.2 产物（前后端 WS 消息格式）
└── test-vectors/                ← T0.3 产物（契约测试用例）
```

**变更流程**:
1. 任一方发现需改契约 → 不要直接改
2. 开 GitHub Issue 描述问题 + 建议
3. 另一方 24 小时内回应
4. 达成一致后 → pair 修改 + 更新 T0.3 测试用例 + commit `contract: ...`
5. 两方各自 rebase 自己的分支

### Mock 协议

- **A 提供 mock 服务端**：`autoservice/tests/mocks/ws_server_mock.py` — B 开发前端时连这个
- **B 提供 mock 客户端**：`frontend/tests/mocks/ws_client_mock.ts` — A 开发后端时连这个
- 两边都基于 `test-vectors/` 的相同数据，**保证对称性**

---

## 6. Red / Yellow 决策流

### Red 任务（9 个）

**触发条件**: 任何 🔴 任务即将启动时

**流程**:
1. Owner 提前 15 分钟在 GitHub Issue 贴方案草稿（含 3 个选项 + 利弊）
2. @另一方 + @Lead 审阅
3. **30 分钟内**达成共识（异步 OK）
4. 若分歧 → 立即 15 分钟短会议解决
5. 共识达成 → Owner 继续实施

**Red 任务清单**:
- T0.1 / T0.2（Wed 09:00-10:30 M0 期间，两人必到）
- T3A.4 / T3A.5 / T3A.6（**Wed PM 启动，与 M1 并行**，法务并行处理）
- T5A.1 / T5B.2（**Thu AM 启动，与 M2 并行**，zchat 协议对齐）

### Yellow 任务（14 个）

**流程**:
1. Owner 产出草稿 → 改状态 🟡 + 加 `REVIEW-PENDING` tag
2. 另一方 / 用户 **30 分钟内**评审
3. 通过 → 改 🟩，继续
4. 不通过 → 改 🟥 `failed`，**30 分钟内**重做
5. 两次失败 → 升级到 Lead / 用户决策

**Yellow 任务清单**（14）: T1A.4 / T1A.5 / T1A.11 / T2A.2 / T2A.5 / T3A.1 / T3A.2 / T3A.7 / T4A.4 / T5A.5 / T5A.7

---

## 7. dev-loop 跑法（每任务）

所有 🟢 Green 任务（以及 🟡 通过评审后）走标准 dev-loop:

```
1. 任务启动 → 改 🟦
2. skill-5-feature-eval (simulate 模式) → 产出 eval-doc → 注册到 registry
3. skill-2-test-plan-generator (基于 eval-doc) → 产出 test-plan → 注册
4. （人类/AI 写业务代码 + 单测）
5. skill-3-test-code-writer (基于 test-plan) → 产出 test-diff → 注册
6. skill-4-test-runner → 产出 e2e-report → 注册
7. e2e-report 全绿 → 任务改 🟩
8. e2e-report 有红 → 改 🟥 → 修 → 重跑 step 6
```

**每任务的 artifact 链**:
```
eval-doc-XXX → test-plan-XXX → test-diff-XXX → e2e-report-XXX
```

完成后在 `task-status.md` 的"关联"列填这 4 个 ID。

---

## 8. 常见问题 FAQ

| Q | A |
|---|---|
| 我想改对方线的文件（紧急 bug） | 1) 先在 task-status.md 把对方 🟩 任务标注 `⚠️ hotfix-requested`；2) 开 Issue 通知对方；3) 对方接手 or 授权你改 |
| task-status.md 合并冲突 | 因为你没有用 Edit 单行。用 `git checkout --theirs task-status.md` 拿 main 的，然后重新 Edit 你的那行 |
| 我的任务依赖对方的任务没完成 | 1) 检查是否可用 mock 解耦；2) 若不行，改 ⚠️ blocked 注明 `WAITING: Tx.x`；3) 挑另一个独立任务做 |
| dev-loop 一直跑不通 | 1) 看是不是 Red 决策缺失；2) 看是不是契约过时（`docs/contracts/`）；3) 降级到手动实现 + 手测，Milestone 同步报告 |
| WS schema 临时改了一个字段 | 立即开 Issue 告知对方，同步更新 mock + test-vectors；改完立刻 commit `contract: ...` |
| 我发现任务粒度太粗 / 太细 | Milestone 同步提；达成一致后更新 `2026-04-15-prd-gap-tasks-v3.md` 和 `task-status.md` 同步拆分/合并 |
| Milestone 没按期完成 | 1) 不能跳过；2) 约加急联调；3) 考虑降级未完成任务到下个 Milestone（需用户批准）|

---

## 9. 关键电话 / 人

（按需填）

- **Lead / PM**: ____
- **用户侧联系人**（Red 决策）: ____
- **zchat 团队对接人**（T5A.1）: ____
- **法务** (T3A.5-6 合规评审): ____
- **SRE / DevOps**（T5B.2 部署约束）: ____

---

## 10. Day 1 快速启动清单

新入职的 A 线 / B 线开发者第一天：

- [ ] 读完本文档 + PRD v1.1（30 分钟）
- [ ] `git clone` + 创建自己的 worktree
- [ ] 跑通 `make setup` 和 `make check`
- [ ] 读完自己线的 tasks-v3 章节（30 分钟）
- [ ] 读一遍 `zchat-plan/01-protocol-primitives.md`（了解协议语义）
- [ ] 加入Milestone 同步
- [ ] 约 Lead 15 分钟 onboard QA
- [ ] 认领第一个 ⬜ 任务（建议 Green 类型作为 warm-up）

### 两人首日会议议题（30 分钟）

- [ ] 确认 Owner 命名（DevA / DevB / 真名？）
- [ ] 确认 commit 前缀格式（已建议，可调整）
- [ ] 决定 T0.1 + T0.2 协作方式（pair vs 草稿 + 审）
- [ ] 确认 Milestone 同步 5 分钟窗口时间（每 M 末立即同步）
- [ ] 确认 Milestone 联调 smoke test 时长（默认 30 min，M5 是 60 min）
- [ ] 交换紧急联系方式

---

## 附：术语表

| 术语 | 含义 |
|---|---|
| **A 线 / B 线** | A = 后端/引擎，B = Web 前端 |
| **M0-M5** | 6 个里程碑（契约 / 客户端 / 工作台 / 管理台 / Dream / 切换） |
| **LocalEngine / ZchatEngine** | 对话引擎的两个实现（先 Local 后 Zchat） |
| **Green / Yellow / Red** | 任务可 AI 独立度分级 |
| **Red 前置** | Red 决策任务与前一 Phase 并行启动（合规 Wed PM / zchat Thu AM） |
| **dev-loop** | skill-5/2/3/4/6 的标准任务执行流水线 |
| **artifact** | dev-loop 产出物（eval-doc / test-plan / e2e-report 等），由 skill-6 管理 |
| **契约漂移** | WS schema 或 ConversationEngine 接口事后变更 |

---

*v1.0 · 2026-04-15 · AutoService 双人协同操作手册 · 按 Milestone 更新*
