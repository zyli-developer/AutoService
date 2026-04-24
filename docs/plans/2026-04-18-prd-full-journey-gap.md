# AutoService · Full-Journey PRD Gap 分析

> 2026-04-18 · 基于 [`docs/prd/autoservice-full-journey.html`](../prd/autoservice-full-journey.html)（三幕三视角九视图）与当前实现逐项对比
> 上游：PRD v1.1 / UserStories v1.1 / [`2026-04-15-prd-gap-v3.md`](2026-04-15-prd-gap-v3.md)
> 作用：**v3 之后的增量差异盘点**——以 Full-Journey HTML 披露的细化业务语义为基准，标注偏差与修复建议

---

## 〇、Full-Journey HTML 的三幕结构

| 幕 | 步骤 | 视角 | 关键业务语义 |
|---|---|---|---|
| **A · 商户自助上线** | 6（注册→上传→权限→预演→合规→沙箱） | 商户控制台 + 租户配置中心 + (沙箱可用后) 已上线独立站 | 一次性 ≤2h · 沙箱先行 · "对外开放"由商户拍板 |
| **B · 日常运营** | 6 状态（触发→接洽→监管→建议→提醒→翻转） | C 端 Web + 商户客服 IM 工作区 + 平台监控 | 三视角并行 · **两种接管触发方式并列**（Agent @ vs /hijack）|
| **C · 闲时学习** | **7 步**（配置规则→临时记忆→Dream 启动→回放→沉淀→晨起审核→灰度） | 管理群 IM + 学习沉淀池 | **step 0 配置规则为新增起点**；5→25→100% 灰度 · /approve /edit /reject /rollback |

---

## 一、显著偏差清单

### Act A · 上线向导（6 项）

#### A-① 缺"注册接入"独立步骤 · P0
- **HTML**：step 0 独立于 upload——商户提交「公司名 / 联系人 / 主营国家 🇨🇳🇪🇺🇺🇸」，平台分配 `tenant_id=mystore_8f3a` + 独立沙箱 + IAM + **按国家匹配合规模板**
- **现状**：[frontend/apps/admin-portal/src/components/wizard/WizardTab.tsx](../../frontend/apps/admin-portal/src/components/wizard/WizardTab.tsx) 从「上传」开始；tenant_id 在 upload 阶段才生成（[autoservice/onboarding.py](../../autoservice/onboarding.py)）
- **影响**：合规预检无法按注册国家自动预选规则集；缺「按国家匹配合规模板」能力
- **修复**：前置 `RegisterStep`，落盘 `countries → compliance_profile`

#### A-② IM 管理群自动建立 + 4 Agent 入群 · P0
- **HTML** step 2：「群已创建 ✓ · 4 个 Agent 已入群 ✓」
- **现状**：[ChannelConfigStep.tsx](../../frontend/apps/admin-portal/src/components/wizard/ChannelConfigStep.tsx) 仅做渠道勾选；无建群 + 入群动作
- **影响**：无「管理群」通知实体——C 幕 Dream Engine 对话式配置、晨起推送、/approve 等都无 IM 载体
- **修复**：在 Web 首发边界下降级为「Web 通知中心开通 + 4 agent 注册到管理群虚拟 channel」，补建前端管理群组件

#### A-③ "一键对外"真实动作缺失 · P0
- **HTML** step 6：沙箱可用 → 团队邀请 5 人 → "对外开放 · 待商户决定"（显式 gate）+ "开放前需完成 1 项额外签署"
- **现状**：`/api/onboard/activate` 直接返回 URL；[SandboxReady.tsx](../../frontend/apps/admin-portal/src/components/wizard/SandboxReady.tsx) 按钮为 cosmetic
- **修复**：新增 `/api/onboard/publish` 端点 + sandbox → production 切换 + 开放前签署 gate

#### A-④ 合规模板按 tenant.countries 过滤 · P2
- **HTML**：平台视图 `[合规模板, EU+US+CN, ok]`——**按注册国家下发子集**
- **现状**：[autoservice/compliance/rules.yaml](../../autoservice/compliance/rules.yaml) 静态全加载 16 条，无按 tenant 过滤
- **修复**：compliance.py 增加 `load_rules_for_tenant(countries)` 过滤器

#### A-⑤ 时间预算监测（15min agent 生成 / 30min 预演 / 1h52min 总） · P2
- **HTML** 给出每步耗时承诺
- **现状**：无埋点 + 无 SLA 验证
- **修复**：在 onboarding 各阶段埋点 + 向导 UI 显示预计/实际耗时

#### A-⑥ 团队邀请（5 人）· P2
- **HTML** step 6：「团队成员 · 已邀请 5 人」
- **现状**：未找到团队邀请流
- **修复**：补团队/子账号邀请 API

---

### Act B · 日常运营（5 项）

#### B-⑦ 商户独立站浮窗 SDK 多租户路由 · P0（核心阻塞）
- **HTML**：客户在**商户自己的独立站**（mystore.com）点 💬 按钮——需一段 `<script>` 按 domain 隔离嵌入
- **现状**：[App.tsx](../../frontend/apps/customer-chat/src/App.tsx) 硬编码 `ws://localhost:8000/ws/customer`；无 `?tenant=` 参数提取；[frontend/packages/ws-client](../../frontend/packages/ws-client) 已发布但未验证跨域/按 tenant 路由
- **影响**："商户独立站"场景不成立——**没有多租户 SDK 就没有商业产品**
- **修复**：
  1. ws-client 支持 `?tenant=X` 路由 + domain 白名单
  2. 发布 iframe/script 两种嵌入形态
  3. 后端 `/ws/customer?tenant=X` 路由到对应 tenant agent 池

#### B-⑧ Agent 主动求助路径（confidence → HumanRequested） · P1
- **HTML** step 4 · 方式 a：Agent 置信度不足时自动「@客服小李 请接管 #2」
- **现状**：[autoservice/triage.py](../../autoservice/triage.py) 只做分流；未见 confidence < 0.6 → 自动 `@operator` 通知链路
- **修复**：
  1. agent 生成时附带 confidence
  2. confidence_threshold trigger → emit `HumanRequested` event
  3. SquadPane 订阅并弹出 @ 提醒

#### B-⑨ 接管态 Agent sidebar 主动 hint 回传 · P1
- **HTML** step 6：人工 driver 时，侧栏持续推送 `[侧栏] agent2: 客户上月购买过 X,可推荐升级`
- **现状**：TakeoverIndicator 只显示倒计时；接管模式下 agent 是否仍生成 sidebar hint 未验证
- **修复**：takeover 模式下保持 agent 运行（输出 visibility=side）+ CopilotSidebar 订阅推送

#### B-⑩ Copilot 建议"采纳/拒绝"回执 · P2
- **HTML** step 4：人工写建议 → agent2 消息显示「已采纳建议并发送给客户」
- **现状**：CopilotSidebar 送出的 suggestion 无 agent 侧采纳/拒绝回传
- **修复**：agent 处理 suggestion 后 emit `suggestion.adopted/rejected` 事件 → UI 显示

#### B-⑪ 平台监控「实时事件流」面板 · P1
- **HTML** Act B 平台视图展示 7 步事件流：`conn.open`, `agent.greet TTFB=2.1s`, `mode.changed`, `slow.query CRM+KB 8.2s`, `agent2.confidence 0.42<0.6`, `HumanRequested`, `takeover_count +1`, `conv.close CSAT=5`
- **现状**：EventBus + metrics_plugin 有数据源；缺独立的「平台监控」可视化页面（admin-portal Dashboard 只有聚合指标，非事件流）
- **修复**：新增 platform-console 或 admin-portal 下的「事件流」标签页，消费 EventBus 渲染

---

### Act C · 闲时学习（5 项，偏差最大）

#### C-⑫ Act C step 0「配置规则」未接入 IM 载体 · P0
- **HTML** step 0：老陈在**管理群 IM 对话式**与 Dream Engine 配置 4 参数（trigger/coverage/risk/canary）
- **现状**：
  - [autoservice/dream_config_dialog.py](../../autoservice/dream_config_dialog.py) 状态机已实现 ✅
  - **但无管理群 IM 通道**承载 → dialog 无触发/展示入口
  - 规则持久化至 per-tenant 配置需验证
  - 与 [autoservice/canary.py](../../autoservice/canary.py) 的联动（5→25→100 stage + 24h 观察）需打通
- **修复**：
  1. 管理群 WebSocket channel（依赖 A-②）
  2. dream_config_dialog 挂入管理群 bot 入口
  3. 输出写入 `tenant_config/{tenant_id}/dream_rules.yaml`
  4. canary.py 读取 tenant rule 动态调整 stage

#### C-⑬ memory_pool 7 天 TTL 滚动淘汰 · P2
- **HTML**：「TTL 7 天滚动 · 未结构化」
- **现状**：[autoservice/memory_pool.py](../../autoservice/memory_pool.py) 有 schema，无 eviction
- **修复**：低峰调度器附加 `evict_turns(older_than=7d)` 定时任务

#### C-⑭ 晨起推送实际 IM 送达 + 命令处理 · P0
- **HTML**：Dream Engine 在管理群发送 3 提案卡片（标题/风险/来源 N 段对话/建议），底部命令提示 `/approve #1 /edit #2 /reject #3`
- **现状**：
  - [autoservice/morning_push.py](../../autoservice/morning_push.py) 仅聚合，**未推送到管理群**
  - `/approve /reject` T6C.3 标 🟩 需回归验证
  - `/edit #N` 改提案内容子命令未见
- **修复**：
  1. morning_push 接入管理群 channel（依赖 A-②）
  2. 补 `/edit` 命令 handler
  3. 全链路回归：提案生成 → 推送 → 命令 → 灰度触发

#### C-⑮ 中风险提案「二次确认」流 · P1
- **HTML**：老陈规则「中风险需二次确认 ✓」；提案清单「流程·投诉升级（中风险）」
- **现状**：proposal_pipeline 产出 risk_level；中风险二次确认 UI/流程未见
- **修复**：risk_level>=middle 时 morning_push 附加 `[需二次确认]` tag，/approve 命令对中风险提案走两阶段确认

#### C-⑯ 灰度「命中 vs 未命中」双值对比 UI · P1
- **HTML**：`CSAT: 4.7 vs 4.5 · 升级率: 持平`——**baseline vs canary delta 并排展示**
- **现状**：[autoservice/canary_monitor.py](../../autoservice/canary_monitor.py) 有 baseline/canary 数据；T4B.2 "灰度进度可视化" UI 是否呈现双值 delta 需视觉验证
- **修复**：admin-portal canary 视图新增 baseline vs canary 对比列

---

### 跨幕系统性偏差（7 项）

| # | 维度 | HTML 要求 | 现状 | 判断 | 优先 |
|---|---|---|---|---|---|
| S1 | **租户隔离** | mystore_8f3a 独立沙箱/IAM/URL | 有 tenant_id；**无进程/DB 隔离** | ⚠️ 部分 | P1 |
| S2 | **管理群 IM 化** | 老陈 @ Dream Engine 对话 | admin-portal dashboard；**无 IM 对话 UI** | ❌ 缺 | **P0** |
| S3 | **客服 Agent 分队 IM 化** | Slack 风频道 + 卡片 + @提醒 | operator-console dashboard 形态 | 🟡 形态差异 | P1 |
| S4 | **独立站 SDK 嵌入** | 商户域名 `<script>` 一行集成 | 单页 SPA 硬编码 | ❌ 缺 | **P0** |
| S5 | **平台监控页面** | 实时 SLA + 事件流 + 配置中心 | 只有商户 admin-portal | ❌ 缺独立平台面板 | P1 |
| S6 | **沙箱 → 生产切换 gate** | 显式"一键对外" + 签署 | 无实际切换端点 | ❌ 缺 | **P0** |
| S7 | **时间预算监测** | 15min/30min/1h52min 承诺 | 无埋点 | 🟡 | P2 |

---

## 二、优先级汇总

### P0（阻塞产品故事成立）——5 项

| ID | 名称 | 核心修复 |
|---|---|---|
| B-⑦ / S4 | 独立站浮窗 SDK 多租户路由 | ws-client 支持 `?tenant=` + domain 隔离 + iframe/script 发布 |
| A-② / S2 | 管理群 IM 载体 | 前端管理群 channel 组件 + 后端虚拟 group |
| C-⑫ | Dream Engine 规则配置接入管理群 | dream_config_dialog 挂入管理群 bot |
| C-⑭ | 晨起推送 + /approve /edit /reject 实送达 | morning_push → 管理群 channel + 命令回归 |
| A-① | 注册接入独立 step | Wizard 前置 RegisterStep + 国家→合规模板映射 |
| A-③ / S6 | "一键对外" gate + publish 端点 | sandbox→prod 切换 + 签署 gate |

### P1（业务语义完整性）——5 项

| ID | 名称 |
|---|---|
| B-⑧ | Agent confidence-triggered HumanRequested |
| B-⑨ | 接管态 agent sidebar hint 回传 |
| B-⑪ / S5 | 平台监控事件流面板 |
| C-⑮ | 中风险提案二次确认 |
| C-⑯ | 灰度 baseline vs canary 双值对比 UI |
| S1 | 租户进程/DB 隔离 |
| S3 | operator-console IM 化形态评估 |

### P2（质量/细节）——5 项

| ID | 名称 |
|---|---|
| A-④ | 合规模板按 tenant.countries 过滤 |
| A-⑤ / S7 | 时间预算埋点 |
| A-⑥ | 团队邀请（5 人）流 |
| B-⑩ | Copilot 建议采纳/拒绝回执 |
| C-⑬ | memory_pool 7 天 TTL 淘汰 |

---

## 三、对 v3 gap 文档的勘误建议

v3（[`2026-04-15-prd-gap-v3.md`](2026-04-15-prd-gap-v3.md)）用模块 α-ζ 组织；HTML 已具象化为**三幕三视角九视图**。建议：

1. **把 v3 缺项重组为三幕坐标**——每项标注所属 Act/Step/View
2. **显式单列两个横向系统能力条目**（当前淹没在 β3/β4）：
   - **X-IM-Hub · 管理群 IM 载体**（跨 A② / C⑫ / C⑭，是多个核心流程的承载面）
   - **X-Tenant-SDK · 独立站浮窗多租户 SDK**（B⑦，商业闭环前置）
3. **增加"gate"类缺项**：注册 gate（A①）/ 开放前签署 gate（A③）/ 中风险二次确认 gate（C⑮）——这些是 PRD 显式 flow control 点，v3 未覆盖

---

## 四、后续行动建议

1. **第一波**（本周）：把上述 P0 六项补成 Phase 7 任务集（`2026-04-18-tasks.yaml`），接入现有 dev-loop pipeline
2. **第二波**：P1 五项作为 M7 质量门
3. **复核机制**：每次 HTML PRD 更新，本文档需同步更新 diff 章节

---

## 五、证据索引（关键 file:line）

### 现有实现
- [autoservice/onboarding.py](../../autoservice/onboarding.py) · tenant 生成 / upload / activate
- [autoservice/soul_generator.py](../../autoservice/soul_generator.py) · 4 角色 soul 生成
- [autoservice/compliance/compliance.py](../../autoservice/compliance/compliance.py) · 合规预检 16 条
- [autoservice/sim_customer.py](../../autoservice/sim_customer.py) · 虚拟预演
- [autoservice/triage.py](../../autoservice/triage.py) · 智能分流
- [autoservice/dream_config_dialog.py](../../autoservice/dream_config_dialog.py) · 4 参数对话配置
- [autoservice/memory_pool.py](../../autoservice/memory_pool.py) · 对话记忆池
- [autoservice/low_peak_scheduler.py](../../autoservice/low_peak_scheduler.py) · 低峰检测
- [autoservice/proposal_pipeline.py](../../autoservice/proposal_pipeline.py) · 提案生成
- [autoservice/morning_push.py](../../autoservice/morning_push.py) · 晨起推送聚合
- [autoservice/canary.py](../../autoservice/canary.py) · 灰度路由
- [autoservice/canary_monitor.py](../../autoservice/canary_monitor.py) · 5 指标监测
- [autoservice/plugins/squad_plugin.py](../../autoservice/plugins/squad_plugin.py) · 分队路由
- [frontend/apps/admin-portal/src/components/wizard/WizardTab.tsx](../../frontend/apps/admin-portal/src/components/wizard/WizardTab.tsx) · 5 步向导
- [frontend/apps/admin-portal/src/components/wizard/ChannelConfigStep.tsx](../../frontend/apps/admin-portal/src/components/wizard/ChannelConfigStep.tsx) · 渠道配置
- [frontend/apps/admin-portal/src/components/wizard/VirtualRehearsalStep.tsx](../../frontend/apps/admin-portal/src/components/wizard/VirtualRehearsalStep.tsx)
- [frontend/apps/admin-portal/src/components/wizard/SandboxReady.tsx](../../frontend/apps/admin-portal/src/components/wizard/SandboxReady.tsx)
- [frontend/apps/customer-chat/src/App.tsx](../../frontend/apps/customer-chat/src/App.tsx) · 硬编码 ws 地址
- [frontend/apps/operator-console/src/components/SquadPane.tsx](../../frontend/apps/operator-console/src/components/SquadPane.tsx) · 分队卡片
- [frontend/apps/operator-console/src/components/CopilotSidebar.tsx](../../frontend/apps/operator-console/src/components/CopilotSidebar.tsx) · Copilot 侧栏
- [frontend/apps/operator-console/src/components/HijackButton.tsx](../../frontend/apps/operator-console/src/components/HijackButton.tsx) · /hijack + /release
- [frontend/apps/operator-console/src/components/TakeoverIndicator.tsx](../../frontend/apps/operator-console/src/components/TakeoverIndicator.tsx) · 接管倒计时

### PRD 源
- [docs/prd/autoservice-full-journey.html](../prd/autoservice-full-journey.html) · 三幕三视角九视图

---

*2026-04-18 · 基于 Full-Journey HTML · 三幕 × 17 具体缺项 × 6 P0 + 7 P1 + 5 P2*
