# Frontend Stack Decision · 全球发行组件方案

> **日期**: 2026-04-15
> **Owner**: DevB
> **状态**: 提案（待 review）
> **影响范围**: `frontend/apps/*`, `frontend/packages/*`, Batch 2 及之后的所有 B 线任务

---

## 1. 背景

T0.6 已搭起 pnpm monorepo 骨架（3 app + ws-client + i18n + ui-components 空壳）。
当前 `customer-chat` 配了 Tailwind，`operator-console` / `admin-portal` 无 UI 库。

进入 Batch 2 前需要定清：
1. 三个 app 分别用什么组件库？
2. 全球发行（22 语种 + RTL + 低带宽 + a11y + 白标）的硬约束如何落地？
3. 三个 app 之间如何共享 token / 组件 / i18n？

---

## 2. 三个 app 的定位差异

| App | 使用者 | 核心 UI 形态 | 部署形态 | 关键 NFR |
|---|---|---|---|---|
| **customer-chat** | 终端客户 | 消息气泡、流式续写、浮动按钮 SDK | 嵌入**客户网站**（第三方 `<script>`） | 包体小、不污染宿主、多语言、RTL |
| **operator-console** | 坐席 | 分队卡片墙、Copilot 侧栏、表格、抢单 | 内部 SaaS | 组件生产力、密集数据、通知/声音 |
| **admin-portal** | 租户管理员 | 配置向导、资料上传、仪表盘、合规 | 内部 SaaS | Form/Steps/Upload/Charts 全家桶 |

**关键洞察**：三者差异巨大，强行统一一套组件库是反模式。

---

## 3. 全球发行的硬约束

| 约束 | 说明 | 必要性 |
|---|---|---|
| **22 语种** | 英/中/日/韩/阿/希伯来/俄/葡/西/法/德 等 | P0 |
| **RTL** | 阿拉伯语、希伯来语 | P0 |
| **CJK 字体 fallback** | Noto Sans CJK 族 | P1 |
| **低带宽市场** | 东南亚、南美、非洲；customer-chat 首屏预算 < 150 KB gz | P0（widget）/ P2（内部台） |
| **白标主题** | 每租户换色/logo | P1 |
| **a11y (WCAG 2.1 AA)** | 欧盟 EAA 2025、US Section 508 | P1 |
| **嵌入不污染宿主** | customer-chat SDK 嵌入客户页面，禁用全局 `body`/`*` 样式 | P0 |
| **时区** | 后端 UTC，前端本地化 | P0 |

---

## 4. 候选方案对比

| 方案 | Bundle | i18n locale | RTL | a11y | 富组件 | 白标 | 嵌入友好 |
|---|---|---|---|---|---|---|---|
| AntD v5 | 大 (~350KB gz) | ⭐⭐⭐ 50+ 内置 | ✅ | ⭐⭐ | ⭐⭐⭐（ProComponents） | ⭐⭐ | ❌ |
| MUI v5 | 大 (~300KB gz) | ⭐⭐⭐ | ✅ 强 | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ❌ |
| Mantine v7 | 中 (~150KB gz) | ⭐⭐ | ✅ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | 中 |
| Radix + Tailwind (shadcn) | 小 (<50KB) | ⚪ 自接 | ✅ | ⭐⭐⭐⭐ | ⭐（需自组） | ⭐⭐⭐ CSS 变量 | ⭐⭐⭐ |
| Arco Design | 大 | ⭐⭐ | ✅ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ❌ |

---

## 5. 决策：按 app 分层

### 5.1 customer-chat → **Radix + Tailwind (shadcn/ui 模式)**

**理由**：
- 作为 SDK 嵌入客户网站，必须包体小 + 不污染宿主
- 消息气泡、流式续写动效都是自定义 UI，组件库成品反而束缚
- Radix 提供 Dialog/Tooltip/Dropdown 无样式 + a11y 第一
- **Shadow DOM 隔离**宿主样式（T1B.5 浮动按钮 SDK 落实）
- 首屏预算：< 150 KB gz（含 React）

**依赖**：
```
react, react-dom
@radix-ui/react-* (按需)
tailwindcss, tailwindcss-rtl, @tailwindcss/typography
class-variance-authority, clsx, tailwind-merge
```

### 5.2 operator-console → **AntD v5**

**理由**：
- 核心是表格墙 + 并发会话卡片 + 侧栏聊天，AntD 的 Table/List/Badge/Notification 省命
- 未读徽章、声音提醒、抢单按钮 — AntD Message/Notification/Badge 直接用
- 坐席为内部用户，bundle 不敏感
- 22 locale 内置，RTL 原生支持

**依赖**：
```
antd, @ant-design/icons
dayjs (AntD 依赖)
```

### 5.3 admin-portal → **AntD v5 + ProComponents**

**理由**：
- 四步配置向导、资料上传、运营仪表盘 — AntD Pro 的原生场景
- `ProForm` / `ProTable` / `StepsForm` / `ProLayout` 覆盖 T3B.2-T3B.7 全部
- 与 operator-console 同栈降低维护成本

**依赖**：
```
antd, @ant-design/pro-components, @ant-design/icons
dayjs
```

### 5.4 packages/ui-components

**职责**：**跨 app 共用的业务组件**（不包装 AntD，那是反模式）
- `<MessageBubble>` — customer-chat + operator-console Copilot 侧栏复用
- `<TenantHeader>` — logo + 语言切换 + 用户菜单
- `<LanguageSwitcher>` — 封装 i18next + AntD ConfigProvider 联动
- `<StreamingPlaceholder>` — AI 流式续写动效
- `tokens.ts` — **单一主题源**，AntD ConfigProvider 与 Tailwind theme.extend 同时消费

---

## 6. 主题 Token 单一源策略

```
packages/ui-components/src/tokens.ts
  ├─ colors: { primary, success, warning, error, ... }
  ├─ radius: { sm, md, lg }
  ├─ spacing: { ... }
  └─ typography: { fontFamily, fontSize, ... }
         │
         ├──► AntD: <ConfigProvider theme={{ token: mapToAntdToken(tokens) }}>
         │
         └──► Tailwind: tailwind.config.ts → theme.extend = mapToTailwind(tokens)
```

运行时白标切换通过 CSS 变量实现：`tokens.ts` 输出 CSS 变量声明，AntD v5 的 `cssVar: true` 开关 + Tailwind 用 `var(--color-primary)`。

---

## 7. i18n + RTL 策略

### 7.1 i18n
- **i18next + react-i18next**：语种独立 JSON chunk，lazy import
- 每个 app 加载自己的 namespace；`packages/i18n` 只放共享 key（如通用按钮、错误码）
- 源语言：英文 `en.json`（单一事实源）；其他语种通过 TMS 翻译
- **TMS 候选**：Crowdin（推荐）/ Lokalise / Weblate（自托管）— T1B.6 选型

### 7.2 RTL
- `<html lang dir>` 由 i18next 当前语言驱动（ar/he 时 `dir="rtl"`）
- AntD：`<ConfigProvider direction="rtl">` 联动
- Tailwind：装 `tailwindcss-rtl` 插件，用 `rtl:` / `ltr:` 前缀
- 所有自定义 CSS 优先用逻辑属性（`padding-inline-start` 而非 `padding-left`）

### 7.3 格式化
- 日期/数字/货币统一走原生 `Intl.*`
- 时间：后端传 UTC ISO8601，前端 `dayjs.tz` 转本地

### 7.4 落地节奏
- **M1 前**：en + zh-CN + ar 三语跑通（验证 lazy load + RTL）
- **M2-M3**：接 TMS，其余 19 语种逐步导入
- **M4 前**：22 语种全量

---

## 8. a11y 策略

- **每 PR 跑 `@axe-core/react`**（dev-only 注入）
- ESLint 加 `eslint-plugin-jsx-a11y`
- customer-chat 走 Radix 天然达标；operator/admin 走 AntD 需补键盘导航测试
- CI 阶段可选加 `pa11y-ci` 对关键页面跑 WCAG 2.1 AA

---

## 9. 嵌入 widget 的特殊工程

customer-chat 作为 `<script>` SDK 发行（T1B.5）：
1. **Shadow DOM 隔离** — `attachShadow({ mode: 'closed' })`，Tailwind 样式注入 Shadow root
2. **命名空间前缀** — Tailwind 加 `prefix: 'as-'`，避免残留类名冲突
3. **独立构建产物** — Vite `build.lib` 模式，输出单 IIFE `autoservice-widget.js`
4. **全局变量唯一** — 挂 `window.AutoService` 一个命名空间
5. **CSP 友好** — 不用 `eval`、不注入 `<style>` 到宿主 head

---

## 10. 落地顺序（Batch 2 起）

| 序 | 任务 | 关联 |
|---|---|---|
| 1 | `packages/ui-components/src/tokens.ts` 定义主题 token（即使空壳先占位） | T1B.1 开头 |
| 2 | operator-console `pnpm add antd dayjs`，App.tsx 套 ConfigProvider | T2B.1 |
| 3 | admin-portal `pnpm add antd @ant-design/pro-components dayjs` | T3B.1 |
| 4 | customer-chat `pnpm add @radix-ui/react-* tailwindcss-rtl`，加 RTL 支持 | T1B.1 |
| 5 | `packages/i18n` 补 ar.json 占位 + lazy load 机制 + `<html dir>` 响应 | T1B.6 |
| 6 | `LanguageSwitcher` 组件统一 i18next + AntD locale | T1B.6 |
| 7 | CI bundle-size gate（customer-chat 主包 < 150 KB gz） | T1B.5 |
| 8 | TMS 接入（Crowdin 工作流） | T1B.6 或更后 |

---

## 11. 风险与权衡

| 风险 | 缓解 |
|---|---|
| 双栈维护成本（Tailwind + AntD） | 单一 tokens.ts 源 + CSS 变量统一；Tailwind 仅用于 customer-chat |
| AntD "中国后台风"辨识度 | 深度 token 定制（圆角/间距/主色）；极端情况可改 Mantine |
| Radix 自组装成本（表格/日期） | 按需装 TanStack Table / react-day-picker；customer-chat 本身不需要复杂数据组件 |
| 22 语种翻译真实成本 | 先 en+zh+ar 跑通，TMS 异步补完；产品可接受渐进式上线 |
| Shadow DOM 与 React 事件冒泡 | React 18 已支持 Shadow DOM 原生事件；T1B.5 做 POC 验证 |
| AntD v5 CSS-in-JS SSR 水合 | 当前 Vite SPA 无 SSR，暂不影响；若未来接 SSR 用 `@ant-design/cssinjs` 官方方案 |

---

## 12. 决策总结

| 决策项 | 选择 |
|---|---|
| customer-chat UI 栈 | Radix + Tailwind (+ Shadow DOM for SDK) |
| operator-console UI 栈 | AntD v5 |
| admin-portal UI 栈 | AntD v5 + ProComponents |
| 主题源 | `packages/ui-components/tokens.ts` 单一源，AntD + Tailwind 共享 |
| i18n | i18next + react-i18next，JSON lazy chunk |
| RTL | `<html dir>` + AntD ConfigProvider + tailwindcss-rtl |
| TMS | Crowdin（待 T1B.6 确认） |
| a11y 门禁 | `jsx-a11y` lint + `@axe-core/react` dev + pa11y-ci（可选） |
| Bundle 预算 | customer-chat < 150 KB gz；其他无硬约束 |

---

## 13. 未决项

- [ ] Crowdin vs Lokalise vs Weblate — 看预算与自托管需求（T1B.6 决策）
- [ ] customer-chat Shadow DOM 开/关开关（可能做成可配置，默认开） — T1B.5
- [ ] 白标主题配置读取来源：后端 API vs 构建时注入 — 等 T3B.2 向导定
- [ ] 是否需要 dark mode — 产品未确认；tokens.ts 预留接口即可

---

*v1.0 · 2026-04-15 · Batch 1 尾段产出；Batch 2 启动前必须 review 并冻结选型*
