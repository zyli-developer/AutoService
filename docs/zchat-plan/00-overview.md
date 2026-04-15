# Channel-Server v1.0 — 协议总览与架构设计

> 版本 v1.0 · 2026-04-14 · ezagent42
> 上位文档: `docs/discuss/prd/AutoService-PRD.md`

---

## 1. 定位

Channel-Server 是一个**通用对话协作协议的实现**，提供人类与 AI Agent 在共享对话空间中协作所需的原语。它不是某个 App 的专用组件，而是一个**可被任何 App 接入的协议层服务**。

第一个接入的 App 是 AutoService（AI 客服系统），但协议本身不包含任何客服领域概念。

### 核心使命

1. **管理对话生命周期** — 创建、激活、闲置、关闭
2. **控制人机协作模式** — 谁主导对话、谁旁听、谁的消息对客户可见
3. **提供消息门控** — 根据模式决定消息的可见性和路由
4. **暴露事件总线** — 让 App 通过订阅事件实现业务逻辑
5. **保持协议纯净** — 不包含任何业务概念，App 通过插件钩子注入行为

### 不做什么

- 不理解消息内容（content-agnostic）
- 不包含任何领域词汇（customer service、sales、CRM 等）
- 不实现 Agent 的 AI 行为（那是 Agent 的 soul.md 和 MCP tools）
- 不实现渠道协议（那是 Bridge 层）
- 不替代 IRC（IRC 是 transport backend）

---

## 2. 与 ESR Protocol 的关系

本协议受 ESR Protocol v0.1 启发，借鉴其分层理念，但做了实质性简化：

| 维度 | ESR Protocol | Channel-Server Protocol |
|------|-------------|------------------------|
| 范围 | 通用 pub/sub 消息协议 | 聚焦人-Agent 对话协作 |
| 核心概念 | Peer + Lobby + 6 原语 | Participant + Conversation + Mode + Gate |
| Transport | Zenoh | IRC (ergo)，可替换 |
| 实现语言 | Rust + PyO3 | Python |
| 消息语义 | content-agnostic opaque bytes | 有 visibility 标签（public/side/system） |
| 模式控制 | PublishAuthority + Draft + quorum 投票 | 三态状态机（auto/copilot/takeover） |
| 扩展方式 | peer 侧 convention | 事件订阅 + 插件钩子 |
| MVP 规模 | ~12,000 行 | ~1,200 行 |

**关键继承**：
- ESR §3 的 Router/Peer 责任线 → 本协议的 Protocol/App 责任线
- ESR 的 "Could two peers cooperate to achieve this?" 测试 → 同样适用
- ESR 的分层架构（Protocol → Implementation → Application）→ 本协议的三层

**关键简化**：
- 不需要 Lobby 嵌套 → Conversation 是扁平的
- 不需要 quorum 审批 → 单人即可切换模式
- 不需要 Targeted delivery + TTL → IRC PRIVMSG 已够
- 不需要 Dead letter → 超时退回到 auto 模式即可

**演进路径**：如果未来需要 ESR 的完整能力（跨 daemon 联邦、lobby 嵌套、PublishAuthority quorum），可以将本协议作为 ESR 的一个 profile（子集实现），通过替换 transport 层接入 esrd。

---

## 3. 三层架构

```
┌─ Layer 2: App 层 ─────────────────────────────────────────┐
│  通过 agent 行为定义（soul.md + MCP tools + 事件订阅）      │
│  实现具体业务逻辑                                          │
│                                                            │
│  AutoService:                                              │
│    agent_behaviors/ — 快慢双模型、升级规则、Dream Engine    │
│    metrics/ — 计费（接管次数）、SLA 监控                    │
│    plugins/ — 知识库、CRM、业务系统接口                     │
│                                                            │
│  未来 App X:                                               │
│    不同的 agent 行为，使用相同的协议原语                     │
└────────────────────────────────────────────────────────────┘
          │ 事件订阅 + 插件钩子
┌─ Layer 1: 协议层 (channel-server) ────────────────────────┐
│                                                            │
│  通用原语（所有 App 共用）:                                 │
│    Conversation — 对话生命周期                              │
│    Participant — 参与者角色（customer/agent/operator）       │
│    Mode — 对话模式状态机（auto/copilot/takeover）           │
│    Gate — 消息门控（根据 mode 控制 visibility）             │
│    MessageVisibility — public / side / system              │
│    Timer — 超时计时器                                      │
│    Event — 事件总线                                        │
│    Commands — /hijack /release /copilot /status /dispatch  │
│                                                            │
│  MCP Server — 对 Agent 暴露 reply/edit/join 等 tools       │
│  IRC Transport — 对下连接 ergo，管理 channel               │
│  Bridge API — 对上给 Bridge 层提供 WebSocket 接口           │
│  Plugin Hooks — 让 App 注入 on_message/on_mode_change 等   │
│                                                            │
└────────────────────────────────────────────────────────────┘
          │ IRC protocol
┌─ Layer 0: Transport 层 ──────────────────────────────────┐
│  ergo IRC Server                                          │
│  职责: 消息投递 + channel 管理 + nick 管理                 │
│  特点: 可替换（未来可换 Zenoh/NATS/自定义 WS）             │
└──────────────────────────────────────────────────────────┘
```

### 层间责任线

| 问题 | 归属 | 测试 |
|------|------|------|
| "消息应该发给谁？" | Layer 0 (IRC channel routing) | 两个 IRC client 能否互发消息？ |
| "这条消息对客户可见吗？" | Layer 1 (Gate + Visibility) | 协议层的判断，不依赖具体 App |
| "什么条件触发接管？" | Layer 2 (App agent behavior) | App 自己定义，协议只提供 /hijack 命令 |
| "接管后发什么安抚消息？" | Layer 2 (App agent behavior) | Agent 的 soul.md 决定 |
| "接管计入计费指标？" | Layer 2 (App metrics) | App 订阅 mode.changed 事件 |
| "消息从飞书怎么到 IRC？" | Bridge 层 | Bridge 是 Layer 1 的渠道适配器 |

---

## 4. 设计原则

### P1. 协议不包含业务概念

channel-server 的代码中不应出现 "customer_service"、"sales"、"CRM"、"knowledge_base" 等词汇。如果一个功能只对某个 App 有意义，它属于 App 层。

### P2. 模式切换是 mechanism，不是 convention

当 mode=takeover 时，agent 的 public 消息被 channel-server **物理拦截**（降级为 side），不是靠 agent 的 prompt 自觉。这是和纯 prompt 方案的根本区别。

### P3. IRC 是 transport，不是 protocol

协议的语义（visibility、mode、gate）不依赖 IRC 的能力。如果未来替换 IRC 为其他 transport，协议行为不变。channel-server 是协议的执行者，IRC 只是消息管道。

### P4. 插件扩展，不改核心

App 通过事件订阅和插件钩子扩展协议行为。新 App 接入不需要改 channel-server 代码，只需要：
1. 定义 agent 行为（soul.md + MCP tools）
2. 注册事件订阅（on_mode_change → 计费、on_message → 路由策略）
3. 配置 timer 参数（超时时长等）

### P5. Conversation 是一等公民

不是 IRC channel 的附属品。Conversation 有自己的生命周期、模式状态、参与者列表。IRC channel 只是 Conversation 的 transport 映射。

---

## 5. 组件全景

```
┌─ 渠道 ──────────────────────────────────────────────────────┐
│  Web (浮动按钮)    Feishu IM     (PSTN/WhatsApp 未来)       │
└────┬────────────────┬────────────────────────────────────────┘
     │ WebSocket      │ WebSocket
┌────▼────────────────▼────────────────────────────────────────┐
│  Bridge 层                                                    │
│  web_bridge.py       feishu_bridge.py                        │
│  职责: 渠道协议 ↔ channel-server API 转换                     │
│  规则: 只转发 visibility=public 的消息给客户端                 │
│  消息编辑: 收到 message.edited 事件 → 调渠道 API 更新消息     │
└────┬─────────────────────────────────────────────────────────┘
     │ WebSocket (channel-server bridge API)
┌────▼─────────────────────────────────────────────────────────┐
│  channel-server (协议核心)                                    │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  ConversationManager  — CRUD + 状态机 + 参与者管理       │ │
│  │  ModeManager          — auto/copilot/takeover 切换       │ │
│  │  MessageGate          — 根据 mode + role 决定 visibility │ │
│  │  TimerManager         — asyncio 计时器                   │ │
│  │  EventBus             — 发布/订阅 + 持久化               │ │
│  │  CommandParser        — /hijack /release 等命令解析       │ │
│  │  MessageStore         — 消息历史 + edit 支持             │ │
│  │  PluginManager        — 钩子注册 + 调用                  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  MCP Server: reply / edit_message / join_conversation / ...   │
│  Bridge API: WebSocket server 给 bridge 用                   │
│  IRC Client: 连接 ergo，管理 channel                         │
└────┬─────────────────────────────────────────────────────────┘
     │ IRC
┌────▼─────────────────────────────────────────────────────────┐
│  ergo IRC Server                                              │
│  #admin        — 管理员监控频道                               │
│  #squad-{name} — 人工客服的 Agent 分队频道                    │
│  #conv-{id}    — 对话频道（每个 conversation 一个）           │
│  #general      — 公共频道                                     │
└────┬─────────────────────────────────────────────────────────┘
     │ IRC (per agent, 每个 agent 一个 MCP 连接)
┌────▼─────────────────────────────────────────────────────────┐
│  Agent 层                                                     │
│  每个 agent = Claude Code session + channel-server MCP client │
│  Agent 行为由 soul.md + MCP tools 定义（App 层）              │
│  Agent 使用协议原语（reply/edit/join）但不感知协议内部        │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Operator 层 (人工客服) — 全部通过 Bridge，不碰 IRC           │
│  飞书"Agent 分队群" → Feishu Bridge → channel-server          │
│    看卡片 → 发建议(side) → /hijack → /resolve                │
│  或 Web 管理后台 → Web Bridge → channel-server               │
│                                                               │
│  Admin 层 (管理员) — 同样通过 Bridge                          │
│  飞书"管理群" → Feishu Bridge → channel-server                │
│    /status → /dispatch → /assign                              │
│                                                               │
│  开发者 (可选) — IRC 仅作为调试入口                            │
│  WeeChat → IRC → channel-server（调试用，租户不需要）          │
└──────────────────────────────────────────────────────────────┘
```

---

## 6. IRC Channel 命名约定

| Channel 模式 | 命名 | 用途 | 谁在里面 |
|-------------|------|------|---------|
| 管理频道 | `#admin` | 全局状态监控、告警、/dispatch 命令 | 管理员 + admin-agent |
| 分队频道 | `#squad-{operator}` | 人工客服的 Agent 分队，接收对话卡片 | operator + 其负责的 agents |
| 对话频道 | `#conv-{id}` | 一个具体的客户对话 | customer (via bridge) + agent(s) + operator (可选) |
| 公共频道 | `#general` | 全局广播 | 所有 agent |

**conversation_id 格式**: `{source}_{external_id}`
- Feishu: `feishu_oc_xxx`（飞书 chat_id）
- Web: `web_{session_id}`
- 手动: `manual_{uuid}`

IRC channel 名 = `#conv-{conversation_id}`

---

## 7. 文档索引

| 文档 | 内容 |
|------|------|
| `00-overview.md` | 本文档 — 协议定位、架构、设计原则 |
| `01-protocol-primitives.md` | 协议原语完整定义（10 个原语 + 状态机 + Gate 算法） |
| `02-channel-server.md` | channel-server 实现设计（模块、文件、接口、App tool 注册） |
| `03-bridge-layer.md` | Bridge 层设计（Feishu/Web 适配、消息编辑、visibility 过滤） |
| `04-prd-mapping.md` | PRD 17 个 User Story → 实现组件映射表（含 SLA timer + CSAT 追踪） |
| `05-user-journeys.md` | 三视角端到端用户旅程（含 /resolve + CSAT 采集流程） |
| `06-gap-fixes.md` | 交叉验证修复补充（SLA timer、并发上限、CSAT、分队、多租户、v1.0 scope） |
| `07-migration-plan.md` | 三层修改方案（zchat CLI / channel-server / AutoService） |
| `08-implementation-plan.md` | 实现计划（Phase 0-Final，已拆分到 plan/ 目录） |
| `09-feishu-bridge.md` | 飞书 Bridge 详细设计（消息解析器 + 群映射 + card + E2E 工具） |

---

*文档所有者: Allen @ ezagent42 · 基于 AutoService-PRD.md v1.0 + ESR Protocol v0.1*
