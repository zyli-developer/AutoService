# Discuss Command — Design Spec

## Overview

`discuss` 是 AutoService 飞书频道中的群组异步讨论命令。管理群成员通过 `/discuss` 发起讨论，AI 作为主持人引导群内自由讨论，最终生成结构化报告并 commit 到仓库。

`discuss` 替代现有的 `/evaluate` skill，作为更通用的"结构化收集团队观点"框架。后续 `evaluate`、`explain`、`feature-request`、`debug` 等将作为子命令纳入。

## Architecture — Hybrid 轻量方案

职责分工：

| 层 | 职责 |
|---|---|
| **channel-server** | (1) 识别 `runtime_mode: "discuss"` 做路由；(2) discuss 群的消息空闲计时，超时发提醒 |
| **channel.py + discuss skill** | 所有讨论逻辑：worktree 创建/销毁、讨论状态追踪（worktree 内文件持久化）、主持引导、报告生成、commit |

设计原则：channel-server 保持"纯路由器"定位，不管理讨论内容、议程、报告。

---

## 1. Command Interface

```
/discuss "话题描述"                        — 纯话题讨论
/discuss @docs/prd.md                     — 基于文档讨论
/discuss @docs/prd.md "重点讨论安全性"      — 文档 + 聚焦方向
/discuss end                              — 结束讨论，生成报告
/discuss status                           — 查看当前讨论进度
```

输入可以是文档路径、一句话描述、或两者结合。文档不是必须的。

## 2. Interaction Flow

```
管理员: /discuss "优化登录流程"
   │
   ▼
AI 读取输入，判断话题类型，生成议程草案（3-5 个讨论维度）
   │
   ▼
AI 回复群：列出议程，请管理员确认或调整
   │
   ▼
管理员确认（或调整后确认）
   │
   ▼
AI 正式开始讨论，群成员自由发言
AI 持续追踪：
  - 记录每个人的观点及对应议题
  - 识别共识和分歧
  - 适时推进下一议题
  - 偏题时温和引导
   │
   ▼
超时无人发言 → AI 提醒管理员是否结束（不自动结束，等管理员确认）
管理员也可随时发 /discuss end
   │
   ▼
AI 生成报告，commit 到仓库，回复群里报告摘要 + action items
```

## 3. Skill Structure

```
skills/discuss/
├── SKILL.md                     # skill 定义（触发条件、命令路由）
├── templates/
│   ├── agenda.md                # 议程生成提示模板
│   ├── report.md                # 报告输出模板
│   └── topic-types.yaml         # 话题类型定义
└── scripts/
    └── init_discuss.py          # 初始化 worktree + 状态文件
```

## 4. State Management

讨论启动后，在 worktree 的 `.discuss/` 目录下维护状态：

```
.discuss/
├── session.yaml                 # 会话元数据
├── agenda.md                    # 确认后的议程
├── transcript.md                # 讨论记录（按时间追加）
└── report.md                    # 结束时生成的最终报告
```

### session.yaml

```yaml
topic: "优化登录流程"
source: null                      # 或文档路径 "docs/prd.md"
topic_type: general               # general | bug | feature | deploy | ...
status: active                    # agenda_draft | active | ended
chat_id: "oc_xxxxx"
started_by: "dai.ming"
started_at: "2026-04-10T10:00:00Z"
participants:                     # AI 从发言中自动收集
  - name: "dai.ming"
    first_seen: "2026-04-10T10:00:00Z"
  - name: "allen.woods"
    first_seen: "2026-04-10T10:03:00Z"
agenda_confirmed: true
```

### transcript.md 追加格式

```markdown
## 2026-04-10T10:03:12Z — allen.woods
[议题 1] 当前登录流程最大的问题是多端状态不同步。

## 2026-04-10T10:05:30Z — dai.ming
[议题 1, 议题 3] 同意，而且 token 刷新逻辑太复杂，用户经常被踢出。
```

AI 在每条消息进来时，判断关联议题并打标签后追加到 transcript。

### 状态流转

```
/discuss 发起 → agenda_draft → 管理员确认 → active → /discuss end → ended
```

## 5. Channel-Server Extensions

### 5.1 路由支持

`runtime_mode: "discuss"` 作为新的 mode 值接入，无需改 `Instance` 数据结构。

**命令拦截与模式切换：** channel-server 在 Feishu 消息处理中识别 `/discuss` 前缀：

- 收到 `/discuss ...`（非 end/status）→ 将该群的 runtime_mode 切换为 `"discuss"`，记录切换前的原模式，然后将消息路由到 channel 实例
- 收到 `/discuss end` → 路由消息到 channel 实例处理报告生成，完成后将 runtime_mode 恢复为切换前的原模式（通常是 `"production"`）
- discuss 模式期间，该群所有后续消息都以 `runtime_mode: "discuss"` 路由

此机制与现有 `/explain` 命令的模式切换逻辑一致。

**更新 `channel-instructions.md`：**

1. 更新 runtime_mode 枚举声明：
```markdown
- `runtime_mode`: "production" | "improve" | "explain" | "discuss"
```

2. 新增 discuss mode 路由规则：
```markdown
### discuss mode
Use /discuss skill. AI acts as discussion moderator.
Messages in this mode are part of an ongoing group discussion session.
```

### 5.2 超时检测

新增数据结构和配置：

```python
_discuss_sessions: dict[str, float] = {}   # chat_id → last_message_timestamp
DISCUSS_IDLE_TIMEOUT = 15 * 60             # 15 分钟，可配置
```

逻辑：
- `runtime_mode == "discuss"` 的消息经过路由时，更新时间戳
- 后台定时任务每分钟检查一次
- 超时时向 channel 实例发送内部消息：

```json
{
  "type": "discuss_idle_reminder",
  "chat_id": "oc_xxxxx",
  "idle_minutes": 15
}
```

- channel.py 收到后注入 Claude Code 会话，AI 在群里提醒管理员
- 管理员回复后时间戳重置；`/discuss end` 清理该条目

## 6. Worktree Lifecycle

### 分支策略

每次讨论使用独立的临时分支 `discuss/{topic-slug}`，避免直接在 main 上操作产生冲突。

这个分支策略同时为未来扩展留出空间：当讨论从"结论阶段"推进到"执行阶段"（如根据讨论结果直接修改代码、新建 skill 等）时，`discuss/{topic-slug}` 分支可以继续承载开发工作，最终通过 PR 合入 main。第一版只做到结论（报告 commit），分支在报告合入后即删除。

### 生命周期

**创建：** `/discuss` 启动时

```bash
git worktree add -b discuss/{topic-slug} /tmp/discuss-{chat_id}-{timestamp} main
```

**讨论过程中：** 所有状态文件写入 worktree 的 `.discuss/` 目录。

**结束时（`/discuss end`）：**

```bash
# 1. 生成报告写入 worktree 内 .discuss/report.md
# 2. 将报告复制到 docs/discussions/（该目录会被 commit）
cp .discuss/report.md docs/discussions/{date}-{topic-slug}.md

# 3. 在 discuss/{topic-slug} 分支上 commit
git add docs/discussions/{date}-{topic-slug}.md
git commit -m "docs(discuss): {topic} — discussion report

Participants: dai.ming, allen.woods
Duration: 45min
Action items: 3"

# 4. 将报告合入 main
git checkout main
git merge discuss/{topic-slug}

# 5. 清理 worktree 和临时分支
git worktree remove /tmp/discuss-{chat_id}-{timestamp}
git branch -d discuss/{topic-slug}
```

只有最终报告进入 `docs/discussions/`，`.discuss/` 下的过程文件随 worktree 清理一并删除。

进程重启时可从 worktree 的 `session.yaml` 恢复状态继续。

### 合并策略

根据变更内容决定合并方式：

- **仅报告文件**（`docs/discussions/*.md`）→ 直接 merge 到 main。讨论本身即 review，无需额外审批
- **包含代码变更**（未来扩展）→ 创建 PR，等待人工 review 后合并。代码影响线上行为，必须有人 review

判断标准：commit 中是否包含 `docs/discussions/` 以外的文件变更。

### 未来扩展路径（第一版不实现）

当讨论达成共识并需要推进到执行阶段时：
- `/discuss end` 后不删除分支，而是保留 `discuss/{topic-slug}` 分支
- AI 基于讨论结论在该分支上继续开发（修改代码、新建 skill 等）
- 开发完成后自动创建 PR，实现"讨论 → 结论 → 开发 → PR review → 合并"的完整闭环

## 7. Report Format

```markdown
# 讨论报告：{topic}

| 字段 | 值 |
|------|-----|
| 发起人 | {started_by} |
| 日期 | {date} |
| 时长 | {duration} |
| 参与者 | {participants} |
| 素材 | {source}（可选） |

## 议程

1. {agenda_item_1}
2. {agenda_item_2}
...

## 讨论纪要

### 1. {agenda_item_1}

**共识/分歧：** {summary}

- **{participant}**: {viewpoint}
- **{participant}**: {viewpoint}

...

## Action Items

- [ ] **{assignee}** — {task}, {deadline}
...

## 未决问题

- {unresolved_item}
...
```

规则：
- 按议题组织，不按时间线
- 每个议题标注"共识"或"分歧"
- Action items 提取负责人和时间点，提取不到标注 TBD
- 未决问题单独列出

## 8. Topic Types & Extensibility

`templates/topic-types.yaml`：

```yaml
general:
  label: "通用讨论"
  agenda_hint: "根据话题内容，生成 3-5 个讨论维度"

# --- 预留，第一版不实现 ---
bug:
  label: "Bug 讨论"
  agenda_hint: "围绕复现步骤、影响范围、根因分析、修复方案展开"

feature:
  label: "功能需求讨论"
  agenda_hint: "围绕用户场景、需求价值、技术可行性、优先级展开"

deploy:
  label: "部署方案讨论"
  agenda_hint: "围绕变更内容、回滚策略、影响评估、上线计划展开"
```

第一版全部走 `general`，AI 根据输入内容自动生成议程。

后续扩展子命令只需：
1. 在 `topic-types.yaml` 补充类型定义
2. 在 `SKILL.md` 命令路由表加一行
3. 不需要改 channel-server 或 worktree 逻辑

## 9. Error Handling

| 场景 | 处理方式 |
|------|----------|
| 群内已有活跃 discuss 会话，又发了 `/discuss` | 提示已有讨论进行中，请先 `/discuss end` |
| channel.py 进程重启 | 从 worktree `session.yaml` 恢复状态，群里发"讨论继续" |
| 非发起人发 `/discuss end` | 只有 `started_by` 可以结束讨论 |
| 无实质发言就结束 | 生成简短"无实质讨论"报告，不创建 action items |
| worktree 创建失败 | 回复错误信息，不进入讨论状态 |
| 发言与议程无关 | AI 温和提醒回到议题，transcript 中标注"题外" |

不做过度防御：不限制参与人数、不做发言频率限制、不做内容审核。

## 10. First Version Scope

**做：**
- `general` 话题类型的完整讨论流程
- 议程生成 → 确认 → 自由讨论 → 报告输出
- worktree 生命周期管理
- channel-server discuss 路由 + 超时检测
- `/discuss`、`/discuss end`、`/discuss status` 三个命令

**不做：**
- 子命令（bug、feature、deploy 等话题类型）
- 自动转 Issue
- 与 `/evaluate`、`/explain` 的迁移整合
- 讨论历史的搜索和索引
