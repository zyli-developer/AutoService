# Channel-Server v1.0 — 用户旅程端到端流程

> 三视角（C 端客户 / 人工客服 / 平台）的完整消息流
> 含具体 IRC 消息和 Bridge API 消息示例

---

## 旅程 1: 客户接入 → Agent 自动服务（US-2.1 + US-2.2）

### 场景

C 端客户 David 通过飞书联系商户，问"B 套餐多少钱"。这是一个简单查询，Agent 直接回答。

### 消息流

```
时间  组件                    消息
─────────────────────────────────────────────────────────────────────

T+0s  [David → Feishu]        David 在飞书群发送 "B 套餐多少钱"
      
T+0s  [Feishu → Bridge]       Feishu WSS 推送事件给 feishu_bridge

T+0s  [Bridge → CS]           Bridge API WebSocket:
                               {"type": "customer_connect",
                                "conversation_id": "feishu_oc_abc123",
                                "customer": {"id": "feishu_ou_david", "name": "David"},
                                "metadata": {"source": "feishu"}}

T+0s  [CS 内部]               ConversationManager.create("feishu_oc_abc123")
                               → state = created
                               → 检查是否已有 → 新客户 → 发 conversation.created 事件
                               → IRC: JOIN #conv-feishu_oc_abc123
                               → Agent fast-agent 通过 MCP 收到 conversation.created

T+0s  [Bridge → CS]           {"type": "customer_message",
                                "conversation_id": "feishu_oc_abc123",
                                "text": "B 套餐多少钱",
                                "message_id": "msg_001"}

T+0s  [CS 内部]               ConversationManager.activate("feishu_oc_abc123")
                               → state = active
                               MessageGate: customer public → 保持 public
                               MessageStore.save(msg_001)
                               IRC: PRIVMSG #conv-feishu_oc_abc123 :David: B 套餐多少钱

T+0s  [CS → Agent MCP]        inject_message: 
                               {"content": "B 套餐多少钱",
                                "meta": {"chat_id": "#conv-feishu_oc_abc123",
                                         "user": "David", "visibility": "public"}}

T+1s  [Agent → CS MCP]        Tool call: reply(
                                 chat_id="#conv-feishu_oc_abc123",
                                 text="B 套餐每月 199 元，当前有 8 折优惠...")

T+1s  [CS 内部]               MessageGate: agent public + mode=auto → 保持 public
                               MessageStore.save(msg_002)
                               IRC: PRIVMSG #conv-feishu_oc_abc123 :fast-agent: B 套餐...

T+1s  [CS → Bridge]           {"type": "reply",
                                "conversation_id": "feishu_oc_abc123",
                                "text": "B 套餐每月 199 元...",
                                "message_id": "msg_002"}

T+1s  [Bridge → Feishu]       Feishu send message API → David 在飞书看到回复
```

### 同时：App 插件动作

```
T+0s  [App Plugin]            on_conversation_created:
                               → customer_manager.get_or_create("feishu_ou_david")
                               → 新客户 → 创建工作目录
                               → 注入 metadata: {"customer_type": "new"}

T+0s  [App Plugin]            on_event(conversation.created):
                               → 向 #squad-xiaoli 发卡片:
                                 "[新对话] #feishu_oc_abc123 · David · 等待 Agent 响应"
```

---

## 旅程 2: 复杂查询 → 占位 → 续写替换（US-2.2）

### 场景

David 追问"和 A 套餐的详细对比？能不能自定义？"，这是复杂查询。

### 消息流

```
T+0s  [David → Feishu]        "和 A 套餐的详细对比？能不能自定义？"

T+0s  [Bridge → CS → Agent]   (同旅程 1 的消息传递链)

T+1s  [Agent 行为]            fast-agent 的 soul.md 判断: 复杂查询
                               → 先发占位消息

T+1s  [Agent → CS MCP]        Tool call: reply(
                                 chat_id="#conv-feishu_oc_abc123",
                                 text="稍等，正在为您查询...")
                               → 返回 message_id = "msg_003"

T+1s  [CS → Bridge → Feishu]  David 看到 "稍等，正在为您查询..."

T+2s  [Agent 行为]            Agent 调用知识库 MCP tool 查询 A/B 套餐对比
                               (这是 App 层的 plugin tool，不是协议)

T+8s  [Agent → CS MCP]        Tool call: edit_message(
                                 message_id="msg_003",
                                 text="以下是 A/B 套餐对比：\n• A 套餐: 99 元/月...\n• B 套餐: 199 元/月...")

T+8s  [CS 内部]               MessageStore.update(msg_003, new_text)
                               EventBus.publish(message.edited)

T+8s  [CS → Bridge]           {"type": "edit",
                                "conversation_id": "feishu_oc_abc123",
                                "message_id": "msg_003",
                                "new_text": "以下是 A/B 套餐对比：..."}

T+8s  [Bridge → Feishu]       Feishu update message API
                               → David 看到"稍等"被替换为完整对比表
```

---

## 旅程 3: 人工 Copilot 旁听 + 建议（US-2.3 + US-2.4）

### 场景

人工客服小李在 Agent 分队频道看到对话卡片，点开进入 copilot 模式观察。

### 消息流

```
T+0s  [CS → Bridge (分队群)]   系统消息推送到小李的飞书"Agent 分队群":
                               "[进行中] feishu_oc_abc123 · David · 询问套餐对比 · Agent 回复中"

T+5s  [小李在飞书分队群]       回复: "进入 feishu_oc_abc123"

T+5s  [Bridge → CS]           {"type": "operator_join",
                                "conversation_id": "feishu_oc_abc123",
                                "operator": {"id": "xiaoli", "name": "客服小李"}}

T+5s  [CS 内部]               conversation_manager.add_participant(conv_id, xiaoli, role=operator)
                               → mode_manager.transition(auto → copilot, trigger="operator_joined")
                               → EventBus.publish(mode.changed)

T+5s  [CS → Bridge (分队群)]   推送历史消息 + mode 状态:
                               {"type": "event", "event_type": "mode.changed",
                                "data": {"to": "copilot"}}
                               + 最近 N 条 public 消息回放

T+5s  [小李在飞书分队群]       看到对话历史和当前 mode=copilot
                               
T+10s [小李在飞书分队群输入]   "建议强调 B 档本月优惠"

T+10s [Bridge → CS]           {"type": "operator_message",
                                "conversation_id": "feishu_oc_abc123",
                                "operator_id": "xiaoli",
                                "text": "建议强调 B 档本月优惠"}

T+10s [CS 内部]               Gate: mode=copilot + operator + public → 降级为 side
                               → Message(visibility=SIDE) 存储
                               → Bridge 只推给 operator 端（不推给客户端）
                               → inject 给 agent MCP:
                                 {"content": "[侧栏建议] 小李: 建议强调 B 档本月优惠",
                                  "meta": {"visibility": "side", "user": "xiaoli"}}

T+10s [Agent 收到 side 建议]  Agent 的 soul.md: "收到 operator 的 side 建议时，采纳后发送"
                               → reply(text="对了，B 档本月有特别优惠，首月可享 8 折！")

T+10s [CS → Bridge (客户端)]  David 在飞书看到 Agent 补充的优惠信息
```

**关键点**: 小李的消息被 Gate 降级为 side，Bridge 只推给 operator 端（分队群），不推给客户端（David 的对话群）。David 完全不知道小李在看。全程小李在飞书操作，不接触 IRC。

---

## 旅程 4: Agent 求助 → 人工接管 → 角色翻转（US-2.5 + US-2.6）

### 场景

David 说"我要退货，你们客服经理在吗"，Agent 判断超出能力，请求人工接管。

### 消息流

```
T+0s  [David]                 "我要退货，你们客服经理在吗"

T+1s  [Agent 行为]            soul.md 判断: 超出能力范围
                               → 发 @operator 消息到 squad channel

T+1s  [Agent → CS MCP]        Tool call: reply(
                                 chat_id="#squad-xiaoli",
                                 text="@xiaoli 客户 David 要求退货并找经理，请接管 #conv-feishu_oc_abc123")

T+1s  [CS → Bridge (分队群)]   推送到小李的飞书分队群:
                               "fast-agent: @xiaoli 客户 David 要求退货并找经理..."

T+1s  [App Plugin]            on_event(message.sent, squad channel):
                               → 设置 timer: takeover_wait(180s)
                               → on_expire: mode → auto + 安抚消息

T+1s  [Agent → CS MCP]        reply(chat_id="#conv-feishu_oc_abc123",
                                     text="好的，正在为您转接人工客服，请稍等...")

T+1s  [CS → Bridge (客户端)]  David 看到 "正在为您转接..."

                               ─── 等待阶段（最多 180s）───

T+15s [小李在飞书分队群]       看到 squad 通知 → 回复 "/hijack feishu_oc_abc123"

T+15s [Bridge → CS]           {"type": "operator_command",
                                "conversation_id": "feishu_oc_abc123",
                                "operator_id": "xiaoli",
                                "command": "/hijack"}

T+15s [CS 内部]               CommandParser: /hijack
                               → mode_manager.transition(copilot → takeover, trigger="/hijack")
                               → cancel timer "takeover_wait"
                               → EventBus.publish(mode.changed)

T+15s [Agent 收到 event]      mode.changed(→ takeover)
                               → soul.md: "生成对话摘要发给 operator"
                               → send_side_message: "[摘要] 客户 David，老客户，
                                  询问 B 套餐后要求退货并找经理。情绪偏激。
                                  历史: 上月购买 X 服务。"

T+15s [CS 内部]               Gate 翻转:
                               - Agent 的 public → 降级为 side（副驾驶建议）
                               - Operator 的消息 → public（到客户）

T+20s [小李在飞书分队群]       "您好，我是客服小李，看到您在询问退货"

T+20s [Bridge → CS]           {"type": "operator_message", "operator_id": "xiaoli",
                                "conversation_id": "feishu_oc_abc123",
                                "text": "您好，我是客服小李，看到您在询问退货"}

T+20s [CS 内部]               Gate: mode=takeover + operator + public → 保持 public
                               → Bridge 推给客户端 → David 看到小李的消息

T+25s [Agent 副驾驶]          Agent 自动通过 side 消息提供建议:
                               send_side_message: "[建议] 客户上月购买 X 服务，
                                  可推荐升级方案替代退货"

T+25s [CS → Bridge (分队群)]  side 消息: 只推给 operator 端（小李的飞书分队群）
                               David 完全看不到

T+30s [小李在飞书分队群]       "注意到您之前买过 X 服务，B 档可以无缝接续，
                               这样可能比退货更划算，您觉得呢？"

T+30s [CS → Bridge (客户端)]  David 看到连贯的对话（不知道背后 Agent 在提供建议）

T+30s [App Plugin]            on_event(mode.changed → takeover):
                               → billing.log_takeover(conversation_id, timestamp)
                               → 计入接管次数

                               ─── 问题解决 ───

T+5m  [David]                 "好的，那我试试升级方案"

T+5m  [小李]                  "太好了！我这就帮您操作升级..."

T+8m  [小李在 channel 中]     /resolve

T+8m  [CS 内部]               CommandParser: /resolve
                               → conversation_manager.resolve(conv_id, "resolved", "xiaoli")
                               → state = closed
                               → EventBus.publish(conversation.resolved)

T+8m  [CS → Bridge]           {"type": "csat_request", "conversation_id": "feishu_oc_abc123"}

T+8m  [Bridge → Feishu]       Feishu 发送评分卡片:
                               "感谢您的耐心，请为本次服务评分 ⭐1-5"

T+9m  [David 在飞书]          点击 ⭐⭐⭐⭐⭐ (5分)

T+9m  [Bridge → CS]           {"type": "csat_response", "conversation_id": "feishu_oc_abc123",
                                "score": 5}

T+9m  [CS 内部]               conversation_manager.set_csat(conv_id, 5)
                               → EventBus.publish(conversation.csat_recorded)

T+9m  [App Plugin]            on_event(conversation.csat_recorded):
                               → 更新 CSAT 统计
                               → 检查升级转结案: takeover + resolved + csat=5 ✓
```

### 如果 180s 超时无人接管

```
T+181s [TimerManager]         timer "takeover_wait" expired
                               → mode_manager.transition(→ auto)
                               → IRC NOTICE: [系统] 人工接管超时，已退回 Agent

T+181s [Agent 收到 event]     timer.expired
                               → soul.md: "超时后发安抚消息"
                               → reply: "非常抱歉让您久等，我来继续帮您处理退货问题..."
```

---

## 旅程 5: 管理员查看状态 + 派发（US-3.2）

### 场景

管理员老陈在飞书管理群查看全局状态。

### 消息流

```
T+0s  [老陈在飞书管理群]       /status

T+0s  [Bridge → CS]           {"type": "admin_command", "admin_id": "laochen",
                                "command": "/status"}

T+0s  [CS CommandParser]       识别 /status
                               → ConversationManager.list_active()
                               → 返回:

T+0s  [CS → Bridge (管理群)]  {"type": "command_response", "command": "/status",
                                "result": "[状态] 当前 active 对话 3 个:
                                  #1 feishu_oc_abc123 · David · mode=takeover · 小李接管中
                                  #2 feishu_oc_def456 · 张三 · mode=auto · fast-agent 处理中
                                  #3 web_sess_789     · 匿名 · mode=auto · fast-agent 处理中"}

T+0s  [Bridge → 飞书管理群]   老陈在飞书管理群看到状态回复

T+5s  [老陈在飞书管理群]      /dispatch feishu_oc_def456 deep-agent

T+5s  [Bridge → CS]           {"type": "admin_command", "admin_id": "laochen",
                                "command": "/dispatch feishu_oc_def456 deep-agent"}

T+5s  [CS CommandParser]       识别 /dispatch → 
                               → deep-agent JOIN #conv-feishu_oc_def456（IRC 内部）
                               → 通知 deep-agent 的 MCP: 新 conversation 加入
                               → CS → Bridge (管理群): "deep-agent 已加入 feishu_oc_def456"
```

---

## 旅程 6: 闲时学习提案 + 灰度（US-4.3 + US-4.4）

> **⚠️ v1.1 scope** — 本旅程展示的 Dream Engine 完整流程不在 v1.0 实现范围内。
> v1.0 仅提供协议层基础（EventBus + #admin 消息推送）。
> Dream Engine pipeline、灰度引擎、/approve /reject /rollback 命令均为 v1.1 内容。

### 场景

Dream Engine 夜间整理后，晨起推送提案到管理群。

### 消息流

```
T 06:00  [Dream Engine agent]  完成夜间回放整理，生成 3 个提案

T 09:00  [Dream Engine → CS]   reply(chat_id="#admin",
                                text="[晨报] 昨夜学习完成，3 个提案待审核:
                                  1. 新增 FAQ: 'B 套餐包含多少流量' (低风险)
                                  2. 更新话术: 退货流程 (中风险)
                                  3. 新增知识: 竞品 X 对比表 (低风险)
                                  
                                  回复 /approve 1 通过 · /reject 2 驳回 · /rollback 提案ID 回滚")

T 09:05  [老陈 #admin]        /approve 1

T 09:05  [Dream Engine]       收到 → 提案 1 进入 5% 灰度
                               reply(#admin, "提案 1 已通过，进入 5% 灰度。将观察 24h。")

         (24h 后如果指标正常)

T+24h   [Dream Engine]        自动: 提案 1 灰度 5% → 25%
                               reply(#admin, "提案 1 灰度升级 5% → 25%，指标正常。")
```

---

## 旅程 7: 开发者调试 — 通过 Zellij 直接进入 Agent Session

> **⚠️ 开发者调试专用** — 此模式仅供开发者排查问题使用，不面向租户。
> 租户（客服/管理员）全部通过 Bridge（飞书/Web）交互，不需要接触 Zellij/IRC。

### 场景

开发者想直接看 Agent 的 Claude Code session 排查问题。

### 操作流

```
T+0s  [开发者在 WeeChat]       看到 #squad-xiaoli 中 fast-agent 处理 #conv-feishu_oc_abc123
                               （这是 IRC 调试视图，租户不使用）

T+1s  [开发者在终端]           切到 zellij tab: fast-agent
                               → 直接看到 Claude Code 的输出
                               → 可以看到 Agent 正在思考什么
                               → 可以看到 Agent 调用了哪些 MCP tools
                               → 上下文完整（Claude Code session 保留全部历史）

T+5s  [开发者在 agent tab]     可以直接在 Claude Code session 中输入
                               → 这会被 Claude 当作"用户输入"处理
                               → Agent 的 soul.md 需要识别: "如果收到 operator 指令..."

      备选: 开发者通过 IRC 交互
      [开发者在 WeeChat]      JOIN #conv-feishu_oc_abc123
                               → 通过协议标准流程（Gate + Mode）交互
```

**两种方式的权衡**:
- **IRC 方式**: 通过协议保护（Gate 强制执行），更安全
- **Zellij 方式**: 直接看 Claude session 上下文，更透明，但绕过了协议层的 Gate

建议日常使用 IRC 方式（协议保护），调试/排查时切 Zellij 直接看 session。

---

## 状态机总览

基于上述旅程，对话的完整状态机（注意：state 和 mode 是两个正交维度——state 有 4 种：created/active/idle/closed；mode 有 3 种：auto/copilot/takeover，仅在 state=active 时有意义）：

```
                         Customer connect
                              │
                              ▼
                        ┌───────────┐
                        │  created  │
                        └─────┬─────┘
                              │ First message
                              ▼
                        ┌───────────┐
              ┌────────►│  active   │◄────────┐
              │         │ mode=auto │          │
              │         └─────┬─────┘          │
              │               │                │
              │    Operator   │    Timeout      │
              │    JOIN       │    5min         │
              │               ▼                │
              │         ┌───────────┐          │
              │    ┌───►│  active   │          │
              │    │    │ mode=     │          │
              │    │    │ copilot   │          │
              │    │    └─────┬─────┘          │
              │    │          │                │
              │    │ /release │ /hijack        │
              │    │          ▼                │
              │    │    ┌───────────┐          │
              │    └────│  active   │          │
              │         │ mode=     │          │
              │         │ takeover  │          │
              │         └─────┬─────┘          │
              │               │                │
              │    /release   │  180s timeout   │
              │               │  (no operator)  │
              │               ▼                │
              │         revert to auto ────────┘
              │
              │  Reactivate
              │         ┌───────────┐
              └─────────│   idle    │
                        └─────┬─────┘
                              │ 1h timeout
                              ▼
                        ┌───────────┐
        /resolve ──────►│  closed   │◄────── /abandon
        (from active)   └───────────┘  (from active/idle)
```

---

## Pre-release 验证映射

每个 User Journey 在 Phase Final 中的验证方式：

| 旅程 | PRD Story | Pre-release 测试 | 验证方式 |
|------|-----------|-----------------|---------|
| 旅程 1: 客户接入 | US-2.1 | TestFeishuFullJourney.test_step1 | 自动 — 发消息 → 验证回复 |
| 旅程 2: 占位续写 | US-2.2 | TestFeishuPlaceholderAndEdit | 自动 — 验证 message_edited 事件 |
| 旅程 3: Copilot 旁听 | US-2.3 + US-2.4 | TestFeishuFullJourney.test_step2/3 + TestFeishuGateIsolation | 自动 — 验证 visibility 路由 |
| 旅程 4: 接管翻转 | US-2.5 + US-2.6 | TestFeishuFullJourney.test_step4/5/6 + TestFeishuTimerAndEscalation + TestFeishuCSATFlow | 自动（CSAT card action 可能需手动） |
| 旅程 5: 管理命令 | US-3.2 | TestFeishuAdminCommands | 自动 — /status + /dispatch |
| 旅程 6: Dream Engine | US-4.x | — | v1.1 scope，不测 |
| 旅程 7: 开发者调试 | — | — | 开发者手动，非 pre-release 范围 |
| 老客户重入 | US-2.1 补充 | TestFeishuConversationReactivation | 自动 — 两轮对话 |
| 授权模型 | 飞书 Bridge spec | TestFeishuAuthorizationModel | 自动 — 3 角色群验证 |

### 全栈操作流程

Pre-release 通过 zchat CLI 启动真实运行栈（在 Zellij session 内）：

```
1. zchat project create prerelease-test     ← fixture / 人工一次性
2. zchat irc daemon start                    ← fixture 自动
3. zchat agent create fast-agent             ← fixture 自动
   → Zellij tab → Claude Code → channel-server (MCP + Bridge API :9999 + IRC)
   → 等待 .ready marker（最多 60s）
4. feishu_bridge 启动                        ← fixture 自动（连接 ws://localhost:9999）
5. 飞书测试群中发消息                         ← FeishuTestClient 自动
6. Claude 真实响应 → channel-server → Bridge → 飞书
7. 验证消息路由和 visibility                  ← assert_message_appears/absent
```

**关键点**: channel-server 不是独立进程，而是 Claude Code 的 MCP server。`zchat agent create` 一条命令启动整个链路（Zellij tab → Claude Code → channel-server → IRC + Bridge API）。

**无 Zellij 降级**: CI 环境可直接启动 channel-server 进程（`uv run zchat-channel`），此模式下无真实 agent 回复，只能验证协议行为。

---

*End of User Journeys v1.0*
