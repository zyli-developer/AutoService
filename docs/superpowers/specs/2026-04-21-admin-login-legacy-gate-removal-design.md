# Admin-Portal · Legacy Login Gate Removal — Design

**Status**: Approved · ready for implementation plan
**Date**: 2026-04-21 (brainstorm started) · 2026-04-22 (finalized)
**Owner**: hjj.gemini@gmail.com
**Scope**: `frontend/apps/admin-portal/` only (operator-console has its own separate legacy form; out of scope here)

## Problem

截图显示 admin-portal 登录页 subtitle 说"我们将通过邮件发送一次性登录链接"，但输入框 placeholder 是 "Tenant ID" —— 文案和输入框不匹配。

## Root Cause

`admin-portal` 目前存在**两个 LoginPage**，并且有**两层登录 gate**：

1. **顶层 gate**（新版，server-side）
   - [App.tsx:46-72](../../../frontend/apps/admin-portal/src/App.tsx#L46-L72) 用 `<AuthGate>` 包住所有非 `/login` 路由
   - `AuthGate` 通过 `useSessionMode()` 探测 `/api/session/mode`；若 anon 重定向到 `/login`
   - `/login` 渲染 [components/auth/LoginPage.tsx](../../../frontend/apps/admin-portal/src/components/auth/LoginPage.tsx)（magic-link 邮箱流）

2. **二层 gate**（legacy，client-side）
   - [MasterLayout.tsx:87-95](../../../frontend/apps/admin-portal/src/layouts/MasterLayout.tsx#L87-L95) `if (!isLoggedIn) return <LoginPage />`
   - 读取 zustand `adminStore.isLoggedIn`（纯客户端 flag）
   - 渲染 legacy [components/LoginPage.tsx](../../../frontend/apps/admin-portal/src/components/LoginPage.tsx)（tenant-id 直登表单）

**触发路径**：用户走 magic-link 登录 → 服务端种 cookie → AuthGate 放行 → MasterLayout 又被 zustand `isLoggedIn=false` 挡住（magic-link 流程不调 `adminStore.login()`） → 用户看到 legacy form，被要求填 Tenant ID。

该 Tenant ID input 的 `onSubmit` 只做 `set({ tenantId, isLoggedIn: true })`，**没有任何实际鉴权作用**，纯粹是个 UI 阻断器。

新版 [auth/LoginPage.tsx:12-15](../../../frontend/apps/admin-portal/src/components/auth/LoginPage.tsx#L12-L15) 的注释已经明确说明了这点：

> NOTE: this file coexists with the legacy `components/LoginPage.tsx`
> (tenant-id-based login used by `MasterLayout`'s zustand `isLoggedIn`
> flow). M2 will eventually remove the legacy one once `MasterLayout`
> drops its internal gate and delegates to `<AuthGate>`.

## Impact Investigation

| 担忧 | 结论 |
|---|---|
| E2E 脚本依赖 legacy testids？ | `e2e-evidence/` 仅存 API JSON evidence，无 Playwright 脚本。✅ 无风险 |
| operator-console 受影响？ | operator-console 有自己独立的 legacy LoginPage；**out of scope** |
| 磁链登录流程本身是否正常？ | 是的，magic-link 流程已经跑通（服务端 session cookie 正确种），只是被二层 gate 挡住 |
| 会造成 admin 登录不了吗？ | **不会** —— 反而是修复一个当前被隐藏的假阳性阻断 |
| TenantLayout 有类似 gate？ | 没有，`TenantLayout` 本来就只依赖 AuthGate |

## Decision · Option B (中等清理)

讨论的三个选项：
- **A 最小修**：只删 MasterLayout gate，保留 zustand `isLoggedIn`/`login()`/`tenantId`。缺陷：留孤儿字段，`tenantId` 永不更新，AvatarMenu 一直显示 `—`。
- **B 中等清理** ✅ **采纳**
- **C 激进重构**：把 6 个 zustand tenantId 消费者全迁到 `useTenantId()` hook。超出 bug fix 范围，风险大。

### Option B 要点

- 删 MasterLayout 的 `isLoggedIn` 分支
- 删 legacy `components/LoginPage.tsx` + `__tests__/LoginPage.test.tsx`
- **删** zustand `adminStore.isLoggedIn` 和 `login()` 字段（auth flag，已无用）
- **保留** zustand `adminStore.tenantId`（它是 "当前 scope 的 tenant" UI state，wizard/rail/topbar/menu 都还要读）
- App.tsx 顶层加一个 sync effect：把 `useSessionMode().data.tenant_id` 镜像到 `adminStore.setTenantId()`（覆盖 ModeDispatch 和 `/t/<tid>/admin` 两条分支）
- 为 adminStore 新增 `setTenantId(tid: string | null)` action（替代被删的 `login`）
- AvatarMenu.handleLogout **保留** `logout()` zustand 调用（= reset 全 store；防止换用户时看到上一用户的 wizard 草稿 / notifications / canary 状态）

### Zustand 消费者清单（Option B 下行为）

| 消费者 | 字段 | B 下行为 |
|---|---|---|
| [MasterLayout.tsx:88](../../../frontend/apps/admin-portal/src/layouts/MasterLayout.tsx#L88) | `isLoggedIn` | 删除整段 gate |
| [AvatarMenu.tsx:26](../../../frontend/apps/admin-portal/src/components/shell/AvatarMenu.tsx#L26) | `tenantId` | 不改，但值由 sync effect 更新 |
| [AdminRail.tsx:132](../../../frontend/apps/admin-portal/src/components/shell/AdminRail.tsx#L132) | `tenantId` | 同上 |
| [AdminTopbar.tsx:45](../../../frontend/apps/admin-portal/src/components/shell/AdminTopbar.tsx#L45) | `tenantId` | 同上 |
| [DreamTab.tsx:85](../../../frontend/apps/admin-portal/src/components/DreamTab.tsx#L85) | `tenantId` | 同上（最近 `3ad81b2` 刚修过 store-placeholder 问题——实施时重点扫，别再复发） |
| [ComplianceCheckStep.tsx:27](../../../frontend/apps/admin-portal/src/components/wizard/ComplianceCheckStep.tsx#L27) | `tenantId` | 同上 |
| [WizardTab.tsx:53](../../../frontend/apps/admin-portal/src/components/WizardTab.tsx#L53) | `tenantId`（作为 seed，`generationResult?.tenantId \|\| tenantId \|\| 'default'`） | master session 下为 null → fallback 到 `'default'`，与现在 legacy form 未填写时行为一致 |
| [SandboxReady.tsx:45-46](../../../frontend/apps/admin-portal/src/components/wizard/SandboxReady.tsx#L45-L46) | `tenantId` | 同 Wizard |

## Design · Section 1 · 架构 & 数据流

### Before（双重 gate）

```
anon → App.tsx → AuthGate (server session probe)
  ├─ anon → /login → auth/LoginPage (magic-link) → server 302 back
  └─ auth → ModeDispatch → MasterLayout
                              ↓
                              [isLoggedIn gate ← zustand]
                                ├─ false → legacy LoginPage (Tenant ID input) → login(tid) → retry
                                └─ true → MasterRoutes ✅
```

### After（单层 gate）

```
anon → App.tsx → AuthGate (server session probe)
              ↓ sync session.tenant_id → adminStore.setTenantId()
  ├─ anon → /login → auth/LoginPage (magic-link)
  └─ auth → ModeDispatch / path-tenant short-circuit
              └─ MasterLayout / TenantLayout → routes ✅
```

### 数据来源变化

| 值 | Before | After |
|---|---|---|
| 是否登录 | zustand `isLoggedIn` + server session（双重） | 仅 server session（`useSessionMode`） |
| 当前 scope tenantId | legacy form 用户输入 → `adminStore.tenantId` | `useSessionMode().data.tenant_id`（或 URL `/t/<tid>/admin`）→ sync effect → `adminStore.setTenantId()` |
| AvatarMenu 展示的 tenant | zustand | zustand（值由 sync effect 更新） |
| Wizard tenantId seed | zustand（用户登录时填的） | zustand（master session 下是 null，wizard 已有 `'default'` fallback） |

## Design · Section 2 · 具体组件改动

### 2.1 MasterLayout · gate 删除

```diff
 // frontend/apps/admin-portal/src/layouts/MasterLayout.tsx
 import { useEffect } from 'react';
 import { BrowserRouter, Routes, Route, useLocation, Outlet } from 'react-router-dom';
-import { useAdminStore } from '../store/adminStore';
-import { LoginPage } from '../components/LoginPage';
+import { useAdminStore } from '../store/adminStore';  // still used by WizardRoute
 ...

 export function MasterLayout() {
-  const isLoggedIn = useAdminStore((s) => s.isLoggedIn);
-  if (!isLoggedIn) return <LoginPage />;
   return (
     <BrowserRouter>
       <MasterRoutes />
     </BrowserRouter>
   );
 }
```

### 2.2 adminStore · 接口变更

```diff
 // frontend/apps/admin-portal/src/store/adminStore.ts
 export interface AdminState {
   tenantId: string | null;
-  isLoggedIn: boolean;
   activeTab: ...;
   ...
-  login: (tenantId: string) => void;
+  setTenantId: (tenantId: string | null) => void;
   logout: () => void;
   ...
 }

 export const initialState = {
   tenantId: null,
-  isLoggedIn: false,
   activeTab: 'notifications' as const,
   ...
 };

 create<AdminState>()(
   persist(
     (set) => ({
       ...initialState,
-      login: (tenantId) => set({ tenantId, isLoggedIn: true }),
+      setTenantId: (tenantId) => set({ tenantId }),
       logout: () => set({ ...initialState }),  // 行为不变——reset 全 store
       ...
     })
   )
 )
```

**持久化兼容**：`persist` middleware 持久化到 localStorage。老用户 localStorage 里可能残留 `isLoggedIn: true`——zustand persist 遇到 schema 里没有的字段默默忽略，无需 migration / schema version bump。

### 2.3 App.tsx · 新增 sync effect（顶层）

Sync effect 放在 `App` 顶层（而不是 `ModeDispatch` 内部），以覆盖 `/t/<tid>/admin` 路径短路分支：

```tsx
// frontend/apps/admin-portal/src/App.tsx
export function App() {
  const { data } = useSessionMode();
  const setTenantId = useAdminStore((s) => s.setTenantId);
  const pathname = typeof window !== 'undefined' ? window.location.pathname : '';
  const pathTenantId = tenantIdFromAdminPath(pathname);

  useEffect(() => {
    // URL 路径 tenant 优先（与 useTenantId 语义一致），回落 session tenant_id
    setTenantId(pathTenantId ?? data?.tenant_id ?? null);
  }, [pathTenantId, data?.tenant_id, setTenantId]);

  // ... rest of dispatch unchanged
}
```

### 2.4 legacy 文件 / 测试 / i18n 清理

- 删 [components/LoginPage.tsx](../../../frontend/apps/admin-portal/src/components/LoginPage.tsx)
- 删 [__tests__/LoginPage.test.tsx](../../../frontend/apps/admin-portal/src/__tests__/LoginPage.test.tsx)
- 删 [__tests__/MasterLayout.test.tsx:15](../../../frontend/apps/admin-portal/src/__tests__/MasterLayout.test.tsx#L15) 的 `vi.mock('../components/LoginPage', ...)`
- 删 [auth/LoginPage.tsx:12-15](../../../frontend/apps/admin-portal/src/components/auth/LoginPage.tsx#L12-L15) 里 "NOTE: this file coexists..." 整段注释（过期）
- 扫 `admin.login.tenant_id` 的 i18n key：若除 legacy LoginPage 外无引用，从 `en.json` + `zh-CN.json` 删除；`operator.login.tenant_id` **不动**（operator-console 独立）

### 2.5 AvatarMenu.handleLogout · 保留现行行为

[AvatarMenu.tsx:46-69](../../../frontend/apps/admin-portal/src/components/shell/AvatarMenu.tsx#L46-L69) 不改——`logout()` 保持 reset 全 store 的行为，防止浏览器换用户时看到上一用户的 wizard 草稿 / notifications / canary。新 `logout()` 定义（Section 2.2）自然仍是 `set({ ...initialState })`，新 initialState 已不含 `isLoggedIn`。

## Design · Section 3 · 测试改动清单

### 3.1 删除

- `frontend/apps/admin-portal/src/__tests__/LoginPage.test.tsx`（legacy 专属）
- [__tests__/MasterLayout.test.tsx:15](../../../frontend/apps/admin-portal/src/__tests__/MasterLayout.test.tsx#L15) 的 `vi.mock('../components/LoginPage', ...)`
- [__tests__/adminStore.test.ts:9-22](../../../frontend/apps/admin-portal/src/__tests__/adminStore.test.ts#L9-L22)（TC-01、TC-02，测 `login()` / `isLoggedIn`）

### 3.2 修改（去掉 `isLoggedIn: true` setup & assertions）

9 个测试文件：
- [__tests__/AdminRail.test.tsx:23](../../../frontend/apps/admin-portal/src/__tests__/AdminRail.test.tsx#L23)
- [__tests__/AdminTopbar.test.tsx:8](../../../frontend/apps/admin-portal/src/__tests__/AdminTopbar.test.tsx#L8)
- [__tests__/AvatarMenu.test.tsx:8,33,37](../../../frontend/apps/admin-portal/src/__tests__/AvatarMenu.test.tsx#L8)（第 33 行 `isLoggedIn === false` 的 assertion 删）
- [__tests__/AdminWorkspace.test.tsx:16,61](../../../frontend/apps/admin-portal/src/__tests__/AdminWorkspace.test.tsx#L16)（第 61 行 assertion 删）
- [__tests__/TenantLayout.test.tsx:60](../../../frontend/apps/admin-portal/src/__tests__/TenantLayout.test.tsx#L60)
- [__tests__/InlineWidget.test.tsx:8](../../../frontend/apps/admin-portal/src/__tests__/InlineWidget.test.tsx#L8)
- [__tests__/MasterLayout.test.tsx:42,47](../../../frontend/apps/admin-portal/src/__tests__/MasterLayout.test.tsx#L42) — 重写这两条 TC：原本测"未登录显示 LoginPage / 已登录显示 routes"，新 TC 测"永远渲染 MasterRoutes（AuthGate 在上游负责 auth）"
- [__tests__/integration.test.tsx:14-34](../../../frontend/apps/admin-portal/src/__tests__/integration.test.tsx#L14-L34) — 去掉 `input-tenant-id` + `btn-login` 交互，改为直接 `useAdminStore.setState({ tenantId: 'foo' })` 准备态

### 3.3 新增

- **adminStore 测试**：`setTenantId('acme')` → `tenantId === 'acme'`；`setTenantId(null)` → `tenantId === null`
- **App.tsx 测试**（合并到已有 `__tests__/App.test.tsx`，不新建文件）：
  - mock `useSessionMode` 返回 `{ tenant_id: 'acme', authenticated: true, mode: 'master' }` → mount `<App />` → 断言 `useAdminStore.getState().tenantId === 'acme'`
  - mock 返回 `{ tenant_id: null, authenticated: true, mode: 'master' }` → 断言同步到 `null`
  - `/t/acme/admin` 路径短路 → 断言 `adminStore.tenantId === 'acme'`（URL 优先于 session）

## Design · Section 4 · 错误处理 & 边缘情况

### 4.1 已被 AuthGate 覆盖

- 服务端 session 探测失败 → AuthGate 渲染 error splash + retry 按钮
- 服务端 session 过期 → AuthGate 重定向到 `/login`
- 登出后再访问受保护路由 → AuthGate 重定向

### 4.2 首帧 null flicker · 需按消费者逐一验证

`useEffect` 在 children render 之后跑一拍，第一次 mount 时：

- Frame N：App render → AuthGate → Master/TenantLayout render → 子组件读 `adminStore.tenantId`（persist 恢复的旧值或 `null`）
- Frame N+1：sync effect 跑 → `setTenantId(session.tenant_id)` → 重渲染

**策略**：实施时为每个 tenantId 消费者补一条"null 场景稳定渲染"单测。已有 fallback 的（AvatarMenu 的 `?? '—'`、WizardTab / SandboxReady 的 `|| 'default'`）无需改。需要重点扫 DreamTab（最近 `3ad81b2` 刚修过 placeholder 问题）、ComplianceCheckStep、AdminRail / AdminTopbar（有 `tenantIdOverride` prop 但 null fallback 需确认）。

### 4.3 路径 tenant 短路的 sync 覆盖

Section 2.3 的 sync effect 放在 `App` 顶层而非 `ModeDispatch` 内部，正是为了覆盖 `/t/<tid>/admin` 分支——该分支不经过 ModeDispatch，但仍在 App 组件树内。URL 路径 tenant 优先于 session.tenant_id，与 `useTenantId` 既有语义一致（[useTenantId.ts:50-51](../../../frontend/packages/shared/useTenantId.ts#L50-L51)）。

### 4.4 Session 切换（同浏览器换用户）

用户 A 登出 → `logout()` 重置 store（`tenantId=null`） → AuthGate 重定向 → 用户 B magic-link 登录 → session 更新 → sync effect 把 B 的 `tenant_id` 同步到 `adminStore.tenantId` ✅ 无状态残留。

### 4.5 持久化兼容

见 Section 2.2 末尾——老用户 localStorage 里的 `isLoggedIn: true` 会被 zustand persist 静默忽略，`tenantId` 也会被 sync effect 在 mount 时覆盖为当前 session 值。无迁移代码。

## Design · Section 5 · 实施顺序（TDD, 8 批次）

原则：每批自成一次 commit，suite 全程绿，前后均可 rollback。Batch 3 commit 后用户侧 UI 已修（不再见 Tenant ID 表单），Batch 4-8 是 cleanup——后续批次若发现问题可随时 stop，不会阻塞用户登录。

### Batch 1 · adminStore 加 `setTenantId`（并存模式）

- 红：`adminStore.test.ts` 新增 TC —— `setTenantId('acme')` → `tenantId === 'acme'`；`setTenantId(null)` → `tenantId === null`
- 绿：新增 `setTenantId` action；**暂不删** `isLoggedIn` / `login`（下游还依赖）

### Batch 2 · App.tsx sync effect

- 红：`App.test.tsx` 新增 3 条 TC（见 Section 3.3）
- 绿：按 Section 2.3 实现 sync effect

### Batch 3 · MasterLayout 拆 gate

- 红：改 `MasterLayout.test.tsx:42,47` 两条 TC —— "未登录显示 LoginPage" 改成 "永远渲染 MasterRoutes"；删 `vi.mock('../components/LoginPage', ...)`
- 绿：删 MasterLayout 的 `isLoggedIn` gate + LoginPage import（Section 2.1）

**⚠️ 此批 commit 后用户侧 bug 已修**，后续批次仅 cleanup。

### Batch 4 · 删 legacy LoginPage

纯删除，无测试变化：
- 删 `components/LoginPage.tsx`
- 删 `__tests__/LoginPage.test.tsx`
- 删 `auth/LoginPage.tsx:12-15` 过期注释

### Batch 5 · 消费者测试 cleanup

9 个测试文件去掉 setState 里的 `isLoggedIn: true`；删 `AvatarMenu.test.tsx:33` + `AdminWorkspace.test.tsx:61` 的 `isLoggedIn` assertion。Suite 仍绿（字段此时还在 store 里，只是无人依赖）。

### Batch 6 · 删 `isLoggedIn` + `login`（终于能删了）

- 删 `adminStore.test.ts` TC-01/TC-02
- 从 `AdminState` / `initialState` / store body 删 `isLoggedIn` + `login`（Section 2.2）
- TS 编译：Batch 5 已清掉所有 setState 引用，此时无 TS 错误

### Batch 7 · integration.test.tsx 重写

替换 `input-tenant-id` + `btn-login` 交互为 `useAdminStore.setState({ tenantId: 'foo' })`——legacy form 已不存在，必须重写此 flow-级用例。

### Batch 8 · i18n key 扫尾

- `admin.login.tenant_id` 在 `en.json` + `zh-CN.json` 扫；若无非 legacy 引用，purge
- `operator.login.tenant_id` 不动（out of scope）

---

**下一步**：以此 spec 为输入调用 `writing-plans` 生成可执行的实施 plan（每批的 TDD 细节、commit message、rollback 策略）。
