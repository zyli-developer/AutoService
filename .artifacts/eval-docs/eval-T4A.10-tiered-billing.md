---
type: eval-doc
id: eval-T4A.10
status: draft
producer: skill-5
created_at: 2026-04-16
mode: simulate
feature: "T4A.10 阶梯计费 billing.py"
submitter: DevA
related:
  - eval-T4A.3
  - eval-T4A.4
---

# Eval: T4A.10 阶梯计费 billing.py

## 基本信息
- 模式：模拟（simulate）
- 提交人：DevA
- 日期：2026-04-16
- 状态：draft

## Feature 描述

基于 T4A.9 `billing_metrics.py` 的 `MetricSnapshot`（takeover_count, CSAT, escalation stats），实现阶梯价格计算引擎，月末生成结构化账单 JSON。

**核心逻辑**: 读取月度 `MetricSnapshot` → 按可配置的阶梯价格表匹配档位 → 计算费用明细 → 输出账单 JSON（供 T4B.3 前端导出 UI 消费）。

### 依赖
- **BillingMetrics (T4A.9)**: 提供 `MetricSnapshot`（takeover_count）和 `close_month()` / `to_billing_json()` 方法
- **PRD δ4**: 阶梯计费计算, 月末账单 JSON
- **PRD Open Q1**: 计费模式（阶梯 vs 订阅+超额）待定价团队 Q3 决定 → 设计需可扩展

### 新增文件
| 文件 | 说明 |
|---|---|
| `autoservice/billing.py` | TieredBilling 类 + BillGenerator |
| `tests/test_billing.py` | 测试 |

### 设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 计费主维度 | takeover_count（接管次数） | PRD ★ 指标明确 "阶梯计费" 以接管次数为主 |
| 阶梯配置方式 | YAML/dict 配置，支持运行时加载 | PRD Open Q1 要求可扩展，定价团队 Q3 前可能调整 |
| 价格表结构 | `List[TierRule]`，每条含 min/max/unit_price | 经典阶梯定价，覆盖累进和分段两种模式 |
| 计费模式抽象 | Strategy pattern（TieredStrategy 为默认） | Q3 可能切换为 订阅+超额，Strategy 便于扩展 |
| 账单输出格式 | JSON dict，包含明细行 + 汇总 + 指标快照 | 供 T4B.3 前端 CSV/PDF 导出消费 |
| 月结触发方式 | 显式调用 `generate_bill(tenant_id, period)` | 与 BillingMetrics.close_month() 配合，不自动触发 |
| 货币/精度 | Decimal 精度，默认 2 位小数，货币可配 | 财务精度要求 |

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|---|---|---|---|---|---|---|
| TC-1 | 基础阶梯计算 — 单档 | 阶梯配置: [{min:0, max:100, unit_price:10}]; 当月 takeover_count=50 | `billing.generate_bill("tenant_a", "2026-04")` | 返回 bill JSON: total=500, line_items=[{tier:"0-100", qty:50, unit:10, amount:500}] | 可实现。从 `BillingMetrics.get_monthly_snapshot("2026-04")` 读 takeover_count=50，匹配单档，计算 50×10=500 | 无差异 | P0 |
| TC-2 | 多档阶梯 — 跨档累进 | 阶梯配置: [{0,100,10}, {101,500,8}, {501,∞,5}]; takeover_count=250 | `billing.generate_bill("tenant_b", "2026-04")` | total = 100×10 + 150×8 = 1000+1200 = 2200; line_items 含 2 条明细 | 可实现。逐档匹配：前 100 次 ×10 = 1000，剩余 150 次 ×8 = 1200，累计 2200。第三档未触及 | 无差异 | P0 |
| TC-3 | 零接管 — 空账单 | takeover_count=0 | `billing.generate_bill("tenant_c", "2026-04")` | total=0, line_items=[], status="zero_usage" | 可实现。takeover_count=0 → 所有档位 qty=0，总金额 0，标记 zero_usage | 无差异 | P0 |
| TC-4 | 账单 JSON 包含指标快照 | takeover=80, csat_avg=4.3, resolution_rate=91.5 | 生成账单 | bill JSON 含 `metrics_snapshot` 字段，嵌入当月 MetricSnapshot 全部字段 | 可实现。调用 `BillingMetrics.to_billing_json(period)` 嵌入 bill 的 metrics_snapshot 字段 | 无差异 | P0 |
| TC-5 | 未关月就生成账单 | 当月数据未调用 close_month() | `billing.generate_bill()` | 使用 live snapshot（get_current_snapshot），bill 标记 status="provisional" | 可实现。检查 `get_monthly_snapshot()` 返回 None 时 fallback 到 live 数据，标 provisional | 无差异 | P1 |
| TC-6 | 阶梯配置为空 | tiers=[] | `billing.generate_bill()` | 抛出 `BillingConfigError` 或返回 error bill | 可实现。配置校验阶段检测空阶梯表，raise 明确异常 | 无差异 | P1 |
| TC-7 | 阶梯配置有间隙/重叠 | tiers=[{0,50,...}, {100,200,...}] (51-99 缺失) | 加载配置 | 配置校验失败，报告间隙位置 | 可实现。validate_tiers() 检查连续性: tier[i].max+1 == tier[i+1].min | 无差异 | P1 |
| TC-8 | 超大量 — 最高档封顶 | tiers 最高档 max=∞; takeover_count=99999 | 生成账单 | 正确计算所有档位累加，最高档吃掉剩余全部量 | 可实现。∞ 用 `None` 或 `float('inf')` 表示上限开放 | 无差异 | P1 |
| TC-9 | 多租户隔离 | 租户 A 和 B 各有独立 BillingMetrics 和阶梯配置 | 分别生成两份账单 | 两份独立 bill，互不影响 | 可实现。BillingMetrics 和 TieredBilling 实例按 tenant 隔离（三层 fork 天然隔离） | 无差异 | P1 |
| TC-10 | 货币精度 — 避免浮点误差 | unit_price=0.03, takeover_count=33333 | 计算费用 | 精确结果 999.99（Decimal），不出现 999.9900000001 | 可实现。内部使用 `Decimal` 运算，最终 `quantize` 到 2 位 | 无差异 | P2 |
| TC-11 | 策略可扩展 — 订阅+超额模式 | 策略切换为 SubscriptionStrategy(base=2000, included=200, overage_price=5) | takeover=250 → base + 50×5 = 2250 | 2250。SubscriptionStrategy 计算 base 费用 + 超出部分 × overage 单价 | 可实现（预留接口），本期只实现 TieredStrategy 默认策略。SubscriptionStrategy 作为 Protocol 留白 | 本期不实现 SubscriptionStrategy，只定义 Protocol 接口 | P2 |
| TC-12 | 账单序列化 — JSON 可导出 | 生成 bill 后 | `json.dumps(bill)` | 所有字段可 JSON 序列化（含 Decimal → str/float 转换） | 可实现。提供 `to_json()` 方法处理 Decimal → str 转换 | 无差异 | P1 |

## 架构可行性分析

### 与现有代码的集成

1. **BillingMetrics (T4A.9)** 已提供完整的三指标追踪和月度快照功能。`billing.py` 只需：
   - 接收 `MetricSnapshot` 或直接调用 `BillingMetrics.get_monthly_snapshot(period)`
   - 从 snapshot 中提取 `takeover_count` 作为计费维度
   - 将 `BillingMetrics.to_billing_json()` 的输出嵌入账单

2. **三层 fork 隔离**：每个租户独立实例，阶梯配置存储在 L3 `plugins/<tenant>/` 的配置中

3. **下游消费者 T4B.3**：前端账单导出 UI 期望 JSON 格式，本模块输出的 dict 结构直接服务

### 风险点

| 风险 | 等级 | 缓解 |
|---|---|---|
| 定价模式 Q3 可能变更 | 中 | Strategy pattern 预留扩展点；本期只实现 TieredStrategy |
| Decimal 精度 vs JSON 序列化 | 低 | to_json() 统一转 str，前端解析 |
| 月结时机与 BillingMetrics.close_month() 协调 | 低 | billing.py 不自动调用 close_month()，由上层编排 |
