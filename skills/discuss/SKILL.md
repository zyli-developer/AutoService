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

3. **Run init script** to ensure the persistent dev worktree and create a session directory:
   ```bash
   REPO="$(git rev-parse --show-toplevel)"
   # Persistent dev worktree lives alongside the repo by default
   WORKTREE="${DISCUSS_WORKTREE:-${REPO}/.discuss-worktree}"
   uv run skills/discuss/scripts/init_discuss.py \
     --topic "{topic}" \
     --slug "{slug}" \
     --chat-id "{chat_id}" \
     --started-by "{user}" \
     --source "{source}" \
     --repo-path "$REPO" \
     --worktree-path "$WORKTREE"
   ```

   The worktree is **persistent** (branch `discuss/dev`). First invocation creates it; subsequent invocations reuse it. The session directory is `<worktree>/.discuss/sessions/{YYYY-MM-DD}-{slug}/`.

4. **If source document exists**, read it to understand the context.

### Phase 2 — Generate Agenda

Session state lives in `<worktree>/.discuss/sessions/{date}-{slug}/` (referred to below as `<session_dir>`).

1. Read `skills/discuss/templates/agenda.md` for the generation guide.
2. Read `skills/discuss/templates/topic-types.yaml` and use the `general` type's `agenda_hint`.
3. Generate 3-5 discussion questions tailored to the topic (and source document if provided).
4. Reply to the group with the proposed agenda. Ask the initiator to confirm or adjust.
5. Write the agenda to `<session_dir>/agenda.md`.
6. Update `<session_dir>/session.yaml`: set `status: agenda_draft`.

### Phase 3 — Agenda Confirmation

When the initiator confirms (says "ok", "确认", "可以", "没问题", etc.) or adjusts:
- If confirmed: update `<session_dir>/session.yaml` → `status: active`, `agenda_confirmed: true`
- If adjusted: update the agenda, ask for confirmation again
- Reply: "讨论正式开始，大家可以针对以上议题自由发言。"

## 2. Process Message

**Trigger:** Any message while the active session's `session.yaml` status is `active`.

For each incoming message:

1. **Identify the speaker** from the message `user` field.
2. **Add participant** to `<session_dir>/session.yaml` if not already listed.
3. **Determine which agenda items** the message relates to. Tag with `[议题 N]`.
4. **Append to transcript** in `<session_dir>/transcript.md`:
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

1. **Verify the sender** is the discussion initiator (`started_by` in `<session_dir>/session.yaml`). If not, reply: "只有讨论发起人 {started_by} 可以结束讨论。"

2. **Generate report:**
   - Read `skills/discuss/templates/report.md` for the report structure guide.
   - Read `<session_dir>/session.yaml` for metadata.
   - Read `<session_dir>/agenda.md` for the agenda.
   - Read `<session_dir>/transcript.md` for the full transcript.
   - Generate the structured report following the template.

3. **Save and commit inside the worktree (do NOT merge back to main):**
   ```bash
   cd <worktree>
   # Write <session_dir>/report.md with the generated report (use Write tool).
   cp .discuss/sessions/{date}-{slug}/report.md discussions/{date}-{slug}.md

   git add discussions/{date}-{slug}.md .discuss/sessions/{date}-{slug}/
   git commit -m "discuss: {topic} — session report

   Participants: {participant_list}
   Duration: {duration}
   Action items: {count}"
   ```

   The report stays on the `discuss/dev` branch inside the persistent worktree. `main` is never touched. Developers can browse `<worktree>/discussions/` to read past reports.

4. **Reply to group** with a summary: key conclusions, action items, and the report location (e.g. `discussions/{date}-{slug}.md` in the discuss worktree).

5. **Update session.yaml** → `status: ended` before committing (so the ended state is captured in the commit and survives restarts).

## 4. Discussion Status

**Trigger:** `/discuss status` message.

Find the session directory for this chat (scan `<worktree>/.discuss/sessions/*/session.yaml` for matching `chat_id` with `status: active`). Read its `session.yaml` and `transcript.md`, then reply with:
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
| Session recovery after restart | Scan `<worktree>/.discuss/sessions/*/session.yaml` for `status: active`, resume from current status, notify group: "我回来了，讨论继续。" |
