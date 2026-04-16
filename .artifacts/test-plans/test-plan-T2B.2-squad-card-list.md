---
type: test-plan
id: "test-plan-009"
status: confirmed
producer: skill-2
created_at: "2026-04-16"
eval_doc: "eval-doc-010"
feature: "T2B.2 分队卡片列表 UI"
submitter: DevB
---

# Test Plan: T2B.2 分队卡片列表 UI

## 测试策略

- **单元测试**：operatorStore conversations CRUD (vitest)
- **组件测试**：ConversationCard 渲染 + SquadPane 过滤 (testing-library/react)
- **集成测试**：WS event → store → UI 全链路 (fake WS client)
- **环境**：vitest + jsdom + @testing-library/react

## 测试文件

| 文件 | 覆盖 TCs | 说明 |
|---|---|---|
| `src/__tests__/operatorStore.conversations.test.ts` | TC-12 | store CRUD |
| `src/__tests__/ConversationCard.test.tsx` | TC-14, TC-15 | 卡片渲染 |
| `src/__tests__/SquadPane.test.tsx` | TC-01, TC-08, TC-09, TC-10 | 列表过滤+排序+点击 |
| `src/__tests__/wsEventDispatch.test.tsx` | TC-02~07, TC-11, TC-13 | WS 事件→状态更新 |

## 15 Test Cases

### operatorStore.conversations (TC-12)
- TC-12a: addConversation 添加新会话到 map
- TC-12b: updateConversation 更新已有会话字段
- TC-12c: removeConversation 删除会话

### ConversationCard (TC-14, TC-15)
- TC-14: 卡片显示 conversation_id 短截取 + customer_id
- TC-15: 卡片显示最后消息摘要 ≤40 字 + 超出截断

### SquadPane (TC-01, TC-08, TC-09, TC-10)
- TC-01: 空 squad 显示"暂无会话"
- TC-08: 多 squad 只显示当前 squadId 对应的卡片
- TC-09: 点击卡片触发 onCardClick(conversationId)
- TC-10: 卡片按 lastActivityTs 倒序排列

### WS Event Dispatch (TC-02~07, TC-11, TC-13)
- TC-02: conversation.created → store 新增卡片，status=idle
- TC-03: mode.changed to=copilot → status=escalation-pending
- TC-04: mode.changed to=takeover → status=human-takeover
- TC-05: conversation.closed → status=closed
- TC-06: message.sent sender=customer → status=waiting-reply
- TC-07: message.sent sender=agent (after customer) → status=idle
- TC-11: conversation.resolved → status=closed
- TC-13: 多个连续 event frames → store 正确累积更新
