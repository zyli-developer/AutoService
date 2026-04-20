---
type: test-plan
id: test-plan-e2e-operator-console
status: draft
producer: skill-2 (e2e)
runner: agent-browser + ffmpeg
created_at: "2026-04-18"
app: operator-console
port: 5174
focus: "坐席端完整 E2E：登录 → 订阅 → IM 显示 → hijack/release → TAKEOVER 倒计时 → 预警"
preconditions:
  - "make start 已启动"
  - "customer-chat 已有至少一个活跃对话（联动场景会补齐；单独跑需先在 5173 发一条消息）"
  - "config.local.yaml 的 takeover: { idle_timeout_ms: 30000, warning_ms: 5000, offline_grace_ms: 30000 }"
evidence:
  video: "e2e-evidence/2026-04-18-full-coverage/videos/operator-console.webm"
  screenshots_dir: "e2e-evidence/2026-04-18-full-coverage/screenshots/operator-console/"
related:
  - "test-plan-T2B.1-operator-console-spa.md (unit)"
  - "test-plan-T2B.2-squad-card-list.md (unit)"
  - "docs/superpowers/specs/2026-04-17-takeover-release-design.md"
---

# E2E Test Plan: operator-console 全功能

## 目标

验证坐席工作台全部用户可见行为。**核心是 takeover/release 双向切换 + 自动释放倒计时 +
预警横幅**——这是最近迭代的新功能，单测不能覆盖"倒计时 UI 和 WS 事件时序"。

## 用例列表

### 分组 A · 登录与工作台壳 (TC-O01 ~ O04)

#### TC-O01: 登录页渲染 (P0)
- **步骤**: navigate `http://localhost:5174/`
- **预期**: `[data-testid=input-operator-id]`, `[data-testid=input-token]`, `[data-testid=btn-login]` 可见；登录按钮 disabled（operatorId 为空）
- **截图**: `01-login.png`

#### TC-O02: 输入 operator-id 启用按钮 + 登录进入 Workspace (P0)
- **步骤**
  1. 输入 operator id `op-alice`（token 留空）
  2. 点击登录
- **预期**: 登录表单消失；`[data-testid=workspace-page]` 或侧边栏可见；WS 状态为 open
- **截图**: `02-workspace.png`

#### TC-O03: 侧边栏 / Squad 列表初始化 (P0)
- **预期**
  - IMSidebar 可见
  - 若无订阅 squad，列表为空或显示占位
  - WS 连接指示（可能在 header 或 banner）为 open/online
- **截图**: `03-sidebar-empty.png`

#### TC-O04: 添加 Squad 订阅 (P0)
- **步骤**: 输入 squad id `default` 并添加（按钮或 Enter）
- **预期**
  - 侧边栏出现 squad 标签/tab
  - devtools Network ws frames 可见 `subscribe` → `subscription_added`
- **截图**: `04-squad-added.png`

### 分组 B · 对话列表 + 消息流 (TC-O05 ~ O07)
**前置**: customer-chat 端有至少 1 条消息的对话（或联动 plan 先跑）

#### TC-O05: 对话卡片在 ConversationFeed 列表中出现 (P0)
- **预期**: ConversationCard 显示 customerId + 最新消息预览 + 未读 badge（UnreadBadge）
- **截图**: `05-conv-feed.png`

#### TC-O06: 点击对话 → IM 视图载入 (P0)
- **预期**
  - IMTitlebar 显示对话信息 + HijackButton
  - 消息历史加载显示
  - HijackButton 文字为 "抢单"（mode != takeover）
- **截图**: `06-im-view.png`

#### TC-O07: Operator 发消息 (P0)
- **步骤**: 在 IMInput 中输入 `你好，我是坐席 Alice` → Enter
- **预期**: 消息在 IM 视图出现（右对齐，operator 样式）
- **截图**: `07-operator-message.png`

### 分组 C · Hijack / Release 双态按钮 (TC-O08 ~ O10)

#### TC-O08: 点击"抢单"→ 进入 TAKEOVER (P0)
- **步骤**: 点击 HijackButton (`btn-hijack-<convId>`)
- **预期**
  - 按钮文字 → "释放回 AI"（`btn-release-<convId>`）
  - TakeoverIndicator 显示 `⚡ TAKEOVER` + 倒计时 `Ns`（初始接近 30s）
  - `mode.changed` 事件 → mode=takeover, `takeover_operator_id=op-alice`
- **截图**: `08-hijack.png`

#### TC-O09: TAKEOVER 倒计时可见且递减 (P0)
- **步骤**: 静止观察 ~3s
- **预期**: `takeover-countdown` 数字递减（30s → 27s → ...）
- **截图**: `09-countdown-running.png`（录屏可见动态递减）

#### TC-O10: 点击"释放回 AI" → 回到 AUTO (P0)
- **步骤**: 点击 `btn-release-<convId>`
- **预期**
  - 按钮文字 → "抢单"
  - TakeoverIndicator 消失
  - `mode.changed` → mode=auto, `takeover_operator_id=null`
- **截图**: `10-release.png`

### 分组 D · 静默超时预警 (TC-O11 ~ O13)
**前置**: 为加速测试，临时把 config 改为 `idle_timeout_ms: 8000, warning_ms: 3000`，重启 gateway。

#### TC-O11: Hijack 后静止 5s → 倒计时进入 warning 色 (P0)
- **步骤**
  1. /hijack 某对话
  2. 5s 不发消息
- **预期**: `takeover-countdown` 切换为 warning 样式（如橙色）；倒计时显示 `~3s`
- **截图**: `11-warning-phase.png`

#### TC-O12: 3s 内收到 `takeover_warning` 帧 → TakeoverWarning 横幅出现 (P0)
- **预期**
  - `takeover-warning-<convId>` 横幅可见
  - 文案 `再 Xs 无响应将自动回到 AI`
  - 两个按钮：`takeover-warning-continue` "继续接管"、`takeover-warning-release` "释放"
- **截图**: `12-warning-banner.png`

#### TC-O13: 点击"继续接管" → 横幅消失 + 计时器重置 (P0)
- **步骤**: 在 3s 倒计时内点击 "继续接管"
- **预期**
  - 横幅消失（收到 `takeover_warning_cancelled` 帧）
  - 倒计时重新回到 idle_timeout_ms 起点（`8s`）
- **截图**: `13-warning-cancelled.png`

### 分组 E · 自动释放（不干预）(TC-O14 ~ O15)

#### TC-O14: Hijack 后放任超时 → 自动回到 COPILOT (P0)
- **步骤**
  1. /hijack
  2. 完全不操作 8s+
- **预期**
  - 横幅出现 → 3s 后消失
  - TakeoverIndicator 消失
  - 按钮文字回 "抢单"
  - mode.changed → COPILOT, trigger=`auto:idle_timeout`
- **截图**: `14-auto-release.png`

#### TC-O15: 再次 /hijack 可逆 (P1)
- **步骤**: 自动释放后再次点 "抢单"
- **预期**: 回到 TAKEOVER 状态，倒计时从 idle_timeout_ms 开始
- **截图**: `15-re-hijack.png`

### 分组 F · 离线自动释放 (TC-O16)
**前置**: config 改 `offline_grace_ms: 5000` 便于测试。

#### TC-O16: Hijack 后关闭坐席标签页 → 5s 后 AUTO (P0)
- **步骤**
  1. operator-console /hijack 对话
  2. 关闭 operator-console 标签页（WS 断开）
  3. 5s+ 后，在另一窗口用另一 operator 登录并查看该对话 mode
- **预期**: 对话 mode=AUTO, trigger=`auto:operator_offline`, `takeover_operator_id=null`
- **说明**: 或通过 `curl` 查 engine state / gateway log 验证
- **截图**: `16-offline-release.png`（日志截图或重新登录后的状态）

### 分组 G · 并发/异常防御 (TC-O17)

#### TC-O17: 多对话并发 takeover (P1)
- **步骤**: 同一 operator 同时 /hijack 两个不同对话
- **预期**: 两个对话各有独立 TakeoverIndicator 倒计时，互不影响
- **截图**: `17-multi-takeover.png`

## 统计

| 指标 | 值 |
|---|---|
| 总用例 | 17 |
| P0 | 13 |
| P1 | 3 |
| P2 | 1 |
| 预计时长 | ~20 分钟（含 config 重启 2 次） |
| 截图数 | ~17 张 |

## 录屏策略

建议分两段录屏：
1. `operator-console-part1.webm` — TC-O01 ~ O10（常规 config）
2. `operator-console-part2.webm` — TC-O11 ~ O17（短 timeout config）

## 退出准则

- 分组 C/D/E（takeover 核心）P0 必须全过
- TC-O16 离线自动释放必过（这是 bug 高发区域）

## 已知风险

- **gateway 重启丢内存 timer**: 切换 config 后要重启 gateway，原 TAKEOVER 对话 timer 丢失。测试前先确保没有"悬空"TAKEOVER。
- **takeover_operator_id 路由**: 最近 commit (940bc10) 修复了 client_hello 带 operator_id 的路由 bug。TC-O11 预警必须送到正确 operator（不能发到同 squad 其他 operator）。
