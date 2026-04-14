# AutoService PRD Gap Analysis & Implementation Roadmap

> 基于 AutoService-PRD.md v1.0 与当前代码库的逐项对比
> 2026-04-14 · 按"先底层后上层"原则分层排优先级
> **v2 更新**: 纳入飞书 IM 原生能力评估（功能完备性 / 接入便捷性 / 运维便利性）
> **v3 更新**: 整合 upstream PR #6 (`docs/prd/im-requirements-analysis.md`) 的需求编号体系、thread 方案、Gap 分析；采用 PR #6 的 R-xxx 需求 ID 作为统一索引
> **v4 更新**: 基于三层架构重构 (L1 socialware / L2 autoservice+channels / L3 plugins) 重新评估。新增 CC Pool、CRM 持久化、声明式 Flow、同步工具链等已实现能力；调整多租户策略（fork 隔离 vs 运行时隔离）；更新分层依赖
> **v5 更新**: 飞书/Lark 官方 API 文档逐项验证完成（详见 `2026-04-14-feishu-api-verification.md`）。确认 thread `reply_in_thread`、卡片 PATCH、建群、审批、Bitable 全部可用；修正占位续写必须走卡片方案、卡片需 `update_multi:true`、14 天有效期等约束；发现 `group_message_type:"thread"` 原生话题群

---

## 零、飞书原生能力对 PRD 的覆盖评估

当前项目以飞书 IM 为主通道，但**仅使用了飞书能力的冰山一角**。
已用：文本消息收发、Emoji Reaction (ACK)、联系人查询、基础斜杠命令。
未用但高度相关的飞书能力可以大幅降低多个 PRD 模块的实现成本。

### 飞书能力 → PRD 需求映射表

> 需求 ID 采用 upstream PR #6 (`docs/prd/im-requirements-analysis.md` v0.2) 定义的 R-xxx 编号体系

| 飞书原生能力 | 当前使用 | 需求 ID 映射 | 功能完备性 | 接入便捷性 | 运维便利性 |
|---|---|---|---|---|---|
| **消息卡片 (CardKit)** — 交互式卡片，含按钮/下拉/表单，支持原地更新 | ❌ 未用 | R-MSG-2 互动卡片 · R-MSG-3 流式刷新卡片 · R-MSG-8 富文本展示 | ★★★ 完全覆盖卡片需求：摘要展示+按钮交互+原地刷新 | ★★★ SDK 直接构建 JSON，无前端开发 | ★★★ 飞书托管渲染和交互，零运维 |
| **消息编辑 (PUT)** — 编辑已发送的文本/富文本消息 | ❌ 未用 | R-MSG-4 占位消息(备选) | ★☆☆ **仅支持 text/post，不支持卡片**；每消息最多 20 次 | ★★★ 一个 API 调用 | ★★★ |
| **卡片更新 (PATCH)** — 更新已发送的交互式卡片内容 | ❌ 未用 | R-MSG-3 流式刷新卡片 · R-MSG-4 占位续写(推荐) | ★★★ **v5 确认**: `PATCH /im/v1/messages/:id`，仅限 interactive 类型；需卡片 config 含 `update_multi:true`；14 天有效期；单消息 5 QPS | ★★★ 一个 API 调用 | ★★★ |
| **话题/Thread 回复** — 消息下挂子讨论，类似 Slack thread | ❌ 未用 | R-CMD-3 对话监管窗 · R-CMD-4 副驾驶侧栏 | ★★★ **v5 确认**: `reply_in_thread: true` 参数，飞书+Lark 均支持；返回 `thread_id` 可追踪 | ★★★ 参数已确认，spike 降级为实测 UI/限额 | ★★★ 客服不离开飞书，历史可追溯 |
| **群组管理 (Chat CRUD)** — 程序化建群/加人/改配置 | ❌ 未用 | R-CHAT-1 自动建管理群 · R-CHAT-2 Agent 分队频道 | ★★★ **v5 确认**: 支持 `group_message_type:"thread"` 创建原生话题群；初始 ≤50 用户 + 5 Bot | ★★☆ 需飞书权限 `im:chat:create` | ★★☆ 群生命周期由飞书管理 |
| **群成员变更事件** | ❌ 未用 | R-CHAT-4 客服离职/休假时 Agent 分队重分配 · R-EVT-3 | ★★★ `im.chat.member.user.added/deleted` 事件完备 | ★★☆ 增加事件订阅注册 | ★★★ |
| **Bot 斜杠命令** — 群内 `/cmd` 触发 Bot 回调 | ⚠️ 部分用 | R-CMD-1 `/status` `/dispatch` `/review` `/hijack` `/rollback` | ★★★ 命令分发+参数解析飞书原生支持 | ★★★ 在开放平台配置即可 | ★★★ |
| **@mention** — 消息中 @ 指定用户/Bot | ⚠️ 仅解析 | R-MSG-5 Agent `@人工` 求助 · 管理员 `@Dream Engine` · R-EVT-4 | ★★★ | ★★★ | ★★★ |
| **审批流 (Approval)** — 多步审批，含表单/状态/催办 | ❌ 未用 | R-CMD-2 卡片按钮回调(✓/✎/✗) · R-EVT-2 | ★★★ **v5 确认**: 模板 (`POST /approval/v4/approvals`) + 实例 (`POST /approval/v4/instances`) 均可用；节点类型 AND/OR/SEQUENTIAL | ★★☆ 需定义审批模板+回调；实例创建限速 100/分 | ★★★ 审批记录/催办/抄送飞书全管 |
| **Webhook 事件订阅** — 消息已读、群变更、审批完成等 | ⚠️ 仅订阅消息接收 | R-EVT-1~5 全部事件需求 | ★★☆ 100+ 事件类型，覆盖充分 | ★★☆ 增加事件回调注册 | ★★★ 飞书推送，无需轮询 |
| **Emoji Reaction** — 消息表情回应 | ✅ 已用 | ACK 确认 + 状态标记 | ★★★ | ★★★ | ★★★ |
| **未读徽章** — 频道级未读数 | ✅ 原生 | R-MSG-6 未读对话数徽章 | ★★★ 客户端原生维护，无需开发 | ★★★ | ★★★ |
| **富文本消息 (Post)** — 标题+多段落+链接+图片 | ⚠️ 仅解析 | R-MSG-8 指标展示 · `/review` 统计报告 | ★★★ | ★★★ | ★★★ |
| **文件/图片上传下载** | ✅ 已用 | R-MSG-7 附件上传（PDF/CSV） · R-EVT-5 | ★★★ | ★★★ | ★★★ |
| **Helpdesk (服务台)** — 工单系统+SLA+自动分配 | ❌ 未用 | R-OPS-1 SLA 告警 | ★★☆ 有原生 SLA+分配；但与 Agent 集成需开发 | ★☆☆ Helpdesk API 复杂度较高 | ★★★ 工单生命周期飞书全管 |
| **多维表格 (Bitable)** — 在线数据库+视图+仪表盘 | ❌ 未用 | US-3.1 运营仪表盘 · 双账本 | ★★★ **v5 确认**: `POST /bitable/v1/apps/:token/tables/:id/records`，50 QPS，支持文本/数字/日期/人员等字段类型 | ★★☆ 需先手动创建表模板 | ★★★ 零运维，飞书托管 |
| **多租户授权（商店应用模式）** | ❌ 未用 | R-OPS-3 多租户隔离 | ★★★ 每企业独立授权，数据隔离 | ★★☆ 需走商店应用发布流程 | ★★★ 授权/安装/卸载飞书管理 |

### 关键结论（v5 API 验证后更新）

1. **卡片 PATCH 是占位续写的唯一方案** — v5 验证确认: PUT 仅支持 text/post，PATCH 仅支持 interactive。**占位续写必须走卡片路线**，且初始卡片必须包含 `"update_multi": true`。
2. **Thread `reply_in_thread: true` 已确认可用** — v5 验证确认飞书+Lark 均支持，返回 `thread_id` 可追踪。spike 从"验证是否存在"降级为"验证 UI 体验和限额细节"。
3. **原生话题群 `group_message_type: "thread"` 是额外加分项** — v5 发现建群 API 支持创建全话题模式群，分队频道建议直接使用此模式。
4. **审批流模板+实例 API 完整可用** — v5 确认节点类型 AND/OR/SEQUENTIAL 均支持；但实例创建限速 100/分需注意批量场景。
5. **Bitable 记录 API 50 QPS** — v5 确认字段类型丰富（文本/数字/日期/人员等），仪表盘指标写入无瓶颈。
6. **Lark 国际版 API 完全对等** — v5 确认仅域名不同 (`open.larksuite.com` vs `open.feishu.cn`)，同一 `lark-oapi` SDK 通过 `domain` 参数切换。用户 ID 不互通。
7. **C 端触点不在飞书职责范围** — R-EXT-1/2/3（独立站/PSTN/20+ 语种）继续由 `web/` + 外部通道承担。

### Gap 状态更新（v5 验证后）

| Gap | 原状态 | v5 验证结果 | 更新后状态 |
|-----|--------|-----------|-----------|
| **Gap 1 · 监管窗/副驾驶** (R-CMD-3/4) | ❓ thread API 未验证 | ✅ `reply_in_thread: true` 确认存在，飞书+Lark 均支持 | ⚠️ 降级为 UI 实测（回复数上限、多端一致性、生命周期事件仍需 spike） |
| **Gap 2 · 卡片刷新限额** (R-MSG-3) | ❓ 未知 | ✅ 单消息 PATCH 5 QPS，全局 1000/分 50/秒 | ⚠️ 已有数字，需压测真实场景是否足够（建议刷新间隔 ≥ 5s） |
| **Gap 3 · 占位续写方案** (R-MSG-4) | ❓ PATCH 文本 or 卡片？ | ✅ **已明确: 必须用卡片 PATCH**，文本 PUT 不支持卡片类型 | ✅ 方案已确定，需实测视觉效果 |
| **Gap 4 · 权限审批阻塞** (R-CHAT-3) | ⚠️ 周期不可控 | 无变化 | ⚠️ 走商店应用预审批缓解 |
| **Gap 5 · 飞书 vs Lark** | ⚠️ 能力是否对等未知 | ✅ API 路径一致，仅域名替换，同 SDK | ✅ 已确认对等，ID 不互通是唯一差异 |
| **Gap 6 · 飞书无 MCP** | — 维持现状 | 无变化 | — |
| **Gap 7 · 卡片 14 天有效期** (新增) | — | ⚠️ v5 发现: PATCH 仅在消息发送后 **14 天内** 有效 | ⚠️ 需设计长对话卡片的"过期→新建"机制 |
| **Gap 8 · 单群 5 QPS 共享** (新增) | — | ⚠️ v5 发现: 分队群内所有 Bot 消息 + thread 回复共享 **5 QPS** | ⚠️ 高并发多对话活跃场景需消息排队 |

---

## 一、已实现能力清单

> v4 更新：基于三层架构 (L1 `socialware/` → L2 `autoservice/`+`channels/` → L3 `plugins/`) 重新盘点

### 1. 三层架构 & 租户管理（**v4 新增**）
- **L1 框架层 `socialware/`** — 通用能力：插件加载、配置机制、会话框架、异步对象池、数据库 CRUD、权限框架
- **L2 应用层 `autoservice/`** — 业务逻辑：域配置 (`domain_config.py`)、域会话 (`domain_session.py`)、域权限 (`domain_permission.py`)、CRM、规则引擎
- **L2 通道层 `channels/`** — 通道适配器：飞书 IM、Web chat（含 L1 提取路线图）
- **L3 租户层 `plugins/<tenant>/`** — 客户特定插件和数据
- **层边界强制** — `.github/CODEOWNERS` + `boundary-check.yml` CI 防止跨层修改
- **向后兼容垫片** — `autoservice/__init__.py` 重导出 `socialware` 模块，旧代码无需改动
- **租户脚手架** — `templates/create-tenant.sh` 一键创建 L3 fork
- **同步工具链** — `scripts/sync.sh`, `sync-all.sh`, `sync-status.sh`, `refine.sh` 管理 L1→L2→L3 fork 同步

### 2. 双通道接入（模块 A 部分）
- **飞书 IM 通道** — `channels/feishu/channel.py` MCP server + `channels/feishu/channel_server.py` WebSocket 路由守护进程 (~1143 行)
- **Web 聊天通道** — `channels/web/app.py` FastAPI + WebSocket，含 access code 鉴权
- **Channel Server 多实例路由** — chat_id 精确/前缀/通配符路由，开发者模式
- **WebChannelBridge** — `channels/web/websocket.py` 多路复用会话桥接（**v4 新增**）
- **多用户会话支持** — 基于 chat_id 的去复用，单服务器连接服务多用户（**v4 新增**）

### 3. CC Pool — Claude Code 实例池（**v4 新增**）
- **通用异步池** — `socialware/pool.py`: `AsyncPool[T]` + `PoolableClient` 协议 + `PoolConfig`
- **CC 特化池** — `autoservice/cc_pool.py`: `CCClient` 封装 `ClaudeSDKClient`，预热/回收/健康检查
- **配置分层** — `.autoservice/config.yaml` → `config.local.yaml` → `CC_POOL_*` 环境变量
- **CLI 管理** — `autoservice/cc_pool_cli.py` + Makefile 命令 (`pool-status`, `pool-start`, `pool-logs`)
- **PRD 关联**: 直接支撑 L1.1 (多角色 Agent) 和 L1.2 (快慢双模型)

### 4. CRM 持久化（**v4 新增**）
- **SQLite CRM** — `autoservice/crm.py`: contacts/conversations/customer_rules 表
- **自动录入** — channel_server 每条飞书消息触发 `upsert_contact()`，记录 name/phone/email/company/department
- **PRD 关联**: 部分覆盖线索收集 Agent 的 CRM 直通需求

### 5. 声明式流程 & 规则（**v4 增强**）
- **流程定义** — `.autoservice/flows/` 6 个 DAG 声明式 YAML 流程（identify-customer-type、new-customer-lead、existing-customer-verify、kb-query-routing、subagent-orchestration、escalation）
- **流程索引** — `_index.yaml` 注册所有流程及触发条件
- **规则引擎** — `autoservice/rules.py`: `load_rules()`, `add_rule()`, `format_rules_for_prompt()`
- **身份系统** — `.autoservice/identity.yaml`: Agent 身份注入到 MCP 指令前言（**v4 新增**）
- **状态**: 流程数据模型已定义，尚未接入实际路由逻辑（待 /discussion 技能集成）

### 6. 插件系统
- **声明式插件** — `plugins/<name>/plugin.yaml` 定义 MCP tools + HTTP routes
- **自动发现加载** — `socialware/plugin_loader.py` (L1) 启动时扫描注册
- **Mock/Real 双模式** — SQLite mock DB 本地 API 或真实后端
- **CINNOX 插件** — 4 个 MCP tools + 3 个 HTTP routes

### 7. 知识库 RAG
- **FTS5 全文检索** — `skills/knowledge-base/` 完整实现
- **领域+地区切片** — domain/region 过滤
- **多源摄入** — PDF / XLSX / Web 导入
- **术语表快速通道** — CINNOX 官方术语即时响应

### 8. 对话能力
- **客服技能** — `skills/customer-service/` HEAR/LAST/LEARN 方法论
- **销售技能** — `skills/marketing/` SPIN/Challenger/Solution Selling
- **线索收集** — `skills/cinnox-demo/` Gate 系统 + `save_lead.py`
- **查询路由** — `route_query.py` 关键词→领域/地区/角色映射
- **子代理编排** — KB 分发→草稿→润色→审核 流水线

### 9. 基础设施
- **权限控制** — `socialware/permission.py` (L1) 四级权限 + `autoservice/domain_permission.py` (L2) 域默认值
- **会话管理** — `socialware/session.py` (L1) + `autoservice/domain_session.py` (L2) 域前缀
- **反幻觉约束** — 所有 Skill 中硬编码"查不到不编造，必须转人工"
- **多语言** — 中/英双语动态切换 (`autoservice/domain_config.py`)
- **冷启动** — 新客户自动创建记录 + 工作目录
- **测试套件** — ~1500 行单元/集成/E2E 测试（**v4 新增**）

---

## 二、缺失能力分层视图

按依赖关系从底至上分为 5 层，高层功能依赖低层先完成。

> v4 更新：三层架构 + CC Pool + CRM + Flow 定义使底层基础显著增厚

```
┌─────────────────────────────────────────────────┐
│  L4 · 产品化运营                                  │  Dream Engine / 计费 / 合规
├─────────────────────────────────────────────────┤
│  L3 · 商户自助 & 可观测                            │  上线向导 / 仪表盘 / 管理命令
├─────────────────────────────────────────────────┤
│  L2 · 人机协作层                                  │  Copilot(thread) / 卡片 / 角色翻转
├─────────────────────────────────────────────────┤
│  L1 · Agent 角色 & 运行时                          │  4 角色拆分 / 双模型 / 情绪识别
├─────────────────────────────────────────────────┤
│  L0 · 基础框架增强                                │  状态机 / 事件总线 / 协议扩展
│  (多租户由 fork 模型解决，优先级降低)                │
├─────────────────────────────────────────────────┤
│  ██████████████ 已实现 ██████████████             │
│  三层架构(L1/L2/L3) · CC Pool · CRM · Flow 定义  │
│  插件系统 · KB RAG · 双通道 · 权限 · 会话           │
│  同步工具链 · 租户脚手架 · 身份系统 · 测试套件       │
└─────────────────────────────────────────────────┘
```

---

## 三、分层详细需求 & 优先级

### L0 · 基础框架增强（最高优先级 — 所有上层功能的前提）

#### L0.1 对话状态机
- **PRD 来源**: 模块 C 六步状态机 (US-2.1 ~ US-2.6)
- **现状**: 无统一对话状态，每条消息独立处理
- **v4 新基础**: `.autoservice/flows/` 已定义 6 个声明式 DAG 流程（identify-customer-type、escalation 等），提供了状态转换的**数据模型**；`autoservice/crm.py` 提供了 conversations 表可用于状态持久化；channel_server 已有 `_chat_modes` 跟踪每个 chat_id 的运行时模式
- **目标**: 将现有流程定义接入实际路由，实现对话生命周期状态机
  ```
  Idle → AgentHandling → CopilotMonitoring → HumanSuggestion
       → HumanAlert → HumanTakeover → Resolved
  ```
- **关键设计**:
  - 每个 conversation 持有 `state` + `assigned_agent` + `assigned_human` + `history`
  - 状态转换触发事件（供上层消费）
  - 状态持久化到 CRM SQLite（复用 `autoservice/crm.py` 的 conversations 表）
  - 流程定义 (`.autoservice/flows/`) 作为状态转换规则的声明式配置
- **建议位置**: `autoservice/conversation.py`（新建，消费 `crm.py` + `flows/`）
- **预估工作量**: 中（流程数据模型已有，需实现运行时状态机引擎）

#### L0.2 统一事件总线
- **PRD 来源**: 实时卡片刷新、SLA 监控、告警推送等都依赖事件
- **现状**: 消息在 channel_server 中点对点路由，无事件广播机制
- **目标**: 发布/订阅事件系统
  - 事件类型: `conversation.started`, `conversation.escalated`, `human.takeover`, `sla.breached`, `agent.suggestion`, `session.ended` 等
  - 支持同进程订阅（内存）和跨进程推送（WebSocket）
- **关键设计**:
  - 基于 `asyncio.Queue` 的进程内 pub/sub
  - channel_server 作为跨实例事件中继
  - 事件 schema 统一: `{type, conversation_id, timestamp, payload}`
- **建议位置**: `autoservice/events.py`
- **预估工作量**: 中

#### L0.3 多租户隔离
- **PRD 来源**: §9 "多租户数据串漏 = 致命风险"
- **需求 ID**: R-OPS-3 (多租户隔离)
- **现状（v4 重评估）**: 三层 fork 架构 (L3 = 租户) 已提供**代码级+数据级隔离**
  - 每个租户 = 一个独立 L3 Git 仓库 (fork of L2)
  - 数据物理隔离: 每个 L3 有自己的 `.autoservice/database/`
  - GitHub 平台强制读权限隔离
  - `scripts/register-fork.sh` + `sync-all.sh` 管理租户生命周期
- **已解决 vs 仍需解决**:
  | 方面 | fork 模型已解决 | 仍需补充 |
  |------|---------------|---------|
  | 代码隔离 | ✅ 每租户独立仓库 | — |
  | 数据隔离 | ✅ 物理分离的 `.autoservice/` | — |
  | 部署隔离 | ✅ 每租户独立进程 | 需编排工具（docker-compose / k8s） |
  | 运行时共享 | ❌ 不适用（每租户独立部署） | 若未来需要多租户共享进程，才需 `TenantContext` |
  | 飞书授权 | ⚠️ 每租户需独立飞书应用或商店应用授权 | 商店应用模式可简化 (PR #6) |
  | 同步更新 | ✅ `sync-all.sh` 批量推送 L2 更新到所有 L3 | 冲突解决需人工介入 |
- **结论**: fork 模型下 L0.3 的优先级**大幅下降** — 不再需要自建运行时租户隔离。重点转为**编排层**（多租户部署自动化）
- **预估工作量**: 小~中（编排脚本，非框架改造）

#### L0.4 统一消息协议扩展
- **PRD 来源**: 模块 A "统一由 Agent 接管，体验一致"
- **现状**: Feishu 和 Web 消息格式各异，channel_server 协议只有基础类型
- **目标**: 扩展 channel_server 协议支持
  - 新增消息类型: `takeover`, `suggestion`, `card_update`, `status_change`
  - 消息元数据: `conversation_id`, `tenant_id`, `state`, `assigned_to`
  - 渠道适配器抽象: 统一 `ChannelAdapter` 接口，Feishu/Web 各实现
- **建议位置**: `autoservice/protocol.py` + 改造 `feishu/channel_server.py`
- **预估工作量**: 中

---

### L1 · Agent 角色 & 运行时（高优先级）

> 依赖: L0.1 (状态机), L0.2 (事件总线)

#### L1.1 四角色 Agent 拆分
- **PRD 来源**: 模块 B "4 个专精角色"
- **现状**: 单一 Agent 通过 Skill prompt 切换行为，无角色隔离
- **v4 新基础**: CC Pool (`autoservice/cc_pool.py`) 已提供多实例管理能力——每个角色可分配独立的池化 Claude SDK 实例，配置不同 model/permission_mode/skill
- **目标**: 4 个独立角色定义
  | 角色 | 职责 | CC Pool 配置 |
  |------|------|-------------|
  | 客服 Agent | 知识库问答 + 反幻觉 + 多轮记忆 | model=sonnet, skill=customer-service |
  | 翻译 Agent | 语言检测 + 术语映射 + 双向翻译 | model=haiku, skill=translate |
  | 线索收集 Agent | 四要素提取 + 意向评估 | model=sonnet, skill=marketing |
  | 智能分流 Agent | 信心评估 + 对话摘要 + 团队匹配 | model=haiku, skill=triage |
- **关键设计**:
  - 角色定义为声明式 YAML（`agents/<role>/agent.yaml`）
  - 每角色对应一个 `CCPool` 实例，配置独立的 `PoolConfig`（model/max_size/skill）
  - 分流 Agent（haiku, 低延迟）作为入口，决定后续路由到哪个角色池
  - 复用 `socialware.pool.AsyncPool[T]` 泛型框架
- **预估工作量**: 中（CC Pool 已解决实例管理，剩余工作是角色定义+路由逻辑）

#### L1.2 快慢双模型架构
- **PRD 来源**: §1 核心差异点 "快慢双模型消除 AI 慢焦虑"，US-2.2 占位消息
- **需求 ID**: R-MSG-4 (占位消息+续写替换)
- **现状**: 单模型同步响应
- **v4 新基础**: CC Pool 的 `PoolConfig` 已支持按实例配置 `model` 参数——可以创建 haiku 池 (快) 和 sonnet 池 (慢)，天然实现双模型架构
- **目标**:
  - 快模型池（Haiku CCPool）: 意图识别、占位消息、简单问答（< 1s）
  - 慢模型池（Sonnet/Opus CCPool）: 复杂查询、知识库检索、推理（5-15s）
  - 续写机制: 快模型先发占位 → 慢模型结果替换（流式或编辑消息）
- **飞书实现 (v5 确认)**: **必须用卡片 PATCH** — v5 验证确认 PUT 仅支持 text/post，卡片更新只能走 `PATCH /im/v1/messages/:id`，且卡片 config 必须包含 `"update_multi": true`。14 天有效期限制对此场景无影响（对话通常远短于 14 天）
- **关键设计**:
  - `ModelRouter`: 根据查询复杂度选择快/慢池
  - 快池: `PoolConfig(model="haiku", min_size=4, max_size=8)` — 高并发低延迟
  - 慢池: `PoolConfig(model="sonnet", min_size=2, max_size=4)` — 低并发深度推理
  - 占位 = interactive 卡片（含 `update_multi:true`）初始状态 → 慢池完成后 `PATCH` 更新内容
  - 单消息 PATCH 限速 5 QPS — 占位续写仅需 1 次更新，无瓶颈
  - channel_server 协议增加 `update_message` 类型
- **建议位置**: `autoservice/model_router.py`
- **预估工作量**: 中（CC Pool 已解决实例管理，剩余工作是路由逻辑+占位续写集成）

#### L1.3 情绪识别
- **PRD 来源**: 模块 B "情绪识别"
- **现状**: 无
- **目标**: 对话级情绪标注（正面/中性/负面/愤怒）
  - 作为快模型的附加输出
  - 情绪恶化触发事件 → 可被升级规则消费
- **预估工作量**: 小（可作为快模型 prompt 的一部分）

---

### L2 · 人机协作层（核心差异化 — 中优先级）

> 依赖: L0.1 (状态机), L0.2 (事件总线), L0.4 (协议扩展), L1.1 (角色拆分)

#### L2.1 Copilot 协议 & 后端
- **PRD 来源**: 模块 C 全部，US-2.3 ~ US-2.6
- **需求 ID**: R-CMD-3 (对话监管窗), R-CMD-4 (副驾驶侧栏), R-MSG-5 (@mention)
- **现状**: 纯 AI 或纯人工，无协作模式
- **目标**: 实现 Agent driver / Human driver 双模式
  - Copilot 模式: Agent 生成草稿 → 人工可见但不发给客户 → 人工建议 → Agent 采纳后发送
  - Takeover 模式: 人工 driver → Agent 侧栏提供建议
  - 模式切换: `@人工` / `/hijack` 触发
- **飞书实现方案** (采纳自 upstream PR #6 Gap 1 方案 A):
  - **方案 A（推荐）· 飞书 Thread 承载监管对话**:
    | AutoService 概念 | 飞书 thread 实现 |
    |---|---|
    | 进行中对话卡片 | 分队群内的主消息（Card 2.0 流式卡片） |
    | 点开卡片进入监管 | 点击"回复话题"进入 thread |
    | 人工发给 Agent 的建议 | thread 内消息，channel_server 订阅后喂给 Agent |
    | Copilot 对客户不可见 | C 端不在飞书群内，thread 天然只对商户可见 |
    | Agent `@人工` 求助 | Agent 在 thread 内 @ 客服成员 |
    | `/hijack` 角色翻转 | 同一 thread 内，后端状态机切换主导方 |
    | 副驾驶侧栏 | 翻转后 Agent 退到 thread 内"只读建议"角色 |
  - **方案 B（备选）· 自建 H5 监管窗**: 仅在方案 A 被 spike 否决时采用
  - **v5 验证更新**: `reply_in_thread: true` 参数已确认存在且飞书+Lark 均支持。spike 从"验证 API 是否存在"降级为"实测 UI 体验和限额细节"（回复数上限、多端一致性、生命周期事件）
- **关键设计**:
  - 对话状态机的 `CopilotMonitoring` / `HumanTakeover` 状态驱动
  - 三方消息流: 客户 ↔ Agent ↔ 人工（人工-Agent 通道 = 飞书 thread，对客户不可见）
  - thread 消息语义由后端状态机解释（同一条 thread 回复在不同状态下含义不同）
- **预估工作量**: 中（方案 A 生效时）/ 大（降级到方案 B 时）

#### L2.2 Agent 分队频道 & 实时卡片
- **PRD 来源**: US-2.3 "Agent 接洽后在分队频道发实时卡片"
- **需求 ID**: R-CHAT-2 (分队频道), R-MSG-3 (流式刷新卡片), R-MSG-6 (未读徽章), R-CHAT-4 (成员变更)
- **现状**: 无分队概念
- **目标**:
  - 每位人工客服关联 N 个 Agent 实例
  - 分队频道内展示实时对话卡片（摘要 + 状态 + 未读数）
  - 卡片内容由事件总线驱动更新
- **飞书实现 (v5 确认)**:
  - 1 分队 = 1 飞书群，**建议使用 `group_message_type: "thread"` 创建原生话题群**，所有消息天然以 thread 组织
  - 建群: `POST /im/v1/chats`，初始 ≤50 用户 + 5 Bot，权限 `im:chat:create`
  - 加人: `POST /im/v1/chats/:chat_id/members`，每次 ≤50 人
  - 每个对话 = 群内 1 条 interactive 卡片（含 `update_multi:true`，主消息）+ 对应 thread（监管通道）
  - 未读数 = 飞书客户端原生维护 (R-MSG-6)，无需开发
  - 成员变更 = 订阅 `im.chat.member.user.added/deleted` 事件 (R-EVT-3)
  - ⚠️ 卡片 PATCH 限速: 单消息 5 QPS；14 天有效期（Gap 7）
  - ⚠️ 单群消息限速: 5 QPS 全群共享（Gap 8）
- **关键设计**:
  - `Squad` 数据模型: `{human_id, agent_ids[], chat_id, active_conversations[]}`
  - 卡片模板: 对话摘要 + 客户类型 + 情绪标签 + "回复话题"入口
  - 利用已有的 channel_server admin group 能力扩展
- **预估工作量**: 中（飞书建群+卡片替代自建 UI）

#### L2.3 人工接管超时回退
- **PRD 来源**: US-2.5 "180s 未接单，卡片退回 Agent"
- **现状**: `escalation.yaml` 定义了升级流程但无超时机制
- **目标**:
  - 180s 计时器（可配置）
  - 超时后: 状态回退到 AgentHandling + 向客户发安抚消息
  - 事件: `human.timeout` → 可触发告警
- **预估工作量**: 小（依赖 L0.1 状态机 + L0.2 事件）

---

### L3 · 商户自助 & 可观测（中低优先级）

> 依赖: L0.3 (多租户), L1.1 (角色拆分), L2.1 (Copilot)

#### L3.1 自助上线向导
- **PRD 来源**: Epic 1 全部 (US-1.1 ~ US-1.4)
- **现状**: 手动 fork + `make setup` + 编辑配置文件
- **目标**: Web 向导 4 步上线
  1. 上传资料（官网 URL + PDF/CSV）→ 自动解析生成 Agent 配置
  2. 权限勾选 → 自动创建 IM 管理群
  3. 虚拟客户预演 → 逐条审阅
  4. 合规预检 → 沙箱开放
- **预估工作量**: 特大

#### L3.2 运营仪表盘
- **PRD 来源**: Epic 3 (US-3.1)
- **现状**: 无
- **目标**:
  - 顶部: 4 Agent 状态 + 今日处理量
  - 中部: 3 个计费指标（接管次数 / CSAT / 升级转结案率）+ 3 个辅助指标
  - 底部: 趋势图 + 人工 Leaderboard
  - 时间切片: 今日 / 本周 / 本月 / 本季度
- **依赖**: 需要先有指标采集（基于 L0.2 事件总线）
- **预估工作量**: 大

#### L3.3 管理群命令
- **PRD 来源**: US-3.2 (`/status`, `/dispatch`, `/review`)
- **现状**: channel_server 有 admin group 通知能力，但无命令处理
- **目标**:
  - `/status` — 返回所有进行中对话列表
  - `/dispatch <chat_id> <agent>` — 派单
  - `/review` — 昨日统计
- **预估工作量**: 中（可基于 channel_server admin group 扩展）

#### L3.4 SLA 监控 & 告警
- **PRD 来源**: US-3.3 + §6 SLA 表
- **现状**: 无
- **目标**:
  - 指标采集: 首屏应答、占位延迟、人工接单等待、首次回复
  - 5 分钟滚动窗口检测
  - 超阈值自动推送告警到管理群
- **预估工作量**: 中

---

### L4 · 产品化运营（低优先级 — 长期目标）

> 依赖: L2 + L3 大部分完成

#### L4.1 Dream Engine 闲时学习
- **PRD 来源**: Epic 4 全部 (US-4.1 ~ US-4.4)
- **现状**: 完全未实现
- **目标**:
  - 白天: 对话写入临时记忆池
  - 低峰: 自动回放 → 抽取经验 → 发现盲区
  - 晨起: 提案卡片推送到管理群
  - 灰度: 5% → 25% → 100% 渐进上线
  - 回滚: `/rollback <proposal_id>`
- **子任务**:
  - L4.1.1 临时记忆池 (对话 embedding + 标注)
  - L4.1.2 回放引擎 (经验抽取 pipeline)
  - L4.1.3 提案管理 (生成/审核/灰度/回滚)
  - L4.1.4 学习规则配置 (管理群对话式 UI)
- **预估工作量**: 特大

#### L4.2 合规引擎
- **PRD 来源**: US-1.4 + §7 "GDPR/CCPA/个保法"
- **现状**: 无
- **目标**:
  - 按商户目标客户地区自动匹配合规检查项
  - 沙箱不阻塞，对外开放前必须全部通过
  - 合规策略模板下发（平台预置 + 商户叠加）
- **预估工作量**: 大

#### L4.3 计费引擎
- **PRD 来源**: §6 计费指标
- **现状**: 无
- **目标**:
  - 接管次数（角色翻转完成次数）阶梯计费
  - CSAT / 升级转结案率 作为 SLA 约束
  - 租户级用量统计 + 账单生成
- **预估工作量**: 大

#### L4.4 多渠道扩展
- **PRD 来源**: §9 "IM 渠道 SDK（微信/WhatsApp/Slack 等）"
- **现状**: 仅飞书
- **目标**: 统一 `ChannelAdapter` 接口，逐步接入:
  - Phase 1: Slack
  - Phase 2: WhatsApp Business API
  - Phase 3: 微信客服 / 企业微信
- **依赖**: L0.4 统一消息协议
- **预估工作量**: 每渠道中等

---

## 四、基于飞书能力的实施策略重评估

纳入飞书原生能力后，各层的**实施策略和工作量**发生显著变化：

### 工作量对比：自建 vs 飞书原生

| 需求项 | 纯自建预估 | 借助飞书后预估 | 节省 | 飞书方案 |
|--------|-----------|---------------|------|---------|
| L1.2 占位消息续写 | 大（需自建消息更新协议+前端） | **小** | ~70% | `PATCH /im/v1/messages/{id}` 原地更新 |
| L2.2 实时对话卡片 | 大（需自建卡片组件+WebSocket推送） | **中偏小** | ~60% | interactive 卡片 (含 `update_multi:true`) + `PATCH /im/v1/messages/:id` 更新 |
| L2.1 Copilot 人工建议 | 大 | **中** | ~40% | 分队群内人工直接回复 → Bot 转发给 Agent；卡片按钮触发 `/hijack` |
| L3.3 管理群命令 | 中 | **小** | ~60% | 飞书 Bot 命令注册 + channel_server 命令路由已有雏形 |
| L3.2 运营仪表盘 MVP | 大 | **中偏小** | ~50% | 多维表格(Bitable) API 写入指标 + 共享仪表盘视图 |
| L3.4 SLA 告警 | 中 | **小** | ~50% | 事件检测 → 飞书群/加急消息推送 |
| L4.3 提案审核 | 大 | **中偏小** | ~50% | 审批流(Approval)定义模板 + 回调处理 |
| L0.2 事件总线 | 中 | **中** | ~20% | 飞书 Webhook 事件订阅覆盖部分场景，但内部编排仍需自建 |
| L0.1 对话状态机 | 中 | **中** | ~0% | 纯业务逻辑，飞书无法替代 |
| L0.3 多租户隔离 | 大 | **大** | ~0% | 纯架构问题，飞书无法替代 |

### 三维度综合评估

#### 维度一 · 功能完备性

**飞书强覆盖区（可直接复用，少量胶水代码）：**
- 消息交互层: 卡片(CardKit) + 消息更新(PATCH) + Reaction + 富文本 → 覆盖 PRD 中几乎所有客户端 UI 交互
- 协作层: 群组管理 + Bot 命令 + @提及 → 覆盖"分队频道"和"管理群命令"的载体
- 审批层: 审批流 → 覆盖"提案审核"的 UI 和流转

**飞书弱覆盖区（需自建核心逻辑）：**
- 对话状态机 — 纯业务状态管理，飞书不涉及
- Agent 编排 — 4 角色拆分、快慢双模型路由、子代理管线
- Dream Engine — 回放/抽取/灰度/回滚的完整 pipeline
- 多租户隔离 — 数据路径/上下文/配置的租户级切分
- 计费引擎 — 用量统计和账单

**飞书不覆盖区（PRD 需求中飞书无对应）：**
- PSTN 语音接入
- 非飞书 IM 渠道（微信/WhatsApp/Slack）
- 合规引擎（GDPR/CCPA/个保法 规则库）
- Web 端自助上线向导

#### 维度二 · 接入便捷性

**即插即用（1-3 天）：**
| 能力 | 接入方式 | 当前基础 |
|------|---------|---------|
| 消息更新 (PATCH) | 调 `im.v1.message.patch`，传 `message_id` + 新内容 | channel_server 已追踪 `message_id` |
| 扩展斜杠命令 | 飞书开放平台注册命令 → 复用 channel_server 命令解析 | 已有 `/improve` `/status` 等命令处理框架 |
| 加急消息 | `im.v1.message.create` 加 `urgent` 参数 | 消息发送已封装 |
| Reaction 扩展 | 增加 emoji 类型（如 🔴 = 升级中） | Reaction 增删已完整实现 |

**中等接入（1-2 周）：**
| 能力 | 接入方式 | 难点 |
|------|---------|------|
| 消息卡片 | 构建 interactive JSON (含 `update_multi:true`) → `POST /im/v1/messages` 发送 | 卡片 JSON schema 较复杂，需定义模板 |
| 卡片更新 | `PATCH /im/v1/messages/:message_id` (v5 确认) | 单消息 5 QPS，14 天有效期，仅 interactive 类型 |
| 卡片按钮回调 | 飞书开放平台配置回调 URL → channel_server 增加 HTTP 端点 | channel_server 目前是纯 WebSocket，需加 HTTP |
| 程序化建群 | `POST /im/v1/chats` + `POST /im/v1/chats/:id/members`；支持 `group_message_type:"thread"` 话题群 | 权限 `im:chat:create` + `im:chat.members:write_only` |
| Bitable 写入 | `POST /bitable/v1/apps/:token/tables/:id/records` (v5 确认: 50 QPS) | 需先手动创建 Bitable 表模板 |

**较重接入（2-4 周）：**
| 能力 | 接入方式 | 难点 |
|------|---------|------|
| 审批流 | 定义审批模板 → 创建实例 → 监听回调 | 审批模板需在管理后台配置，API 交互多步 |
| Helpdesk 集成 | 创建服务台 → 定义工单模板 → 事件订阅 | API 复杂度高，需额外权限 |
| Webhook 事件扩展 | 注册更多事件类型（消息已读、群成员变更等） | 需修改 channel_server 事件分发器 |

#### 维度三 · 运维便利性

**飞书托管 = 零运维的部分：**
- 卡片渲染和交互 — 飞书客户端原生渲染，无需自建前端服务器
- 群组生命周期 — 创建/归档/成员管理由飞书平台管理
- 审批流状态 — 催办/抄送/审计记录由飞书管理
- 消息存储 — 飞书保留消息历史，无需自建消息持久化
- 文件存储 — 上传的文件由飞书 Drive 托管

**仍需自建运维的部分：**
- channel_server 进程管理（已有但需增强健壮性）
- 对话状态和会话持久化（SQLite）
- 知识库索引（FTS5 数据库）
- 指标采集和聚合（写入 Bitable 之前的计算）
- Dream Engine 调度器

**运维风险点：**
- 飞书 API 限流 — 消息发送 50 QPS / 应用，卡片更新有单独限流
- 飞书服务可用性 — 依赖外部服务，需做降级方案
- 卡片回调延迟 — 飞书回调有偶发延迟，影响实时性

---

## 五、更新后的推荐实施路线图

> v3 更新：加入 thread spike 作为 Phase 0 前置验证；Phase 3 工作量因 thread 方案进一步缩减

```
Phase 0 — 前置验证 spike (0.5-1 week)
├── 飞书 Thread API spike            ★★★ 阻塞 L2.1 方案选型（Gap 1）
│   └─ 发主消息 → 回话题 → 订阅事件 → 确认 5 条待核实项
│      1. thread API 具体字段名与幂等行为
│      2. thread 内消息速率是否独立计算
│      3. 单主消息可挂 thread 回复数量上限
│      4. 桌面/移动客户端 thread UI 一致性
│      5. thread 生命周期事件（删除/折叠）可否订阅
├── 流式卡片刷新压测               ★★☆ 确认 R-MSG-3 限额（Gap 2）
└── PATCH message 视觉验证          ★☆☆ 确认 R-MSG-4 连续性（Gap 3）

Phase 1 — 基础框架 + 飞书能力接入 (2-3 weeks)  ← v4 缩短：flow/CRM 已有基础
├── L0.1 对话状态机                ★★★ 消费现有 flows/ + crm.py conversations 表
├── L0.2 事件总线（精简版）         ★★★ 进程内 pub/sub + 飞书 Webhook
├── 飞书消息卡片模板开发            ★★★ 对话摘要卡、状态卡、告警卡
├── 飞书消息更新(PATCH/流式卡片)    ★★☆ 占位续写基础（基于 spike 结论选型）
└── L1.3 情绪识别                  ★☆☆ prompt 扩展，快速胜利

Phase 2 — Agent 运行时 (2-4 weeks)  ← v4 缩短：CC Pool 已解决实例管理
├── L1.1 四角色 Agent 拆分          ★★★ 每角色 = 独立 CCPool（model/skill 配置化）
├── L1.2 快慢双模型 + 占位续写       ★★★ haiku池 + sonnet池 + 流式卡片
├── L3.3 管理群命令扩展             ★★☆ 飞书 Bot 命令（R-CMD-1），低成本
└── L0.4 消息协议扩展              ★★☆

Phase 3 — 人机协作 MVP (3-5 weeks)
├── L2.1 Copilot (thread 方案)      ★★★ 核心差异化
│   └─ 飞书 thread 承载监管+建议+翻转，零前端
├── L2.2 分队频道 + 实时卡片         ★★☆ 飞书建群 + Card 2.0 + thread
├── L2.3 接管超时回退               ★☆☆
└── L3.4 SLA 监控(飞书群告警)       ★☆☆ 事件检测 → 加急消息

Phase 4 — 可观测 & 提案 (3-5 weeks)
├── L3.2 运营仪表盘 MVP             ★★☆ Bitable API 写指标 + 共享视图
├── L4.1.3 提案审核                 ★★☆ 飞书审批流 (R-CMD-2)
├── L0.3 多租户编排                 ★☆☆ 部署自动化（fork 隔离已解决数据层）
└── L3.1 自助上线向导(简化版)        ★☆☆ 管理群对话式引导 + create-tenant.sh

Phase 5 — 产品化 (6-10 weeks)
├── L4.1 Dream Engine 完整版        ★★☆
├── L4.2 合规引擎                   ★★☆
├── L4.3 计费引擎                   ★☆☆
└── L4.4 多渠道扩展                 ★☆☆ 含 Gap 5 飞书/Lark 双端适配 + channels/ L1 提取
```

### vs 原路线图的变化

| 变化 | v1 纯自建 | v2 飞书加速 | v3 整合 PR #6 | **v4 三层架构+CC Pool** | 说明 |
|------|----------|-----------|--------------|------------------------|------|
| Phase 0 | — | — | +0.5-1 周 | **+0.5-1 周** | thread/卡片/PATCH spike |
| Phase 1 | 4-6 周 | 3-4 周 | 3-4 周 | **2-3 周** | flow/CRM 已有基础，状态机可消费 |
| Phase 2 | 4-6 周 | 3-5 周 | 3-5 周 | **2-4 周** | CC Pool 解决实例管理，角色=配置 |
| Phase 3 | 6-8 周 | 4-6 周 | 3-5 周 | **3-5 周** | 不变 |
| Phase 4 | 4-6 周 | 3-5 周 | 3-5 周 | **3-5 周** | 多租户编排替代运行时隔离 |
| **总计** | **22-32 周** | **16-24 周** | **13-21 周** | **11-19 周** | **节省约 45-50%** |

---

## 六、关键依赖图

> v4 更新：CC Pool 和 CRM 作为已有基础设施纳入；多租户由 fork 隔离解决

```
L4.1 Dream Engine ──┐
L4.2 合规引擎 ──────┤
L4.3 计费引擎 ──────┼── L3.x (可观测/自助)
L4.4 多渠道 ────────┘        │
  (Gap 5 飞书/Lark            │
   + channels/ L1 提取)       ▼
              L2.1 Copilot ← L2.2 分队 ← L2.3 超时
              (飞书 thread    (飞书建群+
               方案 A)        Card 2.0)
                    │
                    ├── Phase 0 spike 结论
                    │
         ┌──────────┼──────────┐
         ▼          ▼          ▼
    L1.1 角色   L1.2 双模型   L1.3 情绪
    (CCPool      (haiku池+     (prompt)
     per-role)    sonnet池)
         │          │
         ▼          ▼
    L0.1 状态机 ← L0.2 事件总线     L0.4 协议扩展
    (flows/+crm)  (自建+飞书Webhook)
                                  ┌───────────────────────┐
                                  │ ████ v4 已有基础 ████   │
                                  │ CC Pool (socialware    │
                                  │   .pool + cc_pool)     │
                                  │ CRM SQLite (crm.py)    │
                                  │ 声明式 Flow×6 定义     │
                                  │ 三层 fork 租户隔离     │
                                  │ channel_server 多实例  │
                                  │ 身份系统 identity.yaml │
                                  └───────────────────────┘
```

---

## 七、Quick Wins（可立即开始，不依赖新框架）

这些改进可以在不等待底层重构的情况下先行推进：

| # | Quick Win | 飞书能力 | 工作量 | 效果 |
|---|-----------|---------|--------|------|
| 1 | 管理群 `/status` `/review` 命令 | Bot 命令 + 富文本回复 | 1-2 天 | 管理员无需进后台 |
| 2 | 消息更新(PATCH)接入 | `im.v1.message.patch` | 1 天 | 为占位续写打基础 |
| 3 | 对话摘要卡片 | CardKit 交互式卡片 | 2-3 天 | 管理群内可视化当前对话 |
| 4 | 情绪标注 | Skill prompt 扩展 | 0.5 天 | 为升级规则提供信号 |
| 5 | 升级加急通知 | `urgent` 消息 + @指定人工 | 1 天 | 人工不会漏接升级 |
| 6 | 对话摘要持久化 | session.py 扩展 | 1-2 天 | 为仪表盘/Dream Engine 打基础 |

**建议第一步**: Phase 0 spike（thread + 流式卡片 + PATCH 三合一验证），耗时 0.5-1 周，决定 L2.1 的技术方案。spike 通过后立即做 #3 (对话摘要卡片) 和 #2 (消息更新)，组合起来让管理群从"纯文本流"升级为"可交互的对话监控面板"。

---

## 八、飞书能力接入的技术注意事项

### 需要额外申请的飞书应用权限
- `im:message:send_as_bot` — 已有
- `im:message:patch` — **需新增**（消息更新 / R-MSG-4）
- `im:message:reply_in_thread` — **需新增**（话题回复 / R-CMD-3, R-CMD-4）⚠️ 权限名待 spike 确认
- `im:chat:create` — **需新增**（程序化建群 / R-CHAT-1, R-CHAT-2）
- `im:chat:member:create` — **需新增**（群加人）
- `im:chat.member:event` — **需新增**（成员变更事件 / R-EVT-3）
- `bitable:app:table:record:write` — **需新增**（Bitable 写入）
- `approval:instance:create` — **需新增**（审批流 / R-CMD-2）
- `contact:user.base:readonly` — 已有

### 多租户部署模式选择（来自 PR #6 R-OPS-3）
- **推荐: 飞书商店应用模式** — 每企业独立授权安装，租户级数据隔离由飞书平台保障
- 租户侧授权走"应用商店一键安装"流程（通常秒级），缓解 Gap 4（权限审批阻塞 ≤2h 上线）
- 数据层隔离仍需自建 `autoservice/tenant.py`（L0.3）

### 飞书 vs Lark 地区割裂应对（来自 PR #6 Gap 5）
- **短期**: 锁定首发客群为单一地区，只维护飞书一套
- **中期**: `autoservice/channel/im/` 抽象层，飞书和 Lark 共用 90% 代码，仅 host/auth 差异化
- **长期**: 双端身份映射（AutoService user ID → Feishu user + Lark user 双绑定）

### channel_server 需要的架构变更
当前 `channel_server.py` 是纯 WebSocket 服务。为接收飞书卡片按钮回调，需要增加一个 HTTP 端点：
```
channel_server.py
├── WebSocket server (:9999)  — 已有，实例路由
└── HTTP server (:9998)       — 新增，接收飞书卡片/审批回调
```
建议复用 FastAPI（web/app.py 已有依赖），挂载为 channel_server 的子模块。

### API 限流预算（v5 官方文档验证）

> 完整限流矩阵见 `2026-04-14-feishu-api-verification.md` §五

- 消息发送/回复: 全局 1000/分 50/秒；**单用户 5 QPS，单群 5 QPS**（群内所有 Bot 共享）
- 消息编辑 (PUT text/post): 全局 1000/分 50/秒；**单消息最多 20 次**
- 卡片更新 (PATCH interactive): 全局 1000/分 50/秒；**单消息 5 QPS**；**14 天有效期**；30KB 上限
- Thread 回复: 与消息发送共享配额（单群 5 QPS）
- 建群/加人: 全局 1000/分 50/秒 — 无瓶颈
- 审批实例创建: **100/分** — 批量提案需限速
- Bitable 记录写入: **50/秒** — 指标写入无瓶颈

---

---

## 九、参考文档

- `docs/prd/AutoService-PRD.md` — 产品级 PRD v1.0（upstream PR #6 引入）
- `docs/prd/AutoService-UserStories.md` — 17 stories × 4 epics
- `docs/prd/im-requirements-analysis.md` — IM 需求清单 + 飞书三维评估 v0.2（upstream PR #6）
- `docs/prd/autoservice-full-journey.html` — 交互原型
- upstream PR #6 讨论: thread 方案由 @allenwoods 提出，@FatNine 评估并采纳为方案 A

---

*文档所有者: AutoService Team · 基于 PRD v1.0 gap analysis + 飞书能力评估 + upstream PR #6 IM 分析*
