---
type: test-plan
id: plan-T3B.2
status: draft
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-T3B.2 (simulate): wizard Step1 material upload"
related:
  - eval-T3B.2
---

# Test Plan: T3B.2 向导 Step1 资料上传

## 触发原因

eval-T3B.2 模拟评估通过。新增 MaterialUploadStep 组件 + store 扩展。
测试为 Vitest + React Testing Library 组件测试。

## 用例列表

### TC-001: Step1 表单渲染完整

- **来源**：eval-doc TC1
- **优先级**：P0
- **前置条件**：组件挂载
- **操作步骤**：render MaterialUploadStep
- **预期结果**：DOM 中包含品牌名输入、行业选择、语言选择、文件上传区、备注文本域、生成按钮
- **涉及模块**：MaterialUploadStep.tsx

### TC-002: 品牌名必填验证

- **来源**：eval-doc TC2
- **优先级**：P0
- **前置条件**：表单已渲染
- **操作步骤**：不填品牌名，点击"生成 Agent"
- **预期结果**：按钮不触发生成，表单显示验证错误
- **涉及模块**：MaterialUploadStep.tsx

### TC-003: 文件上传接受 PDF/CSV/TXT

- **来源**：eval-doc TC3
- **优先级**：P0
- **前置条件**：表单已渲染
- **操作步骤**：检查 Upload 组件 accept 属性
- **预期结果**：accept 包含 .pdf,.csv,.txt
- **涉及模块**：MaterialUploadStep.tsx

### TC-004: 提交触发生成 + loading 状态

- **来源**：eval-doc TC5
- **优先级**：P0
- **前置条件**：表单填写完整
- **操作步骤**：填写品牌名 + 行业，点击"生成 Agent"
- **预期结果**：store.generating 变为 true → mock 完成后 → generationResult 有 4 个角色
- **涉及模块**：MaterialUploadStep.tsx, adminStore.ts

### TC-005: 生成结果显示 4 张角色卡片

- **来源**：eval-doc TC6
- **优先级**：P0
- **前置条件**：生成完成
- **操作步骤**：检查结果区域
- **预期结果**：DOM 中有 customer/translate/lead/triage 4 个角色名称
- **涉及模块**：MaterialUploadStep.tsx

### TC-006: 下一步按钮生成前 disabled

- **来源**：eval-doc TC8
- **优先级**：P1
- **前置条件**：表单渲染，未生成
- **操作步骤**：检查"下一步"按钮状态
- **预期结果**：disabled
- **涉及模块**：MaterialUploadStep.tsx

### TC-007: 行业选项与后端 enum 一致

- **来源**：eval-doc TC9
- **优先级**：P1
- **前置条件**：表单渲染
- **操作步骤**：检查行业选项列表
- **预期结果**：包含 ecommerce/saas/finance/healthcare/education/telecom/general
- **涉及模块**：MaterialUploadStep.tsx

## 统计

| 指标 | 值 |
|------|-----|
| 总用例数 | 7 |
| P0 | 5 |
| P1 | 2 |
| 来源：eval-doc | 7 |
