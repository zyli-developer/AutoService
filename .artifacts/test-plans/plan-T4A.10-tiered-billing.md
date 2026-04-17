---
type: test-plan
id: test-plan-T4A.10
status: draft
producer: skill-2
created_at: "2026-04-16T18:10:00Z"
trigger: "eval-doc eval-T4A.10 confirmed — T4A.10 阶梯计费 billing.py"
related:
  - eval-T4A.10
---

# Test Plan: T4A.10 阶梯计费 billing.py

## 触发原因

基于 eval-doc `eval-T4A.10` 的 12 个 testcase 生成。T4A.10 实现阶梯价格计算引擎，依赖 T4A.9 `billing_metrics.py` 的 `MetricSnapshot`。

## 测试文件

| 文件 | 说明 |
|---|---|
| `tests/test_billing.py` | 阶梯计费模块全部测试 |

## 用例列表

### P0 — 核心功能（4 cases）

#### TC-001: 基础阶梯计算 — 单档
- **来源**: eval-doc TC-1
- **前置条件**: 单档阶梯配置 `[{min:0, max:100, unit_price:10}]`；`BillingMetrics` 实例 takeover_count=50 且已 close_month("2026-04")
- **操作步骤**:
  1. 创建 `TieredBilling` 实例，传入单档阶梯配置
  2. 调用 `generate_bill(metrics, "2026-04")`
- **预期结果**:
  - `bill["total"]` == `Decimal("500")`
  - `bill["line_items"]` 长度为 1
  - `bill["line_items"][0]` 包含 `tier="0-100"`, `quantity=50`, `unit_price=Decimal("10")`, `amount=Decimal("500")`
  - `bill["status"]` == `"final"`
- **涉及模块**: `autoservice/billing.py`, `autoservice/billing_metrics.py`

#### TC-002: 多档阶梯 — 跨档累进
- **来源**: eval-doc TC-2
- **前置条件**: 三档阶梯配置 `[{0,100,10}, {101,500,8}, {501,None,5}]`；takeover_count=250，已 close_month
- **操作步骤**:
  1. 创建 `TieredBilling` 实例，传入三档配置
  2. 调用 `generate_bill(metrics, "2026-04")`
- **预期结果**:
  - `bill["total"]` == `Decimal("2200")` (100×10 + 150×8)
  - `bill["line_items"]` 长度为 2（第三档 qty=0 不出现）
  - line_items[0]: tier="0-100", qty=100, amount=1000
  - line_items[1]: tier="101-500", qty=150, amount=1200
- **涉及模块**: `autoservice/billing.py`

#### TC-003: 零接管 — 空账单
- **来源**: eval-doc TC-3
- **前置条件**: takeover_count=0，已 close_month
- **操作步骤**:
  1. 调用 `generate_bill(metrics, "2026-04")`
- **预期结果**:
  - `bill["total"]` == `Decimal("0")`
  - `bill["line_items"]` 为空列表
  - `bill["status"]` == `"zero_usage"`
- **涉及模块**: `autoservice/billing.py`

#### TC-004: 账单包含指标快照
- **来源**: eval-doc TC-4
- **前置条件**: takeover=80, csat_avg=4.3, escalation_resolution_rate=91.5；已 close_month
- **操作步骤**:
  1. 调用 `generate_bill(metrics, "2026-04")`
- **预期结果**:
  - `bill["metrics_snapshot"]` 存在
  - `bill["metrics_snapshot"]["takeover_count"]` == 80
  - `bill["metrics_snapshot"]["csat"]["average"]` == 4.3
  - `bill["metrics_snapshot"]["escalation"]["resolution_rate"]` == 91.5
- **涉及模块**: `autoservice/billing.py`, `autoservice/billing_metrics.py`

### P1 — 重要场景（6 cases）

#### TC-005: 未关月生成临时账单
- **来源**: eval-doc TC-5
- **前置条件**: 当月数据已录入但未调用 `close_month()`
- **操作步骤**:
  1. 调用 `generate_bill(metrics, "2026-04")`
- **预期结果**:
  - 账单正常生成（使用 live snapshot）
  - `bill["status"]` == `"provisional"`
- **涉及模块**: `autoservice/billing.py`

#### TC-006: 阶梯配置为空 — 异常
- **来源**: eval-doc TC-6
- **前置条件**: tiers=[]
- **操作步骤**:
  1. 创建 `TieredBilling(tiers=[])`
- **预期结果**:
  - 抛出 `BillingConfigError`，消息含 "empty"
- **涉及模块**: `autoservice/billing.py`

#### TC-007: 阶梯配置间隙检测
- **来源**: eval-doc TC-7
- **前置条件**: tiers=[{0,50,10}, {100,200,8}]（51-99 缺失）
- **操作步骤**:
  1. 创建 `TieredBilling(tiers=...)`
- **预期结果**:
  - 抛出 `BillingConfigError`，消息含 "gap" 及间隙范围信息
- **涉及模块**: `autoservice/billing.py`

#### TC-008: 超大量 — 最高档无上限
- **来源**: eval-doc TC-8
- **前置条件**: 三档配置最高档 max=None；takeover_count=99999
- **操作步骤**:
  1. 调用 `generate_bill(metrics, "2026-04")`
- **预期结果**:
  - 正确计算：100×10 + 400×8 + 99499×5 = 1000 + 3200 + 497495 = 501695
  - line_items 含 3 条明细
- **涉及模块**: `autoservice/billing.py`

#### TC-009: 多租户隔离
- **来源**: eval-doc TC-9
- **前置条件**: 租户 A（takeover=50, 单档配置）和 租户 B（takeover=200, 三档配置），各自独立的 BillingMetrics 实例
- **操作步骤**:
  1. 为 A 生成账单
  2. 为 B 生成账单
- **预期结果**:
  - 两份账单独立，A.total=500, B.total 按三档计算
  - 修改 A 的配置不影响 B
- **涉及模块**: `autoservice/billing.py`

#### TC-010: 账单 JSON 序列化
- **来源**: eval-doc TC-12
- **前置条件**: 正常生成账单后
- **操作步骤**:
  1. 调用 `bill.to_json()` 或 `json.dumps(bill_dict)`
- **预期结果**:
  - 返回合法 JSON 字符串
  - Decimal 字段序列化为字符串（如 `"500.00"`）
  - `json.loads()` 可还原
- **涉及模块**: `autoservice/billing.py`

### P2 — 扩展性验证（2 cases）

#### TC-011: Decimal 精度验证
- **来源**: eval-doc TC-10
- **前置条件**: unit_price=Decimal("0.03"), takeover_count=33333
- **操作步骤**:
  1. 调用 `generate_bill(metrics, "2026-04")`
- **预期结果**:
  - `bill["total"]` == `Decimal("999.99")`（精确，无浮点误差）
- **涉及模块**: `autoservice/billing.py`

#### TC-012: Strategy Protocol 接口定义
- **来源**: eval-doc TC-11
- **前置条件**: 定义 `BillingStrategy` Protocol
- **操作步骤**:
  1. 验证 `TieredBilling` 满足 `BillingStrategy` Protocol
  2. 验证 Protocol 定义了 `calculate(takeover_count) -> BillResult` 签名
- **预期结果**:
  - `isinstance` 检查通过（runtime_checkable Protocol）
  - Protocol 有 `calculate` 方法签名
- **涉及模块**: `autoservice/billing.py`

## 统计

| 维度 | 数量 |
|---|---|
| 总用例数 | 12 |
| P0（核心） | 4 |
| P1（重要） | 6 |
| P2（扩展） | 2 |
| 来源：eval-doc | 12 |
| 涉及模块 | autoservice/billing.py, autoservice/billing_metrics.py |

## 风险标注

| 区域 | 风险等级 | 说明 |
|---|---|---|
| 阶梯累进计算逻辑 | 高 | 核心计费，差一分钱都是 bug，TC-001/002/008 重点覆盖 |
| Decimal 精度 | 中 | 财务场景不容许浮点误差，TC-011 验证 |
| 配置校验 | 中 | 间隙/重叠/空配置需防御，TC-006/007 覆盖 |
| Strategy 扩展性 | 低 | 本期只验证接口定义，TC-012 |
