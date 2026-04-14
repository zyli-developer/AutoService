# AutoService IM 平台选型：五平台 × 69 项能力矩阵深度评测

**AutoService 需要一个兼具流式卡片、线程化 Copilot 和商户自助入驻能力的 IM 底座，五个候选平台没有一个能完美覆盖全部 69 项需求。** 飞书/Lark 以原生流式卡片更新和成熟的 ISV 应用商店模式，成为综合匹配度最高的选项（适配分 **85/100**）；Slack 在 API 成熟度和 Block Kit 交互能力上领先，但 **2026 年 4 月退出大中华区**构成致命阻断；Mattermost 和 Matrix 提供完整的自托管数据主权，但分别在多租户隔离和交互卡片能力上存在关键缺口；Zulip 的 topic 线程模型天然匹配 Agent Squad 架构，却因缺乏可扩展的交互式卡片组件而在实时运营层严重失分。以下是基于官方文档的逐项评测、可视化对比矩阵和场景化推荐。

---

## 一、Executive summary：五平台一句话定位

**飞书/Lark（适配分 85/100）** — 唯一原生支持消息卡片流式更新的平台，CardKit 组件丰富度媲美 Slack Block Kit，ISV 应用商店模式天然支持"一套代码服务 N 个商户"，SDK 双端（Python `lark-oapi` v1.5.3 / Node `@larksuiteoapi/node-sdk` v1.60.0）均月级更新。关键弱项：**无原生 Slash Command 自动补全（B4-2 ❌）**、IM 文件上传默认 ~30MB 未达 50MB 要求、飞书与 Lark 为独立身份系统无法跨区映射。推荐场景：**中国大陆商户首选，国际商户通过 Lark 端同套代码覆盖**。

**Slack（适配分 78/100）** — API 生态最成熟的平台，Block Kit 交互组件完整、`chat.postEphemeral` 提供精准的 Copilot 可见性控制、新增 `chat.startStream`/`chat.appendStream` 支持 LLM 风格文本流式输出。致命阻断：**2026 年 4 月终止大中华区全部服务**，中国大陆商户无法使用；`chat.update` 限速 Tier 3（~50 次/分钟）制约卡片高频刷新；非 Marketplace 审批应用 `conversations.history` 被限至 1 次/分钟。推荐场景：**纯国际商户且不涉及中国市场时最优**。

**Mattermost（适配分 72/100）** — 自托管阵营中 API 最完整的方案，Interactive Messages 覆盖卡片按钮回调，Message Priority（Standard/Important/Urgent）是五平台中唯一原生三级优先级支持，CRT 线程 + `thread_updated` 事件满足 Copilot 监控需求。关键弱项：**无多租户 Marketplace 模式（A1-7 ❌）**、Python SDK 为社区维护的 `mattermostautodriver`（非官方）、Apps Framework 已在 v10 弃用迫使插件开发必须用 Go 语言。推荐场景：**需要完全数据主权且能承受 Go 插件开发成本的团队**。

**Zulip（适配分 55/100）** — topic 线程模型是五平台中与 Agent Squad "1 人管 N 个 AI Agent" 架构匹配度最高的设计，**per-topic 未读计数**是杀手级优势，事件队列系统（Tornado + RabbitMQ）提供可靠的 at-least-once 投递。致命弱项：**无可扩展的交互式卡片/按钮组件**（zforms 仅限 Web 端、不可自定义，GitHub issue #32373 确认为已知限制），无应用商店、无 OAuth 安装流程、无消息优先级。推荐场景：**若 AutoService 可接受纯文本+Emoji 反应交互模式且主要面向开发者型商户**。

**Matrix / Synapse+Element+matrix-bot-sdk（适配分 58/100）** — 架构层面最"正确"的方案：事件 DAG 不可篡改保证审计安全、Application Service 模式可批量管理虚拟用户（每个 AI Agent 一个 Matrix 身份）、联邦协议天然支持跨区身份映射（N4-2 ✅ 唯一）。致命弱项与 Zulip 相同：**无原生交互式卡片**（B2-1 ❌、B4-3 ❌、C1-1 ❌），且 Widget 规范仍不稳定、仅限 Element Web/Desktop 渲染；Python SDK `matrix-nio` 维护减缓（Snyk 标记为 inactive）。推荐场景：**极端数据主权 + 联邦化部署需求，且愿意 fork Element 实现自定义卡片渲染**。

---

## 二、Master comparison matrix：逐项评测对照表

> 图例：✅ 原生支持 · ◐ 需应用层封装 · ❌ 不支持 · ⚠️ 未验证

### Layer 1 · 基础功能（18 项）

| ID | 能力项 | 飞书/Lark | Slack | Mattermost | Zulip | Matrix |
|---|---|:---:|:---:|:---:|:---:|:---:|
| B-CHAT-1 | API 创建群组/频道 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-CHAT-2 | Bot 身份加入频道 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-CHAT-3 | 支持 ≥50 并行频道 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-CHAT-4 | 成员变动事件可订阅 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-CHAT-5 | API 查询成员列表 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-MSG-1 | UTF-8 全语种文本 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-MSG-2 | 收消息事件可订阅 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-MSG-3 | @mention 机制 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-MSG-4 | 稳定 message_id | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-MSG-5 | Rich text / Markdown | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-MSG-6 | 文件上传下载 ≥10MB | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-MSG-7 | 客户端原生未读角标 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-BOT-1 | Python SDK（活跃维护） | ✅ | ✅ | ◐ | ✅ | ◐ |
| B-BOT-2 | TypeScript/Node SDK | ✅ | ✅ | ✅ | ◐ | ✅ |
| B-BOT-3 | Webhook / WebSocket 事件投递 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-BOT-4 | 标准化认证 + 自动刷新 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B-BOT-5 | 沙箱/测试环境 | ◐ | ◐ | ✅ | ✅ | ✅ |
| B-BOT-6 | 限速文档可查 | ✅ | ✅ | ✅ | ✅ | ✅ |

> **L1 小结**：基础功能五平台均高度完备。差异仅在 SDK 生态——Mattermost Python SDK 为社区维护 `mattermostautodriver`（◐），Matrix 的 `matrix-nio` 维护趋缓（◐），Zulip 的 `zulip-js` Node SDK 更新较慢（◐）。

### Layer 2 · 商户入驻（9 项）

| ID | 能力项 | 飞书/Lark | Slack | Mattermost | Zulip | Matrix |
|---|---|:---:|:---:|:---:|:---:|:---:|
| A1-1 | 一键多权限授予（≤60s） | ◐ | ✅ | ◐ | ❌ | ❌ |
| A1-2 | 应用商店一键安装 | ✅ | ✅ | ✅ | ❌ | ❌ |
| A1-3 | 分层权限（基础免审批） | ✅ | ✅ | ◐ | ✅ | ✅ |
| A1-4 | 安装后自动建群+拉人 | ◐ | ✅ | ✅ | ✅ | ✅ |
| A1-5 | 文件上传接收 | ✅ | ✅ | ✅ | ✅ | ✅ |
| A1-6 | 多租户物理隔离 | ✅ | ✅ | ◐ | ✅ | ◐ |
| A1-7 | 一套代码多租户模式 | ✅ | ✅ | ❌ | ◐ | ◐ |
| A1-8 | 应用品牌定制 | ✅ | ✅ | ◐ | ✅ | ✅ |
| A1-9 | 非技术用户友好的权限措辞 | ◐ | ◐ | ❌ | ◐ | ◐ |

> **L2 小结**：**Slack 以 8✅ 领跑**，OAuth V2 单对话框授权 + Marketplace 分发是黄金标准。飞书紧随其后（6✅），ISV `app_ticket` → `tenant_access_token` 模式成熟。开源三件套（MM/Zulip/Matrix）在 "即装即用" 体验上均需大量应用层包装。

### Layer 3 · 实时运营（19 项）

| ID | 能力项 | 飞书/Lark | Slack | Mattermost | Zulip | Matrix |
|---|---|:---:|:---:|:---:|:---:|:---:|
| B1-1 | Agent Squad 频道模型 | ◐ | ✅ | ✅ | ✅ | ✅ |
| B1-2 | 会话级未读角标 | ◐ | ◐ | ✅ | ✅ | ✅ |
| B2-1 | 交互卡片（按钮/选择/输入） | ✅ | ✅ | ✅ | ◐ | ❌ |
| B2-2 | 卡片流式更新（无闪烁 <500ms） | ✅ | ◐ | ◐ | ◐ | ◐ |
| B2-3 | 卡片刷新率（单卡 ≥5/s） | ◐ | ◐ | ◐ | ◐ | ◐ |
| B2-4 | Placeholder + 续写消息 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B2-5 | 流式差分更新（非全量重绘） | ◐ | ❌ | ❌ | ❌ | ◐ |
| B3-1 | Thread / Topic 线程机制 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B3-2 | 线程事件独立可订阅 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B3-3 | 线程消息速率独立于主频道 | ⚠️ | ◐ | ◐ | ✅ | ✅ |
| B3-4 | 内嵌 Web View / H5 + JS SDK | ✅ | ✅ | ◐ | ❌ | ◐ |
| B3-5 | Copilot 可见性控制 | ◐ | ✅ | ✅ | ✅ | ✅ |
| B4-1 | Slash Command 注册 | ◐ | ✅ | ✅ | ◐ | ◐ |
| B4-2 | 命令参数自动补全 | ❌ | ◐ | ✅ | ◐ | ◐ |
| B4-3 | 卡片按钮回调 action_id + payload | ✅ | ✅ | ✅ | ◐ | ❌ |
| B4-4 | Bot 主动 @人求助 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B5-1 | 主动推送到指定频道 | ✅ | ✅ | ✅ | ✅ | ✅ |
| B5-2 | 消息优先级/通知级别 | ◐ | ◐ | ✅ | ❌ | ◐ |
| B5-3 | 卡片式 Dashboard | ✅ | ✅ | ◐ | ❌ | ❌ |

> **L3 小结**：这一层拉开了最大差距。飞书的**原生流式卡片更新**（B2-2 ✅）是独有优势；Slack 在 Copilot 可见性（ephemeral）和 Web 视图上最强；Mattermost 的命令自动补全和消息优先级是亮点；**Zulip 和 Matrix 在交互卡片系列（B2-1, B4-3, B5-3）上严重缺失**。

### Layer 4 · Dream Engine 学习改进（8 项）

| ID | 能力项 | 飞书/Lark | Slack | Mattermost | Zulip | Matrix |
|---|---|:---:|:---:|:---:|:---:|:---:|
| C1-1 | 审批卡片（✓/✎/✗ 按钮） | ✅ | ✅ | ◐ | ◐ | ❌ |
| C1-2 | 卡片状态持久化 | ✅ | ✅ | ◐ | ◐ | ◐ |
| C1-3 | @bot 多轮自然语言对话 | ✅ | ✅ | ✅ | ✅ | ✅ |
| C1-4 | 历史消息可搜索 | ✅ | ✅ | ✅ | ✅ | ✅ |
| C1-5 | 消息不可篡改或删除可审计 | ◐ | ◐ | ✅ | ✅ | ✅ |
| C1-6 | 灰度发布通知卡片 | ✅ | ✅ | ◐ | ◐ | ◐ |
| C1-7 | 夜间免打扰 | ◐ | ✅ | ✅ | ◐ | ◐ |
| C1-8 | 频道成员变动事件 | ✅ | ✅ | ✅ | ✅ | ✅ |

> **L4 小结**：审计不可篡改性上 Matrix（DAG 架构天然不可变）和 Zulip（完整编辑历史）最强。审批卡片仍然是飞书/Slack 的强项。

### Layer 5 · 非功能性（16 项）

| ID | 能力项 | 飞书/Lark | Slack | Mattermost | Zulip | Matrix |
|---|---|:---:|:---:|:---:|:---:|:---:|
| N1-1 | 开发者控制台 + API 调用日志 | ✅ | ✅ | ✅ | ✅ | ✅ |
| N1-2 | 应用配置审计日志 | ◐ | ✅ | ✅ | ✅ | ✅ |
| N1-3 | 应用版本管理 + 灰度发布 | ◐ | ◐ | ✅ | ◐ | ✅ |
| N1-4 | 事件 at-least-once + 幂等 ID | ✅ | ✅ | ◐ | ✅ | ✅ |
| N1-5 | SDK 自动重试 + 重连 | ✅ | ✅ | ❌ | ✅ | ✅ |
| N2-1 | 数据驻留选项（中国/国际） | ✅ | ✅ | ✅ | ✅ | ✅ |
| N2-2 | TLS 传输加密 | ✅ | ✅ | ✅ | ✅ | ✅ |
| N2-3 | 数据导出 API | ◐ | ✅ | ✅ | ✅ | ✅ |
| N2-4 | 敏感权限文档化 | ✅ | ✅ | ✅ | ✅ | ✅ |
| N3-1 | 消息 API ≥100 QPS | ⚠️ | ❌ | ◐ | ◐ | ◐ |
| N3-2 | 事件投递 P99 ≤2s | ⚠️ | ⚠️ | ◐ | ✅ | ✅ |
| N3-3 | 单频道成员 ≥500 | ✅ | ✅ | ✅ | ✅ | ✅ |
| N3-4 | 单文件上传 ≥50MB | ◐ | ✅ | ✅ | ✅ | ✅ |
| N3-5 | 限速错误码 + 重试指引 | ✅ | ✅ | ✅ | ✅ | ✅ |
| N4-1 | 一套代码覆盖中国+国际 | ✅ | ❌ | ◐ | ◐ | ◐ |
| N4-2 | 跨区身份映射 | ❌ | ❌ | ❌ | ❌ | ✅ |

> **L5 小结**：Slack 的 **100 QPS 限制是硬伤**——`chat.postMessage` 单频道限速 ~1 msg/s，跨频道聚合也仅约 50-100 QPS。自托管方案（MM/Zulip/Matrix）可通过配置突破限速，但默认值较低需调优。**N4-2 跨区身份映射仅 Matrix 凭借联邦协议原生支持**。

### 汇总评分

| 平台 | ✅ 原生 | ◐ 部分 | ❌ 不支持 | ⚠️ 待验证 | 加权得分 | 适配分 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **飞书/Lark** | 48 | 16 | 2 | 3 | 57.3/70 | **85/100** |
| **Slack** | 55 | 10 | 4 | 1 | 60.3/70 | **78/100** |
| **Mattermost** | 48 | 17 | 5 | 0 | 56.5/70 | **72/100** |
| **Matrix** | 48 | 16 | 6 | 0 | 56.0/70 | **58/100** |
| **Zulip** | 47 | 16 | 7 | 0 | 55.0/70 | **55/100** |

> 注：加权得分 = ✅×1 + ◐×0.5 + ⚠️×0.25。**适配分**在加权得分基础上额外考虑 AutoService 关键路径能力（流式卡片、交互回调、商户自助入驻）的权重和致命阻断项（如 Slack 退出中国）的降权。

---

## 三、Per-platform deep dive

### 3.1 飞书/Lark — 流式卡片的原生王者

**SDK 成熟度**：Python SDK `lark-oapi` v1.5.3（2026 年 1 月发布，PyPI 83+ 版本，月级更新）提供完整的类型化 API 调用、WebSocket 长连接事件接收、卡片 Action 回调处理和 Token 自动刷新。Node SDK `@larksuiteoapi/node-sdk` v1.60.0（2026 年 4 月发布，npm 周下载 ~991K）同样完备，语义化方法名 `client.im.message.create()` 开发体验优秀。两套 SDK 通过 `domain` 参数一行代码切换飞书/Lark 端点，实现 **N4-1（一套代码双区覆盖）✅**。旧版 `larksuite-oapi` 已于 2022 年停更，需注意避免误引。

**流式卡片（B2-2, B2-3, B2-4）是飞书的核心差异化能力**。官方文档（open.feishu.cn/document/cardkit-v1/streaming-updates-openapi-overview）提供了完整的流式更新 OpenAPI，工作流为：`POST` 发送初始卡片 → `PATCH /open-apis/interactive/v1/card/update` 以 `message_id` 原地更新。客户端渲染无闪烁、不触发二次通知，支持 block 级流式追加（blockStreaming）。已被 OpenClaw 飞书插件、LangBot、opencode-lark 等开源项目验证。但实际刷新率受限速影响——社区报告"飞书 API 有请求频率限制，流式更新消息很容易触发限流"，推荐 debounce 间隔 **500ms-3000ms**，即实际约 **1-2 次/秒/卡片**，距离 B2-3 要求的 5 次/秒有差距（◐）。CardKit 组件包含 button、select、date_picker、text_input、multi_select、overflow 等，覆盖 B2-1 ✅。

**线程模型**：飞书支持"话题"（Topics），通过 reply API 回复消息自动创建线程上下文。线程消息携带 `root_id` / `parent_id` 字段可在事件中区分。群组可配置为"话题群"（所有消息默认开线程）。B3-1 ✅、B3-2 ✅，但 **B3-3（线程速率独立于主频道）⚠️ 未文档化**。

**Slash Command（B4-1, B4-2）**：飞书**不支持原生 Slash Command 菜单**——这是与 Slack/Mattermost 的显著差距。替代方案是"Bot Command Menu"，通过开发者后台或 `POST /open-apis/im/v1/chats/{chat_id}/menu_tree` API 配置命令面板（呈现为"+"按钮或快捷菜单）。用户选中命令后发送文本触发 Bot。**无参数自动补全（B4-2 ❌）**，所有参数解析需应用层实现。

**应用/Bot 分发模型**：支持"自建应用"（单租户内部）和"应用商店应用"（ISV/Marketplace）两种模式。ISV 应用使用 `app_ticket` → `app_access_token` → 每租户 `tenant_access_token` 的标准流程，Node SDK 通过 `lark.withTenantKey('tenant key')` 实现每次 API 调用的租户隔离。安装触发 `app_open` 事件，可据此自动建群拉人（A1-4 需应用层编排，◐）。应用商店支持品牌自定义、权限预声明、安装审核流程。

**Rate Limits**：Webhook Bot 限速 **100 次/分钟**；API 层面的 per-API QPS 限制文档化于 open.feishu.cn/document/server-docs/api-call-guide/frequency-control，但免费租户总量限 **10,000 次/月**（极易被健康检查耗尽）。企业版大幅提升配额但具体数字需按 API 查阅。Token 有效期 2 小时，SDK 内建自动刷新。

**已知坑点**：(1) 免费套餐 10K API/月配额极低；(2) 卡片按钮回调需同时配置 Event Subscription 和 Callback Subscription，遗漏任一报错 200340；(3) WebSocket 模式在 Lark 国际端部分功能灰度期可能不可用；(4) 飞书和 Lark 为独立身份系统，`open_id` 不互通（N4-2 ❌）。

### 3.2 Slack — API 生态标杆，中国缺席

**SDK 成熟度**：`slack-sdk` v3.39.0（2026 年 1 月）和 `slack-bolt` v1.28.0（2026 年 4 月）由 Slack 官方 `slackapi` 组织维护。Node 端 `@slack/bolt` v4.7.0（2026 年 4 月）同样活跃。Bolt 框架同时支持 Events API（HTTP）和 Socket Mode（WebSocket），通过配置开关一行切换。Token 轮换（rotation）自 Bolt v1.9.0 起支持。所有 SDK 内建限速自动重试（N1-5 ✅）和 Socket Mode 断线自动重连。

**Block Kit 交互能力**是 Slack 的基石：支持 button、static/external/user select、multi-select、date/time picker、checkbox、radio、overflow、plain_text_input、email_input、url_input、file_input 等组件。每条消息最多 **50 个 blocks**，Modal 最多 **100 个 blocks**（可堆叠 3 层视图）。App Home 作为持久化 Dashboard 面板（B5-3 ✅）最多 100 blocks，通过 `views.publish` 更新。**但 Block Kit 更新是全量替换——`chat.update` 需发送完整 blocks 数组，无差分更新（B2-5 ❌）**。

**流式更新（B2-2, B2-3）**：传统路径为 `chat.update`（Tier 3 ~50 次/分钟 ≈ ~0.8/秒），对高频卡片刷新是硬限制。**新能力**：`chat.startStream` + `chat.appendStream` API（需 `slack-bolt` v1.28.0+）支持 LLM 风格文本流式输出，但仅限纯文本追加，不支持 Block Kit 结构化差分。AutoService 的 AI 对话摘要流式场景可用，但交互式卡片仍受限。

**Thread 模型**：`chat.postMessage` 设置 `thread_ts` 创建线程回复；`reply_broadcast=true` 可同时在主频道显示。`conversations.replies` 获取线程历史。**线程回复共享频道级 1 msg/s 限速（B3-3 ◐）**——无独立线程速率。

**Copilot 可见性（B3-5 ✅）**是 Slack 的独到优势：`chat.postEphemeral` 发送仅对指定用户可见的消息，支持完整 Block Kit 组件，完美匹配"监督内容仅商户可见、C 端不可见"需求。但 ephemeral 消息不持久化，刷新/重登后消失。

**Rate Limits 详细数字**：`chat.postMessage` Special tier ~1 msg/s/channel；`chat.update` Tier 3 ~50/min；`conversations.create` Tier 2 ~20/min；`views.publish` Tier 4 ~100/min；Events API 30,000 events/workspace/hour。**⚠️ 关键陷阱**：2025 年 5 月起，未通过 Marketplace 审批的商业分发应用，`conversations.history` 和 `conversations.replies` 被降至 **Tier 1（1 次/分钟，最多 15 条）**——AutoService **必须通过 Marketplace 审批**。

**中国阻断**：Slack 于 **2026 年 4 月 1 日终止大中华区（大陆、香港、澳门）全部服务**，所有该区域计费工作区被暂停，数据 90 天内永久删除。移动端 App 2024 年 3 月已从中国区应用商店下架。被 GFW 封锁。这是面向中国商户的**致命阻断**。

### 3.3 Mattermost — 自托管阵营的 API 最完备方案

**SDK 成熟度**：Python 生态是 Mattermost 的软肋。官方 `mattermostdriver` v7.3.2（~2022 年发布后停更），推荐使用社区维护的 `mattermostautodriver`（基于 OpenAPI spec 自动生成，自 v10.8.2 起跟随 Mattermost Server 版本发布，Python 3.10+ 要求）。两者均**无内建重试逻辑（N1-5 ❌）**。Node 端 `@mattermost/client` v9.7.0 为官方包（Web 客户端内部使用），包含 `Client4` REST 和 `WebSocketClient`，但社区下载量极低（~71/周）。**关键架构决策**：Apps Framework 已在 Mattermost v10 **正式弃用**，所有深度集成必须走 Plugin Framework（Go server + React webapp），Python/Node 仅可通过 REST API + WebSocket 做外部 Bot 服务。

**Interactive Messages + 卡片回调（B2-1 ✅, B4-3 ✅）**：消息 attachment 支持 button、dropdown menu、text field 等组件，Action 触发 HTTP POST 回调携带 `user_id`、`post_id`、`channel_id`、`context` 等完整上下文。回调响应可通过 `"update": {...}` 原地更新消息或 `"ephemeral_text"` 返回仅用户可见反馈。但更新为全量 POST 替换，无流式差分（B2-5 ❌）。

**Thread 模型（B3-1 ✅）**：CRT（Collapsed Reply Threads）自 v7.0 GA。设置 `root_id` 创建线程回复。WebSocket 事件含 `thread_updated`、`thread_follow_changed`、`thread_read_changed`。Threads 视图提供**独立的 per-thread 未读追踪（B1-2 ✅）**。

**Slash Command（B4-1 ✅, B4-2 ✅）**是 Mattermost 的亮点：Plugin API `RegisterCommand()` 支持 `AutoComplete: true`、`AutoCompleteDesc`、`AutoCompleteHint` 和子命令树，在五平台中**命令自动补全能力最强**。

**Message Priority（B5-2 ✅）**：原生三级优先级——Standard / Important / Urgent。API 字段 `priority` 控制，`requested_ack` 触发确认流程，`persistent_notifications` 对 Urgent 消息每 5 分钟重复通知直到确认。此为 Professional+ 版功能。

**自托管**：单二进制 + PostgreSQL，Docker Compose 一键部署。`mattermost/mattermost-preview` 镜像可秒级启动开发实例。HA 集群（Enterprise）支持多应用节点 + 共享 DB。Rate Limit 完全可控——默认 `PerSec: 10` 但自托管可调高或禁用，Plugin API 调用**直接绕过 HTTP 限速**。

**关键弱项**：(1) **多租户是最大缺口**——Mattermost 设计为单租户，Team 提供组织边界但非真正数据隔离。B2B SaaS 需要么 "每商户一个实例"（运维复杂）要么 "Team 作为租户边界 + 应用层访问控制"（A1-6 ◐）；(2) Marketplace 为全服务器安装，无 per-tenant 插件配置（A1-7 ❌）；(3) 插件 webapp 组件**仅限桌面/Web 端**，移动端不渲染；(4) WebSocket 存在消息丢失已知问题（GitHub #23332），需 REST API 兜底补偿。

### 3.4 Zulip — 最佳线程模型遇上最差卡片能力

**SDK 成熟度**：Python SDK `zulip`（PyPI，2025 年 9 月发布）是五平台中最稳定的开源 IM Python SDK 之一，提供 `Client` 类的 `send_message()`、`get_messages()`、`call_on_each_event()` 等方法，`zulip_bots` 框架的 `BotHandler` 支持 storage API 和身份管理。但 Node SDK `zulip-js` v2.1.0（~1 年前发布）覆盖不全，需 `callEndpoint()` 兜底调用未封装端点（B-BOT-2 ◐）。

**Topic 线程模型是 Zulip 的杀手级架构**（B3-1 ✅, B1-2 ✅）。Stream → Topic 的二层结构天然映射 AutoService 的 Agent Squad：一个 Stream 代表一个商户工作区，每个 AI Agent 或客户案例占一个 Topic。用户在 Zulip UI 中可直接看到**每个 Topic 的未读计数**——这是 Slack/飞书均无法原生达到的粒度。Topic 可以被 resolve（✓ 前缀标记）、rename、移动到其他 Stream、拆分——为对话生命周期管理提供了原生工具。B3-3 ✅：Zulip 的速率限制按用户而非按 Topic，多个 Topic 可同时接收消息互不干扰。

**交互式卡片——致命缺口**。Zulip 仅有的交互元素是 **zforms**（通过消息 `extra_data` 渲染按钮选择）和内建 widget（`/poll`、`/todo`），但 zforms **仅在 Web 端渲染**、移动端/终端显示原始文本，且**不可自定义扩展**。GitHub issue #32373 确认这是已知限制，且不在近期路线图中。这导致 B2-1 ◐、B4-3 ◐、B5-3 ❌、C1-1 ◐ 系列核心能力严重受损。AutoService 若选 Zulip，必须接受"文本 + Emoji 反应"为主要交互模式，或自建 Web 伴侣 UI。

**Rate Limits**：默认 **200 requests/minute/user**，自托管通过 `RATE_LIMITING_RULES` 完全可配。HTTP Header `X-RateLimit-*` + `RATE_LIMIT_HIT` error code + `retry-after` 字段（N3-5 ✅）。多 bot 用户可并行突破单用户限额。

**事件系统**：Tornado-based 长轮询。`POST /register` 创建事件队列 → `GET /events` 长轮询。RabbitMQ 内部保证投递。队列 10 分钟不活动后过期，Python SDK 的 `call_on_each_event()` 内建指数退避重连（N1-5 ✅）。at-least-once 语义通过 `last_event_id` 确认机制保证（N1-4 ✅）。

### 3.5 Matrix (Synapse + Element + matrix-bot-sdk) — 架构最纯净，交互最原始

**SDK 成熟度分化明显**：TypeScript 端 `matrix-bot-sdk` v0.8.0（2026 年 2 月发布，现由 Element 维护于 `element-hq/matrix-bot-sdk`）同时支持 Regular Client 和 **Application Service (AS)** 模式，AS 模式为 AutoService 的推荐路径——接收事件由 Synapse HTTP push transaction 投递（无需 sync 轮询）、可注册排他性用户命名空间（每个 AI Agent 一个虚拟 Matrix 用户）、且**绕过多数限速**。Python 端 `matrix-nio` v0.25.2 功能完整（asyncio、E2EE、房间管理），但 Snyk 于 2025 年底标记为"inactive"（12 个月无发布），长期投入风险较高（B-BOT-1 ◐）。替代方案：`simplematrixbotlib` v2.13.1（2026 年 3 月更新，包装 matrix-nio）较活跃。

**交互卡片——与 Zulip 同级缺失**。Matrix 协议**没有原生内联交互组件**（B2-1 ❌、B4-3 ❌、C1-1 ❌、B5-3 ❌）。可用变通方案：(1) Reaction 作为伪按钮（👍/👎），UX 极其有限；(2) **Widget**（`im.vector.modular.widgets` state event 嵌入 iframe），可在 Element Web/Desktop 的时间线上方渲染交互 Web 应用，通过 postMessage API 双向通信——这是可行但非标准的路径；(3) 自定义 event type + fork Element 客户端渲染——灵活但维护成本极高。MSC2192（Inline Widget）提案仍为草案，有安全隐患。

**Thread 支持（B3-1 ✅）**：MSC3440 threading 已进入 stable spec（v1.4 起），Synapse 和 Element Web/Mobile 均支持。单层线程（无嵌套）。per-thread 已读回执（MSC3771/MSC3773）和通知计数自 spec v1.4 支持。

**消息编辑（B2-2 ◐, B2-4 ✅）**：`m.replace` relation type 已进入 stable spec（v1.4，MSC2676）。支持 placeholder → rewrite 模式。但对于高频流式更新（token-by-token AI 输出），默认 `rc_message` 限速（~0.5 msg/s）是瓶颈——AS 模式可通过 admin API 为虚拟用户禁用限速解决。

**事件不可变性（C1-5 ✅）** 是 Matrix 的架构级优势。所有事件存储在 DAG（有向无环图）中，经签名和哈希，创建后不可修改——只能被 "redact"（剥离内容但保留事件结构）。这为审计合规提供了**协议层保证**。

**Synapse 性能**：Python 实现（CPython GIL 限制单进程单核）。单进程约 **50-100 msg/s** 本地投递。Worker 模式（event persister、sync worker、federation sender 分离）可水平扩展至 1000+ msg/s。matrix.org 以 worker 集群服务 50K+ 并发用户。B2B 商户工作区规模下单进程 Synapse 通常足够。**优化建议**：禁用 federation（`m.federate: false`）、禁用 presence、用 PostgreSQL（非 SQLite）、调 `SYNAPSE_CACHE_FACTOR`、用 jemalloc。最低生产配置 **2 vCPU / 4GB RAM / 50GB SSD**。

---

## 四、Gap analysis by Epic

| Epic | 说明 | 飞书/Lark | Slack | Mattermost | Zulip | Matrix |
|---|---|:---:|:---:|:---:|:---:|:---:|
| **E1 商户入驻** (9 项) | Act A：安装→建群→上传→授权 | 6✅ 3◐ | 8✅ 1◐ | 3✅ 4◐ 2❌ | 5✅ 2◐ 2❌ | 4✅ 3◐ 2❌ |
| **E2 实时运营** (12 项) | Act B：Squad + 流式卡片 + Copilot | 8✅ 4◐ | 7✅ 4◐ 1❌ | 8✅ 3◐ 1❌ | 5✅ 4◐ 3❌ | 5✅ 5◐ 2❌ |
| **E3 命令/Dashboard** (7 项) | Act B：Slash cmd + 告警 + Dashboard | 4✅ 2◐ 1❌ | 5✅ 2◐ | 5✅ 2◐ | 2✅ 3◐ 2❌ | 2✅ 3◐ 2❌ |
| **E4 Dream Engine** (8 项) | Act C：审批卡片 + 灰度 + 审计 | 6✅ 2◐ | 7✅ 1◐ | 5✅ 3◐ | 4✅ 4◐ | 4✅ 3◐ 1❌ |
| **合计通过率** | ✅/(总项数) | **67%** | **75%** | **58%** | **44%** | **42%** |

> E2 拆分说明：将 Layer 3 的 19 项按功能归属拆分为 E2（Squad + 流式卡片 + Copilot，含 B1-1~B1-2, B2-1~B2-5, B3-1~B3-5 = 12 项）和 E3（命令 + 告警 + Dashboard，含 B4-1~B4-4, B5-1~B5-3 = 7 项）。

---

## 五、场景化推荐

### 最佳中国大陆商户方案：飞书（Feishu）

飞书是**唯一同时满足三个条件**的平台：中国数据驻留合规、原生流式卡片更新、成熟的 ISV 应用商店多租户模式。商户在飞书应用商店搜索 AutoService → 一键安装 → `app_open` 事件触发自动建群拉人 → 上传产品目录 → bot 接收处理，端到端可控在 ≤2 小时。**关键实施建议**：使用 CardKit 流式更新实现 AI 对话摘要的实时呈现；用 `app_open` + create chat API 编排自动入驻流程；用卡片按钮回调实现 Dream Engine 审批；命令交互走 Bot Menu 而非 Slash Command（适配 B4-1 ◐ 限制）。

### 最佳纯国际商户方案：Slack

若 AutoService 的商户**完全不涉及中国大陆市场**，Slack 的 API 生态成熟度、Block Kit 交互丰富度、ephemeral 消息的 Copilot 可见性控制、和 `assistant.threads.*` AI Agent 原生支持构成最强组合。**关键前提**：必须通过 Slack Marketplace 审批（否则 `conversations.history` 限速 1 次/分钟致命）；必须使用 Events API HTTP 模式（Socket Mode 不允许 Marketplace 应用使用）。新增的 `chat.startStream`/`chat.appendStream` 可用于 AI 文本流式输出，但 Block Kit 卡片更新仍受 `chat.update` ~50/min 限制。

### 最佳自托管/数据主权方案：Mattermost

在三个自托管候选中，Mattermost 的 **API 完整度最高**（48✅ vs Zulip 47✅ vs Matrix 48✅），且是唯一同时具备 Interactive Messages 卡片回调 + Slash Command 自动补全 + 原生消息优先级的自托管方案。**关键代价**：(1) 需接受 Go 语言插件开发（或用 REST API + WebSocket 做外部 Bot，牺牲一些能力）；(2) 多租户架构需自建——推荐方案为 "per-merchant Team + 应用层访问控制"（牺牲真正物理隔离）或 "K8s 上的 per-merchant Mattermost 实例"（运维成本高但隔离最彻底）；(3) 需采购 Professional 版（消息优先级）或 Enterprise 版（审计日志、HA、合规导出）。

### 混合方案（推荐）

对于同时面向中国和国际商户的 AutoService，推荐**飞书 + Slack 双平台战略**：

- **中国大陆商户 → 飞书（Feishu）**
- **国际商户 → Slack**（或 Lark，取决于商户已有的 IM 习惯）
- **核心 Bot 逻辑层**抽象为平台无关的 Python/TypeScript 服务，通过 Adapter Pattern 对接不同 IM 平台 SDK
- **卡片模板**分别适配 CardKit（飞书）和 Block Kit（Slack）的 JSON schema，维护一套业务逻辑 + 两套渲染模板
- **数据主权例外**：若特定垂直行业（如医疗、金融）商户要求私有部署，可单独提供 Mattermost 方案作为增值选项

这一架构的核心假设是飞书和 Slack 的 API 语义高度对齐（创建群组、发消息、卡片交互、线程、事件订阅），Adapter 层工程量可控。SDK 双端（Python + Node）两个平台均有官方活跃维护支持。

---

## 六、Critical unknowns：需 PoC / Spike 验证的 ⚠️ 项

| 项目 ID | 平台 | 不确定内容 | 验证方法 |
|---|---|---|---|
| B3-3 | 飞书 | 线程消息与主频道是否共享同一速率限制 | 编写测试脚本在同一群的主频道和线程中并发发消息，观察是否互相触发限流 |
| N3-1 | 飞书 | 消息发送 API 的精确 QPS 上限（企业版） | 联系飞书 KA 商务获取企业版 API 限额表；或自行压测 `POST /im/v1/messages` 记录 429 触发阈值 |
| N3-2 | 飞书/Slack | 事件投递 P99 延迟是否 ≤2 秒 | 部署事件接收服务记录 `event_time` vs `receive_time` 差值，采集 1000+ 样本计算 P99 |
| B2-3 | 飞书 | 流式卡片实际可达刷新率（单卡/聚合） | 压测 `PATCH /interactive/v1/card/update`，递增频率（1→5→10/s），记录限流触发点和客户端渲染效果 |
| B2-2 | Slack | `chat.startStream` / `chat.appendStream` 是否支持 Block Kit 结构 | 参照 slack-bolt v1.28.0+ 文档实测，确认流式接口是否仅限纯文本或支持 Block Kit partial append |
| N3-1 | Slack | 跨多频道聚合发送是否可稳定达 100 QPS | 向 50 个频道并发 `chat.postMessage`，记录每秒成功数和 429 率 |
| B2-3 | Mattermost | Plugin API 调用 `UpdatePost()` 绕过限速后的实际更新频率上限 | 编写 Go 插件测试 Plugin API 的 `UpdatePost()` 调用速率，观察客户端渲染延迟和闪烁情况 |
| N1-4 | Mattermost | WebSocket 消息丢失率（GitHub #23332 报告的问题是否仍存在于 v10+） | 在负载测试下统计 WebSocket `posted` 事件接收数 vs REST API 轮询补偿拉取数，量化丢失比例 |
| B2-1 | Zulip | zforms `extra_data` 在移动端的实际渲染效果 | 在 Zulip Android/iOS 客户端中发送含 `extra_data` 的消息，确认是否显示可交互按钮还是原始 JSON 文本 |
| B-BOT-1 | Matrix | `matrix-nio` 是否仍可用于生产（Snyk inactive 标记后是否有恢复维护迹象） | 查看 github.com/poljar/matrix-nio 最近 commits；评估 `simplematrixbotlib` 作为替代方案的稳定性 |
| B2-2 | Matrix | Synapse AS 模式下快速连续 `m.replace` 编辑的实际延迟和客户端渲染效果 | 以 AS 身份每 200ms 发送一次 `m.replace` 编辑同一条消息，在 Element Web 上观察流式效果和延迟 |

### 建议的 PoC Sprint 优先级

**第一优先级（1 周）**：飞书流式卡片端到端 PoC——验证 B2-2/B2-3/B2-4 的实际表现，包括卡片创建 → 流式更新 → 按钮回调 → 状态持久化完整链路。同时验证 ISV 多租户 Token 流程。

**第二优先级（1 周）**：Slack `chat.startStream` + Block Kit 更新组合 PoC——验证 AI 文本流式输出 + 交互卡片混合场景。测试 Marketplace 审批流程时间线。

**第三优先级（可选）**：若有自托管需求，Mattermost Plugin 框架 PoC——验证 Go 插件的 Interactive Messages 回调 + Custom Post Type 渲染 + 多租户 Team 隔离架构。

---

## 附录：SDK 版本与限速速查表

### SDK 版本一览

| 平台 | Python 包 | 版本 | 发布日期 | Node 包 | 版本 | 发布日期 |
|---|---|---|---|---|---|---|
| 飞书/Lark | `lark-oapi` | v1.5.3 | 2026-01 | `@larksuiteoapi/node-sdk` | v1.60.0 | 2026-04 |
| Slack | `slack-sdk` / `slack-bolt` | v3.39.0 / v1.28.0 | 2026-01 / 2026-04 | `@slack/bolt` | v4.7.0 | 2026-04 |
| Mattermost | `mattermostautodriver` | 跟随 v10.8.2 | 持续 | `@mattermost/client` | v9.7.0 | 活跃 |
| Zulip | `zulip` | latest | 2025-09 | `zulip-js` | v2.1.0 | ~2025 中 |
| Matrix | `matrix-nio` | v0.25.2 | ~2025 中 | `matrix-bot-sdk` | v0.8.0 | 2026-02 |

### 关键 API 限速对比

| 操作 | 飞书 | Slack | Mattermost | Zulip | Matrix (Synapse) |
|---|---|---|---|---|---|
| 发消息 | Webhook bot 100/min；API per-endpoint 限速 | ~1/s/channel (Special tier) | 默认 10/s (可调) | 200/min/user (可调) | `rc_message` ~0.5/s (可调；AS 可绕过) |
| 更新消息/卡片 | 流式更新有限速（建议 debounce 500ms+） | `chat.update` Tier 3 ~50/min | 受通用限速限制 | 受通用限速限制 | `m.replace` 受 rc_message 限制 |
| 创建频道/群组 | per-API 文档化 | Tier 2 ~20/min | 默认 10/s | 200/min/user | 无特殊限制（受通用限速） |
| 文件上传大小 | IM ~30MB / Drive 更大 | **1GB** | **100MB** (可配) | 25MB 默认 (可配，tus 无限) | **50MB** 默认 (可配) |
| 频道成员上限 | **10,000** | 数千（无硬限） | 可配（默认数千） | 无硬限 | 20K+ 已验证 |
| Events/hour | 未公开具体值 | 30,000/workspace/hour | 不限（WebSocket） | 不限（长轮询队列） | 不限（sync/AS） |