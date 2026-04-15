# AutoService 任务列表 — v3（适配层先行 · 双人并行）

> 2026-04-15 · 基于 PRD v1.1 + gap-v3 · **策略路径 B：适配层先行**
> 取代 v2 作为当前开发基线；v2 历史保留不再维护
> **66 任务** 分为 **A / B 两条并行线**（两人实施，互相独立）
> 标注: 🔧 代码 · 📐 设计+代码 · 🧪 验证 · 📝 配置 · 🎨 前端 · 🔀 A+B 协作

---

## ⚡ 时间快车道（2026-04-15 调整）

由于全程 AI 执行，原"17 周"时间线压缩为 **3 个工作日冲刺**，目标 **2026-04-17（周五）前完成 M5**。

| 原规划 | 实际档期（AI 快车道）| 对应日期 | 里程碑 |
|---|---|---|---|
| 周 0-1 · Phase 0 契约+骨架 | **第 1 日上午** | **Wed 04-15 AM** | M0 + M0.5 |
| 周 1-5 · Phase 1 核心对话 | **第 1 日下午** | **Wed 04-15 PM** | M1 |
| 周 5-8 · Phase 2 工作台+SLA | **第 2 日上午** | **Thu 04-16 AM** | M2 |
| 周 8-11 · Phase 3 管理+合规 | **第 2 日下午** | **Thu 04-16 PM** | M3 |
| 周 11-14 · Phase 4 Dream+计费 | **第 3 日上午** | **Fri 04-17 AM** | M4 |
| 周 14-17 · Phase 5 zchat 切换 | **第 3 日下午** | **Fri 04-17 PM** | M5 验收 |

**以下章节所有"周 X"、"X 周"、"Week X" 引用请按本表换算**。甘特图仅保留作结构参考，不代表实际节奏。

**关键节奏**：
- 每半天推完一个 Phase（AI 并发批次 + 人审窗口收紧到分钟级）
- Red 决策点要求 **30 分钟内响应**（T0.1/T0.2 在 M0；T3A.4-6 合规 / T5A.1 zchat 对齐并行处理）
- Yellow 评审窗口 **30 分钟**（不再是 3 天）
- 每 Phase 结束立即跑 dev-loop 回归，不累积到周末

---

---

## 〇、策略与分线原则

### 1. 路径 B 核心思想

引入 `ConversationEngine` 抽象接口，两个实现：
- **LocalEngine**（现阶段）：基于现有 `channel_server.py` + `cc_pool` + Feishu/Web 直连；Mode/Gate/Timer 用最小 Python 实现
- **ZchatEngine**（M5 切换）：封装 Bridge API WS SDK

切换只改一行配置 `engine: local|zchat`，无需改 App 层和前端。

### 2. 工作流分线

| 分线 | 主责 | 职责 |
|---|---|---|
| **A 线 · 后端引擎与业务** | 一人 | ConversationEngine 抽象、LocalEngine、4 plugin、Agent souls、ModelRouter、Dream Engine、合规、计费、ZchatEngine 适配 |
| **B 线 · Web 前端与交付** | 一人 | 3 个 Web 应用（customer-chat / operator-console / admin-portal）、浮窗 SDK、上线向导 UI、仪表盘、部署编排 |

### 3. 独立性分析

- **A 线交付契约**：`ConversationEngine` 抽象（Python）+ 对前端的 **WebSocket 消息 schema**
- **B 线消费契约**：只依赖 WebSocket schema，不关心 Local/Zchat 实现差异
- **同步点共 5 个**（M0 契约冻结、M1/M2/M3/M4 端到端验证、M5 zchat 切换）

### 4. 相对 v3 原版的变化

- 新增 Phase -1 无 → 改为 **Phase 0 强化为"契约先行"**
- **T0.2 Bridge SDK 从 Phase 0 推迟到 Phase 5**（切 zchat 时）
- **T1.X 所有 plugin 先写 LocalEngine 版**，M5 再加 ZchatEngine 版
- **cc-pool key 迁移（chat_id→conversation_id）从 Phase 1 推迟到 Phase 5**（与 zchat 切换同步）
- **延迟监控埋点（NFR-1~3）集中在 Phase 5**（LocalEngine 下是 baseline，ZchatEngine 下才需要监控）

---

## 一、Phase 0 · 契约与骨架（周 0-1，1 周）

> **里程碑 M0**: ConversationEngine 接口冻结；A/B 可独立开发

| # | 任务 | 线 | 类型 | 产出 |
|---|---|---|---|---|
| T0.1 | **`ConversationEngine` 抽象设计** | 🔀 A+B | 📐 | `autoservice/engine/conversation_engine.py` — Python Protocol: create_conversation / send_reply / edit_message / switch_mode / resolve / on / query |
| T0.2 | **WebSocket 消息 schema 冻结** | 🔀 A+B | 📝 | `docs/contracts/frontend-ws-schema.md` — 前端 ↔ 后端的消息类型（customer_msg / agent_reply / mode_changed / csat_request 等）|
| T0.3 | **契约测试 suite** | 🔀 A+B | 🧪 | `tests/contract/` — schema 校验 + 状态流转 |
| T0.4 | **LocalEngine 骨架** | A | 🔧 | `autoservice/engine/local_engine.py` — 实现 ConversationEngine（暂空方法 + TODO） |
| T0.5 | **WebSocket 服务端骨架** | A | 🔧 | `autoservice/web_gateway.py` — FastAPI + WebSocket，对前端暴露冻结 schema |
| T0.6 | **前端 monorepo 骨架** | B | 🎨 | `frontend/` — pnpm workspace + React + WebSocket client 封装 + i18n 框架 |

---

## 二、Phase 1 · 核心对话流程（周 1-5，4 周）

> **里程碑 M1（周 5）**: customer-chat ↔ LocalEngine ↔ Agent 端到端；占位续写可用

### A 线（后端 · 11 任务）

| # | 任务 | 类型 | 关联 | 产出 |
|---|---|---|---|---|
| T1A.1 | **LocalEngine Mode/Gate 最小实现** | 🔧 | LocalEngine | Mode 状态机（auto/copilot/takeover）+ Gate 可见性决策（public/side）；~150 行 |
| T1A.2 | **LocalEngine Timer 最小实现** | 🔧 | LocalEngine | 7 类 Timer（onboard/placeholder/slow_query/takeover_wait/idle/close/first_reply）；asyncio scheduler |
| T1A.3 | **LocalEngine EventBus 最小实现** | 🔧 | LocalEngine | 进程内 pub/sub + SQLite 异步落盘（NFR-2 为未来 zchat 对齐）|
| T1A.4 | **4 角色 soul.md 规范 + 定义** | 📐 | α1 | `agents/{customer,translate,lead,triage}/soul.md` + `agent.yaml` |
| T1A.5 | **ModelRouter + FastClassifier** | 🔧 | α2 / US-2.2 | `autoservice/model_router.py` + `classify_intent.yaml` (5 类意图 + 4 阶段 timeout) |
| T1A.6 | **占位续写流程（LocalEngine 版）** | 🔧 | α2 / US-2.2 | 快模型占位 + 慢模型续写 + LocalEngine.edit_message → 前端 WS 推送 |
| T1A.7 | **lifecycle plugin（LocalEngine 版）** | 🔧 | γ4 | 订阅 on_conversation_created → 创建 CRM 记录 + 加载历史 |
| T1A.8 | **metrics plugin（LocalEngine 版）** | 🔧 | γ4 / δ1-3 | 订阅 mode.changed / csat_response / conversation.resolved |
| T1A.9 | **squad plugin（LocalEngine 版）** | 🔧 | γ4 / US-2.3 | 订阅 conversation.created → 推分队卡片到 operator-console（经 web_gateway）|
| T1A.10 | **cc_pool plugin（LocalEngine 版）** | 🔧 | γ7 | 订阅 on_conversation_closed → release_sticky；本期 key 保持 chat_id（不改动）|
| T1A.11 | **情绪识别 prompt 扩展** | 🔧 | α4 | Skill 前缀注入 sentiment；恶化 emit 事件 |

### B 线（前端 · 6 任务）

| # | 任务 | 类型 | 关联 | 产出 |
|---|---|---|---|---|
| T1B.1 | **customer-chat SPA 骨架** | 🎨 | β1 / US-2.1 | 独立 Web 聊天页 + WS 连接 web_gateway |
| T1B.2 | **消息流 UI** | 🎨 | β1 | 消息气泡 + 打字指示 + 时间戳 + 多种消息类型（text/image）|
| T1B.3 | **占位续写渲染** | 🎨 | β1 / US-2.2 | 占位态 → edit 事件原地续写替换（非新发）|
| T1B.4 | **断线重连 + 消息回放** | 🎨 | β1 | WS reconnect + 历史拉取 + 消息 ack |
| T1B.5 | **浮动按钮 SDK** | 🎨 | β4 | 一段 `<script>` 嵌入独立站；按 domain 隔离；主题可定制 |
| T1B.6 | **多语言 UI 框架** | 🎨 | β1 / X6 | i18n（22 语种 UI 文案占位；先中/英实填）|

**→ M1 联调**（~2 天）: A 的 web_gateway + B 的 customer-chat 打通，验证占位续写、断线重连、US-2.1/2.2 完整。

---

## 三、Phase 2 · 客服工作台 + SLA（周 5-8，3 周）

> **里程碑 M2（周 8）**: Copilot / /hijack / 角色翻转全链路

### A 线（后端 · 5 任务）

| # | 任务 | 类型 | 关联 | 产出 |
|---|---|---|---|---|
| T2A.1 | **协议命令实现** | 🔧 | LocalEngine | /hijack /resolve /release /copilot /status /dispatch 命令解析 + 路由 |
| T2A.2 | **智能分流 Agent 信心模型** | 🔧 | α5 | `autoservice/triage.py` 替换 route_query；输出信心评分 |
| T2A.3 | **SLAAggregator** | 🔧 | δ5 / US-3.3 | 环形 buffer + P50/P95 + 5m/1h/24h 窗口 |
| T2A.4 | **alerts.yaml + 告警推送** | 📝+🔧 | δ5 | 4 规则（首回/接单/CSAT/消化率）+ 经 web_gateway 推 admin-portal |
| T2A.5 | **22 语种术语 + 注入 + 商户覆盖** | 📝+🔧 | α3 | 22 份 YAML（IATE 源）+ 翻译 Agent prompt 注入 + `tenant/terms.yaml` 覆盖 |

### B 线（前端 · 7 任务）

| # | 任务 | 类型 | 关联 | 产出 |
|---|---|---|---|---|
| T2B.1 | **operator-console SPA 骨架** | 🎨 | β2 | 登录 + 分队视图 + WS 订阅 squad 事件 |
| T2B.2 | **分队卡片列表 UI** | 🎨 | β2 / US-2.3 | 5 状态卡片（idle / waiting-reply / escalation-pending / human-takeover / closed）|
| T2B.3 | **Copilot 侧栏聊天窗** | 🎨 | β2 / US-2.4 | 点卡片 → WS 发 operator_join → 客户对话 + 草稿侧栏 + 建议输入 |
| T2B.4 | **/hijack + 抢单按钮** | 🎨 | β2 / US-2.5 | 一键发 operator_command(/hijack)；180s 计时器 UI |
| T2B.5 | **Takeover 模式 UI** | 🎨 | β2 / US-2.6 | 输入框切换"正式回复"标识；侧栏显示 AI 建议（标 `[AI建议]`） |
| T2B.6 | **并发上限提示** | 🎨 | β2 | 同时 Copilot ≤5 对话，UI 置灰/排队 |
| T2B.7 | **未读徽章 + 声音提醒** | 🎨 | β2 | Tab 标题 + 系统通知 |

**→ M2 联调**（~2 天）: A 的 /hijack 命令 + B 的工作台按钮；SLA 告警端到端。

---

## 四、Phase 3 · 管理后台 + 合规（周 8-11，3 周）

> **里程碑 M3（周 11）**: admin-portal 4 步向导可用；合规预检可用；仪表盘上线

### A 线（后端 · 7 任务）

| # | 任务 | 类型 | 关联 | 产出 |
|---|---|---|---|---|
| T3A.1 | **soul.md 自动生成器** | 🔧 | ζ2 | 从 KB + 配置 → 4 份 soul.md 草稿；基于 kb_ingest 现有 API |
| T3A.2 | **虚拟客户生成 pipeline** | 🔧 | ζ4 | `autoservice/sim_customer.py` — persona 混搭 + 场景覆盖 + AI 答 |
| T3A.3 | **Few-shot 注入机制** | 🔧 | ζ4 | `tenant.fewshot_override.yaml` → soul.md 热加载 |
| T3A.4 | **合规规则 schema** | 📐 | δ6 | rule_id/region/severity/trigger/blocking |
| T3A.5 | **16 条预置规则 YAML** | 📝 | δ7 | EU 6（GDPR）+ US 4（CCPA/COPPA）+ CN 6（PIPL/网信办）|
| T3A.6 | **16 条补救指南 md** | 📝 | δ7 | `docs/compliance/<rule_id>.md` × 16 |
| T3A.7 | **compliance.py 预检引擎 + 策略下发** | 🔧 | δ8 | 扫描 tenant 配置 → 风险等级；沙箱不阻塞 / 对外开放阻塞；Dream Engine 受约束 |

### B 线（前端 · 7 任务）

| # | 任务 | 类型 | 关联 | 产出 |
|---|---|---|---|---|
| T3B.1 | **admin-portal SPA 骨架** | 🎨 | β3 | 登录 + 租户路由 + 4 大 tab（向导/仪表盘/通知/提案）|
| T3B.2 | **向导 Step1 资料上传** | 🎨 | ζ2 / US-1.1 | 表单 + 文件上传 + 调 T3A.1 soul.md 生成 API |
| T3B.3 | **向导 Step2 渠道配置** | 🎨 | ζ3 / US-1.2 v1.1 | 勾选 Web 首发 → 生成 URL + 发凭据邮件 |
| T3B.4 | **向导 Step3 虚拟客户预演 UI** | 🎨 | ζ4 / US-1.3 | ≥10 条对话审阅 + ✓/✎/⚠ + 完成度进度 |
| T3B.5 | **向导 Step4 合规预检可视化** | 🎨 | ζ5 / US-1.4 | 16 条规则扫描结果 + 风险等级 + 补救链接 |
| T3B.6 | **运营仪表盘页** | 🎨 | US-3.1 | 4 Agent 状态 + 3 核心指标 + Leaderboard + 趋势图 + 时间切片 |
| T3B.7 | **通知中心（/rules /status /review）** | 🎨 | US-3.2 / US-4.1 | 对话式组件 + 斜杠命令解析 |

**→ M3 联调**（~2 天）: 4 步向导端到端；合规预检与策略下发联动。

---

## 五、Phase 4 · Dream Engine + 计费（周 11-14，3 周）

> **里程碑 M4（周 14）**: Dream Engine 灰度闭环；三大 ★ 计费指标出账单

### A 线（后端 · 10 任务）

| # | 任务 | 类型 | 关联 | 产出 |
|---|---|---|---|---|
| T4A.1 | **对话记忆池 memory_pool.db** | 🔧 | ε1 | 每轮含意图/情绪/KB 命中/结案状态 |
| T4A.2 | **/rules show\|edit 后端 + 对话式配置** | 🔧 | ε2 / US-4.1 | rules.py 扩展；4 参数对话采集状态机 |
| T4A.3 | **低峰检测调度器** | 🔧 | ε3 / US-4.2 | QPS 30 分钟均值 <20% → 触发回放 |
| T4A.4 | **提案生成 pipeline** | 📐 | ε4 / US-4.3 | LLM 回放 → 抽取建议 → 提案 JSON |
| T4A.5 | **晨起推送** | 🔧 | US-4.3 | 每日 09:00 前聚合 → 通知中心 |
| T4A.6 | **canary.py 灰度路由** | 🔧 | ε6 / US-4.4 | 5%→25%→100% + 24h 观察 |
| T4A.7 | **灰度 5 指标监测 + 自动回滚** | 🔧 | ε6 / US-4.4 | CSAT/升级转结案率/消化率/接单等待/投诉率；恶化 >2× 阈值触发 |
| T4A.8 | **/rollback 命令** | 🔧 | ε7 / US-4.4 | 撤回 + reason + 7 天复盘队列 |
| T4A.9 | **接管次数 + CSAT + 升级转结案率统计** | 🔧 | δ1-3 / ★ | metrics plugin 扩展 + 月聚合 |
| T4A.10 | **阶梯计费 billing.py** | 🔧 | δ4 | 月末账单 JSON |

### B 线（前端 · 3 任务）

| # | 任务 | 类型 | 关联 | 产出 |
|---|---|---|---|---|
| T4B.1 | **admin-portal 提案审核页** | 🎨 | ε5 / US-4.3 | ✓/✎/✗ 按钮 + 来源对话 + 风险等级 |
| T4B.2 | **灰度进度可视化** | 🎨 | US-4.4 | 5 指标实时曲线 + 阶段标记 + /rollback 按钮 |
| T4B.3 | **账单导出 UI** | 🎨 | δ4 | 月末账单预览 + CSV/PDF 导出 |

**→ M4 联调**（~2 天）: 提案从生成 → 审核 → 灰度 → 自动回滚 → 账单。

---

## 六、Phase 5 · zchat 切换 + 部署（周 14-17，3 周）

> **里程碑 M5（周 17）**: ZchatEngine 可替代 LocalEngine；端到端 17 story 通过；可上线内测

### A 线（后端 · 8 任务）

| # | 任务 | 类型 | 关联 | 产出 |
|---|---|---|---|---|
| T5A.1 | **对齐 zchat Bridge API v0.3** | 📝 | γ1 | 与 zchat 团队签字版本锁 + 契约文档 |
| T5A.2 | **Bridge API Python SDK** | 🔧 | γ1 | `autoservice/zchat_client/` — WebSocket 连接 + 14 消息 schema + 重连/心跳 |
| T5A.3 | **ZchatEngine 适配器** | 🔧 | 路径 B 核心 | `autoservice/engine/zchat_engine.py` — 实现 ConversationEngine 接口；底层走 SDK |
| T5A.4 | **4 plugin 双实现对齐** | 🔧 | γ4 | lifecycle/metrics/squad/cc_pool 在 ZchatEngine 下同样工作；注入 zchat channel-server |
| T5A.5 | **cc-pool key 迁移 chat_id → conversation_id** | 🔧 | γ7 | `acquire_sticky(conv.id)`；adapter 层做 chat_id ↔ conv_id 映射 |
| T5A.6 | **延迟监控埋点**（NFR-1/2/3） | 🔧 | γ6 | `bridge_api.roundtrip_ms` / `plugin.hook_duration_ms` / `eventbus.emit_ms`；P95 告警 |
| T5A.7 | **LocalEngine vs ZchatEngine AB 测试** | 🧪 | 风险控制 | 同一流量双后端跑；对比 P50/P95 延迟、正确性、SLA 达成率 |
| T5A.8 | **engine: local\|zchat 配置切换** | 📝+🔧 | 路径 B 核心 | `config.yaml` 一行切换；启动时注入对应 Engine 实现 |

### B 线（前端 + 部署 · 5 任务）

| # | 任务 | 类型 | 关联 | 产出 |
|---|---|---|---|---|
| T5B.1 | **docker-compose 多租户模板** | 📝 | X7 | autoservice + 3 frontend + zchat channel-server + bridges |
| T5B.2 | **同主机部署约束落地**（NFR-4） | 📝 | γ8 | channel-server 与 bridges 同 pod；跨主机需双签审批流程 |
| T5B.3 | **租户创建脚本** | 🔧 | US-1.2 | `create-tenant.sh` 一键生成 web_bridge URL + 凭据 |
| T5B.4 | **端到端自动化 E2E** | 🧪 | M5 验收 | 17 story 的 Gherkin 自动化（Playwright）|
| T5B.5 | **浮窗 SDK npm 发布** | 📝+🔧 | β4 | 发布到 npm；商户独立站一行引入 |

**→ M5 联调**（60 min smoke test）: A 的 ZchatEngine + zchat 真实实例；B 的 E2E 自动化；AB 对比无回归 → 切换默认 engine=zchat。

---

## 七、任务总览

### 7.1 统计

| Phase | A 线 | B 线 | 协作 | 合计 | 周 |
|---|---|---|---|---|---|
| P0 契约 | 2 | 1 | 3 | 6 | 1 |
| P1 核心 | 11 | 6 | — | 17 | 4 |
| P2 工作台+SLA | 5 | 7 | — | 12 | 3 |
| P3 管理+合规 | 7 | 7 | — | 14 | 3 |
| P4 Dream+计费 | 10 | 3 | — | 13 | 3 |
| P5 zchat 切换 | 8 | 5 | — | 13 | 3 |
| **合计** | **43** | **29** | **3** | **66+联调** | **17 周** |

### 7.2 分线独立性评估

| 方面 | 独立程度 | 说明 |
|---|---|---|
| P0 契约设计 | ⚠️ 需协作 | 3 任务 A+B 共同产出 |
| P1-P4 日常开发 | ✅ 高度独立 | 仅通过 WebSocket schema 交互，可各自 mock |
| 每个里程碑联调 | ⚠️ 30 min smoke test | 按 M1-M4 对齐 |
| P5 zchat 切换 | ⚠️ A 主导 | B 配合做部署 + E2E，前端无需改代码 |

### 7.3 按承接关系的任务链

**A 线主链**（关键路径）:
```
T0.1 ConversationEngine
 → T0.4 LocalEngine 骨架
 → T1A.1-.3 Mode/Gate/Timer/EventBus
 → T1A.4-.6 souls + ModelRouter + 占位续写
 → T1A.7-.10 4 plugin
 → T2A.1-.3 命令 + 分流 + SLA
 → T3A.4-.7 合规
 → T4A.1-.10 Dream Engine + 计费
 → T5A.2-.8 ZchatEngine + 切换
```

**B 线主链**（关键路径）:
```
T0.2 WS schema
 → T0.6 前端 monorepo
 → T1B.1-.6 customer-chat
 → T2B.1-.7 operator-console
 → T3B.1-.7 admin-portal
 → T4B.1-.3 提案 UI / 账单
 → T5B.1-.5 部署 + E2E
```

### 7.4 协作/独立分类清单

**🔀 协作任务（必须 A+B 同时在场，3 个）**:
- T0.1 ConversationEngine 抽象设计
- T0.2 WebSocket 消息 schema 冻结
- T0.3 契约测试 suite

**🤝 联调任务（每个 Milestone 30 min smoke test，5 次；M5 60 min）**:
- M1 customer-chat × LocalEngine
- M2 operator-console × 协议命令
- M3 admin-portal × 合规+soul 生成
- M4 提案 UI × Dream Engine
- M5 E2E × ZchatEngine

**🧍 独立任务**（A/B 各自推进，剩余 60 项）: 按各自 Phase 内任务表推进，通过 WebSocket schema + mock 互相解耦

### 7.5 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| zchat v0.3 延期 | Phase 5 延期 | 路径 B 保证 LocalEngine 可独立交付；Phase 1-4 不受影响 |
| WS schema 设计不完整 | M1-M4 多次返工 | T0.1-0.3 花 1.5h 做透；先手写 10 个典型场景跑通 |
| A/B 分线步调不齐 | 联调窗口浪费 | 每 Milestone 末 5 分钟对齐 + 共享 mock |
| LocalEngine Mode/Gate 与 zchat 语义漂移 | M5 切换时发现业务不匹配 | T0.1 设计时参考 zchat-plan/01-primitives；LocalEngine 每个方法对齐 zchat 命名 |
| 延迟监控缺失 → M5 切换后 SLA 劣化未发现 | 高 | T5A.6 埋点必须在 AB 测试前到位 |
| cc-pool key 迁移 bug | 中 | T5A.5 做双跑对照；conv_id ↔ chat_id 映射表保留 30 天 |

---

## 八、Out of Scope（v3 B）

- 飞书 IM 能力（全部由 zchat feishu_bridge 承接）
- 对话状态机在 zchat 引擎层的完整实现（LocalEngine 仅做最小版）
- 其他 IM 渠道（zchat 后续）
- PSTN、移动 App、白标

---

## 九、读法

- **当前唯一开发基线**：本 v3（路径 B）
- **v3 原版（路径 A）已作废**，保留历史
- **A 线开发者**：重点看 §二/三/四/五/六 A 线专栏 + §一 §七
- **B 线开发者**：重点看 §二/三/四/五/六 B 线专栏 + §一 §七 + `docs/contracts/frontend-ws-schema.md`
- **共同关注**：§7.4 协作任务 + Milestone 联调窗口

下次版本触发条件: ① M5 完成后复盘 ② zchat Bridge API 破坏性变更 ③ 新增 App 场景

---

*v3（路径 B）· 2026-04-15 · 基于 PRD v1.1 + gap-v3 · 66 任务 · 17 周 · 双人并行 · 适配层先行 + M5 一次性 zchat 切换*
