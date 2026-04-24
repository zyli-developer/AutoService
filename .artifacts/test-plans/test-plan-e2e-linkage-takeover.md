---
type: test-plan
id: test-plan-e2e-linkage-takeover
status: draft
producer: skill-2 (e2e)
runner: agent-browser + ffmpeg (双 profile)
created_at: "2026-04-18"
apps: [customer-chat, operator-console, gateway]
focus: "TAKEOVER 完整生命周期：客户对话 → /hijack → 坐席回复 → 预警 → 手动或自动 release"
preconditions:
  - "make start + config: takeover.idle_timeout_ms: 8000, warning_ms: 3000, offline_grace_ms: 5000（测试用短值）"
  - "修改 .autoservice/config.local.yaml 后重启 gateway（Ctrl+C 再 make start 或 make stop + make start）"
evidence:
  video: "e2e-evidence/2026-04-18-full-coverage/videos/linkage-takeover.webm"
  screenshots_dir: "e2e-evidence/2026-04-18-full-coverage/screenshots/linkage-takeover/"
related:
  - "docs/superpowers/specs/2026-04-17-takeover-release-design.md"
  - "test-plan-e2e-operator-console.md"
  - "最近 commit: f9d916a, 7015140, 882ee4c, 940bc10"
---

# E2E Test Plan: TAKEOVER 端到端生命周期

## 目标

用真实客户 + 真实坐席 + 真实 gateway 跑完 takeover 从 /hijack 到各种 release
路径的端到端场景。**最重要的用例是 TC-T04 和 TC-T07（bug 高发区）**。

## 用例列表

### TC-T01: 基础 /hijack → AUTO→TAKEOVER 状态切换 (P0)
- **步骤**
  1. 客户发消息建立对话
  2. 坐席登录 + 订阅 + 进入该对话
  3. 坐席点"抢单"
- **预期**
  - 坐席端: HijackButton → "释放回 AI"；TakeoverIndicator 出现 + 倒计时 `8s`
  - 客户端: （可选）如 UI 显示对话模式，应体现 takeover；如无 UI 则验证 WS 帧 `mode.changed` 到达
  - gateway log: `mode.changed trigger=/hijack takeover_operator_id=op-alice`
- **截图**: `01-hijack.png`（坐席）, `02-customer-during-takeover.png`

### TC-T02: TAKEOVER 期间客户发消息 → 坐席看到但 AI 不自动回复 (P0)
- **步骤**
  1. /hijack 后
  2. 客户发 "请帮我查一下订单"
- **预期**
  - 坐席端: 消息 3s 内出现在 IM 视图
  - 客户端: **无** agent typing 指示，**无** AI 自动回复（TAKEOVER 下 AI 静默）
  - gateway log: 无 soul.respond 调用
- **截图**: `03-takeover-customer-msg.png`, `04-operator-sees.png`

### TC-T03: 坐席发消息 → 客户看到 + timer 重置 (P0)
- **步骤**
  1. TC-T02 紧接着，坐席回复 "已为您查询，订单状态是已发货"
- **预期**
  - 客户端: 3s 内收到坐席回复
  - 坐席端: TakeoverIndicator 倒计时 **重置** 回 `8s`（而非继续递减）
- **截图**: `05-operator-reply.png`, `06-countdown-reset.png`

### TC-T04: 预警 → 客户视角无感知 (P0)
- **步骤**
  1. 坐席 /hijack 后静止 5s
  2. 观察两端
- **预期**
  - 坐席端: TakeoverWarning 横幅 3s 倒计时出现
  - 客户端: **无任何异常提示**（预警只给坐席看，客户无需感知）
- **截图**: `07-operator-warning.png`, `08-customer-normal.png`

### TC-T05: 坐席点"继续接管" → 横幅消失 + 客户继续看到坐席消息 (P0)
- **步骤**
  1. TC-T04 期间点 "继续接管"
  2. 坐席发 "别担心我还在"
- **预期**
  - 坐席端: 横幅消失，倒计时重置
  - 客户端: 收到消息
- **截图**: `09-continue-ack.png`, `10-customer-reassured.png`

### TC-T06: 自动释放到 COPILOT → 客户收到 AI 回复 (P0)
- **步骤**
  1. 坐席 /hijack 后完全不理会 8s+
  2. 自动释放触发后，客户发 "还在吗？"
- **预期**
  - 坐席端: TakeoverIndicator 消失；按钮回 "抢单"；gateway log 显示 `trigger=auto:idle_timeout` mode=COPILOT
  - 客户端: 发消息后收到 AI 回复（mode=COPILOT，AI 继续但可能附带人工审核流程）
- **截图**: `11-auto-released.png`, `12-ai-replies.png`

### TC-T07: 离线自动释放 → 对话切回 AUTO (P0) ⭐
- **步骤**
  1. 坐席 /hijack 对话
  2. 直接关闭坐席浏览器标签页（不点 release）
  3. 5s 后（offline_grace_ms）客户发 "还在吗？"
- **预期**
  - gateway log: `trigger=auto:operator_offline` mode=AUTO takeover_operator_id=null
  - 客户端: 收到 AI 回复（AUTO 模式）
- **验证**: 第二个坐席登录查看对话 mode，或 curl `/api/conversations/{id}` 查 state
- **截图**: `13-customer-after-offline.png`, `14-gateway-log.png`（log tail 截图）
- **说明**: 这是 7e3dd29 commit "demote debug prints + cancel stale offline-grace task" 修改的路径，易回归

### TC-T08: 关闭标签页 3s 内重新打开 → 保持 TAKEOVER (P1)
- **步骤**
  1. 坐席 /hijack + 关闭标签页
  2. 3s 内（< 5s grace）重新打开 + 登录 + 进对话
- **预期**
  - 对话仍是 TAKEOVER（offline watcher 的 grace task 被 cancel）
  - 倒计时继续（不重置到 8s，除非 idle timer 走完）
- **截图**: `15-reopen-stays-takeover.png`

### TC-T09: 多 operator 竞争 /hijack (P1)
- **步骤**
  1. Operator A /hijack 对话
  2. Operator B（另一 profile）进同对话 + 尝试 /hijack
- **预期**
  - 根据设计（排他锁 out of scope），B 的 /hijack 可成功也可失败
  - 关键: `takeover_operator_id` 记录最新 actor；前一 operator 不应再收到预警
- **说明**: MVP 不做排他锁，此用例记录观察结果（非 pass/fail）
- **截图**: `16-two-operators.png`

### TC-T10: /hijack ↔ /release ↔ 自动释放 所有路径可逆 (P1)
- **步骤**: 串起 T01 → T06 → T01 → T07 的循环
- **预期**: 每次 /hijack 都能从前一状态进入 TAKEOVER，`takeover_operator_id` 每次正确更新
- **截图**: `17-all-reversible.png`

## 统计

| 指标 | 值 |
|---|---|
| 总用例 | 10 |
| P0 | 7 |
| P1 | 3 |
| 预计时长 | ~30 分钟（含 gateway 重启 1–2 次）|
| 截图数 | ~17 张 |

## 录屏策略

- **part1** `linkage-takeover-part1.webm`: TC-T01 ~ T05（手动 /hijack + 预警 + 继续）
- **part2** `linkage-takeover-part2.webm`: TC-T06 ~ T10（自动释放 + 离线 + 多 operator）

整屏录，左侧客户 + 右侧坐席；gateway log 终端建议放可见位置便于捕获时序。

## 退出准则

- TC-T01/T02/T03/T04/T05/T06/T07 全过 → 核心 takeover 可发布
- TC-T07 任何失败 → 高优先 issue（客户在坐席离线后卡死 TAKEOVER 是严重 bug）
- TC-T09（多 operator）仅记录，不阻塞

## 已知风险与观察点

1. **TC-T07 离线释放**: 7e3dd29 刚 fix 了 "stale offline-grace task" 问题，这里最可能回归
2. **TC-T03 timer reset**: timer 的 reset 依赖 `send_message` 里判断 `source == takeover_operator_id`；若 source 字段因 commit 变化格式会失效
3. **TC-T04 预警发送对象**: 940bc10 commit 修 "client_hello carries operator_id"，若未完全生效，预警可能误发到 squad 内其他 operator
4. **TC-T08 grace cancel**: 重新连接时 grace task 必须被 cancel，否则会重复释放一次
