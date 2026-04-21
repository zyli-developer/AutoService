# Eval: t6f-3 AdminRail variant prop (master vs tenant icon sets)

**Spec**: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) §4.2 Rail 图标集
**Task**: T6F.3 — AdminRail accepts a `variant` prop selecting master (current) or tenant (4-tab subset) icon set.
**Batch**: batch-10 · Green · small · parallel with T6F.4 (different files).
**Related**: eval-doc-011 (batch-9 shell hooks — established `useSessionMode`/`useTenantId` contract consumed by the caller that picks the variant).

## 预期行为

### Props contract (additive, backward-compatible)

- Add `variant?: "master" | "tenant"` to `AdminRailProps`; default `"master"` preserves M1 behavior.
- All existing props (`open`, `onClose`, `hideMasterSection`, `tenantIdOverride`) continue to work unchanged.
- Callers that pass no `variant` render the existing rail exactly as today (zero regression).

### Master variant (default — existing)

- Renders current 4 nav items: `notifications`, `dashboard`, `proposals`, `billing` (the legacy `wizard` entry was already removed in a prior batch; do NOT re-add).
- Preserves the two-section layout (`admin.nav.section.ops` / `admin.nav.section.config`).
- Preserves the Master-section entry (`tab-master-tenants`) with `hideMasterSection` override respected.
- Active-item highlight (`.active` class + `aria-current="page"`) driven by `useAdminStore.activeTab`, unchanged.

### Tenant variant (new — spec §4.2)

- Renders exactly **4 tabs** matching spec §4.2 rows 1/2/4/5 (rows 3 "Wizard" and 6 "Tenants 列表" are explicitly "去除" in tenant):
  1. **Chat** — `admin.nav.tenant.chat` — route `/admin/chat` (reuses ChatIcon)
  2. **Dashboard** — `admin.nav.tenant.dashboard` — route `/admin/dashboard` (reuses DashIcon)
  3. **Proposals** — `admin.nav.tenant.proposals` — route `/admin/proposals` (reuses BulbIcon)
  4. **Billing** — `admin.nav.tenant.billing` — route `/admin/billing` (reuses CardIcon)
- In tenant variant, the Master section (`tab-master-tenants`) is **always suppressed** (spec §4.2 row 6 "去除"), regardless of `hideMasterSection` value.
- Workspace brand strip + usage card remain visible (they're layout chrome, not variant-scoped).

### Declarative config map pattern (CON invariant)

- One `RAIL_CONFIG: Record<RailVariant, RailItem[]>` structure at module scope.
- Component body picks `const items = RAIL_CONFIG[variant]` and maps to `<li>` elements.
- **No** variant-branching JSX (no `variant === "master" ? <X/> : <Y/>` in the tree); branching lives purely in the data lookup.

## 验收标准

Extend existing `__tests__/AdminRail.test.tsx`. All existing 7 tests remain green (back-compat proof).

### New tests (~4)

1. `test_default_variant_is_master_and_renders_existing_icons` — rendering without `variant` shows `tab-notifications` / `tab-dashboard` / `tab-proposals` / `tab-billing` (same 4 items as today's baseline test, expressed as a variant default assertion).
2. `test_tenant_variant_renders_4_tab_icons` — `<AdminRail variant="tenant" />` renders 4 testids: `tab-chat`, `tab-dashboard`, `tab-proposals`, `tab-billing`. Master-section testid `tab-master-tenants` is absent; legacy master-only items like `tab-notifications` (master key) are also absent (tenant uses `tab-chat` instead per spec row-1).
3. `test_tenant_variant_labels_match_spec` — each tenant item text matches the spec §4.2 label (accept resolved CN/EN labels or unresolved i18n key, using the same `toMatch(/.../)` pattern as existing tests since i18n is not initialized in the test env).
4. `test_variant_switch_preserves_active_highlight_behavior` — in tenant variant, clicking `tab-dashboard` sets `useAdminStore.activeTab` and applies `.active` class; back-compat with master variant's highlight logic.

### Regression

- 7 existing tests in `AdminRail.test.tsx` stay green (default variant path is unchanged).
- No other test file edited by this task.

## 关键 invariant

- **CON — declarative config map (not JSX branching)**: `RAIL_CONFIG` is the single source of truth. Tests MAY verify the config shape indirectly via rendered testids; JSX must iterate `RAIL_CONFIG[variant]` and nothing else.
- **CON — additive props**: `variant?: "master" | "tenant" = "master"`. All callers without the prop see zero behavior change. This is the safety net for T6F.4 / T6F.5 which land in the same batch-10 without touching AdminRail.
- **CON — spec §4.2 tenant row-3 & row-6 removal**: tenant variant MUST NOT render `wizard` (already deleted project-wide) nor the Master-section `tab-master-tenants`; `hideMasterSection` is effectively forced-true for tenant variant.
- **CON-03 tech stack**: no new deps. Reuse existing inline SVG icons already defined in AdminRail (ChatIcon / DashIcon / BulbIcon / CardIcon). No `lucide-react` / `heroicons` addition.
- **i18n test invariant**: admin-portal tests run without i18n init; tenant labels use new keys under `admin.nav.tenant.*` but tests use `toMatch(/key|cn|en/)` so they stay green even if keys are unresolved (same pattern as existing `tab-master-tenants` assertion).
- **No store coupling for variant**: `variant` is prop-driven, not read from `useAdminStore`. The caller (TenantLayout in T6F.5, MasterLayout for master) decides. This keeps the rail stateless w.r.t. mode and avoids a cross-cutting store dependency.

## Spec decisions

- **Icon reuse**: tenant variant reuses the 4 existing inline SVG icons (ChatIcon, DashIcon, BulbIcon, CardIcon). Spec §4.2 uses emoji placeholders (🗨 📊 💡 💳) — we map to the existing SVG set for visual consistency with master rail; no new SVG assets needed.
- **Tenant key IDs**: tenant nav keys use `chat` / `dashboard` / `proposals` / `billing` (not `notifications` / `chat-tenant` / etc.) so the testid namespace is clean and callers don't confuse master's `notifications` (→ `_master` management chat) with tenant's `chat` (→ `_local_admin` ChatTab per spec §4.4).
- **Routing**: `to` routes in the config map are declarative — current M1 rail does not navigate on click (it flips `activeTab` in the store). T6F.3 keeps the same click-dispatch for master variant and adds a similar store-driven behavior for tenant variant; actual router navigation to `/admin/chat` etc. is T6F.5's wiring (TenantLayout owns the tab switcher). For T6F.3, `to` is stored in the config for forward-compat but unused at click-time (same as today).
- **`hideMasterSection` vs tenant variant**: tenant variant ignores `hideMasterSection` (always hides Master section). `hideMasterSection` keeps its M1 semantics for master variant only.

## Evidence

| Artifact | Location |
|----------|----------|
| Rail impl | `frontend/apps/admin-portal/src/components/shell/AdminRail.tsx` |
| Tests | `frontend/apps/admin-portal/src/__tests__/AdminRail.test.tsx` |
| Task status row | [docs/plans/m2/task-status.md](../../docs/plans/m2/task-status.md) Phase 6 — T6F.3 |
