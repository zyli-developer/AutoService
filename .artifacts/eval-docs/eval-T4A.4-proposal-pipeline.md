---
type: eval-doc
id: eval-T4A.4
status: draft
producer: skill-5
created_at: 2026-04-16
mode: simulate
feature: "T4A.4 提案生成 pipeline"
submitter: DevA
related:
  - eval-T4A.3
---

# Eval: T4A.4 提案生成 pipeline

## 基本信息
- 模式：模拟（simulate）
- 提交人：DevA
- 日期：2026-04-16
- 状态：draft

## Feature 描述

Dream Engine 核心：从 MemoryPool 中回放历史对话，使用 LLM 分析模式，生成结构化改进提案 JSON。由 LowPeakScheduler (T4A.3) 在低峰期触发。

**Pipeline 流程**: MemoryPool → 选取对话 → LLM 回放分析 → 抽取建议 → 提案 JSON → 存储

### 依赖
- **MemoryPool (T4A.1)**: 读取历史对话 turns
- **LowPeakScheduler (T4A.3)**: 触发时机（通过回调）
- **ComplianceEngine (T3A.7)**: 提案需通过合规预检

### 新增文件
| 文件 | 说明 |
|---|---|
| `autoservice/proposal_pipeline.py` | ProposalPipeline 类 |
| `tests/test_proposal_pipeline.py` | 测试 |

### 提案 JSON Schema

```json
{
  "id": "prop_<ulid>",
  "created_at": "2026-04-16T03:00:00Z",
  "source_conversations": ["web_123", "web_456"],
  "category": "response_quality|workflow|knowledge_gap|tone",
  "title": "改进建议标题",
  "description": "详细描述",
  "evidence": [
    {"conversation_id": "web_123", "turn": 5, "quote": "..."}
  ],
  "suggestion": "具体改进动作",
  "priority": "high|medium|low",
  "status": "draft",
  "compliance_check": {"passed": true, "flags": []}
}
```

### 设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| LLM 调用 | 抽象为 `analyzer` callable | 解耦具体模型，测试可用 stub |
| 对话选取 | 按时间窗口 + 采样（最近 24h，最多 50 条） | 控制 token 开销 |
| 提案存储 | SQLite 表 `proposals` | 与 memory_pool 同库 |
| 批次处理 | 每次回放 5-10 条对话为一批 | 避免单次 LLM 调用过大 |
| 合规预检 | 可选（compliance_engine 参数） | 不阻塞核心流程 |

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|---------|---------|--------|
| 1 | 导入和实例化 | 无 | `ProposalPipeline(memory_pool, analyzer=stub)` | 实例化成功 | 新建 | 无 | P0 |
| 2 | 选取对话 | memory_pool 有 20 条对话 | `pipeline.select_conversations(hours=24, max_count=10)` | 返回最近 24h 内最多 10 条 conv_id | 查 memory_turns 的 distinct conv_id，按最新 timestamp 排序 | 无 | P0 |
| 3 | 回放单条对话 | 选定 conv_id | `pipeline.replay_conversation(conv_id)` | 返回该对话所有 turns 的格式化文本 | MemoryPool.get_turns(conv_id) → 格式化 | 无 | P0 |
| 4 | LLM 分析（stub） | 格式化的对话文本 | `pipeline.analyze(text)` | 返回结构化建议列表 | 调用 analyzer callable，解析返回 JSON | 无 | P0 |
| 5 | 生成提案 JSON | 分析结果 | `pipeline.create_proposal(analysis, source_convs)` | 返回符合 schema 的 Proposal dict | 填充所有字段，生成 ID | 无 | P0 |
| 6 | 端到端 run | memory_pool 有数据 | `await pipeline.run()` | 选取 → 回放 → 分析 → 生成提案列表 | 组合前面步骤 | 无 | P0 |
| 7 | 提案存储 | run 产出提案 | 检查 SQLite proposals 表 | 提案已持久化 | INSERT INTO proposals | 无 | P0 |
| 8 | 提案查询 | 已存储提案 | `pipeline.list_proposals(status="draft")` | 返回 draft 状态的提案 | SELECT WHERE status=? | 无 | P0 |
| 9 | 空 memory_pool | 无对话数据 | `await pipeline.run()` | 返回空列表，不报错 | select 返回 []，跳过分析 | 无 | P1 |
| 10 | analyzer 返回无建议 | 对话质量好 | LLM 分析后无改进点 | run 返回空提案列表 | analyzer 返回 [] | 无 | P1 |
| 11 | 合规预检通过 | compliance_engine 可用 | 生成提案后预检 | proposal.compliance_check.passed = True | 调用 compliance.check(proposal) | 无 | P1 |
| 12 | 合规预检不通过 | 提案触发合规规则 | 预检失败 | proposal.compliance_check.passed = False，附 flags | 标记但不删除提案 | 无 | P1 |
| 13 | 批次处理 | 30 条对话 | run with batch_size=10 | 分 3 批处理 | 循环分批，每批独立分析 | 无 | P1 |
| 14 | 提案分类 | 不同类型建议 | 根据 LLM 输出分类 | category 正确填充 | 从 analyzer 结果提取 category 字段 | 无 | P1 |
| 15 | 提案优先级 | 基于 evidence 数量 | 多条证据 → high，1 条 → medium | priority 自动判定 | len(evidence) >= 3 → high | 无 | P2 |

## Review Checklist（🟡 Yellow）

1. **提案 JSON schema** — 字段是否覆盖前端 T4B.1（提案审核页）的展示需求？
2. **analyzer 接口** — `async def analyze(text: str) -> list[dict]` 是否足够灵活？
3. **对话选取策略** — 24h + 最多 50 条是否合理？
4. **合规集成** — 预检是 optional 还是 mandatory？
5. **存储格式** — SQLite 还是 JSON 文件？

## 后续行动

- [ ] eval-doc 已注册
- [ ] 用户已确认 (draft → confirmed)
