# Report Generation Guide

Generate the final discussion report from the transcript and agenda.

## Input
- Session metadata from `.discuss/session.yaml`
- Confirmed agenda from `.discuss/agenda.md`
- Full transcript from `.discuss/transcript.md`

## Report structure

```
# 讨论报告：{topic}

| 字段 | 值 |
|------|-----|
| 发起人 | {started_by} |
| 日期 | {date} |
| 时长 | {duration} |
| 参与者 | {participants, comma-separated} |
| 素材 | {source, or "无"} |

## 议程

{numbered agenda items}

## 讨论纪要

### 1. {agenda_item}

**共识/分歧：** {one-line summary of whether consensus was reached}

- **{participant}**: {their viewpoint, condensed}
- **{participant}**: {their viewpoint, condensed}

{repeat for each agenda item}

## Action Items

- [ ] **{assignee}** — {specific task}, {deadline or TBD}

## 未决问题

- {any unresolved items that need follow-up}
```

## Rules
1. Organize by agenda topic, NOT chronologically
2. For each topic, clearly label as **共识** (consensus) or **分歧** (divergence)
3. Attribute viewpoints to specific participants
4. Extract concrete action items with assignees where mentioned
5. If no assignee was discussed, mark as TBD
6. List unresolved questions separately
7. If a topic had no discussion, note "未讨论" (not discussed)
