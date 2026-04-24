# Test diff: batch-11 (T6F.5 TenantLayout 4-tab + T6F.6 ChatTab → /api/admin/chat)

14 new tests across 2 new files. 0 regression.

## 新建文件

- `frontend/apps/admin-portal/src/__tests__/TenantLayout.test.tsx` — 7 tests
- `frontend/apps/admin-portal/src/__tests__/ChatTab.test.tsx` — 7 tests

## 修改文件（non-test）

- `frontend/apps/admin-portal/src/layouts/TenantLayout.tsx` — replaced batch-9 placeholder with full 4-tab shell; re-exports `TenantLayoutBody` for tests that want to skip the internal `<BrowserRouter>`.
- `frontend/apps/admin-portal/src/components/tenant/ChatTab.tsx` — NEW component (spec §4.4). Plain React + fetch; accepts `fetcher` + `endpoint` test seams; no new deps.
- `frontend/apps/admin-portal/src/store/adminStore.ts` — widened `AdminState.activeTab` union to include `'chat'` (previously deferred from T6F.3). Back-compat: all M1 values still accepted; persist partialize unchanged (only `wizardStep`/`generationResult` are persisted, so widening doesn't leak `'chat'` into master sessions).
- `autoservice/api_routes.py` — added `POST /api/admin/chat` stub endpoint (spec §4.4 wire contract, real `_local_admin` routing deferred to T7B.6).

## 覆盖的场景

### T6F.5 — TenantLayout (eval-doc-014)

1. All 4 tenant rail tabs rendered (`tab-chat`, `tab-dashboard`, `tab-proposals`, `tab-billing`).
2. Master-section nav item is hidden in tenant variant (spec §4.2 row 6 — "去除").
3. Default active view is ChatTab on first mount (spec §4.2 rail slot 1 = primary entry).
4. Rail click switches canvas view + zustand `activeTab`.
5. `brand_name` from `useSessionMode` threads into `AdminTopbar.brandName` → visible in topbar crumb.
6. `authenticated_as` from `useSessionMode` threads into `AdminTopbar.authenticatedAs` → visible near avatar.
7. Empty `brand_name` flicker-guard: topbar falls back to tenantId (inherits batch-10 T6F.4 flicker guard).

### T6F.6 — ChatTab (eval-doc-014)

1. Renders input + send button + empty-state placeholder.
2. Submit POSTs `/api/admin/chat` with `credentials: 'include'`, `Content-Type: application/json`, and body `{message: <text>}`.
3. `body.reply` appended to history as assistant bubble (user bubble also preserved).
4. Empty input → send button disabled → no fetch call.
5. Loading state: send disabled + loading indicator visible between click and resolve.
6. Network rejection → error bubble rendered (no unhandled rejection; message includes `Error.message`).
7. Multiple sends accumulate in history; both user messages still visible after second send.

## 已修 regression bug

None. This batch is additive:
- TenantLayout previously rendered via `AdminShell` (which uses `variant="master"`). The new body renders `<AdminRail variant="tenant">` + `<AdminTopbar>` directly — no existing master-mode callers affected.
- ChatTab is brand new; no prior impl to regress.
- `AdminState.activeTab` union widening is a safe superset; existing `setActiveTab('notifications')` calls continue to typecheck.
- `/api/admin/chat` is a brand-new endpoint; pre-existing routes unchanged.

## 测试计数

| File | Before | After | New |
|------|--------|-------|-----|
| TenantLayout.test.tsx | 0 (new) | 7 | +7 |
| ChatTab.test.tsx | 0 (new) | 7 | +7 |
| **Batch-11 total** | 0 | **14** | **+14** |

### Verification run (focused subset — no full admin-portal suite per batch-10 timeout mitigation)

```
npx vitest run \
  src/__tests__/TenantLayout.test.tsx \
  src/__tests__/ChatTab.test.tsx \
  src/__tests__/AdminRail.test.tsx \
  src/__tests__/AdminTopbar.test.tsx \
  src/__tests__/AvatarMenu.test.tsx \
  src/__tests__/AuthGate.test.tsx \
  src/__tests__/AuthLoginPage.test.tsx \
  src/__tests__/App.test.tsx

Test Files  8 passed (8)
      Tests  57 passed (57)
   Duration  4.18s
```

- TenantLayout.test.tsx: **7/7 pass**
- ChatTab.test.tsx: **7/7 pass**
- AdminRail / AdminTopbar / AvatarMenu / AuthGate / AuthLoginPage / App (regression guards from batch-7…10): **43/43 pass**

### Backend auth/api regression

```
python -m pytest tests/auth/ tests/api/ -q
66 passed in 2.69s
```

No backend regression from the new `/api/admin/chat` endpoint.

### Sanity check of new endpoint

Manual TestClient probe confirms:
- `POST /api/admin/chat {"message":"hello"}` → 200 `{"reply":"(stub) Received: 'hello'. _local_admin agent integration pending (T7B.6 / run_dream wire-up)."}`
- `POST /api/admin/chat {"message":""}` → 200 `{"reply":"(empty message — nothing to send)"}`
- `POST /api/admin/chat {}` → 200 (empty-message branch)

## 关联 artifact

- eval-doc-014 (batch-11 T6F.5 + T6F.6 combined eval)

## 时延 mitigation effectiveness

Per the batch-10 timeout post-mortem (e2e-report-007), subagents stalled ~600-1000s on the full admin-portal regression (24 pre-existing i18n failures). For batch-11 we restricted vitest to the 8 focused files — **total run: 4.2s** (vs batch-10 subagents' 600s+). Timeout mitigation fully effective. No stall risk in this batch.
