# AutoService 任务状态表

> 基于 [`2026-04-15-prd-gap-tasks-v3.md`](2026-04-15-prd-gap-tasks-v3.md) 的 66 任务追踪表
> **Ground truth for 双人并行**；与 skill-6 管理的 `.artifacts/registry.json` 互补

**状态图例**: ⬜ pending · 🟦 in_progress · 🟩 completed · ⚠️ blocked · 🟥 failed(需重做)
**类型图例**: 🟢 Green(AI 独立) · 🟡 Yellow(AI+人审) · 🔴 Red(人主导)

**最后更新**: 2026-04-17 · **整体进度**: 92/100 (92%) · ⚠️ 9 tasks blocked on zchat · 25 Phase 6 gap-fix tasks added

## ⚡ AI 快车道时间表

目标 **2026-04-17（Fri）前完成 M5**。各 Milestone 档期：

| 里程碑 | 档期 | Phase |
|---|---|---|
| M0 + M0.5 | Wed 04-15 AM | P0（契约 + 骨架）|
| M1 | Wed 04-15 PM | P1（核心对话）|
| M2 | Thu 04-16 AM | P2（工作台 + SLA）|
| M3 | Thu 04-16 PM | P3（管理 + 合规）|
| M4 | Fri 04-17 AM | P4（Dream + 计费）|
| M5 验收 | Fri 04-17 PM | P5（zchat 切换）|

---

## Phase 0 · 契约与骨架（M0 · 2026-04-15 AM）

| ID | 名称 | 线 | 类型 | 状态 | Owner | 依赖 | 关联 artifact |
|---|---|---|---|---|---|---|---|
| T0.1 | ConversationEngine 抽象设计 | A+B | 🔴 | 🟩 | DevA+DevB | — | docs/contracts/conversation-engine.md v1.0 · autoservice/conversation_engine/ |
| T0.2 | WebSocket schema 冻结 | A+B | 🔴 | 🟩 | DevB+DevA | — | docs/contracts/frontend-ws-schema.md v1.0 · test-vectors/events.json |
| T0.3 | 契约测试 suite | A | 🟢 | 🟩 | DevA | T0.1,T0.2 | tests/contract/ (109 cases, 49 pass / 60 awaiting LocalEngine) |
| T0.4 | LocalEngine 骨架 | A | 🟢 | 🟩 | DevA | T0.1 | eval-doc-001, test-plan-001, test-diff-001, e2e-report-001 |
| T0.5 | WebSocket 服务端骨架 | A | 🟢 | 🟩 | DevA | T0.2,T0.4 | eval-doc-002, test-plan-002, test-diff-002, e2e-report-002 |
| T0.6 | 前端 monorepo 骨架 | B | 🟢 | 🟩 | DevB | T0.2 | frontend/ |

---

## Phase 1 · 核心对话（M1 · 2026-04-15 PM）

### A 线

| ID | 名称 | 类型 | 状态 | Owner | 依赖 | 关联 |
|---|---|---|---|---|---|---|
| T1A.1 | Mode/Gate 最小实现 | 🟢 | 🟩 | DevA | T0.4 | eval-doc-003, test-plan-003 |
| T1A.2 | Timer 最小实现 | 🟢 | 🟩 | DevA | T0.4 | eval-doc-T1A.2, test-plan-T1A.2 |
| T1A.3 | EventBus 最小实现 | 🟢 | 🟩 | DevA | T0.4 | eval-doc-004, test-plan-003, test-diff-003 |
| T1A.4 | 4 角色 soul.md 定义 | 🟡 | 🟩 | DevA | T0.1 | agents/{customer,translate,lead,triage}/{soul.md,agent.yaml} |
| T1A.5 | ModelRouter + FastClassifier | 🟡 | 🟩 | DevA | T1A.4 | autoservice/model_router.py + classify_intent.yaml |
| T1A.6 | 占位续写流程 | 🟢 | 🟩 | DevA | T1A.5,T1A.2 | autoservice/placeholder_stream.py |
| T1A.7 | lifecycle plugin | 🟢 | 🟩 | DevA | T1A.3 | autoservice/plugins/lifecycle_plugin.py |
| T1A.8 | metrics plugin | 🟢 | 🟩 | DevA | T1A.3 | autoservice/plugins/metrics_plugin.py |
| T1A.9 | squad plugin | 🟢 | 🟩 | DevA | T1A.3 | autoservice/plugins/squad_plugin.py |
| T1A.10 | cc_pool plugin | 🟢 | 🟩 | DevA | T1A.3 | autoservice/plugins/cc_pool_plugin.py |
| T1A.11 | 情绪识别 prompt 扩展 | 🟡 | 🟩 | DevA | T1A.4 | autoservice/sentiment.py |

### B 线

| ID | 名称 | 类型 | 状态 | Owner | 依赖 | 关联 |
|---|---|---|---|---|---|---|
| T1B.1 | customer-chat SPA 骨架 | 🟢 | 🟩 | DevB | T0.6 | eval-doc-004, test-plan-003, test-diff-003 |
| T1B.2 | 消息流 UI | 🟢 | 🟩 | DevB | T1B.1 | eval-doc-005, test-plan-004, test-diff-004 |
| T1B.3 | 占位续写渲染 | 🟢 | 🟩 | DevB | T1B.2 | eval-doc-006, test-plan-005, test-diff-005 |
| T1B.4 | 断线重连 + 消息回放 | 🟢 | 🟩 | DevB | T1B.1 | eval-doc-007, test-plan-006, test-diff-006 |
| T1B.5 | 浮动按钮 SDK | 🟢 | 🟩 | DevB | T0.6 | eval-doc-008, test-plan-007, test-diff-007 |
| T1B.6 | 多语言 UI 框架 | 🟢 | 🟩 | DevB | T0.6 | test-diff-008 |

**🤝 M1 联调**: Wed EOD，30 min smoke test

---

## Phase 2 · 工作台 + SLA（M2 · 2026-04-16 AM）

### A 线

| ID | 名称 | 类型 | 状态 | Owner | 依赖 | 关联 |
|---|---|---|---|---|---|---|
| T2A.1 | 协议命令实现 | 🟢 | 🟩 | DevA | T1A.1 | eval-doc-T2A.1, test-plan-T2A.1 |
| T2A.2 | 智能分流 Agent 信心模型 | 🟡 | 🟩 | DevA | T1A.4 | autoservice/triage.py |
| T2A.3 | SLAAggregator | 🟢 | 🟩 | DevA | T1A.3 | autoservice/sla_aggregator.py |
| T2A.4 | alerts.yaml + 告警推送 | 🟢 | 🟩 | DevA | T2A.3 | autoservice/alerts.yaml + alert_engine.py |
| T2A.5 | 22 语种术语 + 注入 + 覆盖 | 🟡 | 🟩 | DevA | T1A.4 | autoservice/i18n/ (22 YAML + term_loader.py) |

### B 线

| ID | 名称 | 类型 | 状态 | Owner | 依赖 | 关联 |
|---|---|---|---|---|---|---|
| T2B.1 | operator-console SPA 骨架 | 🟢 | 🟩 | DevB | T0.6 | eval-doc-009, test-plan-008, test-diff-009 |
| T2B.2 | 分队卡片列表 UI | 🟢 | 🟩 | DevB | T2B.1,T1A.9 | eval-doc-010, test-plan-009, test-diff-010 |
| T2B.3 | Copilot 侧栏聊天窗 | 🟢 | 🟩 | DevB | T2A.1 | test-diff-011 |
| T2B.4 | /hijack + 抢单按钮 | 🟢 | 🟩 | DevB | T2A.1 | test-diff-012 |
| T2B.5 | Takeover 模式 UI | 🟢 | 🟩 | DevB | T2B.3 | test-diff-014 |
| T2B.6 | 并发上限提示 | 🟢 | 🟩 | DevB | T2B.1 | test-diff-013 |
| T2B.7 | 未读徽章 + 声音提醒 | 🟢 | 🟩 | DevB | T2B.1 | test-diff-013 |

**🤝 M2 联调**: Thu 13:00，30 min smoke test

---

## Phase 3 · 管理 + 合规（M3 · 2026-04-16 PM）

### A 线

| ID | 名称 | 类型 | 状态 | Owner | 依赖 | 关联 |
|---|---|---|---|---|---|---|
| T3A.1 | soul.md 自动生成器 | 🟡 | 🟩 | DevA | T1A.4 | autoservice/soul_generator.py, eval-T3A.1 |
| T3A.2 | 虚拟客户生成 pipeline | 🟡 | 🟩 | DevA | T1A.4 | eval-T3A.2, test-plan-T3A.2, autoservice/sim_customer.py |
| T3A.3 | Few-shot 注入机制 | 🟢 | 🟩 | DevA | T3A.2 | eval-T3A.3, test-plan-T3A.3, autoservice/fewshot_loader.py |
| T3A.4 | 合规规则 schema | 🔴 | 🟩 | DevA | — | docs/compliance/rule-schema.md v1.0 |
| T3A.5 | 16 条预置规则 YAML | 🔴 | 🟩 | DevA | T3A.4 | autoservice/compliance/rules.yaml (16 rules) |
| T3A.6 | 16 条补救指南 md | 🔴 | 🟩 | DevA | T3A.5 | docs/compliance/{eu,us,cn}-*.md (16 files) |
| T3A.7 | compliance.py 预检 + 策略下发 | 🟡 | 🟩 | DevA | T3A.5 | autoservice/compliance/compliance.py |

### B 线

| ID | 名称 | 类型 | 状态 | Owner | 依赖 | 关联 |
|---|---|---|---|---|---|---|
| T3B.1 | admin-portal SPA 骨架 | 🟢 | 🟩 | DevB | T0.6 | test-diff-015 |
| T3B.2 | 向导 Step1 资料上传 | 🟢 | 🟩 | DevB | T3A.1 | eval-T3B.2, plan-T3B.2, test-diff-021 |
| T3B.3 | 向导 Step2 渠道配置 | 🟢 | 🟩 | DevB | T3B.1 | test-diff-016 |
| T3B.4 | 向导 Step3 虚拟预演 UI | 🟢 | 🟩 | DevB | T3A.2 | eval-T3B.4, plan-T3B.4, test-diff-022 |
| T3B.5 | 向导 Step4 合规预检可视化 | 🟢 | 🟩 | DevB | T3A.7 | test-diff-017 |
| T3B.6 | 运营仪表盘页 | 🟢 | 🟩 | DevB | T1A.8 | test-diff-018 |
| T3B.7 | 管理群（Dream Engine 对话式命令） | 🟢 | 🟩 | DevA | T2A.1 | test-diff-019 |

**🤝 M3 联调**: Thu EOD，30 min smoke test

⚠️ **T3A.4-6 合规需在 Wed 04-15 PM 启动（与 M1 并行），不等 M3 再开**

---

## Phase 4 · Dream Engine + 计费（M4 · 2026-04-17 AM）

### A 线

| ID | 名称 | 类型 | 状态 | Owner | 依赖 | 关联 |
|---|---|---|---|---|---|---|
| T4A.1 | 对话记忆池 memory_pool.db | 🟢 | 🟩 | DevA | T1A.3 | autoservice/memory_pool.py |
| T4A.2 | /rules 后端 + 对话式配置 | 🟢 | 🟩 | DevA | T2A.1 | autoservice/rules.py |
| T4A.3 | 低峰检测调度器 | 🟢 | 🟩 | DevA | T1A.8 | autoservice/low_peak_scheduler.py |
| T4A.4 | 提案生成 pipeline | 🟡 | 🟩 | DevA | T4A.1 | autoservice/proposal_pipeline.py |
| T4A.5 | 晨起推送 | 🟢 | 🟩 | DevA | T4A.4 | autoservice/morning_push.py |
| T4A.6 | canary.py 灰度路由 | 🟢 | 🟩 | DevA | T4A.4 | autoservice/canary.py |
| T4A.7 | 灰度 5 指标监测 + 自动回滚 | 🟢 | 🟩 | DevA | T4A.6,T2A.3 | autoservice/canary_monitor.py |
| T4A.8 | /rollback 命令 | 🟢 | 🟩 | DevA | T4A.6 | autoservice/rollback_command.py |
| T4A.9 | 三指标统计 | 🟢 | 🟩 | DevA | T1A.8 | autoservice/billing_metrics.py |
| T4A.10 | 阶梯计费 billing.py | 🟢 | 🟩 | DevA | T4A.9 | eval-T4A.10, test-plan-T4A.10, autoservice/billing.py |

### B 线

| ID | 名称 | 类型 | 状态 | Owner | 依赖 | 关联 |
|---|---|---|---|---|---|---|
| T4B.1 | 提案审核页 | 🟢 | 🟩 | DevB | T4A.4 | eval-T4B.1, test-diff-023 |
| T4B.2 | 灰度进度可视化 | 🟢 | 🟩 | DevB | T4A.7 | test-diff-024 |
| T4B.3 | 账单导出 UI | 🟢 | 🟩 | DevB | T4A.10 | test-diff-025 |

**🤝 M4 联调**: Fri 14:00，30 min smoke test

---

## Phase 5 · zchat 切换（M5 验收 · 2026-04-17 PM）

### A 线

| ID | 名称 | 类型 | 状态 | Owner | 依赖 | 关联 |
|---|---|---|---|---|---|---|
| T5A.1 | 对齐 zchat Bridge API v0.3 | 🔴 | ⚠️ | DevA | — | BLOCKED-BY: zchat 未就绪，走 B 方案 LocalEngine |
| T5A.2 | Bridge API Python SDK | 🟢 | ⚠️ | — | T5A.1 | WAITING: T5A.1 |
| T5A.3 | ZchatEngine 适配器 | 🟢 | ⚠️ | — | T5A.2 | WAITING: T5A.1 |
| T5A.4 | 4 plugin 双实现对齐 | 🟢 | ⚠️ | — | T5A.3 | WAITING: T5A.1 |
| T5A.5 | cc-pool key 迁移 | 🟡 | ⚠️ | — | T5A.3 | WAITING: T5A.1 |
| T5A.6 | 延迟监控埋点 | 🟢 | ⚠️ | — | T5A.3 | WAITING: T5A.1 |
| T5A.7 | LocalEngine vs ZchatEngine AB 测试 | 🟡 | ⚠️ | — | T5A.6 | WAITING: T5A.1 |
| T5A.8 | engine 配置切换 | 🟢 | ⚠️ | — | T5A.7 | WAITING: T5A.1 |

### B 线

| ID | 名称 | 类型 | 状态 | Owner | 依赖 | 关联 |
|---|---|---|---|---|---|---|
| T5B.1 | docker-compose 多租户模板 | 🟢 | 🟩 | DevB | — | eval-T5B.1, plan-T5B.1, test-diff-020 |
| T5B.2 | 同主机部署约束落地 | 🔴 | 🟩 | DevB | — | test-diff-028, docs/deploy/nfr4-colocation-policy.md |
| T5B.3 | 租户创建脚本 | 🟢 | 🟩 | DevB | T5B.1 | test-diff-026 |
| T5B.4 | 端到端 E2E 自动化 | 🟢 | ⚠️ | — | T5A.8 | WAITING: T5A.1 (zchat) |
| T5B.5 | 浮窗 SDK npm 发布 | 🟢 | 🟩 | DevB | T1B.5 | test-diff-027 |

**🤝 M5 联调**: Fri EOD，60 min（含 AB 测试 + 最终切换决策）

⚠️ **T5A.1 + T5B.2 需在 Thu 04-16 AM 启动（与 M2 并行），不等 M5 再开**

---

## Phase 6 · 实现差异修复（基于代码审计 26 项 issue）

> 详细任务定义: [`2026-04-17-tasks.yaml`](2026-04-17-tasks.yaml)
> 执行计划: [`2026-04-17-execution-plan.md`](2026-04-17-execution-plan.md)

### Phase 6A · 协议层修复（P0 · M6.0）

| ID | 名称 | 类型 | 状态 | Mode | 依赖 | Gap |
|---|---|---|---|---|---|---|
| T6A.1 | 订阅注册表 + S13 响应 | 🟡 | 🟩 | Dev | — | BRK-01 |
| T6A.2 | 消息广播按分队过滤 | 🟢 | 🟩 | Dev | T6A.1 | BRK-02 |
| T6A.3 | 重连消息回放 | 🟢 | 🟩 | Dev | — | BRK-03 |
| T6A.4 | 错误码前后端对齐 | 🟢 | 🟩 | Agent | — | BRK-04 |

### Phase 6B · 向导端到端打通（P0 · M6.0）

| ID | 名称 | 类型 | 状态 | Mode | 依赖 | Gap |
|---|---|---|---|---|---|---|
| T6B.1 | Upload → soul 生成接线 | 🟢 | 🟩 | Agent | — | BRK-05 |
| T6B.2 | Activate 返回可用 URL | 🟢 | 🟩 | Agent | — | BRK-06 |
| T6B.3 | 虚拟预演传正确参数 | 🟢 | 🟩 | Agent | T6B.1 | BRK-07 |
| T6B.4 | 合规预检传真实 config | 🟢 | 🟩 | Agent | T6B.2 | BRK-08 |
| T6B.5 | 向导步骤校验 + 持久化 | 🟢 | 🟩 | Agent | — | DEV-01 |

### Phase 6C · 计费链路打通（P0 · M6.1）

| ID | 名称 | 类型 | 状态 | Mode | 依赖 | Gap |
|---|---|---|---|---|---|---|
| T6C.1 | CSAT 评分全链路 | 🟡 | 🟩 | Dev | T6A.1 | MISS-07 |
| T6C.2 | Metrics→Billing 联通 | 🟢 | 🟩 | Dev | — | DEV-10 |
| T6C.3 | /approve /reject 真实执行 | 🟡 | 🟩 | Dev | — | BRK-09 |

### Phase 6D · 仪表盘补全（P1 · M6.2）

| ID | 名称 | 类型 | 状态 | Mode | 依赖 | Gap |
|---|---|---|---|---|---|---|
| T6D.1 | SLA 接入真实数据 | 🟡 | 🟩 | Dev | T6C.2 | DEV-02 |
| T6D.2 | Dashboard 布局重组 | 🟢 | 🟩 | Agent | — | MISS-01 |
| T6D.3 | 接管次数趋势图 | 🟢 | 🟩 | Agent | T6C.2 | MISS-02 |
| T6D.4 | 人工客服 Leaderboard | 🟢 | 🟩 | Agent | T6C.2 | MISS-03 |
| T6D.5 | 时间切片选择器 | 🟢 | 🟩 | DevA | T6D.1 | eval-T6D.5, test-plan-T6D.5 |

### Phase 6E · 体验打磨（P1-P3 · M6.3）

| ID | 名称 | 类型 | 状态 | Mode | 依赖 | Gap |
|---|---|---|---|---|---|---|
| T6E.1 | 快速三连（并发+通知+语言） | 🟢 | 🟩 | Agent | — | DEV-06/07,MISS-08 |
| T6E.2 | 占位超时自动升级 | 🟢 | 🟩 | Agent | — | DEV-04 |
| T6E.3 | 老客户上下文问候 | 🟢 | 🟩 | Agent | — | DEV-05 |
| T6E.4 | Canary advance 修复 | 🟢 | 🟩 | Agent | — | DEV-03 |
| T6E.5 | Memory Pool 自动录入 | 🟢 | 🟩 | Agent | — | DEV-12 |
| T6E.6 | 旧 WS 栈标记 deprecated | 🟢 | 🟩 | Agent | — | DEV-09 |
| T6E.7 | SLA 告警 WS 推送 | 🟡 | 🟩 | Dev | T6A.1,T6D.1 | MISS-06 |
| T6E.8 | Agent 草稿展示 | 🟡 | 🟩 | Dev | T6A.1 | MISS-09 |
| T6E.9 | Dream Engine 对话式配置 | 🟡 | 🟩 | Dev | — | MISS-05 |
| T6E.10 | Proposal analyzer 替换 | 🟡 | 🟩 | Dev | — | DEV-11 |

---

## 进度汇总

| Phase | 总数 | 待开始 ⬜ | 进行中 🟦 | 完成 🟩 | 阻塞 ⚠️ |
|---|---|---|---|---|---|
| P0 | 6 | 0 | 0 | 6 | 0 |
| P1 | 17 | 0 | 0 | 17 | 0 |
| P2 | 12 | 0 | 0 | 12 | 0 |
| P3 | 14 | 0 | 0 | 14 | 0 |
| P4 | 13 | 0 | 0 | 13 | 0 |
| P5 | 13 | 0 | 0 | 4 | 9 |
| **P6A** | **4** | **0** | **0** | **4** | **0** |
| **P6B** | **5** | **0** | **0** | **5** | **0** |
| **P6C** | **3** | **0** | **0** | **3** | **0** |
| **P6D** | **5** | **1** | **0** | **4** | **0** |
| **P6E** | **10** | **0** | **0** | **10** | **0** |
| **合计** | **100** | **1** | **0** | **92** | **9** | <!-- T6D.5 pending (you) -->

**P0-P5**: A 线 43 / B 线 29 / 协作 3
**P6**: Dev 亲做 8 (Yellow) / Agent 并行 17 (Green)

---

## 更新规则

1. **Owner 字段**只在任务 `in_progress` 时填写；完成后可选择保留（用于回溯）
2. **状态流转**: `⬜ → 🟦 → 🟩`（正常）或 `⬜ → 🟦 → ⚠️`（阻塞）或 `🟦 → 🟥`（失败待重做）
3. **关联 artifact 字段**随 dev-loop 推进填充（格式 `eval-doc-003, test-plan-005`）
4. **每次修改** commit message 格式: `task: T0.1 → in_progress (DevA)` 或 `task: T0.1 → completed`
5. **冲突规避**: 改自己任务行时用 Edit 精确替换单行，避免整表重写
6. **双人并行约定**（轻量同步方案）:
   - DevA 只改 A 线任务行（含 `T?A.*`）；DevB 只改 B 线任务行（含 `T?B.*`）
   - 协作任务（T0.1 / T0.2 / T5A.1）改动需在 PR 中 review，不直接 push
   - **禁止任何人手改**「最后更新」和「进度汇总」两块 —— 由 DevA 每日 EOD 统一刷新
   - `.gitattributes` 已对本文件启用 `merge=union`：合并时保留两边新增行，避免 3-way 冲突；代价是汇总区可能出现重复行，由 EOD 刷新时清理

7. **契约产物同步策略**（T0.1 / T0.2 / T5A.1 等 A+B 协作任务）:
   - 契约任务在各自 dev-a / dev-b 分支完成并冻结（freeze commit）后，**合入公共 `dev` 分支**（不进 main）
   - 合入时机：**等两条线都 ready** 后一起 PR → dev（同一次集成，避免单方先合导致对方 rebase）
   - 合入后 DevA/DevB 执行 `git fetch origin && git merge origin/dev` 把共享契约拉回各自分支，开工下游依赖任务
   - `main` 留给 M5 验收后的整体发布，不承接中间契约
