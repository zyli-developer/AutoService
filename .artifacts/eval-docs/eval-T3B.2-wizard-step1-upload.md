---
type: eval-doc
id: eval-T3B.2
status: draft
producer: skill-5
created_at: 2026-04-16
mode: simulate
feature: 向导 Step1 资料上传
submitter: DevB
related:
  - T3A.1 (soul_generator.py 后端)
  - T3B.1 (admin-portal SPA 骨架)
  - US-1.1 (上传基础信息生成初版 Agent)
---

# Eval: T3B.2 向导 Step1 资料上传

## 基本信息
- 模式：模拟
- 提交人：DevB
- 日期：2026-04-16
- 状态：draft

## Feature 描述

admin-portal 向导第一步：商户管理员填写基础信息并上传产品资料，触发后端 soul.md 自动生成。

**US-1.1 Gherkin**:
- Given 进入 admin-portal 向导步骤 1
- When 填入公司官网 URL 并上传产品目录 PDF 和历史对话 CSV
- Then 系统在 15 分钟内完成解析 + 自动生成 4 个角色 soul.md
- And 展示"Agent 初始化完成"的步骤 2 按钮

**输入表单字段**:
1. 公司官网 URL (text input)
2. 品牌名称 (text input, required)
3. 行业选择 (select: ecommerce/saas/finance/healthcare/education/telecom/general)
4. 支持语言 (multi-select, default: zh+en)
5. 产品资料上传 (file upload: PDF/CSV/TXT, multi-file)
6. 额外备注 (textarea, optional)

**后端调用**: `soul_generator.generate_souls(TenantConfig)` → `GenerationResult`
- TenantConfig fields: tenant_id, brand_name, industry, languages, primary_language, extra_context
- Returns: 4 个 SoulDraft + mode (ai/template_fallback) + warnings

## 代码分析

### 现有架构
- `WizardTab.tsx`: Ant Design Steps 组件，4 步骨架，当前 Step1 为 TODO 占位
- `adminStore.ts`: zustand store，有 tenantId/login/activeTab
- `soul_generator.py`: 完整后端实现，支持 TenantConfig → GenerationResult
- `soul_generator.py` Industry enum: ecommerce/saas/finance/healthcare/education/telecom/general
- admin-portal 使用 Ant Design + @ant-design/icons

### 需要新增
- `components/wizard/MaterialUploadStep.tsx` — Step1 表单组件
- Store 扩展 — wizard 状态 (currentStep, formData, generationResult, loading)
- 模拟 API 调用 — 后端 soul_generator 尚无 HTTP API，前端先 mock

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|---------|---------|--------|
| 1 | 表单渲染 | 用户已登录 admin-portal，进入向导 tab | 查看 Step1 页面 | 显示完整表单：URL 输入、品牌名、行业选择、语言多选、文件上传区、备注 | 可行。用 Ant Design Form + Input/Select/Upload 组件组合。WizardTab 改为受控 Steps，当前步骤渲染对应 Step 组件。 | 无 | P0 |
| 2 | 必填字段验证 | Step1 表单已渲染 | 不填品牌名直接点"下一步" | 表单验证失败，品牌名字段标红提示"请输入品牌名称" | 可行。Ant Design Form rules + required 验证。 | 无 | P0 |
| 3 | 文件上传 — 支持格式 | 表单已渲染 | 上传 .pdf、.csv、.txt 文件 | 文件出现在上传列表中，显示文件名和大小 | 可行。Ant Design Upload 组件 + accept 过滤。文件暂存前端 state（本地存储），后续 Step 完成后统一提交。 | 需注意：当前无文件上传后端 API，前端仅做本地暂存 + UI 展示。实际 KB 解析在 MVP 中可走 mock。 | P0 |
| 4 | 文件上传 — 拒绝不支持格式 | 表单已渲染 | 尝试上传 .exe 文件 | 提示"不支持的文件格式"，文件不被添加 | 可行。Upload beforeUpload 回调检查 MIME/后缀。 | 无 | P0 |
| 5 | 提交触发 soul 生成 | 表单填写完整 | 点击"生成 Agent" 按钮 | Loading 状态 → 模拟调用 soul_generator → 显示生成结果（4 个角色 + 状态） | 可行。前端 mock API 返回 GenerationResult 结构。Loading 动画使用 Ant Design Spin + Progress。生成成功后显示 4 张角色卡片（role name + kb_hit_count + warnings）。 | 后端无 HTTP API，前端用 mock。T5B.3 或后续任务补 API 对接。 | P0 |
| 6 | 生成结果展示 — 成功 | soul 生成完成 (mode=ai) | 查看生成结果区域 | 显示 4 张角色卡片：customer/translate/lead/triage，每张显示"已生成"绿色标记 + KB 命中数 | 可行。用 Ant Design Card + Tag 组件。mode=ai 显示绿色 Tag "AI 生成"，mode=template_fallback 显示黄色 Tag "模板生成"。 | 无 | P1 |
| 7 | 生成结果展示 — 有 warnings | soul 生成完成，部分角色有 warnings | 查看角色卡片 | 有 warning 的卡片显示黄色警告图标 + warning 文本 | 可行。SoulDraft.warnings 数组映射为 Alert 组件。 | 无 | P1 |
| 8 | "下一步" 按钮状态 | 生成完成 | 检查下一步按钮 | 生成成功后"下一步"按钮变为可点击（primary），点击后 WizardTab currentStep 变为 1 (Step2) | 可行。Store 中 wizardStep 状态控制。生成前 disabled，生成后 enabled。 | 无 | P1 |
| 9 | 行业选择与 soul_generator 对齐 | 表单已渲染 | 打开行业下拉框 | 选项与 soul_generator.Industry enum 完全一致：ecommerce/saas/finance/healthcare/education/telecom/general | 可行。选项列表从常量导出，与后端 enum 保持一致。 | 需注意保持前后端选项同步。 | P1 |
| 10 | 向导步骤导航 | 生成完成，已进入 Step2 | 点击 Steps 组件的 Step1 | 可以回退到 Step1，之前填写的表单数据保留 | 可行。表单数据存 zustand store，组件 unmount 不丢失。 | 无 | P2 |

## 风险点

1. **文件上传无后端 API**: 当前 `channels/web/app.py` 无文件上传端点。Step1 前端先做本地暂存 + mock 生成，后续 T5B.3 或专门任务补 API。
2. **soul_generator 无 HTTP 包装**: `soul_generator.py` 是 Python 模块，无 FastAPI route。前端 mock 其返回结构。
3. **KB 解析时间**: US-1.1 要求 15 分钟内完成，但 KB 解析 (PDF → sqlite) 不在 T3B.2 范围内。前端只做进度展示 UI。

## 后续行动

- [ ] eval-doc 已注册到 .artifacts/eval-docs/
- [ ] 用户已确认 testcase 表格 (status: draft → confirmed)
