# Eval Doc: T6D.5 — 时间切片选择器

> **Mode**: simulate (Phase 1 — pre-implementation exploration)
> **Task**: T6D.5 | **Gap**: MISS-04 | **Story**: US-3.1
> **Date**: 2026-04-17 | **Author**: DevA

---

## 1. Feature Summary

运营仪表盘缺少时间维度筛选。当前 `/api/sla/summary` 硬编码返回 `WindowSize.FIVE_MIN`（最近 5 分钟）的 P50/P95 数据，管理员无法查看更长时间跨度的 SLA 指标。

**目标**: 后端增加 `period` 查询参数，前端 Dashboard 顶部添加时间切换 Tabs，让管理员可在不同时间窗口间切换查看 SLA 指标。

---

## 2. Expected Behavior

### 2.1 Backend: `/api/sla/summary?period=<value>`

| period 值 | 映射 WindowSize | 含义 |
|---|---|---|
| `5m` (默认) | `FIVE_MIN` | 最近 5 分钟 |
| `1h` | `ONE_HOUR` | 最近 1 小时 |
| `24h` | `TWENTY_FOUR_HOUR` | 最近 24 小时 |

- 不传 `period` 参数时，默认 `5m`（保持向后兼容）
- 传入无效值时返回 400 错误
- 响应结构不变，仍是 `{metric_name: {p50, p95, count, min, max}}`

**设计决策**: 任务定义提到 `today/week/month/quarter`，但 SLA aggregator 的 ring buffer 只支持 `5m/1h/24h` 三种预计算窗口。扩展到 week/month/quarter 需要持久化存储（当前为纯内存 ring buffer），属于架构变更，超出本任务范围。因此本任务直接暴露现有三种窗口作为 period 选项，这是务实且一致的选择。

### 2.2 Frontend: DashboardTab 时间选择 Tabs

- Dashboard 顶部（Agent 状态卡片之上或之间）添加 3 个 Tab 按钮：`近5分钟` / `近1小时` / `近24小时`
- 默认选中 `近5分钟`
- 切换 Tab 后重新请求 `/api/sla/summary?period=<value>`
- 切换时显示 loading 状态
- 选中态样式与 TakeoverTrendChart 的 period 按钮保持一致

### 2.3 影响范围

- TakeoverTrendChart 和 LeaderboardTable **不受** period 参数影响（它们有各自的时间维度）
- 仅 SLA 指标区域（核心计费指标 + 辅助运营指标）随 period 切换刷新

---

## 3. Files to Modify

| File | Action | Change |
|---|---|---|
| `autoservice/api_routes.py` | modify | `sla_summary()` 增加 `period: str = "5m"` 参数，映射到 `WindowSize`，校验无效值 |
| `frontend/apps/admin-portal/src/components/DashboardTab.tsx` | modify | 添加 period state + Tab UI + 依赖 period 的 useEffect 重新 fetch |

---

## 4. Acceptance Criteria

| # | 验收条件 | 验证方式 |
|---|---|---|
| AC-1 | `/api/sla/summary` 无参数返回 5m 数据（向后兼容） | curl 或 E2E |
| AC-2 | `/api/sla/summary?period=1h` 返回 1h 窗口数据 | curl 或 E2E |
| AC-3 | `/api/sla/summary?period=invalid` 返回 400 | curl 或 E2E |
| AC-4 | 前端默认选中"近5分钟" Tab | 手工/E2E |
| AC-5 | 切换到"近1小时" Tab 后数据刷新（count 数值变化） | 手工/E2E |
| AC-6 | Tab 样式与 TakeoverTrendChart 按钮风格一致 | 目视 |

---

## 5. Design Decisions & Trade-offs

| 决策 | 选择 | 理由 |
|---|---|---|
| Period 值命名 | `5m/1h/24h`（与 WindowSize 枚举一致） | 避免引入额外映射层；前端也用相同值 |
| 不支持 week/month/quarter | 是 | Ring buffer 无持久化，超出本任务范围 |
| Tab 位置 | KPI 区域上方 | 影响范围最小，逻辑清晰 |
| 参数校验 | FastAPI Query + 枚举映射 | 利用框架能力，代码最少 |

---

## 6. Risk Assessment

| 风险 | 等级 | 缓解 |
|---|---|---|
| period 参数命名与任务定义 (today/week/month/quarter) 不一致 | 低 | ring buffer 只有 3 窗口，暴露真实能力更诚实；未来可扩展 |
| ring buffer 24h 窗口数据量大导致 P95 计算慢 | 低 | 当前 `get_percentiles` 用排序数组 + bisect，性能 OK |
| 前端多次快速切换导致竞态 | 低 | useEffect 依赖 period，React 自然处理；可选加 AbortController |

---

## 7. Estimated Effort

~50 行代码变更（后端 ~15 行，前端 ~35 行）。属于 small 任务。
