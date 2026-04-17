# 10 — zchat Issue #59/#60/#61 对接方案分析

> 2026-04-17 会话落地。分析 zchat 三个核心 Issue，评估 AutoService 接入改造方案。
> 后续工作迁移至 zchat worktree 继续。

---

## 1. Issue 索引

| Issue | 标题 | 内容 |
|-------|------|------|
| [ezagent42/zchat#60](https://github.com/ezagent42/zchat/issues/60) | Architecture Guide: zchat Channel-Server 消息总线架构 | zchat 总线架构文档：三层协议（WS JSON 信封 / IRC 编码前缀 / Agent 命名）、消息流转全链路、Plugin 系统、路由表 |
| [ezagent42/zchat#61](https://github.com/ezagent42/zchat/issues/61) | Integration Guide: AutoService 接入 zchat 消息总线 | AutoService 作为 Bridge 接入指南：Bridge Adapter 示例、职责分离清单、常见场景实现、开发环境搭建 |
| [ezagent42/zchat#59](https://github.com/ezagent42/zchat/issues/59) | feat: 基于 zchat 实现客服系统（方案 A） | **核心方案**：4 条评论 — 方案 A 基础设计、实施计划 v1、时序图 (5 场景)、SRS v1.0 (完整规格) |

---

## 2. zchat 架构概要 (Issue #60)

### 2.1 总线模型

IRC (ergo) 是消息总线，channel-server 是路由器，不持有业务逻辑。

```
Web/Feishu/WeeChat  ──WebSocket──►  Channel-Server  ──IRC──►  Agent MCP ──►  Claude
```

### 2.2 三层协议

| 层 | 模块 | 格式 |
|----|------|------|
| 传输层 | `zchat-protocol/ws_messages.py` | WS JSON 信封: register / registered / message / command / event / ack |
| 内容层 | `zchat-protocol/irc_encoding.py` | IRC 编码前缀: `__msg:` / `__edit:` / `__side:` / `__zchat_sys:` |
| 命名层 | `zchat-protocol/naming.py` | Agent nick: `{username}-{agent_name}` |

### 2.3 Plugin 系统

channel-server 业务逻辑全在 plugin 中：

| Plugin | 命令 | 事件 |
|--------|------|------|
| mode | `/hijack` `/release` `/copilot` | `mode_changed` |
| sla | — | `sla_breach` |
| audit | — | takeover/resolved 计数 |
| lifecycle | `/close` `/resolve` | `channel_closed` / `channel_resolved` |
| activation | — | `customer_returned` |

### 2.4 MCP Tools (Agent 可用)

| Tool | 说明 |
|------|------|
| `reply` | 回复/编辑/side 消息 |
| `join_channel` | 加入 IRC channel |
| `join_conversation` | 加入 #conv-xxx |
| `send_side_message` | 发送 side 消息 |
| `run_zchat_cli` | 执行 zchat CLI |

---

## 3. Issue #59 方案核心决策

### 3.1 方案 A：共享 agent，无需新建

agent0 直接 `join_channel` 加入 ticket 频道，单 agent 处理多频道。
- 启动速度：即时（省去 30-60s agent 初始化）
- 适用：人工客服主导对话，agent 辅助

### 3.2 双跳架构（关键！非直连）

```
AutoService web_gateway
    → channel_server :9999      ← 保留，仅加 mode_changed 分支
        → zchat-bridge          ← zchat 团队新建 (~500行)
            → IRC (ergo)
                → agent0
```

**不是** AutoService 直接作为 zchat Bridge。zchat-bridge 是 channel_server 的一个 channel client，注册 `chat_ids=["web_*"]`。

### 3.3 客服不进 IRC

| 实体 | IRC 里的呈现 |
|------|-------------|
| 客户 Alice | `alice-proxy`（bridge 代发） |
| 客服 Bob | **不进入 IRC**；消息通过 AutoService 直接下发 |
| agent0 | IRC 原生 nick |

客服的回复走 AutoService → channel_server → 前端，**不经过 zchat-bridge 和 IRC**。

### 3.4 物理拦截

takeover 模式下，bridge 收到 agent 的 IRC PRIVMSG → **直接丢弃**（不转发给 channel_server）→ 发 `reply_blocked` sys message 给 agent。

保证"客户只看到一个声音"的契约，**不依赖 agent 自觉**。

---

## 4. AutoService 侧改动清单 (Issue #59 SRS)

### 4.1 后端 (~105 行)

| 文件 | 动作 | 行数 | 说明 |
|------|------|------|------|
| `autoservice/channel_server_relay.py` | **新建** | ~80 | 订阅 LocalEngine event_bus → WS 转发 mode_changed 给 channel_server |
| `channels/feishu/channel_server.py:1210` | 加分支 | +20 | `elif msg_type == "mode_changed"` dispatcher，按 chat_id 路由推送 |
| `channels/web/app.py` | 加开关 | +5 | `AS_WEB_BRIDGE_ENABLED` 环境变量控制 WebChannelBridge 是否启动 |

### 4.2 前端 (~60 行)

| 文件 | 动作 | 行数 | 说明 |
|------|------|------|------|
| `operator-console/.../ConversationFeed.tsx` | 订阅事件 | +30 | `ux_event:request_human` → 会话卡片加 badge |
| `operator-console/.../CopilotSidebar.tsx` | 订阅事件 | +30 | `ux_event:agent_suggestion` → 显示建议 |

### 4.3 不改的部分（明确边界）

- ❌ `autoservice/conversation_engine/protocol.py` — v1.0 冻结
- ❌ 核心业务代码（CRM、billing、triage、session）
- ❌ operator-console 现有组件（复用 HijackButton / ConversationFeed / IMInput）
- ❌ 不实现 `ZchatEngine`（M5+ 长期方向）

---

## 5. zchat 侧改动清单 (Issue #59 SRS)

| 文件 | 动作 | 行数 |
|------|------|------|
| `feishu-zchat-bridge/autoservice_client.py` | 新建 | ~150 |
| `feishu-zchat-bridge/channel_manager.py` | 新建 | ~100 |
| `feishu-zchat-bridge/filters.py` | 新建 | ~80 |
| `feishu-zchat-bridge/mode_sync.py` | 新建 | ~60 |
| `feishu-zchat-bridge/bridge.py` | 重写 | ~100 |
| `zchat-channel-server/server.py` | 加 tool | +40 |
| `cli/templates/autoservice-agent/soul.md` | 新模板 | ~150 |

---

## 6. 接口契约摘要

### 6.1 `mode_changed` (channel_server → bridge，新增)

```json
{
  "type": "mode_changed",
  "chat_id": "web_sess_abc",
  "conversation_id": "web_sess_abc",
  "mode": "takeover",           // auto | copilot | takeover
  "previous_mode": "auto",
  "actor": "operator:bob",
  "trigger": "/hijack",
  "ts": 1713350000.123
}
```

### 6.2 `ux_event: request_human` (zchat → channel_server，复用)

```json
{
  "type": "ux_event",
  "chat_id": "web_sess_abc",
  "event": "request_human",
  "data": {
    "reason": "客户明确要求人工",
    "priority": "normal",
    "requested_by": "agent0",
    "context_summary": "..."
  }
}
```

### 6.3 `ux_event: agent_suggestion` (bridge → channel_server，新事件名)

```json
{
  "type": "ux_event",
  "chat_id": "web_sess_abc",
  "event": "agent_suggestion",
  "data": {
    "suggestion": "建议回复：根据 2024 条款...",
    "confidence": "high",
    "source": "knowledge_base"
  }
}
```

### 6.4 IRC sys messages (bridge → agent)

| type | 用途 |
|------|------|
| `mode_sync` | 告知 agent mode 变化 |
| `reply_blocked` | 告知 agent 回复被拦截 |

### 6.5 IRC PRIVMSG 前缀

| 前缀 | 含义 | bridge 处理 |
|------|------|------------|
| (无) | 公开消息 | auto: 转 reply; takeover: 拦截; copilot: 按 /side 处理 |
| `/side ` | 辅助建议 | 转 ux_event:agent_suggestion |
| `/note ` | 仅日志 | 存日志，不转发 |
| `__zchat_sys:` | 系统控制 | bridge 自身消费 |

### 6.6 Reply 过滤决策表

| Mode | 发送者 | 前缀 | 结果 |
|------|--------|------|------|
| auto | agent | 无 | 转 reply 给客户 |
| auto | agent | `/side` | 转 ux_event (warn) |
| auto | agent | `/note` | 仅日志 |
| copilot | agent | 无 | **warn** + 按 /side 处理 |
| copilot | agent | `/side` | 转 ux_event:agent_suggestion |
| copilot | agent | `/note` | 仅日志 |
| takeover | agent | 任何 | **拦截** + reply_blocked |
| takeover | non-agent | 任何 | 不转（走 AutoService 直通） |
| * | bridge自己 | 任何 | 忽略 |

---

## 7. MVP 分阶段

| Phase | 范围 | 预估 | 验收关键 |
|-------|------|------|---------|
| **P1: Auto 基础** | bridge 接管 web_*，agent 回复客户 | 1 周 | 客户打字 → agent 回答 → 浏览器看到 |
| **P2: 转人工请求** | request_human MCP tool + soul.md | +3 天 | Alice 说"转人工" → operator-console badge |
| **P3: Mode 同步** | relay + mode_changed + bridge mode_sync | +1 周 | Bob hijack → agent 闭嘴 → Bob 回复直达 Alice |
| **P4: Copilot** | /side 过滤 + agent_suggestion | +3 天 | 三方协作端到端 |

**总计**: 2.5 周单人 / 1.5 周双线并行

---

## 8. 待 AutoService 团队回答的问题

| # | 问题 | 初步判断 |
|---|------|---------|
| **Q-01** | `conversation_id` ↔ `chat_id` 是否 1:1？ | 待查 web_gateway 和 LocalEngine 的 ID 生成逻辑 |
| **Q-02** | LocalEngine event_bus 对外部进程如何暴露？ | 建议选项 A：嵌入 web_gateway 同进程（零部署变更） |
| **Q-03** | HijackButton 是否已对接 `POST /api/command/hijack`？ | 需 review 前端代码 |
| **Q-04** | 禁用 WebChannelBridge 后 customer-chat 是否受影响？ | 应该只是后端中继变了，前端不受影响 |
| **Q-05** | CRM/billing 是否依赖 channel_server 特定消息？ | CRM (crm.py) 在 channel_server 内记录，需确认 zchat-bridge 消息是否触发同样逻辑 |

---

## 9. 与 AutoService 现有 zchat-plan 文档对比

| 现有文档 | Issue #59 方案差异 |
|----------|-------------------|
| `00-overview.md` — 长期 ZchatEngine 方向 | #59 明确不做 ZchatEngine，保留 LocalEngine |
| `03-bridge-layer.md` — Bridge 层设计 | #59 的 zchat-bridge 是更具体的实现（5个模块） |
| `07-migration-plan.md` — 迁移路线 | #59 是 MVP 子集，2.5 周可交付 |
| `08-current-cs-analysis.md` — channel_server 职能分析 | #59 只动 channel_server ~20 行，保守策略 |
| `09-feishu-bridge.md` — Feishu Bridge | #59 MVP 不涉及 Feishu，只处理 web_* |

---

## 10. 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| event_bus 订阅机制未验证 | 中 | Phase 3 前 spike 30min |
| IRC 大量动态频道性能 | 低 | ergo 支持 10000+ channels |
| async 竞态 (mode 切换 + agent 回复) | 中 | filters.py 决策禁止 await 远程 IO |
| soul.md prompt 工程质量 | 中 | 预留迭代窗口 |
| `zchat-protocol` 包成熟度 | 中 | 需确认是否已发布 |

---

## 11. 结论与下一步

### 评估结论

Issue #59 方案是**务实可行的 MVP 路径**：
- AutoService 改动极小 (~165 行)
- 不破坏现有架构（protocol.py 冻结）
- 回滚简单（停 bridge + 恢复开关）
- 职责分离清晰（`[as]` vs `[zchat]`）

### 下一步

1. **回答 Q-01 ~ Q-05** — 查 AutoService 代码确认
2. **Spike event_bus** — 30min 验证 LocalEngine 事件订阅
3. **zchat worktree** — 在 zchat 仓开始 Phase 1 开发
4. **AutoService PR** — T1.5 (开关) + T3.1 (relay) + T3.2 (dispatcher)

---

*文档基于 2026-04-17 会话分析生成。源 Issues: ezagent42/zchat#59, #60, #61*
