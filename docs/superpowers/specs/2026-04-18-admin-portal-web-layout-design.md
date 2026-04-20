# Admin Portal — Web Layout Redesign

**Status:** Draft
**Date:** 2026-04-18
**Scope:** `frontend/apps/admin-portal/`
**Non-scope:** 设计系统（`packages/design-system/`）不动；坐席台、客户端不改；后端 API 不改。

## 1. 动机

当前 admin-portal 基于 `skills/frontend-design` skill 设计，视觉语言（Aurora light + violet accent + DM Sans + glass 卡片）良好，但**布局偏移动端**：

- `.cs-main { max-width: 1100px; margin: 0 auto }` 压缩 wizard 到窄列，宽屏两侧大量浪费
- 顶部水平 `.cs-tabs` 5 项 tab 像移动底栏抬到顶部
- 顶部 title bar 带"交通灯 dots + 单一 URL"——像嵌在浏览器里的小应用 mockup
- 各视图内部一律纵向堆叠 `cs-card`，没有使用桌面端的水平空间

桌面版 admin 应当是**指挥中心 / god view**，以 AI agent 对话式管理为核心操作面。参考另外两端：客户端是商户站点 + chat widget，坐席台是 IM workspace——admin 都不应照抄。

## 2. 目标与非目标

**目标：**
- 视觉语言 100% 保留（颜色、字体、圆角、阴影、组件类不变）
- 布局骨架改成桌面端应用（app-like，非传统管理工具 chrome）
- 把**管理群 AI 对话**定位为 admin 的默认入口和主要交互面
- 埋下 D-path 种子：Dream Engine 能在 chat 里返回结构化 block，前端渲染为 inline widget（metric / proposal-card / action-launch / alert）

**非目标：**
- 不做设计系统级别的改动（tokens.css / components.css 不动）
- 不做专门的移动端体验（只保证小屏不崩）
- 不实现 `⌘K` 命令搜索（只占位）
- 不改后端 `/api/management/chat` 返回格式；widget 渲染管道对新老回复向下兼容
- 不引入新依赖（不换图标库，不加 icon 包；emoji 作图标先用）

## 3. 架构

**方案 C（icon rail + 主画布），留 D（AI-native）路径**

```
┌──────────────────────────────────────────────────────────────────┐
│ ● acme-corp                                  ⌘K      [avatar ▾]  │  cs-topbar · 40px
├────┬─────────────────────────────────────────────────────────────┤
│    │                                                             │
│ 🗨  │                                                             │
│ 📊  │                                                             │
│ ✨  │       cs-canvas                                              │
│ 💡  │       (每个视图自己决定布局，不再受 max-width 限制)            │
│ 💳  │                                                             │
│    │                                                             │
├────┤                                                             │
│ ⋯  │                                                             │
└────┴─────────────────────────────────────────────────────────────┘
  56px                        1fr
```

三个区：

- **`.cs-topbar`** 顶栏 40px：左 violet `--aurora-3` 小圆点 + 租户名；中空（面包屑/时间/告警全部砍掉）；右 `⌘K` 占位按钮 + avatar 菜单（内置 租户 ID / 退出 / 版本号）
- **`.cs-rail`** 左侧图标导航 56px：5 个功能图标 + 底部 `⋯`；active 态左 3px `--aurora-3` 高亮条；hover 出 tooltip
- **`.cs-canvas`** 主画布：padding 随视图定；Aurora violet 氛围光保留；各视图全宽（wizard 除外，见 §4.3）

## 4. 各视图布局

### 4.1 管理群 chat（默认首页）

完整铺满 canvas。结构保留现有三段（header / feed / input），改 `height: calc(100vh - 140px)` 为 `height: 100%`。feed 与输入框**居中 max-width 860px**（对话不宜过宽）。

**D 种子：inline widget 机制**

消息类型扩展为结构化 block。`ChatMsg.content` 支持两种形态：

```ts
// 旧（继续支持）
content: string

// 新（渲染为 InlineWidget）
content: { type: 'metric' | 'proposal-card' | 'action-launch' | 'alert', data: {...} }
```

`InlineWidget.tsx` 根据 `type` 分派，复用现有组件类：

| type | 复用类 | 交互 |
|---|---|---|
| `metric` | `cs-row` | 无 |
| `proposal-card` | `im-block` + `cs-btn` | `[批准]` `[驳回]` `[详情]`（详情 = 切到提案视图；预选中需跨组件状态，**本期不做**，留后续） |
| `action-launch` | `cs-pg` + `cs-btn ok` | `[启动]` = 切到对应视图 |
| `alert` | `im-handoff` / `im-suggest` | 无或 `[查看]` |

**后端向下兼容：** 本次 `/api/management/chat` 不改；`Dream Engine` 仍返回纯字符串，前端沿用 `im-msg-text` 渲染。widget 管道已在，等后端落地结构化返回时零改造接入。

### 4.2 仪表盘

3 区网格：

```
┌──────────────────────────────────────────────────────────────┐
│ [近5m] [近1h] [近24h]            （cs-wiz-step pill 样式）     │
├──────────────────────────────────────────────────────────────┤
│ ┌─ CSAT ──┐ ┌─ 结案率 ┐ ┌─ 消化率 ┐   3 大 KPI 卡              │
│ │  4.6    │ │  82%    │ │  94%    │   grid-columns: repeat(3) │
│ │  ▁▃▅▇   │ │  ▃▅▇█   │ │  ▅▇█▇   │   sparkline 占位          │
│ └─────────┘ └─────────┘ └─────────┘                          │
│ ┌─ Agent 状态 ────┬─ 辅助指标 ────┐  grid-columns: 1fr 1fr    │
│ │ customer online │ 首字节 240ms  │                          │
│ └──────────────── ┴──────────────┘                          │
│ ┌─ Takeover 趋势图 （全宽）────────────────────────────────┐   │
│ └────────────────────────────────────────────────────────┘   │
│ ┌─ Leaderboard （全宽）─────────────────────────────────┐     │
│ └────────────────────────────────────────────────────────┘   │
│ ┌─ Canary 进度 （全宽）──────────────────────────────────┐    │
│ └────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

改动点：
- 核心 3 指标（`csat_score` / `resolution_rate` / `digest_rate`）从 `cs-row` 升级为大卡（数字 32–40px + sparkline 占位 div）
- 辅助指标 + Agent 状态 2 列并排
- 时间选择器从内联 style 改用 `cs-wiz-step` pill

Sparkline 数据**留占位** div；本期不接入真实时序数据。

### 4.3 向导

几乎不改：
- 顶部 `cs-wiz` 横排 stepper 保留
- 中间 step 内容沿用现有"editorial dashboard"风格（`cs-card` 溶解 + 2 列 grid）
- 底部上一步/下一步按钮保留
- **例外**：wizard 视图**保留** `max-width: 1100px`（表单不宜过宽；其他 4 视图全幅）—— 通过 `.cs-canvas[data-view="wizard"]` 限制

### 4.4 提案（左右分栏 list-detail）

```
┌──────────────────────────────────────────────────────────────┐
│ [全部] [待审核] [已接受] [已拒绝] [已阻止]    [🔄 运行 Pipeline] │
├────────────────────────────┬─────────────────────────────────┤
│ 列表 flex: 0 0 360px       │ 详情 flex: 1                     │
│ ┌ 紧凑卡片（im-card）        │ ┌ im-block 展开                  │
│ │ · #124 high              │ │ 标题 / 描述                      │
│ │ · #123 medium ← active   │ │ 合规状态                        │
│ │ · #122 low               │ │ 源对话引用                       │
│ └                          │ │                                 │
│                            │ │ [批准] [驳回]                    │
└────────────────────────────┴─────────────────────────────────┘
```

新增本地 `selectedId` state；点击列表项切换详情。空状态右侧显示"从左侧选择一条提案"。

### 4.5 账单（左 period 列 + 右 detail）

```
┌────────────────────────────┬─────────────────────────────────┐
│ 账单周期 flex: 0 0 200px   │ 详情 flex: 1                     │
│  · 2026-04 ← active        │  现有两张 cs-card 保留            │
│  · 2026-03                 │  (总金额 / 阶梯明细)             │
│  · 2026-02                 │                                 │
└────────────────────────────┴─────────────────────────────────┘
```

替换原顶部 pill 周期切换。

## 5. 响应式

Desktop-first，CSS 降级，不做专门手机 UI。

| 断点 | 行为 |
|---|---|
| ≥ 1024px | 完整布局 |
| 768–1023px | icon rail 保留；视图内左右分栏坍塌为单列；Dashboard 3 KPI → 2 列 |
| < 768px | icon rail 折叠为顶栏 `☰` 抽屉；所有分栏单列；chat 输入框贴底 |

纯 `@media` 实现；抽屉用 `useState` + body `overflow:hidden`。不做触摸手势、PWA、safe-area。

## 6. 文件改动

### 新增

```
frontend/apps/admin-portal/src/components/shell/
  AdminShell.tsx          # topbar + rail + canvas 外壳
  AdminTopbar.tsx         # 40px 顶栏
  AdminRail.tsx           # 56px icon 导航
  CommandPalette.tsx      # ⌘K 占位
  AvatarMenu.tsx          # 右上菜单
frontend/apps/admin-portal/src/components/chat/
  InlineWidget.tsx        # D 种子渲染入口
```

### 修改

| 文件 | 改动摘要 |
|---|---|
| `components/AdminWorkspace.tsx` | 瘦身；只负责按 `activeTab` 路由到视图；外壳让位给 `AdminShell`；删除顶部 `cs-tb` title bar 与 `cs-tabs` 渲染 |
| `store/adminStore.ts` | `activeTab` 默认 `'wizard'` → `'notifications'` |
| `components/ManagementChat.tsx` | `height: calc(100vh - 140px)` → `height: 100%`；消息类型扩展为结构化 block；旧纯字符串向下兼容；接入 `InlineWidget` |
| `components/DashboardTab.tsx` | 核心 3 KPI 升级为大卡网格；Agent 状态 + 辅助指标 2 列；时间选择器使用 `cs-wiz-step` pill |
| `components/ProposalsTab.tsx` | 左右分栏（list + detail）；新增 `selectedId` state；空详情提示 |
| `components/BillingTab.tsx` | 顶部周期 pill → 左侧纵向列表 |
| `components/WizardTab.tsx` | 不改逻辑；确保在新 canvas 里布局正确 |
| `src/index.css` | 删 `.cs-tabs` / 旧 `.cs-tb` title bar 样式；`max-width: 1100px` 限定到 wizard；新增 `.cs-shell` / `.cs-topbar` / `.cs-rail` / `.cs-rail-item` / `.cs-canvas` / `.cs-kpi` / `.adm-chat-widget-*` / media queries |
| `App.tsx` | 把 `<AdminWorkspace />` 换成 `<AdminShell />` |

### 不改

- `packages/design-system/*`
- `main.tsx` / `api.ts` / `hooks/*`
- `components/wizard/*Step.tsx`
- `components/LoginPage.tsx`
- `components/CanaryProgress.tsx` / `TakeoverTrendChart.tsx` / `LeaderboardTable.tsx` / `AlertCard.tsx`
- 所有 `__tests__/*.test.tsx`

## 7. 测试策略

- **data-testid 保留**：`tab-wizard` / `tab-dashboard` / `tab-notifications` / `tab-proposals` / `tab-billing` / `wizard-next` / `proposal-list` / `wizard-stepper` 等不变；旧单元/集成测试应继续通过
- **新增测试**（轻量）：
  - `AdminRail.test.tsx`：默认 active = `notifications`，5 个图标点击切 tab
  - `AdminTopbar.test.tsx`：avatar 菜单展开、退出按钮工作
  - `InlineWidget.test.tsx`：4 种结构化消息类型各自渲染出预期 DOM
- **不新增 E2E**

## 8. 视觉细节规范（用于实现）

**Topbar**
```
高度 40px
背景 rgba(255,255,255,.6) + backdrop-filter blur(12px) saturate(1.4)
底边 1px solid var(--glass-border)
padding: 0 16px
左：8px violet dot (var(--aurora-3) + 3px rgba(167,139,250,.2) glow) + 13px 租户名 (ink, font-display, 600)
右：⌘K 按钮（28x28, var(--oat-l) bg, 12px mono, 灰度）+ avatar 圆点 (28x28, var(--ink) bg, 白字首字母)
```

**Rail**
```
宽度 56px
背景 rgba(255,255,255,.5) + blur
右边 1px solid var(--glass-border)
padding: 12px 0
每项 40x40, 图标居中 20px, 8px 圆角, 8px margin
active: background var(--ink), 图标白色, 左侧 3px var(--aurora-3) 条
hover: background var(--oat-l), 图标 var(--ink)
tooltip: 12px, paper bg, ink 字，绝对定位右侧 +12px
```

**Canvas**
```
padding 按视图：
  chat → 0（ManagementChat 自己控制 header/feed/input 间距）
  dashboard → 24px 32px
  wizard → 40px 56px（保留现有）
  proposals / billing → 20px 28px
max-width：仅 wizard 限定 1100px（data-view="wizard" 触发）
其他视图全宽
```

**Dashboard 大 KPI 卡**
```
cs-card 扩展（新建 .cs-kpi）:
  padding 24px
  display flex column
  gap 12px
  数字 36px, font-mono, 700, var(--ink)
  label 11px, uppercase, letter-spacing 1.2px, silver
  sparkline div height 36px, 先留空（bg var(--oat-l) 占位）
```

## 9. 实施顺序

1. 建外壳：`AdminShell` + `AdminTopbar` + `AdminRail` + `AvatarMenu` + `CommandPalette` 占位 + 新 CSS
2. `App.tsx` 接入 `AdminShell`；删除 `AdminWorkspace` 外层 chrome
3. `adminStore` 默认页改 `notifications`
4. `index.css` 清理：删 `.cs-tabs` / 旧 `.cs-tb`；`max-width: 1100px` 限定 wizard；新增 shell/rail CSS
5. `ManagementChat` 高度改为 100%；接入 `InlineWidget`
6. 新建 `InlineWidget` 4 种变体 + 单元测试
7. `DashboardTab` 改 KPI 大卡网格 + 2 列辅助区
8. `ProposalsTab` 改左右分栏
9. `BillingTab` 改左 period 列 + 右 detail
10. 响应式 media queries（≥1024 / 768-1023 / <768）
11. `⌘K` 占位弹框（点开显示 "command palette coming soon"）
12. 手工验证 5 视图 + 跑现有测试套件

## 10. 开放风险

- **测试选择器回归**：外层 DOM 结构变了，如果某个测试依赖 `.cs-w > .cs-tabs > button` 这种结构选择器（而不是 `data-testid`），会失效。实施时第一步跑全量测试先看 baseline，再对比
- **wizard 覆盖 CSS 副作用**：`index.css` 244–533 行的 wizard editorial 样式大量用 `!important` + 选择器组合；限定到 `[data-view="wizard"]` scope 时要小心不破坏现有 wizard 渲染
- **ManagementChat 高度**：从 `calc(100vh - 140px)` 改为 `100%`，其祖先链必须每一层都 `height: 100%` 或 flex，否则会塌陷

## 11. 未来路径（不在本次 scope）

- `⌘K` 命令搜索真实实现（模糊匹配视图名 + 执行指令如 "批准提案 #124"）
- Dream Engine 后端返回结构化 block，接入 `InlineWidget` 真实数据
- Inline widget 更多变体（表格、图表缩略图）
- D-path 终局：收起 icon rail，admin 完全以对话驱动
- 多租户切换器（当前 topbar 只显示单租户名）
- 告警中心（topbar 右侧铃铛 + 通知 drawer）
