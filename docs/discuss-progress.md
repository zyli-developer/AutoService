# /discuss 命令 — 开发进度与手动测试指南

## 当前状态

**分支:** `feat/evaluate-skill`
**日期:** 2026-04-10
**状态:** 代码实现完成，单元测试 + e2e 测试全部通过，待飞书真实环境验证

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

### 未来迭代
- 子命令扩展（explain, feature-request, debug）
- 讨论结论推进到开发/测试阶段
- 多讨论并行支持
