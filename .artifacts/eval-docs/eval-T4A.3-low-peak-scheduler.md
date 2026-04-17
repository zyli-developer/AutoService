---
type: eval-doc
id: eval-T4A.3
status: draft
producer: skill-5
created_at: 2026-04-16
mode: simulate
feature: "T4A.3 低峰检测调度器"
submitter: DevA
related:
  - eval-doc-004
---

# Eval: T4A.3 低峰检测调度器

## 基本信息
- 模式：模拟（simulate）
- 提交人：DevA
- 日期：2026-04-16
- 状态：draft

## Feature 描述

Dream Engine 的低峰检测调度器，在系统空闲时触发对话回放（memory_pool 中的历史对话），生成改进提案。

**核心逻辑**: 每 30 分钟计算 QPS 均值，当 QPS < 20% 峰值时判定为"低峰"，触发回放任务。

### 依赖
- **MetricsPlugin (T1A.8)**: 读取 `messages_sent` 作为流量指标
- **SLAAggregator (T2A.3)**: 可选，读取 5m 窗口数据判断实时负载
- **memory_pool (T4A.1)**: 回放目标（下游消费者），调度器只负责触发

### 新增文件
| 文件 | 说明 |
|---|---|
| `autoservice/low_peak_scheduler.py` | LowPeakScheduler 类 |
| `tests/test_low_peak_scheduler.py` | 测试 |

### 设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| QPS 采样方式 | 30 分钟滑动窗口 | PRD 指定 30 分钟均值 |
| 峰值基准 | 过去 24h 最高 30 分钟均值 | 自适应，无需手动配置 |
| 低峰阈值 | 均值 < 峰值 × 20% | PRD 指定 <20% |
| 调度周期 | asyncio 定时器，每 5 分钟检查一次 | 平衡响应速度和 CPU |
| 回调机制 | 注册 callback（async callable） | 解耦调度器和回放逻辑 |
| 冷启动 | 前 30 分钟不触发（无足够数据） | 避免误判 |

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|---------|---------|--------|
| 1 | 导入和实例化 | 无 | `from autoservice.low_peak_scheduler import LowPeakScheduler; s = LowPeakScheduler()` | 实例化成功 | 新建文件，直接构造 | 无 | P0 |
| 2 | 记录 QPS 样本 | scheduler 已创建 | `scheduler.record_sample(qps=50, timestamp=t)` 多次调用 | 内部窗口存储样本 | deque 滑动窗口存储 (timestamp, qps) | 无 | P0 |
| 3 | 计算 30 分钟均值 | 已记录 30 分钟内 6 个样本 | `scheduler.current_avg()` | 返回 30 分钟内样本均值 | sum(qps) / count，只算窗口内的 | 无 | P0 |
| 4 | 过期样本自动清理 | 有 >30 分钟前的样本 | 记录新样本后 `current_avg()` | 旧样本不参与计算 | deque 按时间戳过滤 | 无 | P1 |
| 5 | 峰值跟踪（24h） | 已记录多个 30 分钟周期 | `scheduler.peak_qps` | 返回过去 24h 最高均值 | 维护 rolling max | 无 | P0 |
| 6 | 低峰判定 — 触发 | peak=100, 当前均值=15 (<20%) | `scheduler.is_low_peak()` | 返回 True | 15 < 100*0.2=20 → True | 无 | P0 |
| 7 | 低峰判定 — 不触发 | peak=100, 当前均值=25 (>20%) | `scheduler.is_low_peak()` | 返回 False | 25 >= 20 → False | 无 | P0 |
| 8 | 低峰判定 — 零流量 | peak=100, 当前均值=0 | `scheduler.is_low_peak()` | 返回 True | 0 < 20 → True | 无 | P1 |
| 9 | 冷启动保护 | 不到 30 分钟的数据 | `scheduler.is_low_peak()` | 返回 False（数据不足） | 样本数 < 最小要求 → False | 无 | P0 |
| 10 | 回调注册和触发 | 注册了 async callback | 低峰检测到 | callback 被调用 | `scheduler.on_low_peak(callback)` 注册，触发时 await | 无 | P0 |
| 11 | 回调不重复触发 | 已在低峰期触发过 | 连续两次 check 都是低峰 | 只触发一次，直到恢复高峰后再次低峰 | 内部 `_triggered` 标志，高峰时重置 | 无 | P0 |
| 12 | 高峰恢复重置 | 低峰已触发，流量恢复 | QPS 恢复到 >20% | `_triggered` 重置，下次低峰可再触发 | 检测到非低峰时 reset flag | 无 | P1 |
| 13 | 阈值可配置 | 自定义阈值 0.3 | `LowPeakScheduler(threshold=0.3)` | 30% 作为阈值 | 构造参数覆盖默认 0.2 | 无 | P1 |
| 14 | 窗口大小可配置 | 自定义窗口 15 分钟 | `LowPeakScheduler(window_minutes=15)` | 15 分钟均值计算 | 构造参数覆盖默认 30 | 无 | P1 |
| 15 | 与 MetricsPlugin 集成 | MetricsPlugin 已注册 | 消息到来时 metrics.messages_sent 增加 | scheduler 可从 metrics 读取 QPS | scheduler.record_from_metrics(metrics) 便利方法 | 设计选择 | P1 |

## 风险分析

- **低风险**：纯计算逻辑，无外部依赖，不影响核心对话流程
- **集成点**：与 T4A.4（提案生成 pipeline）通过回调接口连接，回调签名需稳定

## 后续行动

- [ ] eval-doc 已注册到 .artifacts/eval-docs/
- [ ] 用户已确认 testcase 表格 (status: draft → confirmed)
