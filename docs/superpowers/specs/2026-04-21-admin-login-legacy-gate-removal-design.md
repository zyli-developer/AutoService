# Admin-Portal · Legacy Login Gate Removal — Design (WIP)

**Status**: BRAINSTORM WIP · paused before design sections 2–4
**Date**: 2026-04-21
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

## Impact Investigation (已确认)

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
- App.tsx / ModeDispatch 加一个 sync effect：把 `useSessionMode().data.tenant_id` 镜像到 `adminStore.setTenantId()`
- 为 adminStore 新增 `setTenantId(tid: string | null)` action（替代被删的 `login`）
- AvatarMenu.handleLogout 去掉 `logout()` zustand 调用（不再需要清 isLoggedIn；`/api/auth/logout` 清 session 即可）
  - 需要进一步考虑：logout 是否仍需清除 wizard state / notifications？现有 `logout()` 等同于 reset 全 store。留给下一节讨论。

### Zustand 消费者清单（Option B 下行为）

| 消费者 | 字段 | B 下行为 |
|---|---|---|
| [MasterLayout.tsx:88](../../../frontend/apps/admin-portal/src/layouts/MasterLayout.tsx#L88) | `isLoggedIn` | 删除整段 gate |
| [AvatarMenu.tsx:26](../../../frontend/apps/admin-portal/src/components/shell/AvatarMenu.tsx#L26) | `tenantId` | 不改，但值由 sync effect 更新 |
| [AdminRail.tsx:132](../../../frontend/apps/admin-portal/src/components/shell/AdminRail.tsx#L132) | `tenantId` | 同上 |
| [AdminTopbar.tsx:45](../../../frontend/apps/admin-portal/src/components/shell/AdminTopbar.tsx#L45) | `tenantId` | 同上 |
| [DreamTab.tsx:85](../../../frontend/apps/admin-portal/src/components/DreamTab.tsx#L85) | `tenantId` | 同上 |
| [ComplianceCheckStep.tsx:27](../../../frontend/apps/admin-portal/src/components/wizard/ComplianceCheckStep.tsx#L27) | `tenantId` | 同上 |
| [WizardTab.tsx:53](../../../frontend/apps/admin-portal/src/components/WizardTab.tsx#L53) | `tenantId`（作为 seed，`generationResult?.tenantId \|\| tenantId \|\| 'default'`） | master session 下为 null → fallback 到 `'default'`，与现在 legacy form 未填写时行为一致 |
| [SandboxReady.tsx:45-46](../../../frontend/apps/admin-portal/src/components/wizard/SandboxReady.tsx#L45-L46) | `tenantId` | 同 Wizard |

## Design · Section 1 已对齐：架构 & 数据流

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
  ├─ anon → /login → auth/LoginPage (magic-link)
  └─ auth → ModeDispatch
              ├─ sync session.tenant_id → adminStore.setTenantId()
              └─ MasterLayout / TenantLayout → routes ✅
```

### 数据来源变化

| 值 | Before | After |
|---|---|---|
| 是否登录 | zustand `isLoggedIn` + server session（双重） | 仅 server session（`useSessionMode`） |
| 当前 scope tenantId | legacy form 用户输入 → `adminStore.tenantId` | `useSessionMode().data.tenant_id` → sync effect → `adminStore.setTenantId()` |
| AvatarMenu 展示的 tenant | zustand | zustand（值由 sync effect 更新） |
| Wizard tenantId seed | zustand（用户登录时填的） | zustand（master session 下是 null，wizard 已有 `'default'` fallback） |

**Section 1 已用户确认。**

## 待讨论的剩余设计节（恢复 brainstorm 时继续）

### Section 2 · 具体组件改动（待讨论）
- MasterLayout 的 import 清单
- adminStore 接口变更（增 `setTenantId`，删 `isLoggedIn` + `login`，修改 `logout` 行为？）
- App.tsx / ModeDispatch 加 sync effect 的位置 & 写法
- AvatarMenu.handleLogout 的新行为（是否仍调 `logout()` 清 wizard state？）
- legacy i18n key 处理（`admin.login.tenant_id` 是否还有人用？）

### Section 3 · 测试改动清单（待讨论）
需要删除 / 调整的测试文件（scan 已有结果）：

**删除**：
- `frontend/apps/admin-portal/src/__tests__/LoginPage.test.tsx`

**修改**（去掉 `isLoggedIn: true` setup）：
- `frontend/apps/admin-portal/src/__tests__/MasterLayout.test.tsx`
- `frontend/apps/admin-portal/src/__tests__/AdminRail.test.tsx`
- `frontend/apps/admin-portal/src/__tests__/AdminTopbar.test.tsx`
- `frontend/apps/admin-portal/src/__tests__/AvatarMenu.test.tsx`
- `frontend/apps/admin-portal/src/__tests__/AdminWorkspace.test.tsx`
- `frontend/apps/admin-portal/src/__tests__/TenantLayout.test.tsx`
- `frontend/apps/admin-portal/src/__tests__/InlineWidget.test.tsx`
- `frontend/apps/admin-portal/src/__tests__/adminStore.test.ts`（删 login/isLoggedIn 测例）
- `frontend/apps/admin-portal/src/__tests__/integration.test.tsx`（去掉 legacy login dance）

**新增测试**：
- ModeDispatch / App.tsx：session.tenant_id 同步到 adminStore 的 effect
- adminStore：新 `setTenantId` action 的 TC

### Section 4 · 错误处理 & 边缘情况（待讨论）
- master session（tenant_id=null）下 wizard seed = null 的行为是否可接受
- logout 时要不要 reset wizard / notifications（现有 `logout()` 这么做的）
- AuthGate 已有 error splash，不需要改

### Section 5 · 实施顺序（TDD，待讨论）
大致：
1. 先写/改测试让 MasterLayout 不依赖 `isLoggedIn`（red）
2. 删 MasterLayout gate（green）
3. 给 adminStore 加 `setTenantId`，在 App.tsx sync（red → green）
4. 删 legacy LoginPage + 它的测试
5. 删 zustand `isLoggedIn` + `login`，调其他测试的 setup
6. AvatarMenu.handleLogout 调整
7. 清 legacy i18n key（如果确认无引用）

## 恢复点

**下一步**：恢复 brainstorm 时从 Section 2（具体组件改动）开始，确认每个细节后写最终 spec，然后交给 writing-plans 生成实施 plan。

---

*This is a WIP brainstorm snapshot, not a finalized spec. Sections 2–5 need to be aligned with the user before this document becomes implementation-ready.*
