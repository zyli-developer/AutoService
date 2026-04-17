---
type: test-plan
id: "test-plan-T6D.5"
status: draft
producer: skill-2
created_at: "2026-04-17"
eval_doc: "eval-T6D.5"
feature: "T6D.5 时间切片选择器"
submitter: DevA
---

# Test Plan: T6D.5 时间切片选择器

## 测试策略

- **后端单元测试**: `/api/sla/summary` 的 period 参数解析、窗口映射、无效值 400（pytest）
- **前端组件测试**: DashboardTab 的 Tab 切换 + 数据 refetch（vitest + testing-library/react）
- **环境**: pytest (backend), vitest + jsdom (frontend)

## 测试文件

| 文件 | 覆盖 TCs | 说明 |
|---|---|---|
| `tests/test_sla_summary_api.py` | TC-01~TC-05 | 后端 API period 参数 |
| `frontend/apps/admin-portal/src/__tests__/DashboardTab.period.test.tsx` | TC-06~TC-09 | 前端 Tab 切换 |

## 9 Test Cases

### Backend: /api/sla/summary period 参数

- **TC-01**: 无 period 参数 → 默认返回 5m 窗口数据，响应结构含 7 个指标的 {p50, p95, count, min, max}
- **TC-02**: `period=1h` → 返回 ONE_HOUR 窗口数据，count 可能与 5m 不同
- **TC-03**: `period=24h` → 返回 TWENTY_FOUR_HOUR 窗口数据
- **TC-04**: `period=invalid` → 返回 HTTP 400，body 含错误提示
- **TC-05**: `period=5m` 显式传入 → 等价于无参数默认值

### Frontend: DashboardTab 时间选择 Tabs

- **TC-06**: 初始渲染显示 3 个 Tab 按钮（近5分钟 / 近1小时 / 近24小时），默认选中"近5分钟"
- **TC-07**: 点击"近1小时" Tab → fetch 调用 `/api/sla/summary?period=1h`，数据刷新
- **TC-08**: 点击"近24小时" Tab → fetch 调用 `/api/sla/summary?period=24h`
- **TC-09**: 切换 Tab 后再切回"近5分钟" → fetch 调用 `/api/sla/summary?period=5m`（或无参数）

## 验收对照

| 验收条件 (eval-doc) | 覆盖 TC |
|---|---|
| AC-1: 无参数返回 5m（向后兼容） | TC-01, TC-05 |
| AC-2: `period=1h` 返回 1h 数据 | TC-02 |
| AC-3: `period=invalid` 返回 400 | TC-04 |
| AC-4: 前端默认选中"近5分钟" | TC-06 |
| AC-5: 切换 Tab 后数据刷新 | TC-07, TC-08, TC-09 |
| AC-6: Tab 样式一致 | 目视（不做自动化） |
