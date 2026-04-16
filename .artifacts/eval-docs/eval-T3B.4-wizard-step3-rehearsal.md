---
type: eval-doc
id: eval-T3B.4
status: draft
producer: skill-5
created_at: 2026-04-16
mode: simulate
feature: 向导 Step3 虚拟客户预演 UI
submitter: DevB
related:
  - T3A.2 (sim_customer.py 虚拟客户生成 pipeline)
  - T3B.1 (admin-portal SPA 骨架)
  - US-1.3 (虚拟客户预演)
  - ζ4 (步骤 3 虚拟客户预演)
---

# Eval: T3B.4 向导 Step3 虚拟客户预演 UI

## 基本信息
- 模式：模拟
- 提交人：DevB
- 日期：2026-04-16
- 状态：draft

## Feature 描述

admin-portal 向导第三步：展示 sim_customer.py 生成的 ≥10 条虚拟客户-Agent 对话，
管理员逐条审阅（✓ 通过 / ✎ 编辑 / ⚠ 标记），审阅进度可视化，全部审阅完成后可进入下一步。

**US-1.3 Gherkin**:
- Given 向导步骤 1-2 已完成（soul.md 已生成、渠道已配置）
- When 进入向导步骤 3
- Then 自动触发虚拟客户预演，展示 ≥10 条模拟对话
- And 管理员可逐条审阅（✓/✎/⚠），查看完成度进度条
- And 全部审阅完成后"下一步"按钮可用

**后端数据模型（T3A.2 sim_customer.py）**:
- `SimDialog`: id, scenario(Scenario), persona(Persona), turns(SimTurn[]), language, review_status
- `SimTurn`: role("customer"|"agent"), content, metadata
- `Scenario`: id, name_zh, intent, keywords, trap_question, degraded
- `Persona`: id, name_zh, traits[], communication_style
- 6 种 persona: angry-refund, price-sensitive, non-native-speaker, tech-illiterate, repeat-customer, cross-border
- 5 种 intent: product_inquiry, complaint, purchase_intent, language_barrier, general_question

## Testcase 列表

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异 | 优先级 |
|---|------|---------|---------|---------|---------|------|--------|
| TC1 | 步骤3页面渲染完整 | 组件挂载 | render VirtualRehearsalStep | DOM 包含：标题区、对话列表区、进度条、"下一步"按钮 | zustand store + Ant Design Card/List/Progress 组件渲染，所有 data-testid 可查到 | 无 | P0 |
| TC2 | 触发生成预演对话 | 组件挂载 | 组件 mount 时自动调用 mock 生成 | loading 状态显示 → 生成完成后展示 ≥10 条对话卡片 | mockGenerateDialogs() 返回 12 条 SimDialog，使用 fakeTimers 验证 loading → result 过渡 | 无 | P0 |
| TC3 | 对话卡片展示 scenario + persona + turns | 生成完成 | 查看任一对话卡片 | 卡片显示 scenario.name_zh、persona.name_zh、persona 标签（communication_style）、对话轮次 | Card 组件展示结构化信息，turns 用 chat-bubble 样式（customer 左、agent 右）区分角色 | 无 | P0 |
| TC4 | 审阅操作：✓ 通过 | 生成完成 | 点击对话卡片的 ✓ 按钮 | 该对话 review_status 变为 "approved"，卡片显示绿色通过标记，进度条 +1 | store 中 dialogs[i].review_status = 'approved'，Tag 变绿色 CheckCircle | 无 | P0 |
| TC5 | 审阅操作：⚠ 标记 | 生成完成 | 点击对话卡片的 ⚠ 按钮 | 该对话 review_status 变为 "flagged"，卡片显示橙色警告标记，进度条 +1 | store 中 dialogs[i].review_status = 'flagged'，Tag 变橙色 WarningOutlined | 无 | P0 |
| TC6 | 进度条反映审阅完成度 | 生成 12 条对话 | 审阅 6 条后检查 | Progress 组件显示 6/12 (50%) | Ant Design Progress percent={Math.round(reviewed/total*100)}，文字显示 "6/12 已审阅" | 无 | P0 |
| TC7 | 下一步按钮：全部审阅前 disabled | 生成完成，部分未审阅 | 检查"下一步"按钮状态 | disabled | btn-next disabled when reviewed < total | 无 | P0 |
| TC8 | 下一步按钮：全部审阅后 enabled | 全部 12 条已审阅 | 检查"下一步"按钮状态 | enabled | btn-next enabled when reviewed === total | 无 | P0 |
| TC9 | 陷阱问题标识 | 生成完成 | 查看含 trap turn 的对话 | 含 is_trap=true 的 turn 显示特殊标记（如橙色边框或 🪤 图标） | SimTurn.metadata.is_trap 时添加 Tag "陷阱题" | 无 | P1 |
| TC10 | degraded 场景提示 | 生成的 scenario.degraded=true | 查看 degraded 对话卡片 | 卡片顶部显示 "降级场景" 提示（KB 数据不足时的 fallback） | scenario.degraded 时显示 Alert type="info" | 无 | P1 |

## 架构分析

### 前端需要新增

1. **VirtualRehearsalStep 组件** (`components/wizard/VirtualRehearsalStep.tsx`)
   - 核心展示组件，包含对话列表、审阅按钮、进度条
   - 使用 Ant Design: Card, List, Progress, Button, Tag, Space, Typography, Alert, Spin

2. **adminStore 扩展**
   - 新增 state: `rehearsalDialogs: SimDialogUI[]`, `rehearsalLoading: boolean`
   - SimDialogUI: 前端 SimDialog 镜像类型（id, scenario, persona, turns, language, review_status）
   - 新增 actions: `setRehearsalDialogs`, `setRehearsalLoading`, `updateDialogReviewStatus(dialogId, status)`

3. **WizardTab 集成**
   - 替换 wizardStep === 2 的占位符为 `<VirtualRehearsalStep />`

### Mock 策略

使用 `mockGenerateDialogs(tenantId)` 返回 12 条 SimDialog，覆盖：
- 6 种 persona 各出现 ≥1 次
- 5 种 intent 各出现 ≥1 次
- 至少 2 条含 trap turn (is_trap=true)
- 至少 1 条 degraded scenario

## 风险标注

- **无后端 API 联调**：当前仅 mock 数据，真实 sim_customer.py 需 LLM 调用，UI 侧不关心
- **数据量**：12 条对话 × 3-6 轮 = 36-72 条 turns，需注意列表性能（Card 虚拟滚动暂不需要）
- **审阅状态持久化**：当前仅 zustand 内存态，刷新丢失（符合向导流程，不需 persist）

## 统计

| 指标 | 值 |
|------|-----|
| 总用例数 | 10 |
| P0 | 8 |
| P1 | 2 |
| 来源 | eval-doc simulate |
