---
type: test-plan
id: test-plan-e2e-customer-chat
status: draft
producer: skill-2 (e2e)
runner: agent-browser + ffmpeg
created_at: "2026-04-18"
app: customer-chat
port: 5173
focus: "customer 端完整 E2E：FAB → ChatModal → 消息收发 → 断线重连 → CSAT"
preconditions:
  - "make start 已启动 gateway:8000 + customer-chat:5173"
  - "config.local.yaml 至少配置 anthropic api key（以便 agent 回复）"
  - "浏览器 sessionStorage 清空（新 customer_id）"
evidence:
  video: "e2e-evidence/2026-04-18-full-coverage/videos/customer-chat.webm"
  screenshots_dir: "e2e-evidence/2026-04-18-full-coverage/screenshots/customer-chat/"
related:
  - "test-plan-T1B.1-customer-chat-spa.md (unit)"
  - "test-plan-T1B.2-message-flow-ui.md (unit)"
  - "test-plan-T1B.3-placeholder-streaming.md (unit)"
  - "test-plan-T1B.4-reconnect-replay.md (unit)"
  - "test-plan-T1B.5-floating-button-sdk.md (unit)"
---

# E2E Test Plan: customer-chat 全功能

## 目标

以真实浏览器 + 真实 gateway 验证客户端所有用户可见行为。覆盖：
商户落地页渲染、悬浮按钮唤起、连接握手、消息发送、AI 占位/流式回复、
断线重连、CSAT 评分、主题样式。**不重复验证单测已覆盖的逻辑细节**
（如 store action 命名、FakeWSClient），只验证用户肉眼可见的结果。

## 基础环境检查（执行前）

1. `curl -sf http://localhost:8000/health` → 200（或 WS 能建连即可）
2. `curl -sf http://localhost:5173/` → 返回 HTML
3. 打开 devtools → Network 清空 → 录屏开始

## 用例列表

### TC-C01: 商户落地页与悬浮按钮初始渲染 (P0)
- **步骤**
  1. navigate `http://localhost:5173/`
- **预期**
  - 页面渲染商户站 (MerchantSite)，顶部有品牌名
  - 右下角两个悬浮按钮：电话 📞 + 聊天 💬（`aria-label="Open chat"`）
  - 聊天按钮带 `highlight` class（动画）
- **截图**: `01-landing.png`（整页）

### TC-C02: 点击悬浮按钮打开 ChatModal + 握手 (P0)
- **步骤**
  1. 点击 💬 悬浮按钮
- **预期**
  - ChatModal 弹出
  - ConnectionBanner **不**显示（握手成功后即消失，可能闪现一下）
  - Header 显示 agent 名称或品牌名
  - 输入框可编辑，发送按钮可见
- **检查**: devtools Network 有 `101 Switching Protocols` to `/ws/customer`
- **截图**: `02-modal-open.png`

### TC-C03: 发送首条消息 → 乐观渲染 → agent 回复 (P0)
- **步骤**
  1. 在输入框输入 "你好，我想咨询产品价格"
  2. 点击发送 或 按 Enter
- **预期**
  - **立即** 右侧出现用户气泡（乐观渲染，status=sending，可能带半透明）
  - 0.1–0.5s 内 status 变 sent（无半透明）
  - 出现左侧 TypingIndicator（"…" 动画）
  - 数秒内（取决于 model latency）左侧出现 agent 气泡，包含价格相关回答
- **截图**: `03-user-bubble.png`, `04-typing.png`, `05-agent-reply.png`

### TC-C04: 流式占位回复 (P1)
- **步骤**
  1. 发送一条长问题 "详细介绍一下你们的核心功能"
- **预期**
  - agent 气泡出现后，文本逐块追加（流式 placeholder → message_edited 帧）
  - 最终气泡内容完整，无重复段落
- **截图**: `06-streaming-midway.png`（录屏能完整捕获）

### TC-C05: 多轮对话（上下文保持）(P1)
- **步骤**
  1. 再发一条 "那你们支持哪些付款方式？"
- **预期**
  - agent 回复理解上下文（延续"产品价格"话题）
  - 消息列表顺序正确，时间戳递增
- **截图**: `07-multiturn.png`

### TC-C06: 断线重连 + replay (P0)
- **步骤**
  1. devtools → Network → 选 Offline
  2. 等待 2s（ConnectionBanner 应出现"连接中断/重连"）
  3. devtools → Online
  4. 在重连期间发送一条消息 "这条消息在离线时发出"
- **预期**
  - Offline 时：ConnectionBanner 可见
  - Online 后 2s 内：Banner 消失
  - 离线发出的消息被 replay 上送（`isReplaying` 标志），最终 agent 回复
- **截图**: `08-disconnected-banner.png`, `09-reconnected.png`

### TC-C07: 自动滚底 vs 新消息按钮 (P1)
- **步骤**
  1. 发送多条消息直到内容超过 viewport
  2. 手动滚到顶部（距底 >50px）
  3. 再发一条消息
- **预期**
  - 处于顶部时收到新消息 → 显示 "新消息" 按钮（不自动滚）
  - 点击"新消息"按钮 → 滚到底
- **截图**: `10-new-msg-btn.png`

### TC-C08: CSAT 评分流（如 backend 触发）(P2)
- **步骤**
  1. 若 backend 在对话结束发送 `csat_request` 帧，UI 显示 CSATRating 组件
  2. 点击某个分数（1–5）
- **预期**
  - UI 切换为 "感谢反馈"
  - `csat_response` 帧已发送（devtools Network → ws frames）
- **说明**: 若 backend 未自动触发，本用例跳过，记为 `skipped`
- **截图**: `11-csat.png`（若触发）

### TC-C09: 关闭再打开 Modal 状态保留 (P2)
- **步骤**
  1. 关闭 ChatModal（X 按钮或 overlay click）
  2. 再次点击悬浮按钮
- **预期**
  - 历史消息完整保留（不重新握手丢消息）
  - WS 连接保持（devtools Network 无新握手）
- **截图**: `12-reopen.png`

## 统计

| 指标 | 值 |
|---|---|
| 总用例 | 9 |
| P0 | 4 (C01, C02, C03, C06) |
| P1 | 3 |
| P2 | 2 |
| 预计时长 | ~10 分钟 |
| 截图数 | ~12 张 |

## 录屏策略

单次录屏覆盖 TC-C01 → TC-C09 连续流程。估计 8–10 分钟。ffmpeg 录 Chrome 窗口区域（1280×800）或整屏。

## 退出准则

- P0 全部通过 → 总体通过
- 任一 P0 失败 → 进 Skill 5 verify 记录 eval-doc + 建 issue
- P1/P2 失败 → 记录但不阻塞

## Skill 4 执行约束

1. 录屏名称与 evidence.video 一致
2. 截图按 TC 顺序编号，文件名包含 TC-ID
3. 每个 TC 的"预期"全部达成才标 passed，部分达成标 partial
4. 若 agent 回复质量差（答非所问）不算 fail（prompt/模型问题），但记录在报告 notes
