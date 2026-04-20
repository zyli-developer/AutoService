---
type: test-plan
id: test-plan-e2e-admin-portal
status: draft
producer: skill-2 (e2e)
runner: agent-browser + ffmpeg
created_at: "2026-04-18"
app: admin-portal
port: 5175
focus: "管理端完整 E2E：租户登录 → Wizard 5 步 → Dashboard → ManagementChat → Proposals → Billing"
preconditions:
  - "make start 已启动"
  - "新租户 id（未 onboard 过）或清空 .autoservice/data/tenants/<tid>"
  - "后端 /api/onboard/upload 可用（必要的 LLM key 已配置）"
evidence:
  video: "e2e-evidence/2026-04-18-full-coverage/videos/admin-portal.webm"
  screenshots_dir: "e2e-evidence/2026-04-18-full-coverage/screenshots/admin-portal/"
related:
  - "plan-T3B.2-wizard-step1-upload.md"
  - "plan-T3B.4-wizard-step3-rehearsal.md"
  - "plan-T4A.10-tiered-billing.md"
  - "plan-T6A.1-subscription-registry.md"
---

# E2E Test Plan: admin-portal 全功能

## 目标

验证管理后台全部用户可见行为：登录、Wizard 5 步 onboarding、Dashboard 数据展示、
管理群聊、提案列表、账单页。**5 步 Wizard 是主戏**。

## 分组 A · 登录 + 工作台壳 (TC-A01 ~ A04)

### TC-A01: LoginPage 渲染 (P0)
- **步骤**: navigate `http://localhost:5175/`
- **预期**: `[data-testid=login-card]`、`input-tenant-id`、`btn-login` 可见
- **截图**: `01-login.png`

### TC-A02: 输入 tenant_id 登录进入 Workspace (P0)
- **步骤**: 输入 `demo-tenant-e2e-2026-04-18` → 点登录
- **预期**: `[data-testid=admin-workspace]` 可见；tab 栏含 5 个 tab（向导/仪表盘/管理群/提案/账单）
- **截图**: `02-workspace.png`

### TC-A03: Tab 切换 (P1)
- **步骤**: 依次点 `tab-dashboard` → `tab-notifications` → `tab-proposals` → `tab-billing` → `tab-wizard`
- **预期**: 每次切换内容区域更新，URL/store 中 activeTab 同步
- **截图**: `03-tabs-switched.png`

### TC-A04: 退出登录 (P2)
- **步骤**: 点 `btn-logout`
- **预期**: 回到登录页
- **截图**: `04-logout.png`

## 分组 B · Wizard 5 步 (TC-A05 ~ A20)

重新登录 + 确保停留在 "向导" tab。

### TC-A05: WizardStepper 初始状态 (P0)
- **预期**: 5 个步骤 `1.上传 › 2.权限 › 3.预演 › 4.合规 › 5.可用`；step 0 为 current
- **截图**: `05-stepper.png`

### Step 1 · 上传 (MaterialUploadStep)

#### TC-A06: Step1 表单可见 (P0)
- **预期**: `[data-testid=material-upload-step]`；品牌名输入 `input-brand`；行业 Select；文件上传区；生成按钮
- **截图**: `06-step1.png`

#### TC-A07: 品牌名必填 (P1)
- **步骤**: 不填品牌名，点"生成 Agent"
- **预期**: 表单不提交或按钮 disabled；如有错误文案，截图记录
- **截图**: `07-brand-required.png`

#### TC-A08: 填写基础信息并生成 → 4 张角色卡片 (P0)
- **步骤**
  1. 品牌名 `MyDemoStore`
  2. 行业 `电商`
  3. 网址 `https://example.com`
  4. 不上传文件（或上传一个小 txt）
  5. 点"生成 Agent"
- **预期**
  - 按钮进入 loading
  - 10–60s 内返回 4 个角色卡片：customer / translate / lead / triage
  - 每卡显示 kb_hit_count 和 mode
- **截图**: `08-step1-generating.png`, `09-step1-4-roles.png`
- **说明**: 慢调用，录屏要捕获完整等待过程

### Step 2 · 权限 (ChannelConfigStep)

#### TC-A09: Step 2 渲染 (P0)
- **步骤**: 点"下一步"进入 Step 2
- **预期**: 渠道配置界面可见（Feishu / Web 渠道选项、API key 输入等）
- **截图**: `10-step2.png`

#### TC-A10: 配置渠道并保存 (P1)
- **步骤**: 勾选 Web 渠道（最简单），其他默认，点"下一步"
- **预期**: 进入 Step 3
- **截图**: `11-step2-saved.png`

### Step 3 · 预演 (VirtualRehearsalStep)

#### TC-A11: Step 3 初始状态 (P0)
- **预期**: 虚拟客户/候选问题列表；"开始预演"按钮
- **截图**: `12-step3-init.png`

#### TC-A12: 开始预演 → 虚拟 QA 流水线运行 (P0)
- **步骤**: 点"开始预演"
- **预期**
  - 列表逐项进入 running → 显示虚拟客户提问 + agent 回复
  - 每项可批准/拒绝（approve/reject）
- **截图**: `13-step3-running.png`, `14-step3-midway.png`

#### TC-A13: 批准所有 → 可进入 Step 4 (P0)
- **步骤**: 所有项 approve
- **预期**: "下一步"按钮变 enabled
- **截图**: `15-step3-all-approved.png`

### Step 4 · 合规 (ComplianceCheckStep)

#### TC-A14: 合规检查列表渲染 + 全部通过 (P0)
- **预期**: PII 检测、品牌词检查、回答长度等合规项；全部 pass 后"下一步"启用
- **截图**: `16-step4-compliance.png`

### Step 5 · 可用

#### TC-A15: Step 5 展示上线信息 (P0)
- **预期**: 显示 tenant_id、channel 配置、JS snippet 或 webhook url；完成 / 返回 dashboard 按钮
- **截图**: `17-step5-ready.png`

## 分组 C · Dashboard (TC-A16 ~ A19)

#### TC-A16: 切到仪表盘 (P0)
- **步骤**: `tab-dashboard`
- **预期**: DashboardTab 加载；接管趋势图 TakeoverTrendChart；Leaderboard；AlertCard；CanaryProgress
- **截图**: `18-dashboard.png`

#### TC-A17: 时间范围切换器 (P1)
- **步骤**: 切换时间片（如 1d / 7d / 30d）
- **预期**: 图表数据刷新（loading → 新数据）
- **截图**: `19-dashboard-period.png`

#### TC-A18: Leaderboard 内容 (P1)
- **预期**: 表格展示 operator / conversation / score 等列；至少 1 行或空态提示
- **截图**: `20-leaderboard.png`

#### TC-A19: AlertCard 与 Canary 进度可见 (P1)
- **预期**: 卡片渲染正常；进度条百分比与文字一致
- **截图**: `21-alerts-canary.png`

## 分组 D · 管理群聊 / 提案 / 账单 (TC-A20 ~ A23)

#### TC-A20: 管理群 (ManagementChat) (P1)
- **步骤**: `tab-notifications`
- **预期**: ManagementChat 组件渲染；输入框 + 消息列表
- **交互**: 发送一条 `/help` → backend 回复
- **截图**: `22-management-chat.png`

#### TC-A21: 提案 (ProposalsTab) (P1)
- **步骤**: `tab-proposals`
- **预期**: 提案列表渲染；至少显示空态或样例卡片；approve/reject 按钮可见
- **截图**: `23-proposals.png`

#### TC-A22: 账单 (BillingTab) (P1)
- **步骤**: `tab-billing`
- **预期**: 当前周期用量、分层计费表、历史账单列表
- **截图**: `24-billing.png`

#### TC-A23: 跨 tab 状态保持 (P2)
- **步骤**: wizard 进行到 step 2 → 切 dashboard → 再切回 wizard
- **预期**: wizard 仍停在 step 2（不被重置）
- **截图**: `25-wizard-persistent.png`

## 统计

| 指标 | 值 |
|---|---|
| 总用例 | 23 |
| P0 | 11 |
| P1 | 10 |
| P2 | 2 |
| 预计时长 | ~25 分钟（含 wizard generate 慢调用） |
| 截图数 | ~25 张 |

## 录屏策略

建议分 2 段：
1. `admin-portal-part1.webm` — login + wizard 5 步（最慢、最核心）
2. `admin-portal-part2.webm` — dashboard + tabs

## 退出准则

- 分组 B（Wizard 5 步）P0 全过为通过标准
- Step 1 生成调用失败（LLM/backend）→ 记录为 blocker，跳过后续 wizard 步骤
- Dashboard 若后端无 metrics 数据，空态渲染即可算 pass

## 已知风险

- Step 1 依赖后端 `/api/onboard/upload` + LLM 调用；若 key 失效会卡住
- Step 3 预演是 LLM 慢调用，录屏会很长；接受 per-item 5-20s 延迟
- Dashboard 的图表在空数据时是否崩溃（容错）—— TC-A16 要检查
