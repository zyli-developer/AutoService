---
name: discuss
description: "Group discussion moderator skill. Use when runtime_mode is 'discuss'. Manages discussion lifecycle: agenda generation, free-form group discussion tracking, consensus/divergence identification, and structured report generation. TRIGGER when: runtime_mode is 'discuss', user says '/discuss', or message type is 'discuss_idle_reminder'."
---

# /discuss — Group Discussion Moderator

When invoked, this skill moderates a structured group discussion in a Feishu chat. You guide free-form conversation, track viewpoints per participant, identify consensus and divergence, and generate a report at the end.

## Command Routing

Parse the incoming message to determine the action:

| Pattern | Action |
|---------|--------|
| `/discuss "topic"` or `/discuss @file` | **Start discussion** — go to [Start Discussion](#1-start-discussion) |
| `/discuss end` | **End discussion** — go to [End Discussion](#3-end-discussion) |
| `/discuss status` | **Show status** — go to [Discussion Status](#4-discussion-status) |
| `discuss_idle_reminder` message type | **Idle reminder** — go to [Idle Reminder](#5-idle-reminder) |
| Any other message while in discuss mode | **Discussion message** — go to [Process Message](#2-process-message) |

---

## 1. Start Discussion

**Trigger:** First message with `runtime_mode: "discuss"` containing `/discuss` prefix.

### Phase 1 — Initialize

1. **Parse the command** to extract topic and optional source document:
   - `/discuss "优化登录流程"` → topic="优化登录流程", source=null
   - `/discuss @docs/prd.md` → topic=filename, source="docs/prd.md"
   - `/discuss @docs/prd.md "重点讨论安全性"` → topic="重点讨论安全性", source="docs/prd.md"

2. **Derive slug** from topic: lowercase, replace spaces/special chars with hyphens, truncate to 50 chars.

3. **Run init script** to create worktree and state files:
   ```bash
   uv run skills/discuss/scripts/init_discuss.py \
     --topic "{topic}" \
     --slug "{slug}" \
     --chat-id "{chat_id}" \
     --started-by "{user}" \
     --source "{source}" \
     --repo-path "$(git rev-parse --show-toplevel)" \
     --worktree-path "/tmp/discuss-{chat_id}-$(date +%s)"
   ```

4. **If source document exists**, read it to understand the context.

### Phase 2 — Generate Agenda

1. Read `skills/discuss/templates/agenda.md` for the generation guide.
2. Read `skills/discuss/templates/topic-types.yaml` and use the `general` type's `agenda_hint`.
3. Generate 3-5 discussion questions tailored to the topic (and source document if provided).
4. Reply to the group with the proposed agenda. Ask the initiator to confirm or adjust.
5. Write the agenda to `.discuss/agenda.md` in the worktree.
6. Update `.discuss/session.yaml`: set `status: agenda_draft`.

### Phase 3 — Agenda Confirmation

When the initiator confirms (says "ok", "确认", "可以", "没问题", etc.) or adjusts:
- If confirmed: update `session.yaml` → `status: active`, `agenda_confirmed: true`
- If adjusted: update the agenda, ask for confirmation again
- Reply: "讨论正式开始，大家可以针对以上议题自由发言。"

## 2. Process Message

**Trigger:** Any message while `session.yaml` status is `active`.

For each incoming message:

1. **Identify the speaker** from the message `user` field.
2. **Add participant** to `session.yaml` if not already listed.
3. **Determine which agenda items** the message relates to. Tag with `[议题 N]`.
4. **Append to transcript** in `.discuss/transcript.md`:
   ```markdown
   ## {timestamp} — {user}
   [议题 {N}] {message content}
   ```
5. **Track consensus/divergence** mentally across the discussion.

### Moderator Behaviors

- **Pushing forward:** When one topic has sufficient discussion, suggest moving to the next: "议题 1 大家意见比较一致了，我们来看看议题 2？"
- **Off-topic redirect:** When messages are unrelated to any agenda item, gently redirect: "这个点很有意思，不过我们先聚焦在当前议题上？" Tag as `[题外]` in transcript.
- **Summary checkpoints:** After several messages on one topic, briefly summarize what's been said so far to keep everyone aligned.
- **Do NOT** reply to every single message — only intervene when it adds value (pushing forward, summarizing, redirecting).

## 3. End Discussion

**Trigger:** `/discuss end` message.

1. **Verify the sender** is the discussion initiator (`started_by` in `session.yaml`). If not, reply: "只有讨论发起人 {started_by} 可以结束讨论。"

2. **Generate report:**
   - Read `skills/discuss/templates/report.md` for the report structure guide.
   - Read `.discuss/session.yaml` for metadata.
   - Read `.discuss/agenda.md` for the agenda.
   - Read `.discuss/transcript.md` for the full transcript.
   - Generate the structured report following the template.

3. **Save and commit:**
   ```bash
   # Write report to worktree
   # (use Write tool to create the report file)

   # Copy to docs/discussions/ and commit
   cd {worktree_path}
   cp .discuss/report.md docs/discussions/{date}-{slug}.md
   git add docs/discussions/{date}-{slug}.md
   git commit -m "docs(discuss): {topic} — discussion report

   Participants: {participant_list}
   Duration: {duration}
   Action items: {count}"

   # Merge to main and cleanup
   cd $(git rev-parse --show-toplevel)
   git merge discuss/{slug}
   git worktree remove {worktree_path}
   git branch -d discuss/{slug}
   ```

4. **Reply to group** with a summary: the key conclusions, action items, and where the full report is saved.

5. **Update session.yaml** → `status: ended` (before cleanup, for crash recovery).

## 4. Discussion Status

**Trigger:** `/discuss status` message.

Read `.discuss/session.yaml` and `.discuss/transcript.md`, then reply with:
- Current status (agenda_draft / active / ended)
- Topic and agenda items
- Number of participants and their names
- Number of messages per agenda item
- Duration so far

## 5. Idle Reminder

**Trigger:** Message with `type: "discuss_idle_reminder"`.

Reply to the group:
"讨论已静默 {idle_minutes} 分钟。@{started_by} 是否要结束讨论并生成报告？发送 `/discuss end` 结束，或继续发言继续讨论。"

## Error Handling

| Scenario | Response |
|----------|----------|
| `/discuss` while another discuss is active | "当前已有讨论进行中，请先 `/discuss end` 结束当前讨论。" |
| Non-initiator sends `/discuss end` | "只有讨论发起人 {started_by} 可以结束讨论。" |
| `/discuss end` with no substantive messages | Generate minimal report noting no discussion occurred |
| Worktree creation fails | Reply with error, do not enter discuss state |
| Session recovery after restart | Read `.discuss/session.yaml`, resume from current status, notify group: "我回来了，讨论继续。" |
