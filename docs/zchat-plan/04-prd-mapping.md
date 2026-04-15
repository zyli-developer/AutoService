# Channel-Server v1.0 — PRD User Story 映射表

> 17 个 US 逐条映射到具体组件和实现方式
> P = Protocol 层 · CS = Channel-Server · B = Bridge · Z = zchat CLI · A = App 层 · F = Frontend · I = Infrastructure

---

## Epic 1 · 自助上线（4 个 US）

### US-1.1 · 上传基础信息生成初版 Agent

| AC | 实现组件 | 实现方式 |
|----|---------|---------|
| 填入 URL + 上传 PDF | `A` + `F` | AutoService 上线向导 Web UI + 知识库导入 pipeline（skills/knowledge-base 的 kb_ingest.py 已有基础） |
| 15 分钟 CI 解析 | `A` | 异步解析 worker：URL 爬取 + PDF 解析 + 结构化知识提取。可用 Claude API 辅助 |
| 生成 4 个 Agent | `Z` + `A` | `zchat agent create-team` 批量创建命令（新增）。每个 agent 从模板生成 soul.md + MCP tools 配置 |
| 格式不支持提示 | `A` + `F` | 上传校验逻辑（前端 + 后端） |

**协议层不涉及**。全部是 App 层和 zchat CLI 的工作。

### US-1.2 · 勾选权限并关联管理群

| AC | 实现组件 | 实现方式 |
|----|---------|---------|
| 勾 4 个权限 | `F` | Web 权限配置页面 |
| 自动建管理群 | `Z` + `I` | `zchat irc channel create admin` → 创建 IRC #admin channel + agents 自动 JOIN |
| 4 个 Agent 进群 | `CS` | channel-server 启动时根据配置自动 JOIN #admin + #squad-{operator} |

**协议层关联**：#admin channel 的自动创建和 agent 加入是 `CS` 的启动流程。

### US-1.3 · 虚拟客户预演

| AC | 实现组件 | 实现方式 |
|----|---------|---------|
| 生成 10 条虚拟对话 | `A` | Claude API 根据知识库生成模拟对话（全新开发） |
| ✓ 通过 / ✎ 修改 UI | `F` | 审阅界面（全新开发） |

**协议层不涉及**。

### US-1.4 · 合规预检

| AC | 实现组件 | 实现方式 |
|----|---------|---------|
| GDPR/CCPA/个保法检查 | `A` | 合规规则引擎（全新开发，可用 AutoService rules.py 扩展） |
| 沙箱不阻塞 | `I` | zchat project 天然隔离，增加 "sandbox" / "production" 标记 |
| 2 小时内完成 | — | 流程优化指标，不需要代码实现 |

**协议层不涉及**。

---

## Epic 2 · 实时对话（6 个 US）— 协议核心

### US-2.1 · 3 秒内问候

| AC | 实现组件 | 实现方式 | Spec 引用 |
|----|---------|---------|----------|
| 点开聊天按钮 | `F` + `B` | Web 浮动按钮 → WebSocket → web_bridge | `03-bridge-layer.md §3` |
| 3s 内问候 | `P` + `CS` + agent 行为 | Bridge 发 `customer_connect` → CS 创建 Conversation → 设置 `sla_onboard(3s)` timer → agent 收到 `conversation.created` 事件 → agent 发问候 → timer 取消 | `01-protocol.md §1 create` + `§6 sla_onboard` |
| 老客户引用历史 | `P` + `A` | CS 在 `conversation.create` 时检查 conversation_id 是否已存在 → 存在则 `reactivate` + 加载 metadata。App 插件的 `on_conversation_created` 钩子加载客户历史 | `01-protocol.md §1 reactivate` |
| 新客户创建工作目录 | `A` | App 插件的 `on_conversation_created` 钩子调用 AutoService customer_manager.get_or_create | `01-protocol.md §9 Plugin Hooks` |

**协议原语使用**: Conversation.create / Conversation.reactivate / Event: conversation.created / Plugin Hook: on_conversation_created

### US-2.2 · 占位消息 + 续写替换

| AC | 实现组件 | 实现方式 | Spec 引用 |
|----|---------|---------|----------|
| 1s 内占位 | agent 行为 (`A`) + `P` (Timer) | fast-agent soul.md 发占位。App 插件检测复杂查询后设置 `sla_placeholder(1s)` timer，占位消息发出时取消 | Agent soul.md + `01-protocol.md §6 sla_placeholder` |
| 慢模型 5-15s | agent 行为 (`A`) | fast-agent 调用知识库/CRM 等 MCP tools 查询 | AutoService plugins/ |
| 续写替换 | `P` + `CS` + `B` | Agent 调用 `edit_message(message_id, new_text)` → 取消 `sla_slow_query` timer → CS MessageStore 更新 → Bridge API 推送 edit | `01-protocol.md §5 edit` + `§6 sla_slow_query` / `03-bridge.md §5` |

**协议原语使用**: Message.edit / Event: message.edited / MCP Tool: edit_message

**关键点**: "快慢双模型"是 agent 行为，不是协议。协议只提供 `edit_message` 原语。Agent 自己决定何时先发占位、何时编辑替换。

### US-2.3 · 分队卡片实时刷新

| AC | 实现组件 | 实现方式 | Spec 引用 |
|----|---------|---------|----------|
| 新客户 → 卡片 | `P` + `CS` | conversation.created event → CS 在 #squad-{operator} channel 发系统消息（包含对话摘要） | `01-protocol.md §7 Event` |
| 卡片实时刷新 | `CS` + agent 行为 | Agent 定期调用 `send_side_message` 发摘要到 squad channel；或 CS 在每 N 条 public 消息后自动推送摘要事件 | `02-channel-server.md §4 MCP Tools` |
| 未读徽章 | `F` (IM 层) | 飞书群天然支持未读消息计数；Web 后台通过 WebSocket push 徽章 | — |

**协议原语使用**: Event: conversation.created / Message visibility=system (卡片消息) / MCP Tool: send_side_message

**分队频道映射**: 每个 operator 有一个 IRC `#squad-{operator}` channel。Agent 在创建时配置属于哪个 operator 的分队。Agent 接入新对话后，在 squad channel 发卡片通知。

### US-2.4 · 对话监管（Copilot 模式）

| AC | 实现组件 | 实现方式 | Spec 引用 |
|----|---------|---------|----------|
| 点开卡片 | `B` + `CS` | Operator 在飞书分队群中回复"进入 conv_id" → Bridge 发 `operator_join` → CS 自动切 copilot | `02-channel-server.md §5 Bridge API` |
| 自动进入 copilot | `P` + `CS` | CS 检测到 operator JOIN #conv-{id} → mode.transition(auto → copilot) | `01-protocol.md §3 状态转换` / `02-channel-server.md §6 on_join` |
| 标题显示 mode | `B` + `F` | Bridge 发送 `mode.changed` event → 飞书群/Web 前端显示当前模式 | `01-protocol.md §3 mode.changed event` |
| Agent 回复对 operator 可见 | IRC | Operator 在 channel 中自然看到所有消息 | ✅ 天然支持 |
| Operator 输入不发给客户 | `P` (Gate) | mode=copilot → operator 的 public 消息被 Gate 降级为 side → Bridge 不转发 | `01-protocol.md §5 Gate` |
| 客户不感知 operator | `B` | Bridge 不转发 side 消息 + 不通知客户端有人加入 | `03-bridge.md §4` |

**协议原语使用**: ConversationMode.COPILOT / MessageGate / Message visibility=side / Event: mode.changed

### US-2.5 · 人工提醒（两种触发）

| AC | 实现组件 | 实现方式 | Spec 引用 |
|----|---------|---------|----------|
| Agent @小李 请接管 | agent 行为 + `CS` | Agent 的 soul.md: "超出能力时发 @operator 消息到 squad channel"。CS 在 squad channel 中转发 | Agent soul.md |
| 180s 接管等待 | `P` (Timer) | Agent 发出 @operator 后，App 插件设置 timer: `timer_manager.set("conv_id", "takeover_wait", 180s, on_expire=mode→auto + 安抚消息)` | `01-protocol.md §6 Timer` |
| 超时退回 + 安抚 | `P` + agent 行为 | Timer 超时 → mode 恢复 auto → CS 发 system 消息 "已退回 agent" → Agent 收到 timer.expired 事件，按 soul.md 发安抚消息 | `01-protocol.md §6` |
| /hijack 立即翻转 | `P` (Command) | Operator 在 #conv-{id} 中发 `/hijack` → CS 解析 → mode.transition(→ takeover) + 取消 takeover_wait timer | `01-protocol.md §8 Commands` |

**协议原语使用**: Timer / Command: /hijack / ModeTransition / Event: timer.expired + mode.changed

### US-2.6 · 角色翻转（Takeover）

| AC | 实现组件 | 实现方式 | Spec 引用 |
|----|---------|---------|----------|
| 人工首条消息带入背景 | agent 行为 + `P` | Agent 收到 `mode.changed(→ takeover)` 事件 → 按 soul.md 生成对话摘要 → 通过 `send_side_message` 发给 operator | `01-protocol.md §9 on_mode_changed` |
| 60s 人工首回 | `P` (Timer) | mode 切换到 takeover 时，App 设置 timer: `sla_first_reply(60s)` | `01-protocol.md §6` |
| Agent 退居副驾驶 | `P` (Gate) | mode=takeover → Agent 的 public 消息被 Gate 降级为 side | `01-protocol.md §5 Gate` |
| 客户看到连贯对话 | `B` | Bridge 只转发 public → 客户只看到 operator 的消息，不感知切换 | `03-bridge.md §4` |
| 计入接管次数 | `A` | App 插件订阅 `mode.changed(→ takeover)` 事件 → 写入计费日志 | `01-protocol.md §9 on_event` |
| **对话结案** | `P` (Command) | 问题解决后 operator 发 `/resolve` → state=closed + 触发 CSAT 采集 | `01-protocol.md §1 Resolution` + `§8 /resolve` |
| **CSAT 采集** | `P` + `B` | `/resolve` 后 Bridge 向客户发评分邀请 → 客户评分 → `set_csat()` | `01-protocol.md §1 set_csat` + `06-gap-fixes.md §3` |
| **升级转结案率** | `A` | count(takeover + resolved) / count(takeover)，通过 EventBus 查询 mode.changed + conversation.resolved | `06-gap-fixes.md §3` |

**协议原语使用**: ModeTransition(→ takeover) / MessageGate(agent public → side) / Timer / Event: mode.changed + conversation.resolved / Plugin Hook: on_mode_changed / ConversationResolution / /resolve command

---

## Epic 3 · 双账本与仪表盘（3 个 US）

### US-3.1 · AI + 人工双账本

| AC | 实现组件 | 实现方式 |
|----|---------|---------|
| 4 个 Agent 状态 | `Z` + `CS` | `zchat agent list` 已有；CS 通过 EventBus 追踪 agent 当前参与的 conversation 数 |
| 3 个计费指标 | `A` + `P` (EventBus) | App 插件查询 EventBus: `event_bus.query(event_type=MODE_CHANGED, data.to="takeover")` → 统计接管次数 |
| 辅助指标 | `A` + `P` (EventBus) | 平均首回: 从 conversation.created 到首条 agent reply 的时间差（event 查询） |
| 时间切片 | `F` | Web 仪表盘 UI（全新开发） |

**协议支持**: EventBus 的 query 接口（按时间范围、事件类型查询）是统计的基础。

### US-3.2 · 管理群命令

| AC | 实现组件 | 实现方式 |
|----|---------|---------|
| /status | `P` (Command) + `CS` | 协议内建命令 | `01-protocol.md §8` |
| /dispatch | `P` (Command) + `CS` | 协议内建命令 | `01-protocol.md §8` |
| /review | `A` (App 层命令) | 非协议命令。由 admin-agent 的 soul.md 处理，查询 EventBus 数据返回统计 | Agent 行为 |
| /assign /reassign /squad | `P` (Command) + `CS` | 协议内建分队管理命令 | `01-protocol.md §8` |

### US-3.3 · SLA 超时告警

| AC | 实现组件 | 实现方式 |
|----|---------|---------|
| 5 分钟滚动平均 | `A` + `P` (Timer + Event) | App 插件注册周期性 timer（每分钟），查询 EventBus 计算滚动平均 |
| 告警推到管理群 | `CS` | timer 超时回调 → CS 向 #admin channel 发系统消息 |
| 一键 /dispatch | `F` (IM 层) | 消息内嵌 /dispatch 命令，operator 可直接复制执行 |

---

## Epic 4 · 闲时学习（4 个 US）

### US-4.1 · 配置 Dream Engine 学习规则

| AC | 实现组件 | 实现方式 |
|----|---------|---------|
| @Dream Engine 对话配置 | `A` (agent 行为) | Dream Engine 是一个特殊 agent，soul.md 定义了"收到配置请求时询问 4 个参数" |
| 保存规则 | `A` | AutoService rules.py（已有 add_rule/load_rules） |
| /rules show / edit | `A` + agent 行为 | Dream Engine agent 识别命令 → 调用 rules API |
| 平台合规模板 | `A` | 预置规则文件，load_rules 时叠加 |

### US-4.2 · 业务低峰自动触发

| AC | 实现组件 | 实现方式 |
|----|---------|---------|
| QPS 检测 | `A` + `P` (EventBus) | App 查询 EventBus 的 message.sent 事件频率 |
| Dream Engine 启动 | `A` + `I` | 调度器（cron 或 EventBus 触发）启动 Dream Engine agent |
| 中断恢复 | `A` | Dream Engine agent 支持暂停/恢复 |

### US-4.3 · 晨起推送提案

| AC | 实现组件 | 实现方式 |
|----|---------|---------|
| 提案卡片 | `CS` + `A` | Dream Engine agent 通过 reply tool 向 #admin channel 发结构化提案消息 |
| ✓/✎/✗ 按钮 | `F` (IM 层) | 飞书卡片消息（interactive card）或 Web UI 按钮 |
| 通过 → 灰度 | `A` | 灰度发布引擎（全新开发） |

### US-4.4 · 灰度 + 回滚

| AC | 实现组件 | 实现方式 |
|----|---------|---------|
| 灰度策略 | `A` | 灰度引擎按配置执行 5% → 25% → 100% |
| /rollback | `A` + agent 行为 | admin 在管理群发 /rollback → Dream Engine agent 处理回滚 |
| 观察指标 | `A` + `P` (EventBus) | 查询 EventBus 对比灰度前后的 CSAT 和结案率 |

---

## 共用约束映射

| 约束 | 实现组件 | 实现方式 |
|------|---------|---------|
| 反幻觉硬约束 | agent 行为 (`A`) | soul.md: "查不到就转人工，不编造" + 知识库 plugin 返回空时触发 @operator |
| 多语言 | agent 行为 (`A`) | Claude 天然支持 20+ 语言；翻译 agent 的 soul.md 定义双向翻译策略 |
| 上下文加载 | `P` + `A` | conversation.reactivate → App 插件加载历史 metadata → Agent 的 MCP inject 包含历史 |
| 设计系统 | `F` | 前端遵循"江峡泼墨"设计系统 |

---

## 汇总：协议层 vs App 层

| 统计 | 协议层实现 | App 层实现 | 其他 |
|------|-----------|-----------|------|
| Epic 1 (4 US) | 0 | 4 | zchat CLI + Frontend |
| Epic 2 (6 US) | **6** (全部) | 6 (行为定义) | Bridge × 2 |
| Epic 3 (3 US) | 2 (命令 + 事件) | 3 | Frontend |
| Epic 4 (4 US) | 0 | 4 | Infrastructure |

**协议层是 Epic 2 的基座**。Epic 1/3/4 主要是 App 层，通过 EventBus 和 Plugin Hooks 与协议层交互。

---

*End of PRD Mapping v1.0*
