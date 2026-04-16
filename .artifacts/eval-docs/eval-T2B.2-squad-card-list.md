---
type: eval-doc
id: "eval-doc-010"
status: draft
producer: skill-5
created_at: "2026-04-16"
mode: simulate
feature: "T2B.2 分队卡片列表 UI"
submitter: DevB
related:
  - "task:T2B.2"
  - "task:T2B.1 (operator-console skeleton)"
  - "task:T1A.9 (squad plugin)"
  - "contract:docs/contracts/frontend-ws-schema.md §S8"
  - "contract:docs/contracts/conversation-engine.md §ConversationMode/State"
---

# Eval: T2B.2 分队卡片列表 UI

## 基本信息
- 模式：模拟（simulate）
- 提交人：DevB
- 日期：2026-04-16
- 状态：draft
- 任务类型：🟢 Green · B 线
- 依赖：T2B.1（🟩）、T1A.9（🟩）

## 任务范围与验收标准

**范围**：
1. 扩展 `operatorStore.ts` — 新增 `conversations` 状态 + CRUD actions
2. 扩展 `useOperatorWS.ts` — 处理 S8 `event` frames，分发到 store
3. 重写 `SquadPane.tsx` — 渲染 5 状态卡片列表
4. 新增 `ConversationCard.tsx` — 单张会话卡片组件

**不在范围内**：
- Copilot 侧栏（T2B.3）
- /hijack 按钮（T2B.4）
- Takeover UI（T2B.5）
- 卡片点击后的 operator_join 发送（T2B.3 负责，本任务只预留 onCardClick prop）

**5 状态卡片模板**：

| 卡片状态 | 映射条件 | 颜色标签 |
|---|---|---|
| `idle` | state=created/active, mode=auto, 无近期消息 | `default` |
| `waiting-reply` | state=active, mode=auto, 有客户消息待回复 | `blue` |
| `escalation-pending` | state=active, mode=copilot | `orange` |
| `human-takeover` | state=active, mode=takeover | `red` |
| `closed` | state=closed/resolved | `gray` |

**卡片展示字段**：
- conversation_id（短截取）
- customer_id
- 当前状态标签（颜色 Tag）
- 最后一条消息摘要（≤40 字）
- 最后活动时间（相对时间）
- 当前 mode

**验收标准**（M2 smoke test 相关）：
- customer-chat 发消息 → operator-console 卡片在 SquadPane 出现
- mode 变化 → 卡片状态实时更新
- conversation 关闭 → 卡片标记 closed

## 改动文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/store/operatorStore.ts` | 修改 | 新增 Conversation 类型 + conversations map + actions |
| `src/hooks/useOperatorWS.ts` | 修改 | onFrame 增加 event 类型处理分发 |
| `src/components/SquadPane.tsx` | 重写 | 从 TODO 占位改为卡片列表渲染 |
| `src/components/ConversationCard.tsx` | 新增 | 单张卡片组件（Ant Design Card + Tag） |

## 风险与约束

1. **事件格式依赖 WS schema §S8**：payload.event.type + payload.event.data 结构需严格对齐
2. **状态推导逻辑**：waiting-reply vs idle 需根据最后消息发送者判断（customer 发了但 agent 未回 → waiting-reply）
3. **实时性**：卡片更新走 WS 推送，不做轮询

## Testcase 表格

| TC | 场景 | 输入 | 期望 | 优先级 |
|---|---|---|---|---|
| TC-01 | 空 squad 显示空状态 | squads=["sq-A"], conversations=[] | 显示"暂无会话"提示 | P0 |
| TC-02 | conversation.created 事件 → 卡片出现 | S8 event type=conversation.created | 新卡片渲染，状态=idle | P0 |
| TC-03 | mode.changed → auto→copilot | S8 event mode.changed to=copilot | 卡片状态变 escalation-pending | P0 |
| TC-04 | mode.changed → copilot→takeover | S8 event mode.changed to=takeover | 卡片状态变 human-takeover | P0 |
| TC-05 | conversation.closed 事件 | S8 event type=conversation.closed | 卡片状态变 closed，标签灰色 | P0 |
| TC-06 | message.sent → waiting-reply 推导 | message.sent by customer | 卡片状态变 waiting-reply | P1 |
| TC-07 | message.sent by agent → idle 恢复 | message.sent by agent after customer | 卡片状态回 idle | P1 |
| TC-08 | 多 squad 过滤 | sq-A 有 2 个会话, sq-B 有 1 个 | 切换 tab 只看到对应 squad 的卡片 | P0 |
| TC-09 | 卡片点击触发 onCardClick | 点击卡片 | onCardClick(conversationId) 被调用 | P0 |
| TC-10 | 卡片按最后活动时间倒序 | 3 个会话不同时间 | 最新活动排最前 | P1 |
| TC-11 | conversation.resolved 事件 | S8 event type=conversation.resolved | 卡片状态变 closed | P1 |
| TC-12 | store conversations CRUD | add/update/remove actions | state 正确更新 | P0 |
| TC-13 | WS event 分发到 store | 各类 event frames | store.conversations 正确更新 | P0 |
| TC-14 | 卡片显示 customer_id | conversation with customer_id | 卡片上显示 customer_id | P0 |
| TC-15 | 卡片显示最后消息摘要 | message.sent 后 | 卡片显示消息前 40 字 | P1 |
