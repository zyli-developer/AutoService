---
type: test-plan
id: plan-T3B.4
status: draft
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-T3B.4 (simulate): wizard Step3 虚拟预演 UI"
related:
  - eval-T3B.4
---

# Test Plan: T3B.4 向导 Step3 虚拟预演 UI

## 触发原因

eval-T3B.4 模拟评估通过。新增 VirtualRehearsalStep 组件 + store 扩展。
测试为 Vitest + React Testing Library 组件测试。

## 用例列表

### TC-001: Step3 页面渲染完整

- **来源**：eval-doc TC1
- **优先级**：P0
- **前置条件**：组件挂载
- **操作步骤**：render VirtualRehearsalStep
- **预期结果**：DOM 包含标题、对话列表区、进度条、"下一步"按钮
- **涉及模块**：VirtualRehearsalStep.tsx

### TC-002: 触发生成显示 loading 后展示对话

- **来源**：eval-doc TC2
- **优先级**：P0
- **前置条件**：组件挂载
- **操作步骤**：点击"开始预演"按钮，等 fakeTimer 完成
- **预期结果**：loading indicator 出现 → 完成后 ≥10 条对话卡片
- **涉及模块**：VirtualRehearsalStep.tsx, adminStore.ts

### TC-003: 对话卡片展示 scenario + persona 信息

- **来源**：eval-doc TC3
- **优先级**：P0
- **前置条件**：生成完成
- **操作步骤**：检查对话卡片内容
- **预期结果**：卡片显示 scenario.name_zh、persona.name_zh、communication_style 标签
- **涉及模块**：VirtualRehearsalStep.tsx

### TC-004: 审阅操作 ✓ 通过

- **来源**：eval-doc TC4
- **优先级**：P0
- **前置条件**：生成完成
- **操作步骤**：点击第一条对话的 ✓ 按钮
- **预期结果**：该对话显示绿色通过标记，进度 +1
- **涉及模块**：VirtualRehearsalStep.tsx, adminStore.ts

### TC-005: 审阅操作 ⚠ 标记

- **来源**：eval-doc TC5
- **优先级**：P0
- **前置条件**：生成完成
- **操作步骤**：点击第一条对话的 ⚠ 按钮
- **预期结果**：该对话显示橙色警告标记，进度 +1
- **涉及模块**：VirtualRehearsalStep.tsx, adminStore.ts

### TC-006: 进度条反映审阅完成度

- **来源**：eval-doc TC6
- **优先级**：P0
- **前置条件**：生成 12 条对话
- **操作步骤**：审阅 6 条后检查进度
- **预期结果**：Progress 显示 50%，文字 "6/12 已审阅"
- **涉及模块**：VirtualRehearsalStep.tsx

### TC-007: 下一步按钮全部审阅前 disabled

- **来源**：eval-doc TC7
- **优先级**：P0
- **前置条件**：部分审阅
- **操作步骤**：检查"下一步"按钮状态
- **预期结果**：disabled
- **涉及模块**：VirtualRehearsalStep.tsx

### TC-008: 下一步按钮全部审阅后 enabled

- **来源**：eval-doc TC8
- **优先级**：P0
- **前置条件**：全部审阅完成
- **操作步骤**：审阅所有 12 条后检查
- **预期结果**：enabled
- **涉及模块**：VirtualRehearsalStep.tsx

### TC-009: 陷阱问题标识

- **来源**：eval-doc TC9
- **优先级**：P1
- **前置条件**：生成完成
- **操作步骤**：查看含 is_trap turn 的对话
- **预期结果**：trap turn 有 "陷阱题" 标签
- **涉及模块**：VirtualRehearsalStep.tsx

### TC-010: degraded 场景提示

- **来源**：eval-doc TC10
- **优先级**：P1
- **前置条件**：生成含 degraded scenario 的对话
- **操作步骤**：查看 degraded 对话卡片
- **预期结果**：显示 "降级场景" 提示
- **涉及模块**：VirtualRehearsalStep.tsx

## 统计

| 指标 | 值 |
|------|-----|
| 总用例数 | 10 |
| P0 | 8 |
| P1 | 2 |
| 来源：eval-doc | 10 |
