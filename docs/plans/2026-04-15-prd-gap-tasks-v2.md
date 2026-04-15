# AutoService PRD 任务列表 — v2

> 2026-04-15 · 基于 `2026-04-15-prd-gap-v2.md` 的协同开发任务列表
> 取代 `2026-04-14-prd-gap-tasks.md` (v1, 65 任务) 作为当前基线
> **78 个任务**（v1 65 保留 61 + 新增 13 + 替换 4）· 双工作流并行 · 6 个同步点
> 标注: 🔧 纯代码 · 📐 设计+代码 · 🧪 验证/spike · 📝 配置/文档 · 💼 商务

**上游依据**:
- PRD: [`docs/prd/AutoService-PRD.md`](../prd/AutoService-PRD.md) v1.0 (2026-04-15)
- Stories: [`docs/prd/AutoService-UserStories.md`](../prd/AutoService-UserStories.md)
- Gap 分析 v2: [`2026-04-15-prd-gap-v2.md`](2026-04-15-prd-gap-v2.md)
- 飞书 API: [`2026-04-14-feishu-api-verification.md`](2026-04-14-feishu-api-verification.md)

---

## 〇、相对 v1 的变化

| 类型 | 任务 ID | 说明 |
|---|---|---|
| **新增 Phase** | Phase -1 | 商务前置（与开发并行） |
| **新增** | T0.0, T0.0a | 飞书/Lark 权限审批提交（商务线） |
| **替换** | T0.3 → T0.3' | 技术可行性已关闭，降级为纯视觉验证 |
| **新增** | T1.2a | Conversation 超时调度器 |
| **新增** | T1.10a | `CardRefreshCoalescer` 群级限频聚合 |
| **新增** | T1.10b | 卡片 14 天换卡机制 |
| **替换** | T2.5 → T2.5a/b/c | 22 语种术语表 + prompt 注入 + 商户覆盖 |
| **新增** | T2.6a | FastClassifier intent schema |
| **新增** | T3.14a | `SLAAggregator` 环形 buffer |
| **替换** | E1.3 原占位 → T4.10a/b/c | 虚拟客户预演 generate + UI + few-shot 注入 |
| **新增** | T5.2a | 灰度恶化自动告警 |
| **新增** | T5.5a/b | 16 条合规规则 YAML + 补救指南 |
| **细化** | T1.1, T1.2, T2.6, T2.7, T3.4, T3.8, T3.9, T3.11, T3.14, T3.15, T5.2, T5.3 | 按 gap-v2 §3 深化验收标准 |

---

## 一、Phase -1 · 商务前置（周 -2 至周 0，与 Phase 0 并行）

> 目标: 飞书/Lark 应用商店审批提前启动，避免阻塞 Phase 1 的卡片/建群/审批能力
> Owner: 项目经理 + 商务对接人（非开发）

| # | 任务 | 类型 | 关联 gap-v2 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T0.0 | **飞书开放平台权限审批提交** | 💼 | §1.2 | 审批单号 | 一次性提交全部 6 个新增权限: `im:message:update`, `im:chat:create`, `im:chat.members:write_only`, `approval:approval`, `base:record:create`, `im:message.reactions:write_only`；周 0 前至少 3 个权限通过 |
| T0.0a | **Lark 国际版权限审批提交** | 💼 | §1.2 | 审批单号 | 同上，针对 Lark 独立流程 |
| T0.0b | **MVP v1 白名单机制就绪** | 📝 | §1.2 | 开发者后台配置 | 自建应用模式，仅限 ≤5 个内测租户；v2 上架商店前的过渡方案 |

**与主线关系**: 不计入开发关键路径；T1.8 (Phase 1) 将变为"验证权限生效"而非"申请权限"。

---

## 二、Phase 0 · 前置验证（周 0，0.5-1 周）

> 目标: 实测飞书 UI 体验（技术可行性已由 gap-v2 §1.1 关闭）

| # | 任务 | 类型 | 关联缺项 | 产出 | 验收标准 |
|---|------|------|---------|------|---------|
| T0.1 | **飞书 Thread UI/限额 spike** | 🧪 | C5, C6 | spike 报告 | 实测: ① 单主消息 thread 回复数上限 ② 桌面/移动客户端 thread UI 一致性 ③ thread 生命周期事件可否订阅 ④ `group_message_type:"thread"` 话题群交互体验 |
| T0.2 | **卡片 PATCH 压测** | 🧪 | C4 | 压测脚本 + 限额报告 | 实测真实网络延迟分布，验证 gap-v2 §1.1 的 250ms/500ms 限频策略可行性 |
| T0.3' | **卡片 PATCH 客户端视觉验证** | 🧪 | B7 | 视觉验证报告 | 实测: 卡片更新在桌面+移动端是否无闪烁/无二次通知/无滚动跳动。**技术可行性已关闭，仅做视觉验证** |
| T0.4 | **方案决策文档** | 📝 | 全部 | `thread-spike-conclusion.md` | 基于 T0.1~T0.3' 实测结论，确认 Copilot 方案 A (thread) + 占位续写方案 (卡片 PATCH + Coalescer) |

---

## 三、Phase 1 · 基础框架 + 飞书能力（周 1-3，2-3 周）

### 1.1 对话状态机

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T1.1 | **设计对话状态机** | 📐 | C1 / gap-v2 §3.1 | 设计文档 | **7 状态**（新增 Closed）+ 每态 SLA + 超时行为矩阵（见 gap-v2 §3.1 表） |
| T1.2 | **实现 `autoservice/conversation.py`** | 🔧 | C1 | 模块代码 + 单元测试 | `Conversation` 类含字段: `state`, `state_entered_at`, `escalation_deadline`, `card_id`, `thread_id`, `pending_queries[]`；持久化到 crm.conversations |
| **T1.2a** | **超时调度器**（新增） | 🔧 | gap-v2 §3.1 | `Conversation.check_timeouts()` | 每秒轮询所有 active conversations，命中 `state_entered_at + sla` 则触发 timeout 事件 |
| T1.3 | **接入 flows/ 声明式配置** | 🔧 | C1 | 流程加载逻辑 | 状态转换规则从 `.autoservice/flows/*.yaml` 加载 |
| T1.4 | **集成到 channel_server** | 🔧 | C1 | channel_server 改造 | 每条消息经过状态机处理；`_chat_modes` 升级为 `Conversation` 实例 |

### 1.2 事件总线

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T1.5 | **实现 `autoservice/events.py`** | 🔧 | C2 | 模块代码 + 单元测试 | 进程内 pub/sub: `emit/on`；事件 schema: `{type, conversation_id, timestamp, payload}` |
| T1.6 | **状态机接入事件总线** | 🔧 | C1, C2 | 集成代码 | 10 个事件按 gap-v2 §2.3 埋点表发出 |
| T1.7 | **飞书 Webhook 事件扩展** | 🔧 | C2 | channel_server 改造 | 订阅: 消息已读、群成员变更、卡片按钮点击、审批回调 |

### 1.3 飞书卡片能力

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T1.8 | **验证飞书应用权限生效** | 📝 | C4, C5 | 权限验证报告 | 检查 T0.0 申请的权限已全部生效；若未全部通过，按 §1.2 降级方案执行 |
| T1.9 | **飞书卡片构建器** | 🔧 | C4 | `channels/feishu/cards.py` | CardKit JSON 构建器: 对话摘要卡（5 状态, 见 gap-v2 §3.3）、告警卡、审核卡；所有需后续更新的卡片强制包含 `"update_multi": true` |
| T1.10 | **飞书卡片 PATCH 基础实现** | 🔧 | B7, C4 | `_patch_card(message_id, card_json)` | 封装 `PATCH /im/v1/messages/:id`；异常处理（404/429/超 14 天） |
| **T1.10a** | **`CardRefreshCoalescer`**（新增） | 🔧 | gap-v2 §1.1 | 群级限频聚合器 | 同群内所有 PATCH 进入队列；500ms 滑窗合并；≥200ms 间隔；全局 ≤4 QPS；token-diff <threshold 跳过 |
| **T1.10b** | **卡片 14 天换卡机制**（新增） | 🔧 | gap-v2 §1.1 | `CardLifecycleManager` | 对话超过 12 天仍活跃 → 自动 close 老卡片 + 发新卡；`Conversation.card_id` 更新 |
| T1.11 | **channel_server HTTP 端点** | 🔧 | C4 | FastAPI 子模块 (:9998) | 接收卡片按钮回调 + 审批回调；路由到事件总线 |

### 1.4 快速胜利

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T1.12 | **情绪识别 prompt 扩展** | 🔧 | B8 | Skill prompt 改造 | 每条回复附带 `sentiment`；情绪恶化时 emit `sentiment.degraded` |
| T1.13 | **管理群 `/review` 命令** | 🔧 | E3.2 | channel_server 命令 | 返回昨日统计的飞书富文本消息 |

---

## 四、Phase 2 · Agent 运行时（周 3-6，2-4 周）

### 2.1 四角色 Agent

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T2.1 | **设计角色定义规范** | 📐 | B4 | 设计文档 + YAML schema | `agents/<role>/agent.yaml`: model/skill/pool_config/trigger_conditions |
| T2.2 | **定义 4 个角色配置** | 📝 | B4 | 4 份 agent.yaml | 客服 (sonnet)、翻译 (haiku)、线索 (sonnet)、分流 (haiku) |
| T2.3 | **角色路由器** | 🔧 | B4, B6 | `autoservice/agent_router.py` | 分流 Agent 作为入口；意图 → 路由目标角色池 |
| T2.4 | **多 CCPool 实例管理** | 🔧 | B4 | cc_pool.py 扩展 | 按角色独立池；分流池常驻 (min_size≥1)，其余按需 (min_size=0) |

### 2.2 多语言术语（gap-v2 §2.4 细化）

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| **T2.5a** | **22 语种术语 YAML**（替换原 T2.5） | 📝 | X6, B5 | `autoservice/i18n/terms/<lang>.yaml` × 22 | 22 语种 × 150 核心术语 = 3300 条；来源 IATE/MS Terminology |
| **T2.5b** | **翻译 Agent prompt 注入**（新增） | 🔧 | B5 | `translate_agent.py` | 根据客户语言动态加载术语表 → 注入 system prompt 前缀；token 预算 <2k |
| **T2.5c** | **商户术语覆盖机制**（新增） | 🔧 | B5 | `tenant/terms.yaml` 加载 | 商户自定义术语优先级高于全局；支持单租户覆盖 |

### 2.3 快慢双模型（gap-v2 §3.2 细化）

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T2.6 | **`ModelRouter` 决策树** | 🔧 | B7 | `autoservice/model_router.py` | 5 类别分类（greeting/simple-faq-hit/complex-query/transactional/out-of-scope）→ 选择 fast-only / fast-placeholder+slow / slow-only / escalation 路径 |
| **T2.6a** | **FastClassifier intent schema**（新增） | 📝 | gap-v2 §3.2 | `classify_intent.yaml` | 5 类别定义 + haiku 分类 prompt + 置信度阈值 |
| T2.7 | **占位续写流程** | 🔧 | B7 | channel_server + cards.py 集成 | **4 阶段 timeout**（200ms/1s/10s/25s）+ 降级文案模板；走 T1.10a `CardRefreshCoalescer` |
| T2.8 | **消息协议扩展** | 🔧 | A5 | channel_server 协议改造 | 新增 `update_message`, `card_update`；metadata 加 `conversation_id`, `state`, `query_id` |

### 2.4 管理群命令

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T2.9 | **`/dispatch` 命令** | 🔧 | E3.2 | channel_server 命令 | `/dispatch <chat_id> <agent_role>` 指定角色接管 |
| T2.10 | **飞书 Bot 命令注册** | 📝 | E3.2 | 开放平台配置 | 注册 /status, /dispatch, /review, /rules, /rollback 菜单化命令 |

---

## 五、Phase 3 · 人机协作 MVP（周 6-9，3-5 周）

### 3.1 Agent 分队频道

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T3.1 | **设计 Squad 数据模型** | 📐 | C3 | 设计文档 + DB schema | `Squad {id, human_open_id, agent_roles[], feishu_chat_id, active_conversations[]}` |
| T3.2 | **程序化建群** | 🔧 | C3 | `channels/feishu/squad.py` | 使用 `group_message_type:"thread"` 原生话题群 |
| T3.3 | **分队注册管理** | 🔧 | C3 | autoservice/squad.py | CRUD + 人工-Agent 关联 + SQLite 持久化 |

### 3.2 对话卡片（gap-v2 §3.3 细化）

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T3.4 | **对话摘要卡片模板** | 🔧 | C4 | cards.py 卡片模板 | **5 状态**（idle/waiting-reply/escalation-pending/human-takeover/closed），每态独立标题+按钮 |
| T3.5 | **卡片生命周期管理** | 🔧 | C4 | cards.py | 新对话→发卡片→事件驱动更新→结案关闭；card_id 追踪；集成 T1.10b 换卡 |
| T3.6 | **事件驱动卡片刷新** | 🔧 | C4, C2 | 事件订阅 | 订阅 `conversation.*` → T1.10a Coalescer → patch_card |

### 3.3 Copilot thread（gap-v2 §3.3 细化）

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T3.7 | **thread 消息发送** | 🔧 | C5 | `_send_thread_reply()` | `reply_in_thread:true`；单群 5 QPS 共享队列 |
| T3.8 | **thread 消息路由** | 🔧 | C5, C6 | channel_server 路由表 | 按 gap-v2 §3.3 路由表实现：草稿/已采纳/建议/Takeover/AI建议 5 种发送者-标签-可见性映射 |
| T3.9 | **Copilot 协议** | 🔧 | C5, C6 | conversation.py Copilot 逻辑 | 草稿态 `draft.pending` → 人工建议 → Agent 采纳 `draft.adopted` → 发客户 |

### 3.4 升级与翻转

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T3.10 | **Agent @人工求助** | 🔧 | C7 | conversation.py | 触发条件匹配 → thread 内 @客服 → 180s 计时器启动 |
| T3.11 | **超时回退** | 🔧 | C7 | 计时器 + 安抚模板 | 180s 未响应 → 回退 AgentHandling → 安抚消息（模板 YAML 化）→ emit `escalation.timeout` |
| T3.12 | **`/hijack` 命令** | 🔧 | C8 | 命令解析 + 状态转换 | thread 内 `/hijack` → HumanTakeover → Agent 切只读 |
| T3.13 | **Agent 副驾驶模式** | 🔧 | C9 | conversation.py | HumanTakeover 下 Agent 发 `[AI建议]` 仅对人工可见 + 接管次数++ |

### 3.5 SLA 监控（gap-v2 §2.3 细化）

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T3.14 | **指标采集** | 🔧 | E3.3 | `autoservice/metrics.py` | 按 gap-v2 §2.3 埋点 10 事件；基于事件总线 |
| **T3.14a** | **`SLAAggregator`**（新增） | 🔧 | gap-v2 §2.3 | metrics.py | 环形 buffer 存事件；滚动窗口 5m/1h/24h；P50/P95 计算 |
| T3.15 | **SLA 告警** | 🔧 | E3.3 | `alerts.yaml` + 推送 | 4 条规则 YAML 化（首回/接单/CSAT/消化率）；超阈值推送管理群加急卡片 |

---

## 六、Phase 4 · 可观测 & 提案（周 9-12，3-5 周）

### 4.1 运营仪表盘

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T4.1 | **Bitable 指标模板** | 📝 | E3.1 | 飞书多维表格模板 | 日指标表：接管数/CSAT/升级转结案率/首回/接单等待/会话时长 |
| T4.2 | **Bitable 指标写入** | 🔧 | E3.1 | `autoservice/dashboard.py` | 每小时聚合 → `bitable.v1.app_table_record.create` |
| T4.3 | **管理群仪表盘卡片** | 🔧 | E3.1 | cards.py | 每日定时推送: 4 Agent 状态 + 3 核心指标 + 趋势箭头 |

### 4.2 Dream Engine 提案审核

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T4.4 | **对话记忆池写入** | 🔧 | D2 | session 扩展 | 每轮对话含意图/情绪/KB 命中/结案状态 → `.autoservice/database/memory_pool.db` |
| T4.5 | **`/rules show\|edit` 命令** | 🔧 | D1 | channel_server 命令 | 管理群查看/修改 4 参数学习规则 |
| T4.6 | **提案生成 pipeline** | 📐 | D4, D5 | `autoservice/dream_engine.py` | LLM 回放记忆池 → 抽取建议 → 提案 JSON |
| T4.7 | **提案审核卡片** | 🔧 | D5 | cards.py | 卡片含: 来源对话/影响范围/风险等级 + ✓/✎/✗ 按钮 |
| T4.8 | **飞书审批流集成** | 🔧 | D5 | `channels/feishu/approval.py` | 模板 + 实例（100/分限速）+ 回调监听 + 通过后进灰度 |

### 4.3 自助上线向导（gap-v2 §2.2 细化）

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T4.9 | **docker-compose 多租户模板** | 📝 | X7 | `templates/docker-compose.tmpl.yaml` | 每租户: channel_server + cc_pool + web 三容器 |
| T4.10 | **自助上线 MVP** | 🔧 | E1.1 | 向导骨架 | 管理群对话式引导 + `create-tenant.sh` + `kb_ingest.py` |
| **T4.10a** | **虚拟客户预演生成**（新增/替换 E1.3） | 🔧 | gap-v2 §2.2 | `autoservice/sim_customer.py` | 输入 KB + 目标地区 → 生成 ≥10 条覆盖主要场景的虚拟对话 + AI 答 |
| **T4.10b** | **预演审阅 UI**（新增/替换 E1.3） | 🔧 | gap-v2 §2.2 | Web `/wizard/step3` | ✓/✎/⚠ 三按钮；所有 ⚠ 处理完才能进下一步 |
| **T4.10c** | **Few-shot 注入机制**（新增） | 🔧 | gap-v2 §2.2 | `tenant.fewshot_override.yaml` | 修改的预演对话 → 注入 Agent prompt few-shot |

---

## 七、Phase 5 · 产品化（周 12+，6-10 周）

### 5.1 Dream Engine 完整版

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T5.1 | **低峰检测调度器** | 🔧 | D3 | dream_engine.py | QPS 30 分钟均值 < 白天 20% → 触发回放 |
| T5.2 | **灰度路由** | 🔧 | D6 | `autoservice/canary.py` | 5%→25%→100%；**每阶段 24h + 5 指标全部满足才升阶**（gap-v2 §3.4） |
| **T5.2a** | **灰度恶化自动告警**（新增） | 🔧 | gap-v2 §3.4 | alerts.yaml 扩展 | 任一指标恶化 >2× 阈值 → 自动回滚 + 管理群告警 |
| T5.3 | **`/rollback` 命令** | 🔧 | D7 | channel_server 命令 | `/rollback <proposal_id> <reason>` → 撤回 → `proposal.history` 记录 → 7 天待复盘队列 |
| T5.4 | **晨起推送** | 🔧 | D5 | dream_engine.py 定时任务 | 每日 09:00 前推送聚合提案；审批实例创建排队（100/分限速） |

### 5.2 合规引擎（gap-v2 §2.1 细化）

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T5.5 | **合规规则库 schema 设计** | 📐 | E1.4 | schema + 加载器 | rule_id/region/severity/trigger/sandbox_blocking/public_blocking |
| **T5.5a** | **16 条预置规则 YAML**（新增） | 📝 | gap-v2 §2.1 | `compliance/rules/{eu,us,cn}.yaml` | EU 6 条 GDPR + US 4 条 CCPA/COPPA + CN 6 条 PIPL/网信办 |
| **T5.5b** | **补救指南文档**（新增） | 📝 | gap-v2 §2.1 | `docs/compliance/<rule_id>.md` × 16 | 每条规则一页补救方法 + 示例 |
| T5.6 | **合规预检引擎** | 🔧 | E1.4 | `autoservice/compliance.py` | 扫描商户配置 → 输出结果+等级；沙箱不阻塞，对外开放阻塞 |
| T5.7 | **合规策略模板下发** | 🔧 | E1.4 | 平台模板 YAML | 平台预置 + 商户叠加；Dream Engine 受约束 |

### 5.3 计费引擎

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T5.8 | **接管次数统计** | 🔧 | X8 | metrics.py 扩展 | HumanTakeover 转换计入；按租户月聚合 |
| T5.9 | **阶梯计费计算** | 🔧 | X8 | `autoservice/billing.py` | 阶梯价表 → 月末账单 JSON |
| T5.10 | **CSAT 采集** | 🔧 | X8 | 结案评分卡片 | 飞书卡片 1-5 星 → metrics |

### 5.4 多渠道扩展

| # | 任务 | 类型 | 关联 | 产出 | 验收标准 |
|---|------|------|------|------|---------|
| T5.11 | **`ChannelAdapter` 抽象** | 📐 | A5, A7 | `socialware/channel.py` | 接口: connect/send/receive/update/react；L1 提取 |
| T5.12 | **飞书/Lark 双端适配** | 🔧 | A7 | channels/feishu/ 改造 | host/auth 配置化；共用 90% 代码 |
| T5.13 | **Slack 适配器** | 🔧 | A7 | `channels/slack/` | 实现 ChannelAdapter 的 Slack Bot 版 |

---

## 八、任务统计

| Phase | 任务数 | v1 对照 | 预估工期 | 关键产出 |
|-------|--------|--------|---------|---------|
| Phase -1 | 3 | — (新增) | 周 -2 至 0（并行） | 权限审批提交 |
| Phase 0 | 4 | 4 | 0.5-1 周 | UI spike 结论 |
| Phase 1 | 16 | 13 (+3) | 2-3 周 | 状态机 + 事件 + 卡片 + Coalescer |
| Phase 2 | 12 | 10 (+2) | 2-4 周 | 4 角色 + 22 语种 + ModelRouter |
| Phase 3 | 16 | 15 (+1) | 3-5 周 | Squad + thread Copilot + SLA |
| Phase 4 | 13 | 10 (+3) | 3-5 周 | 仪表盘 + 提案 MVP + 预演 UI |
| Phase 5 | 16 | 13 (+3) | 6-10 周 | 灰度 + 合规 16 条 + 计费 + 多渠道 |
| **合计** | **80** | **65** | **9.5-16 周** | 较 v1 +1.5-2 周 |

> 说明: 合计 80（而非 gap-v2 §四 的 78）因本 tasks-v2 另加入 T0.0b 和 T5.5（作为父任务保留），结构性任务。

---

## 九、双工作流并行编排（更新）

### 9.1 工作流划分

- **γ 商务线**（新增）: 周 -2 至 0 启动，Phase -1 权限审批、应用上架
- **α 引擎层**: 对话状态机、事件总线、Agent 角色、模型路由、Dream Engine 后端、合规/计费
- **β 交互层**: 飞书能力、分队频道、Copilot UI、SLA 告警、仪表盘、上线向导

### 9.2 全局甘特

```
周 -2 -1  0   1   2   3   4   5   6   7   8   9  10  11  12+
    ├───┤───┼──────────┼──────────┼──────────┼──────────┼──────
γ   │审批│等│  (持续跟进)
    └───┘
             ┌───┐
共享 P0      │T01-4│
             └───┘
              ⇣ S0
              ┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌──────
α 引擎        │T1.1-.6   ││T2.1-.7   ││T3.10-.14 ││T4.4-.6   ││T5.1-3
              │T1.2a新   ││T2.5a-c 新││T3.14a 新 ││          ││T5.2a 新
              │T1.12 情绪││T2.6a 新  ││          ││          ││T5.5a-b 新
              └────⇣────┘└────⇣────┘└────⇣────┘└────⇣────┘└────⇣
                  S1         S2         S3         S4        S5
              ┌────⇣────┐┌────⇣────┐┌────⇣────┐┌────⇣────┐┌────⇣
β 交互        │T1.8-.11  ││T2.9-.10  ││T3.1-.9   ││T4.1-.3   ││T5.4
              │T1.10a-b新││          ││T3.15     ││T4.7-.8   ││T5.10-13
              │T1.13     ││          ││          ││T4.9-.10  ││
              │T1.4 集成 ││          ││          ││T4.10a-c新││
              └──────────┘└──────────┘└──────────┘└──────────┘└──────
```

### 9.3 同步点（6 个，新增 S0）

| 同步点 | 时间 | α 交付给 β | β 交付给 α | γ 交付 | 联调内容 |
|--------|------|-----------|-----------|--------|---------|
| **S0** | 周 0 | — | — | 核心权限已通过审批 | 确认可进入 Phase 1 |
| **S1** | 周 3 | `events.py` API, `conversation.py` | `cards.py` + `_patch_card` + `CardRefreshCoalescer` | — | 状态转换 → emit → 卡片刷新冒烟 |
| **S2** | 周 5 | `conversation.py` 集成到 channel_server | `/dispatch` 触发角色路由 | — | 端到端: 消息进入 → 分流 → 角色池 → 占位续写 |
| **S3** | 周 8 | T3.10~T3.13 状态转换事件 | T3.7~T3.9 thread 交互 + T3.14a Aggregator 前端 | — | Agent @人工 → thread 通知 → 建议 → 采纳 → /hijack → 翻转 |
| **S4** | 周 11 | T4.6 提案 JSON | T4.7~T4.8 审核卡片 + 审批流 + T4.10a-c 预演 UI | — | 提案生成 → 推送 → 审核 → 灰度/回滚 |
| **S5** | 周 14+ | T5.1-3 灰度后端 + T5.5a-b 合规规则 | T5.4 晨起推送 + T5.10 CSAT 卡片 | — | 端到端: 学习规则→灰度→恶化告警→自动回滚 |

### 9.4 任务分配汇总

| 工作流 | P-1 | P0 | P1 | P2 | P3 | P4 | P5 | 合计 |
|--------|-----|----|----|----|----|----|----|------|
| γ 商务 | 3 | — | — | — | — | — | — | **3** |
| α 引擎 | — | 2 | 7 | 8 | 5 | 3 | 10 | **35** |
| β 交互 | — | 3 | 9 | 4 | 11 | 10 | 5 | **42** |
| 合计（去重共享） | 3 | 4 | 16 | 12 | 16 | 13 | 16 | **80** |

### 9.5 关键路径

**v2 关键路径** (↑ 表示新增卡点):
```
γ: T0.0 → 审批通过 (外部不可控)
α: T1.2 → T1.2a↑ → T2.4 → T2.6 → T2.6a↑ → T3.10 → T3.12 → T5.2a↑
β: T0.1 → T1.9 → T1.10a↑ → T3.4 → T3.7 → T3.9 → T4.10b↑
```

对比 v1 关键路径压缩 ~25-30% 的结论依然成立，新增任务多为并行填充不延长关键路径。

---

## 十、风险与缓解（更新）

| 风险 | 影响 | 缓解 |
|------|------|------|
| **γ 飞书审批延迟** | 阻塞 β Phase 1 全部卡片功能 | P-1 周 -2 启动；MVP v1 走白名单应用绕过商店审批 |
| **T1.10a Coalescer 丢帧率过高** | 多对话场景摘要不够实时 | 监控丢帧率 >5% 触发"分队扩容"（拆群） |
| **T2.5a 术语表版权** | 法务阻塞多语言上线 | 优先用 IATE/MS Terminology 公开许可源 |
| **T5.5a 合规规则覆盖不全** | 地区推广受阻 | MVP 16 条兜底；按事件驱动扩展 |
| **T5.2 灰度 5 指标并行过严** | 卡阶 | v2 观测数据后重新校准阈值 |
| **S1/S3 联调复杂度** | 多组件拼装 bug 面大 | 预留 2 天 buffer；前期双方 mock 测试 |
| **CC Pool 4 角色预热成本** | 资源消耗大 | 分流池常驻；其余 min_size=0 按需启动 |

---

## 十一、Open Questions（从 PRD 继承）

| # | 问题 | 影响任务 | 待决时间 |
|---|------|---------|---------|
| OQ1 | 计费模式（阶梯 vs 订阅+超额） | T5.9 | Q3 前 |
| OQ2 | 提议采纳率是否计费 | T5.8 扩展 | Q3 前 |
| OQ3 | Agent 分队重分配原子性 | T3.3 | Phase 3 中 |
| OQ4 | Dream Engine 做梦频率（每夜 vs 按量） | T5.1 | Phase 5 初 |
| OQ5 | PSTN 延迟 SLA | T5.11+ | 后续版本 |
| OQ6 | 合规按地区 vs 按语言 | T5.6 | v2 采用按地区，待产品复核 |

---

## 十二、读法建议

本 tasks-v2 是**当前开发基线**。与 v1 关系：

- v1 `2026-04-14-prd-gap-tasks.md` 保留作为 04-14 历史快照，不再维护
- **所有新任务分配、进度跟踪、sprint 规划以本 v2 为准**
- 本 v2 依赖的深化细节（状态机矩阵、ModelRouter 决策树、告警规则等）去读 `2026-04-15-prd-gap-v2.md`
- 飞书 API 限制/参数去读 `2026-04-14-feishu-api-verification.md`

下次版本（v3）触发条件: ① PRD 有新版本 ② 任务数 ≥ 100 ③ 完成 S3 同步点后再做一次全面复盘。

---

*v2 · 2026-04-15 · 基于 gap-v2 分析 · 80 任务 · 9.5-16 周工期 · 三工作流（γ/α/β）并行*
