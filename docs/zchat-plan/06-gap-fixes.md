# Channel-Server v1.0 — GAP 修复与补充

> 基于 PRD 交叉验证的修复项

---

## 修复 1: SLA Timer 补全

01-protocol-primitives.md §6 的预定义 Timer 需要补充：

| Timer 名称 | 默认时长 | 超时动作 | 对应 PRD SLA |
|-----------|---------|---------|-------------|
| `takeover_wait` | 180s | mode → auto + 安抚消息 | 人工接单等待 < 180s |
| `idle_timeout` | 300s | state → idle | — |
| `close_timeout` | 3600s | state → closed | — |
| `sla_first_reply` | 60s | event: sla.breach | 人工首次回复 < 60s |
| **`sla_onboard`** | **3s** | **event: sla.breach** | **onboard 首屏应答 < 3s** |
| **`sla_placeholder`** | **1s** | **event: sla.breach** | **占位消息 < 1s** |
| **`sla_slow_query`** | **15s** | **event: sla.breach** | **慢查询续写 < 15s** |

**实现方式**：
- `sla_onboard`: conversation.created 时自动设置。首条 agent public 消息发出时取消。
- `sla_placeholder`: 复杂查询检测（App 插件通过 on_message 钩子标记）后设置。占位消息发出时取消。
- `sla_slow_query`: 占位消息发出后设置。edit_message 调用时取消。

**度量**：每个 SLA timer 在设置和取消/超时时都记录事件。实际响应时间 = cancel_time - set_time。App 层通过 EventBus.query 计算平均值。

---

## 修复 2: 并发上限

在 ConversationManager 中增加 operator 并发限制：

```python
class ConversationManager:
    MAX_OPERATOR_CONCURRENT = 5  # 默认值，可通过 config 覆盖
    
    def add_participant(self, conv_id: str, participant: Participant) -> None:
        if participant.role == ParticipantRole.OPERATOR:
            current_count = self._count_operator_conversations(participant.id)
            if current_count >= self.MAX_OPERATOR_CONCURRENT:
                raise ConcurrencyLimitExceeded(
                    f"Operator {participant.id} already in {current_count} conversations "
                    f"(limit: {self.MAX_OPERATOR_CONCURRENT})"
                )
        # ... 正常添加
```

**配置**：
```toml
[channel_server.participants]
max_operator_concurrent = 5  # 一个客服同时 Copilot ≤ 5 个对话
```

operator JOIN #conv-{id} 时，如果已达上限，channel-server 返回系统消息 "已达并发上限 (5/5)，请先释放其他对话" 并拒绝 JOIN。

---

## 修复 3: Conversation 结案与 CSAT

协议层需要增加"结案"概念，用于支撑计费指标。

### Conversation 扩展

```python
@dataclass
class Conversation:
    # ... 已有字段
    resolution: ConversationResolution | None = None  # 结案信息

@dataclass
class ConversationResolution:
    outcome: str          # "resolved" | "abandoned" | "escalated"
    resolved_by: str      # participant_id（agent 或 operator）
    csat_score: int | None = None  # 1-5, 客户评分（可选）
    timestamp: datetime = field(default_factory=datetime.now)
```

### 新增命令

| 命令 | 发送者 | 效果 |
|------|--------|------|
| `/resolve` | operator 或 agent | 标记 conversation 为 resolved，触发 CSAT 流程 |
| `/abandon` | system | 标记 conversation 为 abandoned（长期无响应） |

### CSAT 采集流程

```
/resolve 命令执行
  → conversation.state = closed
  → conversation.resolution = {outcome: "resolved", ...}
  → Bridge 向客户发送评分邀请
    Feishu: 发送卡片消息 "请为本次服务评分 ⭐1-5"
    Web: WebSocket push 评分 UI
  → 客户回复评分
  → Bridge 转发给 CS
  → CS 更新 conversation.resolution.csat_score
  → EventBus.publish(conversation.resolved)
```

### 升级转结案率

```
升级转结案率 = count(mode.changed→takeover AND conversation.resolved) 
             / count(mode.changed→takeover)
```

通过 EventBus.query 关联 mode.changed 和 conversation.resolved 事件计算。

---

## 修复 4: 卡片刷新策略（消除"或"）

**决策**：采用事件驱动方式，不用定期轮询。

当 conversation 中发生以下事件时，channel-server 自动向 `#squad-{operator}` 发送更新：

1. **conversation.created** → 发新卡片
2. **每 3 条 public 消息** → 更新卡片摘要（最近 3 条消息的摘要）
3. **mode.changed** → 更新卡片状态（"copilot → takeover"）
4. **conversation.closed** → 卡片标记为已关闭

摘要内容由 channel-server 生成（取最近 3 条消息的前 50 字），不依赖 Agent。

---

## 修复 5: 多租户隔离

v1.0 通过 **zchat project 隔离**实现多租户：

```
每个租户 = 一个 zchat project
         = 一个独立的 ergo 实例（独立端口）
         = 一个独立的 channel-server 实例
         = 一个独立的 SQLite 数据库
         = 一个独立的 plugins/ 目录
```

**Conversation 和 Event 不需要 tenant_id**——因为每个租户是完全独立的进程和数据库。

**租户管理**：
```bash
zchat project create tenant-acme --port 6670
zchat project create tenant-beta --port 6671
# 每个 project 独立启动 channel-server + agents + bridges
```

**数据隔离保证**：不同租户的 IRC server 在不同端口，channel-server 进程完全隔离，SQLite 文件在不同目录。不存在跨租户数据访问的可能。

---

## 修复 6: 分队动态分配

### Agent-Operator 分配注册表

```python
class SquadRegistry:
    """管理 operator ↔ agent 分队分配。"""
    
    def __init__(self):
        self._assignments: dict[str, list[str]] = {}  # operator_id → [agent_ids]
    
    def assign(self, operator_id: str, agent_id: str) -> None:
        """将 agent 分配给 operator 的分队。"""
        self._assignments.setdefault(operator_id, []).append(agent_id)
    
    def unassign(self, operator_id: str, agent_id: str) -> None:
        """从分队移除 agent。"""
        if operator_id in self._assignments:
            self._assignments[operator_id].remove(agent_id)
    
    def reassign(self, agent_id: str, from_operator: str, to_operator: str) -> None:
        """将 agent 从一个 operator 转移到另一个。"""
        self.unassign(from_operator, agent_id)
        self.assign(to_operator, agent_id)
    
    def get_squad(self, operator_id: str) -> list[str]:
        return self._assignments.get(operator_id, [])
    
    def get_operator(self, agent_id: str) -> str | None:
        for op, agents in self._assignments.items():
            if agent_id in agents:
                return op
        return None
```

### 新增命令

| 命令 | 发送者 | 效果 |
|------|--------|------|
| `/assign {agent} {operator}` | admin | 将 agent 分配给 operator 的分队 |
| `/reassign {agent} {from} {to}` | admin | 转移 agent |
| `/squad` | operator | 查看自己分队的 agent 列表 |

### IRC 映射

agent 被 assign 给 operator 后：
- agent 自动 JOIN `#squad-{operator}`
- operator 的飞书分队群中看到 agent 加入分队的通知

---

## 修复 7: 多 Agent 协作模型

PRD 描述了 4 个角色（客服/翻译/线索收集/智能分流），这些是 **App 层的 agent 行为定义**，不是协议原语。但协议需要支持 agent 间通信。

### Agent-to-Agent 通信

agent 之间通过 **同一个 conversation 的 side channel** 通信：

```
#conv-feishu_oc_abc123 中有两个 agent: fast-agent + deep-agent

fast-agent 判断需要深度查询:
  → send_side_message(conv_id, "@deep-agent 请分析这个对比需求")
  → side 消息 → deep-agent 的 MCP inject（visibility=side）
  → deep-agent 收到，执行查询
  → deep-agent 的 public reply → Gate → 到客户

或通过 /dispatch 命令:
  → admin 在 #admin: /dispatch feishu_oc_abc123 deep-agent
  → deep-agent JOIN #conv-feishu_oc_abc123
```

**路由策略不在协议层**。智能分流 agent 的路由决策是 agent 自己的 soul.md 定义的行为，通过 @mention 或 /dispatch 触发其他 agent 加入 conversation。

---

## 修复 8: v1.0 明确的 Out of Scope

以下 PRD 需求在 v1.0 中 **不实现**，标注为后续版本：

| 需求 | PRD 来源 | 原因 | 后续版本 |
|------|---------|------|---------|
| Dream Engine 完整 pipeline | Epic 4 | 复杂度高，需独立设计 | v1.1 |
| 灰度发布引擎 | US-4.4 | 需要 A/B testing 框架 | v1.1 |
| 事实准确率度量 | §6 | 需要 evaluation pipeline | v1.1 |
| 快慢双模型路由策略 | §5 模块 B | Agent 行为层，v1.0 用 soul.md 实现 | v1.1 可考虑协议级支持 |
| 合规规则引擎 | US-1.4 | 需要法律团队输入 | v1.1 |
| 虚拟客户预演 | US-1.3 | 上线向导的一部分 | v1.1 |
| 管理仪表盘 Web UI | US-3.1 | Frontend 独立开发 | v1.1 |
| PSTN 电话接入 | §5 模块 A | 需要 PSTN 网关 | v2.0 |
| 跨租户联邦 | — | 单租户先跑通 | v2.0 |

**v1.0 交付范围**：
- 协议原语全部实现（Conversation + Mode + Gate + Visibility + Timer + Event + Commands）
- channel-server 核心引擎（ConversationManager + ModeManager + MessageGate + TimerManager + EventBus + PluginManager）
- Feishu Bridge（从 AutoService 迁移）
- Web Bridge（从 AutoService 迁移）
- Epic 2 全部 6 个 US 的端到端流程
- Epic 3 的 /status /dispatch /review 命令
- CSAT 采集基础流程
- 并发上限控制
- 分队分配管理

---

## 实现状态追踪（Phase 4 完成后）

> 更新于 2026-04-15，基于 `feat/server-v1` 分支 `5289488` commit

### 已完成（WORKING）

| 组件 | 实现文件 | 测试 |
|------|---------|------|
| MessageGate (gate_message) | `protocol/gate.py` | 28 unit tests |
| ModeManager (6 种转换) | `engine/mode_manager.py` | 19 unit tests |
| ConversationManager (CRUD + resolve + set_csat + reactivate) | `engine/conversation_manager.py` | 22 unit tests |
| MessageStore (save + edit + get) | `engine/message_store.py` | unit tests |
| TimerManager (set + cancel + expire event) | `engine/timer_manager.py` | unit tests |
| EventBus (subscribe + publish + query + SQLite) | `engine/event_bus.py` | unit tests |
| PluginManager (hook load + call) | `engine/plugin_manager.py` | unit tests |
| ParticipantRegistry | `engine/participant_registry.py` | unit tests |
| SquadRegistry (assign + unassign + reassign + get) | `engine/squad_registry.py` | unit tests |
| CommandParser (parse 10 commands) | `protocol/commands.py` | unit tests |
| IRC Transport (extract + handle) | `transport/irc_transport.py` | 7 unit tests |
| Bridge API (WebSocket register + customer_connect + message routing) | `bridge_api/ws_server.py` | 4 E2E tests |
| MCP tools: reply, edit_message, join_conversation, send_side_message, list_conversations, get_conversation_status | `server.py` | 4 unit + E2E |
| /hijack /release /copilot handler | `server.py:412-443` | E2E mode_switching |
| Gate enforcement E2E | `tests/e2e/test_gate_enforcement.py` | 2 E2E tests |

**总计**: 125 tests PASS, 0 FAIL

### 待实现（命令 Handler）

以下命令在 `protocol/commands.py` 中已定义和解析，但 **缺少执行 handler**：

| 命令 | 优先级 | 前置 | Phase Final 阻塞 |
|------|--------|------|------------------|
| `/resolve` | **P0** | ConversationManager.resolve() 已实现，需在 bridge callback 中接通 | ✅ 阻塞 |
| `/status` | **P0** | ConversationManager.list_active() 已实现，需返回格式化结果 | ✅ 阻塞 |
| `/dispatch` | **P1** | 需实现：指定 agent JOIN conversation + 通知 agent MCP | ✅ 阻塞 |
| `/abandon` | P2 | ConversationManager.close() 已实现 | 否 |
| `/assign` | P2 | SquadRegistry.assign() 已实现，需在 bridge callback 中接通 | 否 |
| `/reassign` | P2 | SquadRegistry.reassign() 已实现 | 否 |
| `/squad` | P2 | SquadRegistry.get_squad() 已实现 | 否 |

**实现位置**: 命令 handler 应添加到 `server.py` 的 `_on_operator_command()` 或 `_on_admin_command()` 回调中，与现有 /hijack handler 模式一致。

### 待验证（端到端路径）

以下路径各组件单独 WORKING，但未串成端到端测试：

| 路径 | 涉及组件 | 状态 |
|------|---------|------|
| edit_message → Bridge → Feishu 编辑 | MCP tool + Bridge send_edit + feishu sender.update | MCP tool WORKING，Bridge→Feishu 在 Phase 4.5 |
| /resolve → close + CSAT 请求 → Bridge → 评分卡片 → csat_response → set_csat | ConversationManager WORKING，Bridge→Feishu 在 Phase 4.5 |
| Timer expire → mode auto-revert → 安抚消息 | TimerManager WORKING，需 App plugin 配合设置 timer |
| @operator 求助 → timer start → timeout → auto-revert | Agent 行为 + Timer + Plugin，需集成 |

---

*End of GAP Fixes v1.0*
