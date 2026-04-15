# AutoService Tasks-v3 AI 执行计划

> 2026-04-15 · 基于 [`2026-04-15-prd-gap-tasks-v3.md`](2026-04-15-prd-gap-tasks-v3.md) · 按 AI 可执行度分类 + 并行批次编排
> 面向 AI 全程研发（非人工工时）；两条并行线（A 后端 / B 前端）

---

## 一、分类总览

| 类型 | 数量 | 占比 | 执行特点 | 失败重试 |
|---|---|---|---|---|
| 🟢 **Green**（AI 独立完成）| 43 | 65% | 契约清晰 + 代码 + 单测；验证通过即完成 | 自动重试 ≤3 次 |
| 🟡 **Yellow**（AI 主导 + 人审）| 14 | 21% | 需架构/产品判断；AI 出方案 → 人拍板 → AI 实施 | 评审失败 → 重做 |
| 🔴 **Red**（人类主导 + AI 辅助）| 9 | 14% | 契约/法务/切换决策；必须人类在场 | 无自动化 |

---

## 二、逐 Phase 分类明细

### Phase 0 · 契约与骨架（6 任务）

| 任务 | 类型 | 说明 |
|---|---|---|
| T0.1 ConversationEngine 抽象设计 | 🔴 Red | 协议契约，决定后续 16 周走向 |
| T0.2 WebSocket schema 冻结 | 🔴 Red | 前后端唯一接口面，需人类签字 |
| T0.3 契约测试 suite | 🟢 Green | Schema 自动化验证 |
| T0.4 LocalEngine 骨架 | 🟢 Green | 空壳实现 + TODO |
| T0.5 WebSocket 服务端骨架 | 🟢 Green | FastAPI + WS |
| T0.6 前端 monorepo 骨架 | 🟢 Green | pnpm + React + i18n |

### Phase 1 · 核心对话（17 任务）

**A 线**:

| 任务 | 类型 |
|---|---|
| T1A.1 Mode/Gate 最小实现 | 🟢 |
| T1A.2 Timer 最小实现 | 🟢 |
| T1A.3 EventBus 最小实现 | 🟢 |
| T1A.4 4 角色 soul.md 定义 | 🟡 |
| T1A.5 ModelRouter + FastClassifier | 🟡 |
| T1A.6 占位续写流程 | 🟢 |
| T1A.7 lifecycle plugin | 🟢 |
| T1A.8 metrics plugin | 🟢 |
| T1A.9 squad plugin | 🟢 |
| T1A.10 cc_pool plugin | 🟢 |
| T1A.11 情绪识别 prompt | 🟡 |

**B 线**:

| 任务 | 类型 |
|---|---|
| T1B.1 customer-chat SPA 骨架 | 🟢 |
| T1B.2 消息流 UI | 🟢 |
| T1B.3 占位续写渲染 | 🟢 |
| T1B.4 断线重连 + 消息回放 | 🟢 |
| T1B.5 浮动按钮 SDK | 🟢 |
| T1B.6 多语言 UI 框架 | 🟢 |

### Phase 2 · 工作台 + SLA（12 任务）

**A 线**: T2A.1 协议命令（🟢）· T2A.2 智能分流信心模型（🟡）· T2A.3 SLAAggregator（🟢）· T2A.4 alerts + 告警推送（🟢）· T2A.5 22 语种术语（🟡）

**B 线**: T2B.1-7 operator-console 全部（🟢）

### Phase 3 · 管理 + 合规（14 任务）

**A 线**: T3A.1 soul.md 生成器（🟡）· T3A.2 sim_customer（🟡）· T3A.3 few-shot 注入（🟢）· T3A.4 合规 schema（🔴）· T3A.5 16 条规则（🔴）· T3A.6 补救指南（🔴）· T3A.7 compliance.py（🟡）

**B 线**: T3B.1-7 admin-portal 全部（🟢）

### Phase 4 · Dream Engine + 计费（13 任务）

**A 线**: T4A.1 记忆池（🟢）· T4A.2 /rules 后端（🟢）· T4A.3 低峰检测（🟢）· T4A.4 提案生成 pipeline（🟡）· T4A.5 晨起推送（🟢）· T4A.6 canary.py（🟢）· T4A.7 灰度监测 + 回滚（🟢）· T4A.8 /rollback（🟢）· T4A.9 三指标统计（🟢）· T4A.10 billing.py（🟢）

**B 线**: T4B.1-3 提案 UI / 账单 UI（🟢）

### Phase 5 · zchat 切换（13 任务）

**A 线**: T5A.1 对齐 zchat API（🔴）· T5A.2 Bridge SDK（🟢）· T5A.3 ZchatEngine 适配器（🟢）· T5A.4 4 plugin 双实现对齐（🟢）· T5A.5 cc-pool key 迁移（🟡）· T5A.6 延迟监控埋点（🟢）· T5A.7 AB 测试（🟡）· T5A.8 配置切换（🟢）

**B 线**: T5B.1 docker-compose（🟢）· T5B.2 同主机部署约束（🔴）· T5B.3 租户脚本（🟢）· T5B.4 E2E 自动化（🟢）· T5B.5 浮窗 SDK 发布（🟢）

---

## 三、依赖图（核心链）

```
T0.1 ConversationEngine (🔴) ──┬─→ T0.4 LocalEngine (🟢) ──→ T1A.1-3 Mode/Gate/Timer/EventBus
                               │                              │
T0.2 WS Schema (🔴) ──────────┤                              ├─→ T1A.4-6 souls/ModelRouter/占位
                               │                              │
T0.3 契约测试 (🟢) ────────────┘                              ├─→ T1A.7-10 4 plugin
                                                              │
T0.5 WS 服务端骨架 ──────────────┐                            │
                                ├─→ T1B.1 customer-chat ─────┘
T0.6 前端 monorepo ─────────────┘    ↓
                                    T1B.2-6 消息流/重连/SDK/i18n
                                    ↓
                                    **M1 端到端**（周 5）
                                    ↓
T2A.1 协议命令 ──→ T2B.3 Copilot 侧栏 / T2B.4 /hijack
T2A.3 SLAAggregator ─→ T2A.4 告警推送
                                    ↓
                                    **M2 客服工作台**（周 8）
                                    ↓
T3A.4-6 合规 (🔴 法务提前 1 周启动)
T3A.1 soul.md 生成器 ──→ T3B.2 向导 Step1
T3A.2 sim_customer ──→ T3B.4 向导 Step3
T3A.7 compliance.py ──→ T3B.5 向导 Step4
                                    ↓
                                    **M3 管理后台 + 合规**（周 11）
                                    ↓
T4A.1 记忆池 ─→ T4A.4 提案生成 ─→ T4A.6-7 灰度 ─→ T4B.1-2 UI
T4A.9 三指标统计 ──→ T4A.10 billing
                                    ↓
                                    **M4 Dream + 计费**（周 14）
                                    ↓
T5A.1 zchat API 对齐 (🔴 提前 1 周启动)
T5A.2 Bridge SDK ─→ T5A.3 ZchatEngine ─→ T5A.4 plugin 对齐
T5A.5 cc-pool 迁移 ─→ T5A.7 AB 测试
T5B.2 部署约束 (🔴)
                                    ↓
                                    **M5 切换上线**（周 17）
```

**跨线依赖**（A→B 或 B→A）:
- P1: T0.5 (A) → T1B.1 (B) WebSocket server 先于前端连接
- P2: T2A.1 协议命令 (A) → T2B.3/T2B.4 操作台 (B)
- P3: T3A.1 生成器 / T3A.2 sim / T3A.7 compliance (A) → T3B.2/4/5 向导页 (B)
- P4: T4A.4 提案 JSON (A) → T4B.1 审核 UI (B)

---

## 四、并行批次表（AI Agent 派发）

每批 3-6 任务可同时派发；批内任务无依赖；批间必须等前批完成。

### Batch 0 · 契约（周 0，1-2 天）
| 任务 | 线 | 类型 |
|---|---|---|
| T0.1 ConversationEngine 设计 | A+B | 🔴 |
| T0.2 WS schema 冻结 | A+B | 🔴 |
| T0.3 契约测试 | A | 🟢 |

### Batch 1 · 骨架（周 1，1 天）
| 任务 | 线 | 类型 |
|---|---|---|
| T0.4 LocalEngine 骨架 | A | 🟢 |
| T0.5 WS 服务端骨架 | A | 🟢 |
| T0.6 前端 monorepo | B | 🟢 |

### Batch 2 · LocalEngine 基础（周 1-2，2-3 天）
| 任务 | 线 | 依赖 |
|---|---|---|
| T1A.1 Mode/Gate | A | T0.4 |
| T1A.2 Timer | A | T0.4 |
| T1A.3 EventBus | A | T0.4 |
| T1B.1 customer-chat 骨架 | B | T0.5 |
| T1B.6 多语言 UI | B | T0.6 |
| T1B.5 浮动按钮 SDK | B | T0.6 |

### Batch 3 · Agent 行为（周 2-3，Yellow 需人审）
| 任务 | 线 | 类型 |
|---|---|---|
| T1A.4 4 soul.md 定义 | A | 🟡 |
| T1A.5 ModelRouter | A | 🟡 |
| T1A.11 情绪识别 | A | 🟡 |
| T1B.2 消息流 UI | B | 🟢 |
| T1B.3 占位续写渲染 | B | 🟢 |
| T1B.4 断线重连 | B | 🟢 |

### Batch 4 · Plugin + 占位（周 3-4）
| 任务 | 线 |
|---|---|
| T1A.6 占位续写 | A |
| T1A.7 lifecycle plugin | A |
| T1A.8 metrics plugin | A |
| T1A.9 squad plugin | A |
| T1A.10 cc_pool plugin | A |

**→ M1 联调** (2-3 天)

### Batch 5 · SLA + 工作台基础（周 5-6）
| 任务 | 线 |
|---|---|
| T2A.1 协议命令 | A |
| T2A.3 SLAAggregator | A |
| T2A.4 alerts 推送 | A |
| T2B.1 operator-console 骨架 | B |
| T2B.2 分队卡片列表 | B |

### Batch 6 · 工作台功能（周 6-7）
| 任务 | 线 |
|---|---|
| T2A.2 智能分流 (🟡) | A |
| T2A.5 22 语种术语 (🟡) | A |
| T2B.3 Copilot 侧栏 | B |
| T2B.4 /hijack 按钮 | B |
| T2B.5 Takeover UI | B |
| T2B.6-7 上限/徽章 | B |

**→ M2 联调** (2-3 天)

### Batch 7 · 合规启动（周 8-9，Red 法务）
⚠️ **法务审批周期不可控，周 8 必须启动**
| 任务 | 线 | 类型 |
|---|---|---|
| T3A.4 合规 schema | A | 🔴 |
| T3A.5 16 条规则 | A | 🔴 |
| T3A.6 补救指南 × 16 | A | 🔴 |

### Batch 8 · 向导 + 后端工具（周 9-10）
| 任务 | 线 | 类型 |
|---|---|---|
| T3A.1 soul.md 生成器 | A | 🟡 |
| T3A.2 sim_customer | A | 🟡 |
| T3A.3 few-shot 注入 | A | 🟢 |
| T3A.7 compliance.py | A | 🟡 |
| T3B.1 admin-portal 骨架 | B | 🟢 |
| T3B.2 Step1 资料上传 | B | 🟢 |

### Batch 9 · 向导 + 仪表盘（周 10-11）
| 任务 | 线 |
|---|---|
| T3B.3 Step2 渠道配置 | B |
| T3B.4 Step3 预演 UI | B |
| T3B.5 Step4 合规可视化 | B |
| T3B.6 运营仪表盘 | B |
| T3B.7 通知中心 | B |

**→ M3 联调** (2-3 天)

### Batch 10 · Dream Engine（周 12-13）
| 任务 | 线 |
|---|---|
| T4A.1 记忆池 | A |
| T4A.2 /rules 后端 | A |
| T4A.3 低峰检测 | A |
| T4A.4 提案生成 (🟡) | A |

### Batch 11 · 灰度 + 计费（周 13-14）
| 任务 | 线 |
|---|---|
| T4A.5 晨起推送 | A |
| T4A.6 canary.py | A |
| T4A.7 灰度监测回滚 | A |
| T4A.8 /rollback | A |
| T4A.9 三指标统计 | A |
| T4A.10 billing.py | A |
| T4B.1 提案审核页 | B |
| T4B.2 灰度可视化 | B |
| T4B.3 账单导出 | B |

**→ M4 联调** (2-3 天)

### Batch 12 · zchat 前置（周 14-15，Red）
| 任务 | 线 | 类型 |
|---|---|---|
| T5A.1 对齐 zchat API | A | 🔴 |
| T5B.2 同主机部署约束 | B | 🔴 |

### Batch 13 · zchat 适配（周 15-16）
| 任务 | 线 |
|---|---|
| T5A.2 Bridge SDK | A |
| T5A.3 ZchatEngine 适配器 | A |
| T5A.4 4 plugin 对齐 | A |
| T5A.5 cc-pool 迁移 (🟡) | A |
| T5A.6 延迟埋点 | A |
| T5B.1 docker-compose | B |
| T5B.3 租户脚本 | B |

### Batch 14 · 切换与验收（周 16-17）
| 任务 | 线 |
|---|---|
| T5A.7 AB 测试 (🟡) | A |
| T5A.8 engine 切换 | A |
| T5B.4 E2E 自动化 | B |
| T5B.5 浮窗 SDK 发布 | B |

**→ M5 最终验收**

---

## 五、人类决策点清单

### 🔴 Red 任务（9 个，必须人类主导）

| # | 任务 | 决策时机 | 决策内容 |
|---|---|---|---|
| 1 | T0.1 ConversationEngine 设计 | 周 0 Day 1 | 抽象接口方法签名、语义约定 |
| 2 | T0.2 WS schema 冻结 | 周 0 Day 2 | 前后端消息格式、事件类型 |
| 3-5 | T3A.4/5/6 合规 schema + 16 规则 + 补救指南 | **周 8 Day 1（前置）** | 法务审批、合规措辞 |
| 6 | T5A.1 对齐 zchat Bridge API | **周 14 Day 1（前置）** | 版本锁、变更策略 |
| 7 | T5B.2 同主机部署约束 | 周 14-15 | SRE 审批跨主机例外 |

### 🟡 Yellow 任务（14 个，需人审评测）

每个任务：AI 产出草稿 → 3 天内人审 → 通过则继续，失败则重做。

| 任务 | 评审重点 |
|---|---|
| T1A.4 4 soul.md | Agent 人格、反幻觉约束、多轮规则 |
| T1A.5 ModelRouter | 5 类意图分类边界、timeout 阈值 |
| T1A.11 情绪识别 | sentiment 类别定义、升级阈值 |
| T2A.2 智能分流信心模型 | 置信度公式、路由策略 |
| T2A.5 22 语种术语 | 术语表源（IATE）、注入机制 |
| T3A.1 soul.md 生成器 | 从 KB 推 Agent 行为的逻辑 |
| T3A.2 sim_customer | persona 多样性、场景覆盖度 |
| T3A.7 compliance.py | 检查逻辑、风险等级映射 |
| T4A.4 提案生成 | LLM prompt 质量、提案结构 |
| T5A.5 cc-pool key 迁移 | chat_id ↔ conv_id 映射安全性 |
| T5A.7 AB 测试 | 指标对比、切换门槛 |

---

## 六、建议合并/拆分/降级

### 🔁 建议合并（3 组 → 省 4 任务）

| 原任务 | 建议 |
|---|---|
| T3A.5 16 条规则 + T3A.6 补救指南 | 合并为"合规规则包"（规则 + 文档同批产出）|
| T4A.9 三指标统计（接管次数/CSAT/升级率）| 原是 1 任务，保持；若拆细则合回 |
| T1A.1/T1A.2/T1A.3 Mode/Timer/EventBus | 可视为 1 个大任务"LocalEngine 核心"分 3 子任务 |

### ✂️ 建议拆分（2 个 → 需细化）

| 原任务 | 拆分建议 |
|---|---|
| T4A.4 提案生成 pipeline | 拆为：①对话聚类 ②异常识别 ③提案模板 ④质量自评 四步 |
| T3A.2 sim_customer | 拆为：①persona 生成 ②场景覆盖 ③AI 答生成 ④评审分类 |

### ⬇️ 可降级（压力大时）

| 任务 | 降级方案 |
|---|---|
| T3B.7 通知中心 | 先用页面手动刷新，M4 后补实时推送 |
| T4A.5 晨起推送 | 先用后台手动触发，内测足够 |
| T5B.5 npm 发布 | 内测用本地 script，上线前补 |

---

## 七、风险与缓解

| 风险 | 缓解 |
|---|---|
| WS schema 设计不完整 → 多次返工 | Batch 0 花足 2 天 + 跑通 10 个典型场景 |
| zchat Bridge API 延期 | LocalEngine 独立可用（路径 B 保证）；P5 可推 2-4 周不影响其余 |
| Red 决策延迟 | 关键 Red 提前 1 周启动（合规周 8、zchat 周 14）|
| Yellow 评审失败 | 允许 3 天重做；两次失败转人工接手 |
| A/B 步调不齐 | 每周 1 次 30 分钟对齐 + 共享 mock |
| 延迟监控缺失 → M5 切换后 SLA 劣化 | T5A.6 必须在 AB 测试前到位 |

---

## 八、artifact-registry 注册策略（两人协同）

### 集中注册 + git 同步（推荐）

```
.artifacts/
├── tasks/
│   ├── T0.1-conversation-engine.md       # 每任务一个 artifact
│   ├── T0.2-ws-schema.md
│   ├── T1A.1-mode-gate.md
│   └── ... (共 66 个)
├── registry.json                          # 依赖图 + 状态索引
└── progress.log                           # JSON Lines, 每次状态变更一行
```

**流程**:
1. **Lead 开发者**（A 或 B 任一）在 Batch 0 完成后**一次性注册 66 任务**
2. **双方 git pull** 拿到完整 registry
3. **执行时**在 registry.json 改自己任务状态：`pending → in_progress → completed`
4. **每日 rebase**：自动可见对方进度
5. **registry.json 用 JSON Lines**（每任务一行），合并冲突近乎零

### 协同铁律

1. 只有 task owner 改自己任务状态
2. artifact 文件改名/删除必须 PR 通知
3. 跨线依赖变更（T0.1/T0.2 schema 调整）必须双方同意

---

## 九、立即可执行动作

**Day 0（现在）**:
1. Lead 执行 `dev-loop-skills:skill-6-artifact-registry` 初始化 `.artifacts/`
2. 按本文档 §二 把 66 任务批量写入 `.artifacts/tasks/`（AI 可自动生成模板）
3. 构建 `registry.json` 依赖图

**Day 1-2（周 0）**:
1. 人类 + AI 协作完成 Batch 0（T0.1-0.3）
2. 并行启动 Batch 1 骨架任务

**Day 3 起**:
- 按 §四 Batch 表顺序派发
- 每批派发用 Claude Code `Agent` tool + `run_in_background`
- Yellow/Red 任务触发时暂停等人类决策

---

*v1.0 · 基于 tasks-v3 · 43 Green / 14 Yellow / 9 Red · 14 并行批次 · 双人协同基线*
