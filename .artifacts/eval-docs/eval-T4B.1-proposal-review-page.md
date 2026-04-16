---
type: eval-doc
id: eval-T4B.1
status: confirmed
producer: skill-5
created_at: 2026-04-16
mode: simulate
feature: 提案审核页
submitter: DevB
related:
  - T4A.4 (proposal_pipeline.py)
  - US-4.1
---

# Eval: T4B.1 提案审核页

## Feature 描述

admin-portal 提案审核页：展示 Dream Engine 生成的改进提案列表，
管理员可审核（接受/拒绝），按分类和优先级筛选。

**后端数据模型 (T4A.4 proposal_pipeline.py)**:
- Proposal: id, created_at, source_conversations[], category, title, description, evidence[], suggestion, priority, status, compliance_check
- category: response_quality | workflow | knowledge_gap | tone
- priority: high | medium | low
- status: draft | accepted | rejected | implemented

## Testcase 列表

| # | 场景 | 优先级 |
|---|------|--------|
| TC1 | 页面渲染：标题 + 筛选器 + 提案列表 + 统计 | P0 |
| TC2 | mock 加载提案列表（6 条） | P0 |
| TC3 | 按 status 筛选 (draft/accepted/rejected) | P0 |
| TC4 | 按 category 筛选 | P1 |
| TC5 | 接受提案 → status 变 accepted | P0 |
| TC6 | 拒绝提案 → status 变 rejected | P0 |
| TC7 | priority 标签颜色：high=red, medium=orange, low=blue | P0 |
| TC8 | 提案卡片展示完整信息 | P0 |

统计: 8 TCs (7×P0 + 1×P1)
