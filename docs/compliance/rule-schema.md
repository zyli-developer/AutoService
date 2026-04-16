# 合规规则 Schema v1.0

> T3A.4 产出 | 2026-04-16 | Owner: DevA
> 关联: PRD δ6 / US-1.4 | 下游: T3A.5 (规则 YAML), T3A.7 (compliance.py), T3B.5 (预检 UI)

## 1. 概述

定义 AutoService 合规规则的数据结构。所有预置规则存储在单一 YAML 文件中，供预检引擎 (`compliance.py`) 扫描租户配置并输出风险等级。

- **存储**: `autoservice/compliance/rules.yaml` — 单文件，16 条规则
- **触发机制**: 声明式条件表达式（非代码引用）
- **严重等级**: 4 级 (critical / high / medium / low)
- **阻塞策略**: 三环境独立控制 (sandbox / production / dream_engine)
- **多语言**: 内嵌双语 (en + zh)

## 2. Schema 定义

```yaml
# autoservice/compliance/rules.yaml
# 所有字段除 tags 外均为必填

- rule_id: string           # 唯一标识，格式: <region>-<seq>，如 "eu-01", "cn-03"
  name: string              # 规则名称（英文）
  name_zh: string           # 规则名称（中文）
  region: enum              # 适用地区: EU | US | CN | GLOBAL
  regulation: string        # 法规引用，如 "GDPR Art.13", "PIPL §24"
  severity: enum            # critical | high | medium | low
  trigger:                  # 触发条件（声明式）
    type: enum              #   检查类型: config_check | content_scan | data_flow
    field: string           #   检查目标字段/路径（dot notation，如 "soul.disclosure_enabled"）
    condition: enum         #   匹配条件: must_be_true | must_be_false | must_exist
                            #            | must_not_empty | must_match:<regex>
                            #            | must_contain:<value>
  blocking:                 # 阻塞策略（三环境独立控制）
    sandbox: bool           #   沙箱模式是否阻塞（通常 false）
    production: bool        #   生产模式是否阻塞（critical/high 通常 true）
    dream_engine: bool      #   是否约束 Dream Engine 提案
  description: string       # 规则说明（英文）
  description_zh: string    # 规则说明（中文）
  remediation_doc: string   # 补救指南路径: docs/compliance/<rule_id>.md
  tags: list[string]        # 可选，分类标签，如 ["consent", "disclosure"]
```

## 3. 字段规范

### 3.1 rule_id

格式: `<region>-<seq>`，region 小写，seq 两位数字补零。

| region 前缀 | 数量 | 范围 |
|---|---|---|
| `eu-` | 6 条 | eu-01 ~ eu-06 (GDPR + EU AI Act) |
| `us-` | 4 条 | us-01 ~ us-04 (CCPA + COPPA) |
| `cn-` | 6 条 | cn-01 ~ cn-06 (PIPL + 网信办) |

### 3.2 region

| 值 | 说明 |
|---|---|
| `EU` | 欧盟（GDPR, EU AI Act） |
| `US` | 美国（CCPA, COPPA） |
| `CN` | 中国（PIPL, 网信办规定） |
| `GLOBAL` | 全球通用（预留，v1 暂无） |

### 3.3 severity

| 等级 | 含义 | 前端映射建议 |
|---|---|---|
| `critical` | 违规即不可上线 | 红色 |
| `high` | 高风险，强烈建议修复 | 红色 |
| `medium` | 中风险，建议修复 | 黄色 |
| `low` | 低风险，提示性 | 灰色 |

### 3.4 trigger.type

| 类型 | 说明 | 示例 |
|---|---|---|
| `config_check` | 检查租户配置字段 | soul.disclosure_enabled 必须为 true |
| `content_scan` | 扫描 soul.md / prompt 内容 | 是否包含隐私政策链接 |
| `data_flow` | 检查数据流向配置 | 用户数据是否跨境传输 |

### 3.5 trigger.condition

声明式条件表达式，引擎按类型解析:

| condition | 语义 |
|---|---|
| `must_be_true` | 字段值必须为 true |
| `must_be_false` | 字段值必须为 false |
| `must_exist` | 字段必须存在且非 null |
| `must_not_empty` | 字段必须非空（字符串/列表） |
| `must_match:<regex>` | 字段值匹配正则，如 `must_match:https?://.*privacy` |
| `must_contain:<value>` | 列表字段必须包含指定值 |

### 3.6 blocking

PRD 约束（直接映射）:
- **sandbox**: 沙箱 / 预演模式 — 通常 `false`（不阻塞，允许测试）
- **production**: 对外开放 / 生产模式 — critical/high 通常 `true`（阻塞上线）
- **dream_engine**: Dream Engine 自动提案 — 涉及数据/内容变更的规则设为 `true`（约束自动优化）

## 4. 示例规则

```yaml
- rule_id: eu-01
  name: "Disclosure of AI identity"
  name_zh: "AI 身份披露"
  region: EU
  regulation: "EU AI Act Art.52(1)"
  severity: critical
  trigger:
    type: config_check
    field: "soul.disclosure_enabled"
    condition: "must_be_true"
  blocking:
    sandbox: false
    production: true
    dream_engine: true
  description: "AI systems interacting with users must clearly disclose their AI identity"
  description_zh: "AI 系统与用户交互时必须明确披露 AI 身份"
  remediation_doc: "docs/compliance/eu-01.md"
  tags: ["disclosure", "transparency"]

- rule_id: cn-01
  name: "Real-name registration of AI service provider"
  name_zh: "AI 服务提供者实名备案"
  region: CN
  regulation: "PIPL §24 + 网信办《生成式 AI 管理暂行办法》§7"
  severity: critical
  trigger:
    type: config_check
    field: "tenant.provider_registration_id"
    condition: "must_not_empty"
  blocking:
    sandbox: false
    production: true
    dream_engine: false
  description: "AI service providers must complete real-name registration before going live"
  description_zh: "AI 服务提供者上线前须完成实名备案"
  remediation_doc: "docs/compliance/cn-01.md"
  tags: ["registration", "provider"]
```

## 5. 与现有 rules.py 的关系

| 维度 | `autoservice/rules.py` (行为规则) | `autoservice/compliance/rules.yaml` (合规规则) |
|---|---|---|
| **用途** | 运营层行为指导（如"不要讨论竞品"） | 法规合规预检（如"必须披露 AI 身份"） |
| **管理者** | 租户运营人员，通过 /rules 命令 | 平台预置，admin-portal 向导 Step4 展示 |
| **存储** | `.autoservice/rules/*.yaml` (运行时) | `autoservice/compliance/rules.yaml` (代码库) |
| **消费者** | channel prompt 注入 | `compliance.py` 预检引擎 (T3A.7) |

两者独立，不互相依赖。

## 6. 验收标准

- [ ] schema 文档完整，包含所有必填字段定义
- [ ] 示例规则可被 `yaml.safe_load()` 正常解析
- [ ] 下游任务 T3A.5 可依据本 schema 编写 16 条规则
- [ ] 下游任务 T3A.7 可依据本 schema 实现预检引擎
- [ ] 下游任务 T3B.5 可依据本 schema 渲染预检结果 UI
