# AutoService PRD 缺项补齐 — 任务列表

> 配套 `2026-04-14-prd-gap-checklist.md` · 每个任务关联缺项编号
> 按 Phase 分组，Phase 内按依赖序排列
> 标注: 🔧 纯代码 · 📐 设计+代码 · 🧪 验证/spike · 📝 配置/文档
> v5 更新: 纳入飞书 API 官方验证结论（详见 `2026-04-14-feishu-api-verification.md`），调整 T0.x spike 范围、T1.x 卡片约束、T2.7 占位续写方案、T3.2 话题群模式

---

## Phase 0 — 前置验证 (0.5-1 week)

> 目标: 实测飞书 thread / 卡片 PATCH / 话题群的 UI 体验和限额细节
> v5 更新: API 参数已通过文档验证确认存在 (`reply_in_thread:true`, `PATCH /im/v1/messages/:id`, `group_message_type:"thread"`)。spike 范围从"验证 API 是否存在"**降级为"验证实际行为和体验"**。

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T0.1 | **飞书 Thread UI/限额 spike** | 🧪 | C5, C6 | spike 报告 | v5 已确认 `reply_in_thread:true` 存在。剩余验证: ① 单主消息 thread 回复数上限 ② 桌面/移动客户端 thread UI 一致性 ③ thread 生命周期事件(删除/折叠)可否订阅 ④ `group_message_type:"thread"` 话题群的实际交互体验 |
| T0.2 | **卡片 PATCH 压测** | 🧪 | C4 | 压测脚本 `tests/e2e/feishu_card_stress.py` + 限额报告 | v5 已确认限速: 单消息 5 QPS, 全局 1000/分。实测: 真实网络下延迟分布、高并发场景是否稳定、推荐刷新间隔 |
| T0.3 | **卡片 PATCH 视觉验证** | 🧪 | B7 | 验证报告 | v5 已确认: **占位续写必须走卡片 PATCH**（PUT 仅支持 text/post）。实测: 卡片更新在桌面+移动端是否无闪烁/无二次通知/无滚动跳动 |
| T0.4 | **方案决策文档** | 📝 | C5 | `docs/plans/thread-spike-conclusion.md` | 基于 T0.1~T0.3 实测结论，确认 Copilot 方案 A (thread) + 占位续写方案 (卡片 PATCH) |

---

## Phase 1 — 基础框架 + 飞书能力接入 (2-3 weeks)

> 目标: 搭建对话状态机 + 事件总线 + 飞书卡片能力，为上层人机协作打地基

### 1.1 对话状态机

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T1.1 | **设计对话状态机** | 📐 | C1 | 设计文档 | 定义 6 个状态 + 转换条件 + 事件触发 |
| T1.2 | **实现 `autoservice/conversation.py`** | 🔧 | C1 | 模块代码 + 单元测试 | `Conversation` 类: state/assigned_agent/assigned_human/history；状态转换方法；持久化到 CRM SQLite (复用 `crm.py` conversations 表) |
| T1.3 | **接入 flows/ 声明式配置** | 🔧 | C1 | 流程加载逻辑 | 状态转换规则从 `.autoservice/flows/` YAML 加载，而非硬编码 |
| T1.4 | **集成到 channel_server** | 🔧 | C1 | channel_server 改造 | 每条消息经过状态机处理；`_chat_modes` 升级为 `Conversation` 实例 |

### 1.2 统一事件总线

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T1.5 | **实现 `autoservice/events.py`** | 🔧 | C2 | 模块代码 + 单元测试 | 进程内 pub/sub: `emit(event_type, payload)` + `on(event_type, callback)`；事件 schema: `{type, conversation_id, timestamp, payload}` |
| T1.6 | **状态机接入事件总线** | 🔧 | C1, C2 | 集成代码 | 每次状态转换自动 emit 事件 (`conversation.started`, `conversation.escalated`, `human.takeover` 等) |
| T1.7 | **飞书 Webhook 事件扩展** | 🔧 | C2 | channel_server 改造 | 订阅新事件类型: 消息已读、群成员变更、卡片按钮点击 |

### 1.3 飞书卡片能力接入

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T1.8 | **申请新增飞书应用权限** | 📝 | C4, C5 | 权限申请 | v5 已确认所需权限: `im:message:update` (PATCH+PUT), `im:chat:create` (建群), `im:chat.members:write_only` (加人), `approval:approval` (审批), `base:record:create` (Bitable)。thread 回复复用已有 `im:message:send_as_bot` |
| T1.9 | **实现飞书卡片构建器** | 🔧 | C4 | `channels/feishu/cards.py` | CardKit JSON 构建工具函数: 对话摘要卡、状态卡、告警卡模板。**v5 约束: 所有需后续更新的卡片 config 必须包含 `"update_multi": true`** |
| T1.10 | **实现飞书卡片 PATCH** | 🔧 | B7, C4 | channel_server 卡片更新方法 | v5 确认端点: `PATCH /im/v1/messages/:message_id`，仅限 interactive 类型。实现 `_patch_card(message_id, card_json)`。约束: 单消息 5 QPS, 14 天有效期, 30KB 大小限制 |
| T1.11 | **channel_server 增加 HTTP 端点** | 🔧 | C4 | FastAPI 子模块 (:9998) | 接收飞书卡片按钮回调 + 审批回调；路由到事件总线 |

### 1.4 快速胜利

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T1.12 | **情绪识别 prompt 扩展** | 🔧 | B8 | Skill prompt 改造 | 每条回复附带 `sentiment: positive/neutral/negative/angry`；情绪恶化时 emit `sentiment.degraded` 事件 |
| T1.13 | **管理群 `/review` 命令** | 🔧 | E3.2 | channel_server 命令扩展 | 返回昨日统计 (消息数/会话数/平均时长) 的飞书富文本消息 |

---

## Phase 2 — Agent 运行时 (2-4 weeks)

> 目标: 将单一 Agent 拆分为 4 个专精角色 + 快慢双模型

### 2.1 四角色 Agent 拆分

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T2.1 | **设计角色定义规范** | 📐 | B4 | 设计文档 + YAML schema | `agents/<role>/agent.yaml` 格式: model/skill/pool_config/trigger_conditions |
| T2.2 | **定义 4 个角色配置** | 📝 | B4 | 4 个 agent.yaml 文件 | 客服 (sonnet/customer-service)、翻译 (haiku/translate)、线索收集 (sonnet/marketing)、分流 (haiku/triage) |
| T2.3 | **实现角色路由器** | 🔧 | B4, B6 | `autoservice/agent_router.py` | 分流 Agent 作为入口：意图分类 → 路由到对应角色的 CCPool |
| T2.4 | **实现多 CCPool 实例管理** | 🔧 | B4 | cc_pool.py 扩展 | 支持按角色名注册和获取独立的 CCPool 实例；每角色独立 PoolConfig |
| T2.5 | **翻译 Agent 术语映射扩展** | 🔧 | B5 | 术语表扩展 | 从中/英双语扩展到覆盖 CJK + 欧洲主要语种的术语映射表 |

### 2.2 快慢双模型

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T2.6 | **实现 ModelRouter** | 🔧 | B7 | `autoservice/model_router.py` | 根据查询复杂度 (快模型预判) 选择 haiku 池 / sonnet 池 |
| T2.7 | **实现占位续写流程** | 🔧 | B7 | channel_server + cards.py 集成 | v5 确认: **必须走卡片 PATCH 路线**。流程: 快模型 → 发 interactive 卡片 (含 `update_multi:true`, 占位状态) → 慢模型完成 → `PATCH /im/v1/messages/:id` 更新卡片内容 (续写)；客户感知"一条完整回答" |
| T2.8 | **集成消息协议扩展** | 🔧 | A5 | channel_server 协议改造 | 新增消息类型: `update_message`, `card_update`；消息元数据增加 `conversation_id`, `state` |

### 2.3 管理群命令

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T2.9 | **实现 `/dispatch` 命令** | 🔧 | E3.2 | channel_server 命令 | `/dispatch <chat_id> <agent_role>` 指定角色接管对话 |
| T2.10 | **飞书 Bot 命令注册** | 📝 | E3.2 | 飞书开放平台配置 | 在飞书 Bot 配置中注册 /status, /dispatch, /review 的菜单化命令 |

---

## Phase 3 — 人机协作 MVP (3-5 weeks)

> 目标: 实现 Copilot 核心流程——分队频道 + 实时卡片 + 监管 + 角色翻转
> 前置: Phase 0 spike 已通过，确定方案 A (thread)

### 3.1 Agent 分队频道

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T3.1 | **设计 Squad 数据模型** | 📐 | C3 | 设计文档 + DB schema | `Squad {id, human_open_id, agent_roles[], feishu_chat_id, active_conversations[]}` |
| T3.2 | **实现程序化建群** | 🔧 | C3 | `channels/feishu/squad.py` | v5 确认: `POST /im/v1/chats` + `POST /im/v1/chats/:id/members`。**建议使用 `group_message_type:"thread"` 创建原生话题群**，所有消息天然话题化。初始 ≤50 用户 + 5 Bot |
| T3.3 | **实现分队注册管理** | 🔧 | C3 | autoservice/squad.py | 分队 CRUD + 人工-Agent 关联 + 持久化到 SQLite |

### 3.2 实时对话卡片

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T3.4 | **实现对话摘要卡片模板** | 🔧 | C4 | cards.py 卡片模板 | 显示: 客户名 + 类型 + 情绪 + 最新摘要 + "回复话题"入口 + 状态标签 |
| T3.5 | **实现卡片生命周期管理** | 🔧 | C4 | cards.py 管理逻辑 | 新对话 → 发卡片 → 事件驱动更新 → 结案关闭；card_id 追踪 |
| T3.6 | **事件驱动卡片刷新** | 🔧 | C4, C2 | 事件订阅集成 | 订阅 `conversation.*` 事件 → 聚合 (≥5s 间隔) → patch_card |

### 3.3 Copilot 模式 (thread 方案)

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T3.7 | **实现 thread 消息发送** | 🔧 | C5 | channel_server thread 方法 | v5 确认: `POST /im/v1/messages/:id/reply` + `reply_in_thread: true`，返回 `thread_id`。实现 `_send_thread_reply(parent_message_id, content)`。单群 5 QPS 限制需消息排队 |
| T3.8 | **实现 thread 事件订阅** | 🔧 | C5, C6 | channel_server 事件处理 | 识别 thread 内消息 → 区分"人工建议"vs"Agent 回复" → 转发给对应 CCPool |
| T3.9 | **实现 Copilot 协议** | 🔧 | C5, C6 | conversation.py Copilot 逻辑 | Agent driver: 生成草稿 → thread 内展示 → 人工建议 → Agent 采纳 → 发给客户 |

### 3.4 升级与角色翻转

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T3.10 | **实现 Agent @人工求助** | 🔧 | C7 | conversation.py 升级逻辑 | 触发条件匹配 (escalation.yaml) → thread 内 @客服 → 180s 计时器启动 |
| T3.11 | **实现超时回退** | 🔧 | C7 | 计时器逻辑 | 180s 未响应 → 状态回退 AgentHandling → 向客户发安抚消息 → emit `human.timeout` |
| T3.12 | **实现 `/hijack` 命令** | 🔧 | C8 | 命令解析 + 状态转换 | thread 内输入 `/hijack` → 状态机转 HumanTakeover → Agent 切只读建议 |
| T3.13 | **实现 Agent 副驾驶模式** | 🔧 | C9 | conversation.py 副驾驶逻辑 | HumanTakeover 状态下: Agent 在 thread 内只发建议 (标记为 `[AI建议]`) + 接管次数计入统计 |

### 3.5 SLA 监控

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T3.14 | **实现指标采集** | 🔧 | E3.3 | `autoservice/metrics.py` | 采集: 首屏应答时间、人工接单等待、首次回复时间；基于事件总线 |
| T3.15 | **实现 SLA 告警** | 🔧 | E3.3 | metrics.py 告警逻辑 | 5 分钟滚动窗口检测 → 超阈值 → 飞书管理群加急消息推送 |

---

## Phase 4 — 可观测 & 提案 (3-5 weeks)

> 目标: 商户可见运营数据 + Dream Engine 审核流程 MVP

### 4.1 运营仪表盘

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T4.1 | **创建 Bitable 指标模板** | 📝 | E3.1 | 飞书多维表格模板 | 表: 日指标 (接管数/CSAT/升级转结案率/首回/接单等待/会话时长) |
| T4.2 | **实现 Bitable 指标写入** | 🔧 | E3.1 | `autoservice/dashboard.py` | 定时 (每小时) 聚合 metrics → `bitable.v1.app_table_record.create` 写入 |
| T4.3 | **管理群仪表盘卡片** | 🔧 | E3.1 | cards.py 仪表盘卡片模板 | 每日定时推送: 4 Agent 状态 + 3 核心指标 + 趋势箭头 |

### 4.2 Dream Engine 提案审核 MVP

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T4.4 | **实现对话记忆池写入** | 🔧 | D2 | session.py 扩展 | 每轮对话完整记录 (含意图/情绪/KB 命中/结案状态) 写入 `.autoservice/database/memory_pool.db` |
| T4.5 | **实现 `/rules show\|edit` 命令** | 🔧 | D1 | channel_server 命令 | 管理群内查看/修改学习规则 (触发时机/覆盖范围/风险阈值/灰度策略) |
| T4.6 | **实现提案生成 pipeline** | 📐 | D4, D5 | `autoservice/dream_engine.py` | LLM 回放记忆池 → 抽取话术/FAQ 改进建议 → 生成提案 JSON |
| T4.7 | **实现提案审核卡片** | 🔧 | D5 | cards.py 提案卡片 | 卡片含: 提案来源对话、影响范围、风险等级 + ✓通过/✎修改/✗驳回 按钮 |
| T4.8 | **实现飞书审批流集成** | 🔧 | D5 | `channels/feishu/approval.py` | v5 确认: 模板 `POST /approval/v4/approvals` + 实例 `POST /approval/v4/instances` (100/分限速)。节点类型 AND/OR/SEQUENTIAL。流程: 定义审批模板 → 创建实例 → 监听回调 → 通过后进入灰度队列 |

### 4.3 部署编排

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T4.9 | **编写 docker-compose 多租户模板** | 📝 | X7 | `templates/docker-compose.tmpl.yaml` | 每租户: channel_server + cc_pool + web 三容器 |
| T4.10 | **自助上线简化版** | 🔧 | E1.1 | 管理群对话式引导 | 管理群内 @Bot → 对话式采集公司名+上传资料 → 调用 `create-tenant.sh` + `kb_ingest.py` → 返回沙箱链接 |

---

## Phase 5 — 产品化 (6-10 weeks)

> 目标: Dream Engine 完整版 + 合规 + 计费 + 多渠道

### 5.1 Dream Engine 完整版

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T5.1 | **实现低峰检测调度器** | 🔧 | D3 | dream_engine.py 调度 | 监测 QPS (30 分钟均值 < 白天 20%) → 自动触发回放 pipeline |
| T5.2 | **实现灰度路由** | 🔧 | D6 | `autoservice/canary.py` | 提案通过后: 5% 流量使用新话术 → 24h 指标无下跌 → 自动升阶 25% → 100% |
| T5.3 | **实现 `/rollback` 命令** | 🔧 | D7 | channel_server 命令 | `/rollback <proposal_id>` → 立即撤回灰度 → emit `proposal.rollback` → 管理群确认 |
| T5.4 | **实现晨起推送** | 🔧 | D5 | dream_engine.py 定时任务 | 每日 09:00 前: 聚合昨夜提案 → 飞书管理群推送卡片列表 |

### 5.2 合规引擎

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T5.5 | **设计合规规则库** | 📐 | E1.4 | 规则库 schema + 预置规则 | GDPR/CCPA/个保法 三套检查项；按商户目标客户地区自动匹配 |
| T5.6 | **实现合规预检引擎** | 🔧 | E1.4 | `autoservice/compliance.py` | 扫描商户配置 → 输出检查结果 + 风险等级；沙箱不阻塞，对外开放前必须全部通过 |
| T5.7 | **实现合规策略模板下发** | 🔧 | E1.4 | 合规模板 YAML | 平台预置 + 商户叠加；Dream Engine 学习规则受合规约束 |

### 5.3 计费引擎

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T5.8 | **实现接管次数统计** | 🔧 | X8 | metrics.py 扩展 | 每次 HumanTakeover 状态转换计入 "接管次数"；按租户按月聚合 |
| T5.9 | **实现阶梯计费计算** | 🔧 | X8 | `autoservice/billing.py` | 配置阶梯价格表 → 月末计算账单 → 输出 JSON |
| T5.10 | **实现 CSAT 采集** | 🔧 | X8 | 结案后评分卡片 | 对话结案 → 飞书卡片推送评分 (1-5 星) → 写入 metrics |

### 5.4 多渠道扩展

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T5.11 | **抽象 ChannelAdapter 接口** | 📐 | A5, A7 | `socialware/channel.py` (L1 提取) | 统一接口: connect/send/receive/update/react；Feishu/Web 各实现 |
| T5.12 | **飞书/Lark 双端适配** | 🔧 | A7 | channels/feishu/ 改造 | host/auth 配置化；共用 90% 代码 |
| T5.13 | **Slack 适配器** | 🔧 | A7 | `channels/slack/` | 实现 ChannelAdapter 接口的 Slack Bot 版本 |

---

## 任务统计

| Phase | 任务数 | 预估工期 | 关键产出 |
|-------|--------|---------|---------|
| Phase 0 | 4 | 0.5-1 周 | thread spike 结论 |
| Phase 1 | 13 | 2-3 周 | conversation.py + events.py + cards.py + HTTP 端点 |
| Phase 2 | 10 | 2-4 周 | agent_router.py + model_router.py + 4 角色配置 |
| Phase 3 | 15 | 3-5 周 | squad.py + Copilot thread + 角色翻转 + SLA |
| Phase 4 | 10 | 3-5 周 | dashboard.py + dream_engine.py MVP + docker-compose |
| Phase 5 | 13 | 6-10 周 | 灰度 + 合规 + 计费 + 多渠道 |
| **合计** | **65** | **11-19 周** | |

---

## 双工作流并行编排

### 设计原则

两条工作流按**职责边界**划分：
- **工作流 α "引擎层"** — 对话状态机、事件总线、Agent 角色拆分、双模型路由、协议扩展、Dream Engine 后端、计费/合规
- **工作流 β "交互层"** — 飞书能力接入（卡片/thread/建群/命令）、分队频道、Copilot UI、SLA 告警、仪表盘、自助上线

两条线在 **4 个同步点** 交汇，交汇后各自继续推进。

### 全局视图

```
周次   0   1   2   3   4   5   6   7   8   9  10  11  12  ...
      ├───┤───────────┤───────────┤───────────┤───────────┤──────────
      │P0 │  Phase 1  │  Phase 2  │  Phase 3  │  Phase 4  │ Phase 5
      │共 │           │           │           │           │
      │享 │  α 状态机  │  α 角色   │  α 升级   │  α Dream  │ α 灰度
      │   │  α 事件    │  α 双模型  │  α 翻转   │  α 提案   │ α 合规
      │   │  ─────────│──────⇣────│───⇣───────│───────────│ α 计费
      │   │  β 卡片    │  β 命令   │  β 分队   │  β 仪表盘  │ β 多渠道
      │   │  β PATCH   │  β Bot   │  β thread  │  β 上线   │
      │   │  β HTTP    │  β 协议   │  β SLA    │  β 编排   │
      │   │           │           │           │           │
      │   │     ⇣S1   │     ⇣S2   │     ⇣S3   │     ⇣S4   │
      同步点:    S1         S2         S3         S4
```

---

### 工作流 α · 引擎层

> 职责: 业务逻辑核心 — 状态管理、Agent 编排、模型路由、Dream Engine pipeline
> 技术栈: Python (autoservice/)、SQLite、CCPool、LLM prompt

#### α Phase 0 (共享)

| # | 任务 | 说明 |
|---|------|------|
| T0.3 | PATCH message 视觉验证 | α 主导，验证占位续写的技术可行性 |
| T0.4 | 方案决策文档 (参与) | α 提供状态机视角的约束输入 |

#### α Phase 1 (周 1-3): 状态机 + 事件总线

| # | 任务 | 依赖 | 说明 |
|---|------|------|------|
| T1.1 | 设计对话状态机 | — | 定义 6 状态 + 转换规则 |
| T1.2 | 实现 `conversation.py` | T1.1 | 核心模块：状态/角色/历史，持久化到 CRM |
| T1.3 | 接入 flows/ 声明式配置 | T1.2 | 状态转换规则从 YAML 加载 |
| T1.5 | 实现 `events.py` | — | 与 T1.1 并行启动 |
| T1.6 | 状态机接入事件总线 | T1.2, T1.5 | 状态转换自动 emit 事件 |
| T1.12 | 情绪识别 prompt 扩展 | — | 快速胜利，与 T1.1 并行 |

**α Phase 1 产出**: `conversation.py` + `events.py`，状态机可运行、事件可订阅

#### ⇣ 同步点 S1 — α 向 β 交付事件总线 API

> β 拿到 `events.py` 的 `emit()` / `on()` 接口后，才能实现"事件驱动卡片刷新"(T3.6)。
> α 拿到 β 的卡片构建器 (T1.9) 后，才能在 Phase 2 做占位续写集成 (T2.7)。

#### α Phase 2 (周 3-6): 四角色 + 双模型

| # | 任务 | 依赖 | 说明 |
|---|------|------|------|
| T2.1 | 设计角色定义规范 | — | agent.yaml schema |
| T2.2 | 定义 4 个角色配置 | T2.1 | 4 个 YAML 文件 |
| T2.4 | 多 CCPool 实例管理 | T2.2 | 按角色名注册独立池 |
| T2.3 | 角色路由器 | T2.4 | 分流 Agent → 路由到对应池 |
| T2.6 | ModelRouter | T2.4 | 快/慢池选择逻辑 |
| T2.7 | 占位续写流程 | T2.6, **β T1.10** | 快模型→流式卡片→慢模型→patch_card |
| T2.5 | 翻译 Agent 术语映射 | — | 与 T2.1 并行 |
| T2.8 | 消息协议扩展 | T1.4 (β) | 新增 update_message/card_update 类型 |

**α Phase 2 产出**: `agent_router.py` + `model_router.py`，4 角色独立运行，占位续写可用

#### ⇣ 同步点 S2 — α 向 β 交付状态机集成到 channel_server

> β 开始做分队/thread 前，需要 channel_server 已经用 `Conversation` 对象管理每个对话的状态。
> α 在 Phase 1 的 T1.4 (集成到 channel_server) 完成后 β 才能感知对话状态。

#### α Phase 3 (周 6-9): 升级 + 角色翻转逻辑

| # | 任务 | 依赖 | 说明 |
|---|------|------|------|
| T3.10 | Agent @人工求助逻辑 | T1.2 | 触发条件匹配 + 状态转换到 HumanAlert |
| T3.11 | 超时回退逻辑 | T3.10 | 180s timer + 状态回退 AgentHandling |
| T3.12 | `/hijack` 状态转换 | T1.2 | HumanTakeover 状态处理 |
| T3.13 | Agent 副驾驶模式逻辑 | T3.12 | 只读建议模式 + 接管次数统计 |
| T3.14 | 指标采集 `metrics.py` | T1.5 | 基于事件总线采集 SLA 指标 |

**α Phase 3 产出**: 升级/翻转的**状态逻辑**完成（不含飞书 UI 交互，那是 β 的事）

#### ⇣ 同步点 S3 — α 升级逻辑 + β thread UI 联调

> α 的 `T3.10~T3.13` 输出状态转换事件，β 的 `T3.7~T3.9` 在 thread 中渲染 UI 效果。
> 两边需要联调: 状态转换 → emit 事件 → β 订阅事件 → thread 内发对应消息。

#### α Phase 4 (周 9-12): Dream Engine + 提案后端

| # | 任务 | 依赖 | 说明 |
|---|------|------|------|
| T4.4 | 对话记忆池写入 | T3.14 | session 扩展，写入 memory_pool.db |
| T4.6 | 提案生成 pipeline | T4.4 | LLM 回放 → 抽取建议 → 生成提案 JSON |
| T4.5 | `/rules show\|edit` 后端 | — | rules.py 扩展 |

**α Phase 4 产出**: `dream_engine.py` 可生成提案 JSON

#### ⇣ 同步点 S4 — α 提案 JSON + β 审批卡片联调

#### α Phase 5 (周 12+): 灰度 + 合规 + 计费

| # | 任务 | 依赖 | 说明 |
|---|------|------|------|
| T5.1 | 低峰检测调度器 | T4.4 | QPS 监测 + 定时触发 |
| T5.2 | 灰度路由 `canary.py` | T4.6 | 5%→25%→100% 渐进 |
| T5.3 | `/rollback` 后端逻辑 | T5.2 | 提案状态管理 + 撤回 |
| T5.5 | 合规规则库设计 | — | GDPR/CCPA/个保法检查项 |
| T5.6 | 合规预检引擎 | T5.5 | compliance.py |
| T5.7 | 合规策略模板下发 | T5.6 | 平台预置 + 商户叠加 |
| T5.8 | 接管次数统计 | T3.13 | metrics.py 扩展 |
| T5.9 | 阶梯计费计算 | T5.8 | billing.py |
| T5.11 | ChannelAdapter 接口抽象 | — | socialware/channel.py L1 提取 |

---

### 工作流 β · 交互层

> 职责: 飞书能力接入、用户可见的交互界面、运营工具
> 技术栈: 飞书 Open API (lark_oapi)、CardKit JSON、FastAPI、Bitable

#### β Phase 0 (共享)

| # | 任务 | 说明 |
|---|------|------|
| T0.1 | 飞书 Thread API spike | β 主导 |
| T0.2 | 流式卡片刷新压测 | β 主导 |
| T0.4 | 方案决策文档 (参与) | β 提供飞书 API 约束输入 |

#### β Phase 1 (周 1-3): 飞书卡片 + HTTP 端点

| # | 任务 | 依赖 | 说明 |
|---|------|------|------|
| T1.8 | 申请飞书应用权限 | — | 第一天就提交，不阻塞其他工作 |
| T1.9 | 飞书卡片构建器 `cards.py` | T0.2 结论 | 对话摘要卡、状态卡、告警卡模板 |
| T1.10 | 飞书消息更新 (PATCH/patch_card) | T0.3 结论 | channel_server 新增方法 |
| T1.11 | channel_server HTTP 端点 | — | FastAPI 子模块 (:9998) 接收卡片/审批回调 |
| T1.7 | 飞书 Webhook 事件扩展 | — | 新增事件订阅: 已读/群变更/卡片点击 |
| T1.4 | 状态机集成到 channel_server | **α T1.2** | 消息过状态机；需等 α 交付 conversation.py |
| T1.13 | 管理群 `/review` 命令 | — | 与 T1.9 并行；富文本回复 |

**β Phase 1 产出**: `cards.py` + PATCH 能力 + HTTP 回调端点，飞书卡片可发送和更新

#### ⇣ 同步点 S1 (同上)

#### β Phase 2 (周 3-6): 命令 + Bot 注册

| # | 任务 | 依赖 | 说明 |
|---|------|------|------|
| T2.9 | `/dispatch` 命令 | T1.4 | 指定角色接管对话 |
| T2.10 | 飞书 Bot 命令注册 | T1.8 权限到位 | 开放平台菜单化注册 |

> β Phase 2 任务较少，**剩余时间提前启动 Phase 3 的 T3.1~T3.3 分队频道**。

#### β Phase 3 (周 5-9): 分队 + 卡片 + Copilot thread

| # | 任务 | 依赖 | 说明 |
|---|------|------|------|
| T3.1 | 设计 Squad 数据模型 | — | 可在 Phase 2 剩余时间提前启动 |
| T3.2 | 程序化建群 | T1.8 权限 | im.v1.chat.create |
| T3.3 | 分队注册管理 | T3.1 | CRUD + 持久化 |
| T3.4 | 对话摘要卡片模板 | T1.9 | 显示: 客户名/情绪/摘要/"回复话题"入口 |
| T3.5 | 卡片生命周期管理 | T3.4 | 新对话→发卡片→更新→结案关闭 |
| T3.6 | 事件驱动卡片刷新 | T3.5, **α T1.5** | 订阅 conversation.* 事件 → 聚合 → patch_card |
| T3.7 | thread 消息发送 | T0.1 结论 | _send_thread_reply() |
| T3.8 | thread 事件订阅 | T3.7 | 区分人工建议 vs Agent 回复 |
| T3.9 | Copilot 协议 (交互侧) | T3.8, **α T1.2** | 草稿展示 → 人工建议 → 转发给 Agent |
| T3.15 | SLA 告警推送 | **α T3.14** | 超阈值 → 飞书管理群加急消息 |

**β Phase 3 产出**: 分队频道可用，卡片实时刷新，thread Copilot 可交互

#### ⇣ 同步点 S3 (同上)

#### β Phase 4 (周 9-12): 仪表盘 + 审批 + 上线

| # | 任务 | 依赖 | 说明 |
|---|------|------|------|
| T4.1 | 创建 Bitable 指标模板 | — | 飞书多维表格模板 |
| T4.2 | Bitable 指标写入 | T4.1, **α T3.14** | 定时聚合 metrics → API 写入 |
| T4.3 | 管理群仪表盘卡片 | T1.9 | 每日定时推送核心指标 |
| T4.7 | 提案审核卡片 | T1.9 | ✓/✎/✗ 按钮卡片模板 |
| T4.8 | 飞书审批流集成 | T1.11 | 审批模板→创建实例→监听回调 |
| T4.9 | docker-compose 多租户模板 | — | 每租户三容器 |
| T4.10 | 自助上线简化版 | T3.2 | 管理群对话式引导 + create-tenant.sh |

**β Phase 4 产出**: Bitable 仪表盘可查，提案审核卡片可交互，自助上线 MVP

#### β Phase 5 (周 12+): 多渠道 + CSAT

| # | 任务 | 依赖 | 说明 |
|---|------|------|------|
| T5.4 | 晨起推送 | **α T4.6** | 定时聚合提案 → 飞书管理群卡片列表 |
| T5.10 | CSAT 评分卡片 | T1.9 | 结案后推送评分卡 (1-5 星) |
| T5.12 | 飞书/Lark 双端适配 | **α T5.11** | host/auth 配置化 |
| T5.13 | Slack 适配器 | **α T5.11** | 新渠道 ChannelAdapter 实现 |

---

### 并行甘特图

```
周    0    1    2    3    4    5    6    7    8    9   10   11   12+
     ┌──┐
P0   │共│ T0.1~T0.4
     └──┘
      ⇣
     ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────
α    │ T1.1 状态机  │  │ T2.1 角色设计│  │ T3.10 @人工  │  │ T4.4 记忆池  │  │ T5.1
引   │ T1.2 conv   │  │ T2.2 4角色   │  │ T3.11 超时   │  │ T4.6 提案    │  │ T5.2
擎   │ T1.3 flows  │  │ T2.4 多CCPool│  │ T3.12 hijack │  │ T4.5 rules   │  │ T5.5
层   │ T1.5 events │  │ T2.3 路由    │  │ T3.13 副驾驶 │  │              │  │ T5.8
     │ T1.6 集成   │  │ T2.6 Model   │  │ T3.14 指标   │  │              │  │ T5.9
     │ T1.12 情绪  │  │ T2.7 占位⇡   │  │              │  │              │  │ T5.11
     └──────⇣──────┘  └──────⇣──────┘  └──────⇣──────┘  └──────⇣──────┘  └──────
           S1              S2              S3              S4
     ┌──────⇣──────┐  ┌──────⇣──────┐  ┌──────⇣──────┐  ┌──────⇣──────┐  ┌──────
β    │ T1.8 权限   │  │ T2.9 dispatch│ │ T3.1 Squad  │  │ T4.1 Bitable │  │ T5.4
交   │ T1.9 cards  │  │ T2.10 Bot注册│ │ T3.2 建群    │  │ T4.2 写入    │  │ T5.10
互   │ T1.10 PATCH │  │ (提前启动⇣)  │ │ T3.4 卡片    │  │ T4.3 日推    │  │ T5.12
层   │ T1.11 HTTP  │  │ T3.1 Squad⇡ │ │ T3.6 刷新⇡   │  │ T4.7 审核卡  │  │ T5.13
     │ T1.7 事件   │  │ T3.3 管理   │  │ T3.7 thread  │  │ T4.8 审批流  │  │
     │ T1.4 集成⇡  │  │              │  │ T3.9 Copilot⇡│ │ T4.10 上线  │  │
     │ T1.13 review│  │              │  │ T3.15 SLA⇡   │  │ T4.9 编排   │  │
     └─────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  └──────

⇡ = 依赖对方工作流的交付件     S1~S4 = 同步点
```

---

### 同步点详细说明

| 同步点 | 时间 | α 交付给 β | β 交付给 α | 联调内容 |
|--------|------|-----------|-----------|---------|
| **S1** | 周 3 | `events.py` API (`emit`/`on`)；`conversation.py` 可调用 | `cards.py` 卡片构建器；`_patch_message` 方法 | α 状态转换 → emit → β 卡片刷新（冒烟测试） |
| **S2** | 周 5 | `conversation.py` 集成到 channel_server（T1.4 完成） | `/dispatch` 命令（T2.9）可触发角色路由 | 端到端: 消息进入 → 分流 → 角色池 → 回复 → 占位续写 |
| **S3** | 周 8 | T3.10~T3.13 的状态转换事件 | T3.7~T3.9 的 thread 交互 | 端到端: Agent @人工 → thread 通知 → 人工建议 → Agent 采纳 → /hijack → 角色翻转 |
| **S4** | 周 11 | T4.6 提案 JSON | T4.7~T4.8 审核卡片+审批流 | 端到端: 提案生成 → 卡片推送 → 审核 → 灰度/回滚 |

---

### 任务分配汇总

| 工作流 | Phase 0 | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 | 合计 |
|--------|---------|---------|---------|---------|---------|---------|------|
| **α 引擎层** | 2 | 6 | 7 | 5 | 3 | 9 | **32** |
| **β 交互层** | 3 | 7 | 3→提前做 P3 | 10 | 7 | 4 | **33** |
| **合计** | 4(去重) | 13 | 10 | 15 | 10 | 13 | **65** |

### 并行效率分析

| 指标 | 串行执行 | 双流并行 | 说明 |
|------|---------|---------|------|
| 总工期 | 11-19 周 | **8-14 周** | 压缩 ~25-30% |
| 关键路径 | T1.2→T1.6→T3.6→T3.10→T3.12→T3.13 | **α: T1.2→T2.4→T2.6→T3.10→T3.12** | α 关键路径 ~7-10 周 |
| | | **β: T0.1→T1.9→T3.4→T3.7→T3.9** | β 关键路径 ~6-9 周 |
| 等待浪费 | 0 (但总时间长) | S1~S4 各有 0-2 天等待窗口 | β Phase 2 可提前启动 Phase 3 填补 |
| 联调风险 | 低 | S3 (升级+thread 联调) 复杂度最高 | 预留 S3 后 2 天 buffer |

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| T0.1 thread spike UI 不可接受 | β Phase 3 需改用 H5 方案，延长 2-3 周 | v5 已确认 API 存在，spike 仅验证 UI 体验；风险降低 |
| 飞书应用权限审批延迟 (T1.8) | 阻塞 β T1.9~T1.11 全部卡片功能 | 第一天就提交申请；v5 已列出完整权限清单 |
| S1 同步延迟（α 状态机晚交付） | β 卡片刷新无事件可订阅，Phase 3 推迟 | α Phase 1 的 T1.5 事件总线优先于 T1.3 flows 接入 |
| S3 联调复杂度高 | 升级+thread 交互链路长，bug 面大 | S3 前双方各自做 mock 测试；预留 2 天联调 buffer |
| CC Pool 在多角色场景下资源消耗大 | 4 角色 × min_size 实例 = 预热成本高 | 分流 Agent (haiku) 常驻；其余按需启动 (min_size=0) |
| Dream Engine 提案质量差 (T4.6) | 商户失去信任 | 5% 灰度起步 + 人工审核兜底 |

---

*基于 PRD v1.0 + roadmap v5 + gap checklist + 飞书 API 验证 · 2026-04-14*
