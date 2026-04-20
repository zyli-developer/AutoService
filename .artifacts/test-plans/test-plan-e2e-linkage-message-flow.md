---
type: test-plan
id: test-plan-e2e-linkage-message-flow
status: draft
producer: skill-2 (e2e)
runner: agent-browser + ffmpeg (双 Chrome profile 双开)
created_at: "2026-04-18"
apps: [customer-chat, operator-console]
ports: [5173, 5174]
focus: "customer ↔ operator 双端消息穿透 + 实时性 + squad/subscription 路由"
preconditions:
  - "make start 已启动全套"
  - "config.local.yaml: takeover: { idle_timeout_ms: 30000 }（默认）"
  - "两个独立 Chrome profile（或 Edge + Chrome）代表客户与坐席"
evidence:
  video: "e2e-evidence/2026-04-18-full-coverage/videos/linkage-message-flow.webm"
  screenshots_dir: "e2e-evidence/2026-04-18-full-coverage/screenshots/linkage-message-flow/"
related:
  - "test-plan-T6A.2-squad-filtered-broadcast.md"
  - "test-plan-T6A.1-subscription-registry.md"
  - "docs/contracts/frontend-ws-schema.md"
---

# E2E Test Plan: 客户 ↔ 坐席消息联动

## 目标

验证真实场景下客户与坐席两端**同时打开**时的消息联动：
- 客户发消息 → 坐席立即在工作台看到
- 坐席回复 → 客户立即收到
- 多对话并发 + squad 订阅过滤正确

## 环境布置

- **左屏/Profile A**: 客户 `http://localhost:5173/` — 清 sessionStorage，新客户
- **右屏/Profile B**: 坐席 `http://localhost:5174/` — 登录 `op-alice`，订阅 squad `default`

（ffmpeg 录整屏或分两段窗口录屏）

## 用例列表

### TC-L01: 两端建连 + 坐席订阅 squad (P0)
- **步骤**
  1. 客户端: 打开 5173 + 点聊天 FAB（建 WS）
  2. 坐席端: 5174 登录 `op-alice` → 添加 squad `default`
- **预期**
  - 客户端握手成功，ChatModal 打开，ConnectionBanner 不显示
  - 坐席端订阅确认（看到 `subscription_added` 帧）
- **截图**: `01-both-connected.png`

### TC-L02: 客户首条消息 → 坐席 feed 出现新对话 (P0)
- **步骤**
  1. 客户端: 输入并发送 `你好，我需要帮助订单 #12345`
- **预期**
  - 客户端: 乐观气泡 → sent → TypingIndicator → agent 回复
  - 坐席端: ConversationFeed 在 **3s 内** 出现新对话卡片
    - 卡片含 customerId 前 8 位
    - 显示最新消息预览 `你好，我需要帮助...`
    - 未读 badge `1` 或 `2`（含 agent 回复）
- **截图**: `02-customer-send.png`（左）, `03-operator-feed.png`（右）

### TC-L03: 坐席点击对话 → 消息历史同步 (P0)
- **步骤**: 坐席端点对话卡片
- **预期**
  - IM 视图加载该对话所有消息（客户 + agent）
  - 顺序正确，时间戳递增
  - 未读 badge 清零
- **截图**: `04-operator-opened.png`

### TC-L04: 坐席不 hijack 直接回复 (COPILOT 模式) (P1)
- **步骤**: 坐席在 IMInput 输入 `我是坐席 Alice，正在为您核实订单` → 发送
- **预期**
  - 坐席端: 消息出现
  - 客户端: **3s 内** 收到新气泡，source 显示为 agent/operator 名称
- **截图**: `05-operator-reply.png`（右）, `06-customer-sees.png`（左）

### TC-L05: 客户继续发消息 → 坐席实时看到 (P0)
- **步骤**: 客户端发 `订单号是 12345，谢谢`
- **预期**: 坐席端 IM 视图 **2s 内** 追加新消息；列表自动滚底（若启用）
- **截图**: `07-customer-msg2.png`, `08-operator-sees.png`

### TC-L06: Squad 过滤 —— 错误 squad 的对话不推给坐席 (P0)
- **步骤**
  1. 打开 3 个客户标签页（Profile A1/A2/A3）
  2. A1 发消息指向 squad `vip`（若 backend 支持，或通过 gateway 配置）
  3. A2/A3 发消息默认 squad `default`
- **预期**
  - 坐席 `op-alice` 只订阅 `default`，feed 只看到 A2/A3，不看到 A1
  - 如 backend 没提供 squad 路由 → 此用例降级：至少验证订阅帧被发出
- **说明**: 如未实现 squad 路由，记 `skipped`
- **截图**: `09-squad-filter.png`

### TC-L07: 坐席端关闭页面 + 再打开 → 对话状态恢复 (P1)
- **步骤**
  1. 关闭坐席标签页
  2. 30s 内重新打开 + 登录
- **预期**
  - ConversationFeed 重新加载，历史对话仍在
  - 最新消息仍显示
- **截图**: `10-operator-reopen.png`

### TC-L08: 客户端断线重连期间坐席发送 → 客户重连后收到 (P1)
- **步骤**
  1. 客户 devtools Network Offline
  2. 坐席发消息 "连接恢复后请查看"
  3. 5s 后客户端 Online
- **预期**
  - 客户端 ConnectionBanner 断开 → 重连消失
  - replay 机制上送离线期间消息，客户端看到坐席消息
- **截图**: `11-offline-msg.png`, `12-replay-seen.png`

### TC-L09: 并发多客户 —— 坐席端 feed 保持最新 (P1)
- **步骤**
  1. 3 个客户（A1/A2/A3）依次发消息
  2. 坐席端观察 feed
- **预期**
  - 3 张对话卡片出现
  - 按最新消息时间排序（或按 backend 实现）
  - 各自 unread badge 正确
- **截图**: `13-multi-conv-feed.png`

## 统计

| 指标 | 值 |
|---|---|
| 总用例 | 9 |
| P0 | 5 |
| P1 | 4 |
| 预计时长 | ~15 分钟 |
| 截图数 | ~13 张 |

## 录屏策略

整屏录（两个窗口并排），ffmpeg 录桌面分辨率（如 2560×1440）。标题栏注明"左=客户 / 右=坐席"便于回放。

## 退出准则

- TC-L01/L02/L03/L04/L05 全过：双端核心联动无问题
- TC-L06 若 backend 未实现 squad 路由，降级通过
- 任一 P0 的"消息延迟 > 3s"视作 partial

## 已知风险

- Windows 上两个独立 Chrome profile 要指定 `--user-data-dir=<path>` 启动
- 如 customer 和 operator 共用同一 Chrome 窗口会因 cookie/storage 冲突
- 多客户 A1/A2/A3 可用无痕窗口隔离 sessionStorage
