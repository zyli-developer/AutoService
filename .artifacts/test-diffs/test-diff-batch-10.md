# Test diff: batch-10 (T6F.3 AdminRail variant + T6F.4 AdminTopbar/AvatarMenu)

新增/扩展 27 tests across 3 files (AdminRail +~10 / AdminTopbar +4 / AvatarMenu +3 logout integration).

## 修改文件

- `frontend/apps/admin-portal/src/__tests__/AdminRail.test.tsx` — +92 lines (T6F.3 variant tests: renderRailVariant helper, master/tenant icon sets, legacy wizard-tab removed, labels vocabulary)
- `frontend/apps/admin-portal/src/__tests__/AdminTopbar.test.tsx` — +4 tests (T6F.4 brandName + authenticatedAs props, empty-string flicker guard)
- `frontend/apps/admin-portal/src/__tests__/AvatarMenu.test.tsx` — +3 tests (T6F.4 logout flow: fetch POST /api/auth/logout, redirect to /login, network-error best-effort path)

## 覆盖的场景

### T6F.3 (eval-doc-012)
- master variant renders default icon set
- tenant variant renders Dashboard/Proposals/Billing/Chat icon set
- variant switch preserves active-highlight behavior
- legacy "tab-wizard" removed (moved to TenantListTab's 新建租户 button)

### T6F.4 (eval-doc-013)
- AdminTopbar.brandName replaces tenant crumb when provided; empty string is flicker-guarded to fall back to tenantId
- AdminTopbar.authenticatedAs renders `Signed in as <email>` inline near the avatar (data-testid=`topbar-authed-as`); empty string renders nothing
- AvatarMenu btn-logout POSTs /api/auth/logout with `credentials: "include"`
- Logout redirects to /login via injected `redirector` prop (test seam matching batch-9 AuthGate)
- Network error does NOT block redirect — best-effort logout (cookie is HttpOnly; backend revokes server-side)

## 已修 regression bug

None. Both T6F.3 and T6F.4 are additive:
- AdminRail keeps `variant="master"` as default → pre-existing tests pass unchanged
- AdminTopbar's new props are optional with empty-string falsy → pre-existing tests pass unchanged
- AvatarMenu's zustand `logout()` kept for M1 legacy tests; new fetch is a layer above

## 测试计数

| File | Before | After | New |
|------|--------|-------|-----|
| AdminRail.test.tsx | ~4 | ~14 | +10 |
| AdminTopbar.test.tsx | 4 | 8 | +4 |
| AvatarMenu.test.tsx | 4 | 7 | +3 |
| **Batch-10 total** | 12 | **29** | **+17** |

Pre-existing i18n baseline unchanged: 112 pass / 24 fail in admin-portal (same 9 files as batch-9 baseline — NOT caused by batch-10).

## 关联 artifact

- eval-doc-012 (T6F.3 AdminRail variant prop)
- eval-doc-013 (T6F.4 AdminTopbar + AvatarMenu ext)
