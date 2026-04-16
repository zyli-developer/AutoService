# Batches M1-M5 Kickoff · AI 快车道冲刺手册

> 2026-04-15 · M0.5 骨架通过后启动（Wed 14:30 起）
> 覆盖 Batch 2 → Batch 14（M1-M5，共 13 批次）
> 总时长: 约 30 小时（Wed PM + Thu 全天 + Fri 全天）
>
> **用法**: 每个 Milestone 打开对应章节按顺序执行；每批次提供 CC prompt 模板

---

## 0. 前置条件与通用规则

### 前置

- [ ] M0 + M0.5 全绿（`task-status.md` P0 行 6/6 🟩）
- [ ] `docs/contracts/` 契约三件套已冻结
- [ ] `.artifacts/registry.json` 有 T0.1-T0.6 产出记录
- [ ] A/B 两条 worktree 存活

### 通用执行规则

1. **每批次启动前**：DevA / DevB 各自在 CC 贴 `cc-prompt-templates.md §12.1` "我该做什么？"
2. **每个任务启动**：贴 `cc-prompt-templates.md §1` 启动模板，替换占位符
3. **Yellow 任务**：CC 产出后 **30 分钟内** 人审；超时默认通过
4. **Red 任务**：GitHub Issue 贴 3 选项，另一方 **30 分钟内** 回应
5. **每批次末**：`pytest` 全绿 + `task-status.md` 对应任务改 🟩 + commit/push
6. **每 Milestone 末**：30 min smoke test（除 M5 60 min）
7. **阻塞 15 分钟未解**：改 ⚠️ blocked + 换下个任务 + 发 Issue

### 并行规则

- 同一批次内 A 线 / B 线任务**同时执行**（两个 CC 会话并跑）
- 批次间**严格等待前批完成**（除非明确标注可提前）
- **Red 前置任务**（T3A.4-6 合规、T5A.1 zchat 对齐）与主线并行

---

## 1. M1 · 客户端端到端（Wed 14:30-20:00，5.5 小时）

**目标**: customer-chat ↔ LocalEngine ↔ Agent 端到端；US-2.1/2.2/2.6 验收。

### Batch 2 · LocalEngine 基础 + customer-chat 骨架（Wed 14:30-17:00）

| Owner | 任务 | 类型 | prompt |
|---|---|---|---|
| DevA | **T1A.1** Mode/Gate 最小实现 | 🟢 | 用 §1 启动模板；读 T0.1 Protocol 实现 Mode 状态机 + Gate 可见性决策函数 |
| DevA | **T1A.2** Timer 最小实现 | 🟢 | 承接 T1A.1 完成；7 类 Timer asyncio scheduler |
| DevA | **T1A.3** EventBus 最小实现 | 🟢 | 承接 T1A.2；内存 pub/sub + 异步 SQLite 落盘（NFR-2）|
| DevB | **T1B.1** customer-chat SPA 骨架 | 🟢 | 基于 T0.6 apps/customer-chat 扩展；React/Vue + ws-client 连 T0.5 |
| DevB | **T1B.6** 多语言 UI 框架 | 🟢 | i18n 占位（中/英先实，其余 20 语种 T2A.10 产出后填入）|

**smoke**: DevA 跑 `pytest tests/engine/ -v`；DevB 浏览器打开 customer-chat，F12 看 WS 握手成功。

### Batch 3 · Agent 行为 + UI（Wed 17:00-19:00，含 Yellow 人审）

| Owner | 任务 | 类型 | 提示 |
|---|---|---|---|
| DevA | **T1A.4** 4 角色 soul.md | 🟡 | 30 min 草稿 → 30 min 人审 → 修正；参考 cc-prompt-templates §6 |
| DevA | **T1A.5** ModelRouter + FastClassifier | 🟡 | 读 tasks-v3 §3.2 决策树；产出 model_router.py + classify_intent.yaml |
| DevA | **T1A.11** 情绪识别 prompt | 🟡 | Skill 前缀注入 sentiment；简单枚举 4 类 |
| DevB | **T1B.2** 消息流 UI | 🟢 | 消息气泡 + 打字指示 + 时间戳 |
| DevB | **T1B.3** 占位续写渲染 | 🟢 | 收 edit 事件原地替换 |
| DevB | **T1B.4** 断线重连 + 消息回放 | 🟢 | ws-client 封装 reconnect + 历史拉取 |

**Yellow 并发审批策略**: CC 一次性产出 T1A.4+T1A.5+T1A.11 三份草稿 → 人审 30 分钟一次过；不通过的单项重做。

### Batch 4 · Plugin + 占位续写（Wed 19:00-20:00）

| Owner | 任务 | 类型 | 提示 |
|---|---|---|---|
| DevA | **T1A.6** 占位续写流程 | 🟢 | 承接 T1A.5；快模型 → T1A.3 emit → T0.5 WS 推送 edit |
| DevA | **T1A.7** lifecycle plugin | 🟢 | on_conversation_created → CRM 记录 |
| DevA | **T1A.8** metrics plugin | 🟢 | 订阅 mode.changed / csat_response 等 |
| DevA | **T1A.9** squad plugin | 🟢 | 订阅 conversation.created → operator-console 推送（operator-console 尚未建，先落本地事件队列）|
| DevA | **T1A.10** cc_pool plugin | 🟢 | on_conversation_closed → release_sticky(conv.id) |
| DevB | **浮动按钮 SDK** 从 T1B.5 抽时间做（若 Batch 2 未做完）| 🟢 | — |

**启动合规 T3A.4-6（Red 并行）**：
```
额外贴到 DevA CC 作为并行任务:
"启动 Red 并行任务 T3A.4 合规 schema + T3A.5 16 条规则 + T3A.6 补救指南。
用 cc-prompt-templates §5 Red 模板。产出后 @我 30 分钟内决议。
本任务与 Batch 4 并行，不影响主线。"
```

### 🤝 M1 smoke test（Wed 20:00-20:30，30 min）

1. 启动 A 线 `python -m autoservice.web_gateway`
2. 启动 B 线 `pnpm dev:customer`
3. 浏览器打开 http://localhost:5173
4. 验收点：
   - [ ] 页面 3 秒内显示 Agent 问候（US-2.1）
   - [ ] 提一个复杂问题 → 1 秒内占位 → 5-15 秒续写（US-2.2）
   - [ ] 断网 10 秒 → 恢复后历史对话仍在（断线重连）
   - [ ] Console 无红色 error
5. 跑 `pytest tests/engine/ tests/gateway/ tests/frontend/` 全绿
6. task-status.md: P1 全部任务 🟩
7. **merge milestone-M1 到 main**

---

## 2. M2 · 工作台 + SLA（Thu 09:00-13:00，4 小时）

**目标**: Copilot / /hijack / 角色翻转全链路；US-2.3/2.4/2.5/2.6 验收。

### Batch 5 · SLA + 工作台骨架（Thu 09:00-11:00）

| Owner | 任务 | 类型 | 提示 |
|---|---|---|---|
| DevA | **T2A.1** 协议命令实现 | 🟢 | /hijack /resolve /release /copilot /status /dispatch 命令解析 |
| DevA | **T2A.3** SLAAggregator | 🟢 | 环形 buffer + P50/P95 + 5m/1h/24h 窗口 |
| DevA | **T2A.4** alerts.yaml + 告警推送 | 🟢 | 4 规则 → WS 推 admin（admin-portal 尚未建，暂 stdout）|
| DevB | **T2B.1** operator-console SPA 骨架 | 🟢 | 登录页 + 分队视图 + WS /ws/operator |
| DevB | **T2B.2** 分队卡片列表 UI | 🟢 | 5 状态卡片模板 |

**启动 zchat T5A.1（Red 并行）**：
```
额外贴到 DevA CC 作为并行任务:
"启动 Red 并行任务 T5A.1 对齐 zchat Bridge API v0.3。
用 cc-prompt-templates §5 Red 模板。
产出后需 @zchat 团队对接人确认版本锁。
本任务与 M2 并行。"
```

### Batch 6 · 工作台功能 + 多语言（Thu 11:00-13:00）

| Owner | 任务 | 类型 | 提示 |
|---|---|---|---|
| DevA | **T2A.2** 智能分流信心模型 | 🟡 | 替换 route_query；输出置信度 |
| DevA | **T2A.5** 22 语种术语 + 注入 + 覆盖 | 🟡 | CC 用 Agent tool 并发生成 22 份 YAML（每份 ~150 条）|
| DevB | **T2B.3** Copilot 侧栏聊天窗 | 🟢 | 点卡片 → operator_join → 草稿侧栏 |
| DevB | **T2B.4** /hijack + 抢单按钮 | 🟢 | 一键发 operator_command |
| DevB | **T2B.5** Takeover 模式 UI | 🟢 | 切换"正式回复"标识 |
| DevB | **T2B.6/.7** 并发上限 + 未读徽章 | 🟢 | UI 增强 |

### 🤝 M2 smoke test（Thu 13:00-13:30，30 min）

1. 启动 A + B，另开 B 的 operator-console
2. 验收点：
   - [ ] customer-chat 发消息 → operator-console 卡片出现（US-2.3）
   - [ ] operator 点卡片 → Copilot 侧栏打开，mode 切到 copilot
   - [ ] operator 发建议 → customer 看不到（Gate 生效）
   - [ ] operator 输入 /hijack → mode=takeover，customer 看到 operator 真实回复
   - [ ] 翻转后 AI 继续发 `[AI建议]` 在侧栏
   - [ ] 180s 不接单 → 自动退回 + 安抚消息（可缩短 timer 测试）
3. SLA 告警：模拟 6 min 内超阈值 → 管理通道（暂 stdout）收到 alert
4. task-status.md: P2 全部 🟩，T5A.1 若完成也标 🟩
5. **merge milestone-M2 到 main**

---

## 3. M3 · 管理后台 + 合规（Thu 13:30-20:00，6.5 小时）

**目标**: admin-portal 4 步向导可用；16 条合规预检可运行；仪表盘上线。

**注**: T3A.4/5/6 合规规则应在 Wed PM 已 M1 并行启动；Thu AM 应已完成草稿；现在只需收尾。

### Batch 7 · 合规收尾（Thu 13:30-15:30）

| Owner | 任务 | 类型 | 提示 |
|---|---|---|---|
| DevA | **T3A.4** 合规 schema 收尾 | 🔴 | 若 Wed PM 未完成，现立即完成 |
| DevA | **T3A.5** 16 条 YAML 终稿 | 🔴 | EU 6 + US 4 + CN 6 |
| DevA | **T3A.6** 补救指南 × 16 | 🔴 | CC 可并发生成 16 份 md |
| DevA | **T3A.7** compliance.py 预检引擎 | 🟡 | 扫描 tenant 配置 → 风险等级 |

### Batch 8 · 向导后端 + admin 骨架（Thu 15:30-17:30）

| Owner | 任务 | 类型 | 提示 |
|---|---|---|---|
| DevA | **T3A.1** soul.md 自动生成器 | 🟡 | 从 KB + 配置 → 4 份 soul.md 草稿 |
| DevA | **T3A.2** sim_customer pipeline | 🟡 | persona 混搭 + 场景覆盖 + AI 答 |
| DevA | **T3A.3** Few-shot 注入机制 | 🟢 | tenant.fewshot_override.yaml |
| DevB | **T3B.1** admin-portal SPA 骨架 | 🟢 | 登录 + 租户路由 + 4 tab |
| DevB | **T3B.2** 向导 Step1 资料上传 | 🟢 | 表单 + 调 T3A.1 生成 API |

### Batch 9 · 向导页 + 仪表盘（Thu 17:30-20:00）

| Owner | 任务 | 类型 | 提示 |
|---|---|---|---|
| DevB | **T3B.3** Step2 渠道配置 | 🟢 | 勾选 Web 首发 → 生成 URL + 邮件 |
| DevB | **T3B.4** Step3 虚拟预演 UI | 🟢 | ≥10 条对话审阅 + ✓/✎/⚠ |
| DevB | **T3B.5** Step4 合规预检可视化 | 🟢 | 16 条结果 + 风险等级 + 补救链接 |
| DevB | **T3B.6** 运营仪表盘页 | 🟢 | 4 Agent 状态 + 3 核心指标 + 趋势图 |
| DevB | **T3B.7** 通知中心 | 🟢 | 对话式组件 + /rules /status /review |

### 🤝 M3 smoke test（Thu 20:00-20:30，30 min）

1. admin-portal 打开
2. 验收点：
   - [ ] 走完 4 步向导：上传 PDF → 生成 4 份 soul.md → 勾 Web 渠道 → 预演 ≥10 条 → 合规预检 16 项
   - [ ] 合规有未通过项 → 沙箱可用 + 对外开放被阻塞（US-1.4）
   - [ ] 虚拟预演 ✓/✎/⚠ 完整流程
   - [ ] 仪表盘显示当前租户的 Agent 状态 + 指标
   - [ ] 通知中心收到 SLA 告警（从 M2 继续）
3. task-status.md: P3 全部 🟩
4. **merge milestone-M3 到 main**

---

## 4. M4 · Dream Engine + 计费（Fri 09:00-14:00，5 小时）

**目标**: Dream Engine 闭环（记忆池 → 提案 → 灰度 → 回滚）；三大 ★ 计费指标出账单。

### Batch 10 · Dream Engine 核心（Fri 09:00-12:00）

| Owner | 任务 | 类型 | 提示 |
|---|---|---|---|
| DevA | **T4A.1** 记忆池 memory_pool.db | 🟢 | session 扩展，含意图/情绪/KB 命中/结案 |
| DevA | **T4A.2** /rules 后端 + 对话式配置 | 🟢 | 4 参数对话采集状态机 |
| DevA | **T4A.3** 低峰检测调度器 | 🟢 | QPS 30min 均值 <20% → 触发 |
| DevA | **T4A.4** 提案生成 pipeline | 🟡 | LLM 回放 → 提案 JSON；Yellow 评审重点看 prompt 质量 |

### Batch 11 · 灰度 + 计费 + 提案 UI（Fri 12:00-14:00）

| Owner | 任务 | 类型 | 提示 |
|---|---|---|---|
| DevA | **T4A.5** 晨起推送 | 🟢 | 每日 09:00 前 → 通知中心 |
| DevA | **T4A.6** canary.py 灰度路由 | 🟢 | 5%→25%→100% |
| DevA | **T4A.7** 5 指标监测 + 自动回滚 | 🟢 | 恶化 >2× 阈值自动回滚 |
| DevA | **T4A.8** /rollback 命令 | 🟢 | 撤回 + reason + 7 天复盘队列 |
| DevA | **T4A.9** 三指标统计 | 🟢 | 接管次数 / CSAT / 升级转结案率月聚合 |
| DevA | **T4A.10** billing.py | 🟢 | 阶梯计费月末账单 JSON |
| DevB | **T4B.1** 提案审核页 | 🟢 | ✓/✎/✗ + 来源对话 + 风险 |
| DevB | **T4B.2** 灰度进度可视化 | 🟢 | 5 指标实时曲线 |
| DevB | **T4B.3** 账单导出 UI | 🟢 | 月末预览 + CSV/PDF |

### 🤝 M4 smoke test（Fri 14:00-14:30，30 min）

1. 模拟业务低峰（手动触发 / 改阈值） → 触发 Dream Engine
2. 验收点：
   - [ ] 记忆池写入正确
   - [ ] /rules show 显示配置
   - [ ] 晨起推送出现在通知中心（可手动模拟）
   - [ ] 提案审核页展示提案 + ✓ 通过 → 进 5% 灰度
   - [ ] 模拟指标恶化 → 自动回滚 + 通知中心告警
   - [ ] /rollback <id> 手动回滚工作
   - [ ] 账单页显示本月三指标 + 费用预览
3. task-status.md: P4 全部 🟩
4. **merge milestone-M4 到 main**

---

## 5. M5 · zchat 切换 + 最终验收（Fri 14:30-20:00，5.5 小时）

**目标**: ZchatEngine 替代 LocalEngine；AB 测试通过；17 story E2E 全绿；可上线内测。

**注**: T5A.1 zchat API 对齐应在 Thu AM 已 M2 并行启动；现在只需收尾 SDK 实施。

### Batch 12 · Bridge SDK + ZchatEngine（Fri 14:30-16:30）

| Owner | 任务 | 类型 | 提示 |
|---|---|---|---|
| DevA | **T5A.1** zchat API 对齐终稿 | 🔴 | 若 Thu AM 未完成，立即收尾 |
| DevA | **T5A.2** Bridge API Python SDK | 🟢 | WS 连接 + 14 消息 schema + 重连心跳 |
| DevA | **T5A.3** ZchatEngine 适配器 | 🟢 | 实现 ConversationEngine Protocol；底层走 SDK |
| DevB | **T5B.1** docker-compose 多租户模板 | 🟢 | autoservice + 3 frontend + zchat channel-server |
| DevB | **T5B.2** 同主机部署约束 | 🔴 | NFR-4；SRE 审批跨主机例外流程 |

### Batch 13 · plugin 对齐 + 监控埋点（Fri 16:30-18:00）

| Owner | 任务 | 类型 | 提示 |
|---|---|---|---|
| DevA | **T5A.4** 4 plugin 双实现对齐 | 🟢 | lifecycle/metrics/squad/cc_pool 在 ZchatEngine 下同样工作 |
| DevA | **T5A.5** cc-pool key 迁移 | 🟡 | chat_id → conversation_id；adapter 映射表 30 天 |
| DevA | **T5A.6** 延迟监控埋点 | 🟢 | bridge_api.roundtrip_ms / plugin.hook_duration_ms / eventbus.emit_ms |
| DevB | **T5B.3** 租户创建脚本 | 🟢 | create-tenant.sh 一键生成 URL+凭据 |

### Batch 14 · AB 测试 + E2E + 切换（Fri 18:00-20:00）

| Owner | 任务 | 类型 | 提示 |
|---|---|---|---|
| DevA | **T5A.7** LocalEngine vs ZchatEngine AB | 🟡 | 同流量双跑；对比 P50/P95 延迟、正确性、SLA |
| DevA | **T5A.8** engine: local\|zchat 配置切换 | 🟢 | config.yaml 一行切换；启动时注入 |
| DevB | **T5B.4** 端到端 E2E 自动化 | 🟢 | 17 story Gherkin Playwright |
| DevB | **T5B.5** 浮窗 SDK npm 发布 | 🟢 | 发布到 npm |

### 🤝 M5 最终验收（Fri 20:00-21:00，60 min）

1. **AB 对比报告**（T5A.7 产出）:
   - [ ] P95 延迟 ZchatEngine 相对 LocalEngine 增量 ≤30ms（NFR-1 目标 ≤20ms）
   - [ ] 正确性：同样输入同样输出
   - [ ] SLA 达成率无显著下降
2. **17 story E2E**（T5B.4 产出）:
   - [ ] Epic 1 (4 US) 全绿
   - [ ] Epic 2 (6 US) 全绿
   - [ ] Epic 3 (3 US) 全绿
   - [ ] Epic 4 (4 US) 全绿
3. **切换决策**:
   - 若 AB 全绿 + E2E 全绿 → **切换 engine=zchat**
   - 若 AB 有风险 → **保持 engine=local 上线内测**（路径 B 兜底）
4. task-status.md: **P5 全部 🟩 + 整体 66/66 完成**
5. **merge milestone-M5 到 main**
6. **发布 tag v1.1.0-mvp**
7. **开 MVP 内测 Issue，邀请 3-5 家内测商户**

---

## 6. 全局备用预案

### 预案 A · 某 Milestone 超时

| 超时 | 动作 |
|---|---|
| M1 超 Wed 20:30 | 把 T1A.11（情绪识别）降级到 M3，腾出时间收尾 |
| M2 超 Thu 13:30 | 把 T2A.2（分流信心）降级到 M4 |
| M3 超 Thu 20:30 | 把 T3B.7（通知中心）改为最简轮询实现 |
| M4 超 Fri 14:30 | 把 T4B.3（账单 UI）改为 JSON 导出，不做 CSV/PDF |
| M5 超 Fri 21:00 | **保持 engine=local 上线**，zchat 切换推迟到下周 |

### 预案 B · Red 决策卡住

- T0.1/T0.2（M0）—— 不应在此处发生，应已签
- T3A.4-6（合规）—— 若 Thu AM 未完成法务确认，先用"内部测试"版本上线沙箱，正式开放延后
- T5A.1（zchat）—— 若 Thu AM 未获 zchat 确认，保持 LocalEngine（预案 A M5 兜底）

### 预案 C · Yellow 评审大面积失败

- 单次失败率 >50% → 暂停 CC 派发 → 15 分钟复盘 prompt / 上下文 → 重启批次
- 常见原因: PRD 描述歧义 / 契约遗漏 / CC 缺上下文

### 预案 D · 跨线依赖阻塞

- DevA 卡住且影响 DevB：DevB 切到 UI 独立任务（样式 / 动画 / 无障碍）
- DevB 卡住且影响 DevA：DevA 切到 Yellow 任务草稿准备

---

## 7. Milestone 同步模板（每次 5 min）

每完成一个 M，双方快速贴：

```
@DevA @DevB · M{X} 同步 · {时刻}

1. 进度: task-status.md P{X} 状态 ({N}/{Total})
2. 契约漂移: {无 / 有，详情}
3. Yellow 人审待办: {列表}
4. Red 任务状态: {T3A.4-6 / T5A.1 / T5B.2 当前}
5. 下 Milestone 启动时间: {HH:MM}
6. 风险: {无 / 列举}

如 5 min 内无人反对 → 进入下 Milestone
```

---

## 8. 读法

- **Milestone 级别**: 按 §1-5 顺序执行
- **Batch 级别**: 每 Milestone 内按 Batch 顺序，批内 A/B 并行
- **Task 级别**: 用 `cc-prompt-templates.md` §1 (启动) / §2 (推进) / §3 (归档) 三段式

配合阅读:
- 任务详情: [`2026-04-15-prd-gap-tasks-v3.md`](2026-04-15-prd-gap-tasks-v3.md)
- 状态追踪: [`task-status.md`](task-status.md)
- 协同规则: [`collaboration-playbook.md`](collaboration-playbook.md)
- Prompt 模板: [`cc-prompt-templates.md`](cc-prompt-templates.md)

---

*v1.0 · 2026-04-15 · M0 后启动 · 3 日冲刺 M1-M5 完整手册 · Fri EOD 验收*
