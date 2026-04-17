# /discuss 命令 — 开发进度与手动测试指南

## 当前状态

**分支:** `feat/evaluate-skill`
**日期:** 2026-04-11（手动测试通过）
**状态:** v1 功能完成，飞书真实环境手动测试全部通过，可合并到 main

## 已完成

### 1. 设计文档
- `docs/2026-04-10-discuss-command-design.md` — 完整设计 spec（10 个章节）
- `docs/plans/2026-04-10-discuss-command-impl-plan.md` — 9 个 task 的实现计划

### 2. 代码实现

| 文件 | 改动 |
|------|------|
| `feishu/channel_server.py` | `/discuss` 命令路由（start/end/status/usage），模式切换，空闲超时检测 |
| `feishu/channel.py` | `discuss_idle_reminder` 消息转换处理 |
| `feishu/channel-instructions.md` | 新增 discuss runtime_mode 路由说明 |
| `skills/discuss/SKILL.md` | 讨论主持人技能定义（议程生成、发言跟踪、报告生成） |
| `skills/discuss/scripts/init_discuss.py` | Git worktree + `.discuss/` 状态文件初始化脚本 |
| `skills/discuss/templates/agenda.md` | 议程生成指南模板 |
| `skills/discuss/templates/report.md` | 报告结构模板 |
| `skills/discuss/templates/topic-types.yaml` | 话题类型定义（当前仅 general） |

### 3. 测试覆盖

| 测试文件 | 数量 | 覆盖范围 |
|----------|------|----------|
| `tests/test_discuss_command.py` | 15 | 命令路由、模式切换、空闲超时、生命周期集成 |
| `tests/test_init_discuss.py` | 3 | worktree 创建、状态文件、清理 |
| `tests/e2e/test_discuss_e2e.py` | 13 | 完整生命周期 e2e（WebSocket 模拟） |

**全量测试结果:** 32 passed, 4 skipped, 0 failed

### 4. 提交历史

```
f0e71b4 feat(discuss): implement /discuss command for group discussion moderation
e4016b1 docs(discuss): add design spec and implementation plan
e4c5096 test(discuss): add routing, duplicate-start, and idle-reminder tests
```

## 待完成

### 手动测试（飞书真实环境）

**前置条件:**
1. 在飞书开放平台创建应用，配置所需权限（见下方）
2. 创建 `.feishu-credentials.json`：
   ```json
   {
     "app_id": "cli_xxxxxxxxxx",
     "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxx"
   }
   ```
3. 在飞书后台设置事件订阅（WebSocket 模式）

**启动服务:**
```bash
# 终端 1: 启动 channel-server
make run-server

# 终端 2: 启动 channel (MCP client)
make run-channel
```

**测试步骤:**
1. 在管理群发送 `/discuss` — 应返回 usage 帮助
2. 发送 `/discuss "测试话题"` — 应回复"正在启动讨论"并生成议程
3. 确认议程后，多人自由发言，观察 AI 主持行为
4. 发送 `/discuss status` — 应显示当前讨论状态
5. 发送 `/discuss end` — 应生成报告并恢复到之前的模式

### 飞书应用权限配置

**必需权限（API Permissions）:**

| 权限 | 权限标识 | 用途 |
|------|----------|------|
| 获取与发送单聊、群组消息 | `im:message` | 接收群消息 + 发送回复 |
| 读取用户发给机器人的单聊消息 | `im:message.receive_v1` | WebSocket 事件订阅 |
| 以应用的身份发消息 | `im:message:send_as_bot` | 发送消息到群聊 |
| 获取群组信息 | `im:chat:readonly` | 识别管理群 |
| 消息与群组 - 添加消息表情回复 | `im:message.reactions:write` | ACK 表情反应 |
| 获取用户基本信息 | `contact:user.base:readonly` | 解析发言人姓名 |
| 通过手机号或邮箱获取用户 ID | `contact:user.id:readonly` | 用户 ID 查询 |
| 获取通讯录基本信息 | `contact:contact:readonly_as_app` | 启动通知（遍历可见用户） |

**事件订阅:**

| 事件 | 事件标识 | 说明 |
|------|----------|------|
| 接收消息 | `im.message.receive_v1` | 核心事件，接收所有消息 |

**连接方式:** 选择 **WebSocket** 模式（非 HTTP 回调），代码中使用 `lark.ws.Client` 建立长连接。

**应用可用性:** 在「应用发布」中设置可用范围，确保管理群成员在可用范围内。

## 飞书手动测试结果（2026-04-11）

| 测试案例 | 结果 | 说明 |
|----------|------|------|
| `/discuss` 无参数 | ✅ | 返回 Usage 帮助文本 |
| `/discuss "topic"` 启动讨论 | ✅ | 生成 5 个议程，确认后进入自由讨论 |
| 自由发言 + AI 主持 | ✅ | AI 追踪观点、做阶段小结、引导下一议题 |
| `/discuss status` | ✅ | 显示各议题覆盖情况和整体趋势 |
| `/discuss end` | ✅ | 生成结构化报告（共识/待办/未决），保存到 git |
| `/discuss @file` | ✅ | 读取文件内容，生成针对性议程 |
| 模式恢复 | ✅ | end 后回到 production 模式正常回复 |
| 提前结束（议程未确认） | ✅ | 生成最小报告 |

## 运维要点

- **启动需要 `ADMIN_CHAT_ID` 环境变量**，否则 `/discuss` 命令不会被 channel-server 拦截
- **代理配置**写入 `autoservice.local.sh`（已被 gitignore），`autoservice.sh` 会自动 source
- **快速测试脚本** `test-discuss.sh` 无需 tmux，一键启动 channel-server + Claude Code
- 讨论报告自动保存在 `docs/discussions/` 目录，通过 `discuss/{slug}` 临时分支合并到当前分支（v1.0 行为，v1.1 起改为常驻 worktree）

## v1.1 修正方向（2026-04-13 启动）

对比会议原始愿景（`docs/my_task.md`），v1.0 有三处方向偏离需要修正。完整说明见设计 spec 的 Revision History 节。

- **worktree 常驻化**：改为单一 `discuss/dev` 分支 + 常驻 worktree，讨论沉淀其中，不再每次新建临时分支
- **报告不合并 main**：报告留在 worktree 的 `discussions/` 目录，main 保持干净
- **子命令命名对齐**：预留类型从 `bug/feature/deploy` 改为 `explain/feature-request/debug`

### v2 路线
- **v2.0 Meta Command Creator**：命令→skill 映射抽成可热更新的配置文件，Creator 写配置即可注册新命令
- **v2.1 `/explain`**：首个子命令，对接现有 explain skill
- **v2.2 `/debug` + Bug → Issue 自动化**
- **v2.3 跨天异步模式**：晚间汇总报告，次日推送
