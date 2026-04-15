# AutoService Contracts Index

> Path B 适配层契约索引。所有前端 / 业务层 / channel 代码必须依赖本目录下的契约，不得旁路。

## 契约清单

| 契约 | 版本 | 状态 | 负责人 | 文档 |
|---|---|---|---|---|
| T0.1 ConversationEngine | 1.0 | ✅ FROZEN (2026-04-15) | DevA (author) / DevB (reviewer) | [conversation-engine.md](./conversation-engine.md) |
| T0.2 Frontend WS Schema | — | ⏳ Day 2 AM | DevB (author) / DevA (reviewer) | `frontend-ws-schema.md` (待起) |
| T0.3 Contract Tests | — | ⏳ Day 2 PM | DevA (author) / DevB (reviewer) | `../../tests/contract/` (待起) |

## 变更流程

- **v1.0 frozen 前**：Issue 评论区讨论，DevA/DevB 双签后落地
- **v1.0 frozen 后**：RFC issue → 影响面分析 → PR → 双 review → bump minor/major

## 相关

- Batch 0 Kickoff issue: [#21](https://github.com/ezagent42/AutoService/issues/21)
- Plan: [../plans/batch-0-kickoff.md](../plans/batch-0-kickoff.md)
