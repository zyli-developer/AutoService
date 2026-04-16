---
type: test-plan
id: test-plan-T3A.2
status: draft
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-T3A.2 — 虚拟客户生成 pipeline (sim_customer.py)"
related:
  - eval-T3A.2
---

# Test Plan: T3A.2 虚拟客户生成 pipeline

## 触发原因

eval-T3A.2 已产出（simulate 模式），需要为 `autoservice/sim_customer.py` 生成可执行测试。
测试目标文件：`tests/sim_customer/test_sim_customer.py`

## 测试策略

sim_customer 核心是一个**离线生成 pipeline**（非实时对话）。测试分三层：

1. **单元层**：数据结构验证、YAML 加载、场景分配逻辑（无 LLM 调用）
2. **集成层**：mock LLM 调用，验证 pipeline 端到端流程
3. **约束验证层**：验证生成结果满足 US-1.3 验收条件

LLM 调用全部 mock（使用预置 fixture），确保测试确定性和速度。

## 用例列表

### TC-001: YAML 配置加载 — personas

- **来源**：eval-doc（#3, #12）
- **优先级**：P0
- **前置条件**：`autoservice/sim_scenarios.yaml` 存在，含 6 个 persona 定义
- **操作步骤**：
  1. `load_sim_config("sim_scenarios.yaml")`
  2. 检查返回的 personas 列表
- **预期结果**：6 个 Persona dataclass，每个含 id/name_zh/traits/communication_style
- **涉及模块**：sim_customer.py, sim_scenarios.yaml

### TC-002: YAML 配置加载 — scenarios（静态）

- **来源**：eval-doc（#2, #12）
- **优先级**：P0
- **前置条件**：sim_scenarios.yaml 含 fallback 场景定义
- **操作步骤**：
  1. `load_sim_config("sim_scenarios.yaml")`
  2. 检查 fallback_scenarios 列表
- **预期结果**：≥3 个 Scenario dataclass（通用场景），每个 intent 字段映射到 classify_intent.yaml 的 5 种之一
- **涉及模块**：sim_customer.py, sim_scenarios.yaml

### TC-003: KB 场景提取 — 正常 KB

- **来源**：eval-doc（#4）
- **优先级**：P0
- **前置条件**：FTS5 DB 含 ≥20 条目、覆盖 3+ 业务主题
- **操作步骤**：
  1. 准备 fixture KB（sqlite FTS5，含退款/产品/配送三类条目）
  2. `extract_scenarios(kb_path)` （mock LLM 聚类调用，返回预设场景列表）
- **预期结果**：返回 3-8 个 Scenario，每个含 id/name_zh/intent/keywords/trap_question
- **涉及模块**：sim_customer.py

### TC-004: KB 场景提取 — 空 KB 降级

- **来源**：eval-doc（#9）
- **优先级**：P1
- **前置条件**：FTS5 DB 为空或 <3 条目
- **操作步骤**：
  1. 准备空 KB fixture
  2. `extract_scenarios(kb_path)`
- **预期结果**：返回 fallback 场景列表（从 sim_scenarios.yaml 读取），每个标注 `degraded=True`
- **涉及模块**：sim_customer.py, sim_scenarios.yaml

### TC-005: 场景-persona 分配矩阵

- **来源**：eval-doc（#2, #3）
- **优先级**：P0
- **前置条件**：5 个 scenario + 6 个 persona 已加载
- **操作步骤**：
  1. `build_assignment_matrix(scenarios, personas, count=12)`
  2. 统计每个 intent 出现次数
  3. 统计每个 persona 出现次数
- **预期结果**：
  - 返回 12 个 (scenario, persona) 对
  - 5 种 intent 每种 ≥1 次
  - 6 种 persona 每种 ≥1 次
- **涉及模块**：sim_customer.py

### TC-006: 单条对话生成 — 结构验证

- **来源**：eval-doc（#1, #8）
- **优先级**：P0
- **前置条件**：mock LLM 返回预设对话 JSON
- **操作步骤**：
  1. `generate_single_dialog(scenario, persona, kb_path, language="zh")`
  2. 检查返回的 SimDialog 结构
- **预期结果**：
  - SimDialog 含 id/scenario/persona/turns/language/review_status
  - turns 为 SimTurn 列表，3-6 个
  - 每个 turn 含 role ("customer"|"agent") + content (非空)
  - 首个 turn.role == "customer"
  - customer/agent 交替出现
  - review_status == "pending"
- **涉及模块**：sim_customer.py

### TC-007: trap question 存在性

- **来源**：eval-doc（#5）
- **优先级**：P1
- **前置条件**：mock LLM 按 prompt 生成含 trap 的对话
- **操作步骤**：
  1. `generate_single_dialog(scenario, persona, kb_path)`
  2. 检查 turns 中是否有 metadata 标注 `is_trap=True` 的 customer turn
- **预期结果**：至少 1 个 customer turn 标记为 trap question
- **涉及模块**：sim_customer.py

### TC-008: AI 回复使用 soul.md prompt

- **来源**：eval-doc（#6）
- **优先级**：P0
- **前置条件**：customer agent soul.md 存在
- **操作步骤**：
  1. Mock LLM 客户端，捕获实际发送的 system prompt
  2. `generate_single_dialog(scenario, persona, kb_path)`
  3. 检查 AI 回复生成时传入的 system prompt
- **预期结果**：system prompt 包含 soul.md 核心内容（角色定位、行为约束、反幻觉规则）
- **涉及模块**：sim_customer.py, agents/customer/soul.md

### TC-009: 术语注入（zh）

- **来源**：eval-doc（#7）
- **优先级**：P1
- **前置条件**：i18n/terms/zh.yaml 存在
- **操作步骤**：
  1. Mock LLM 客户端，捕获 system prompt
  2. `generate_single_dialog(scenario, persona, kb_path, language="zh")`
  3. 检查 prompt 中是否含术语表
- **预期结果**：system prompt 含 TermLoader.render_prompt_prefix("zh") 输出的术语 markdown 表格
- **涉及模块**：sim_customer.py, i18n/term_loader.py

### TC-010: 术语注入（en）

- **来源**：eval-doc（#7）
- **优先级**：P1
- **前置条件**：i18n/terms/en.yaml 存在
- **操作步骤**：
  1. Mock LLM 客户端，捕获 system prompt
  2. `generate_single_dialog(scenario, persona, kb_path, language="en")`
- **预期结果**：prompt 含英文术语表；生成的 SimDialog.language == "en"
- **涉及模块**：sim_customer.py, i18n/term_loader.py

### TC-011: 端到端 generate_sim_dialogs — 正常路径

- **来源**：eval-doc（#1, #2, #3）
- **优先级**：P0
- **前置条件**：fixture KB + mock LLM（返回 12 条预设对话）
- **操作步骤**：
  1. `await generate_sim_dialogs(tenant_id="test", kb_path=fixture_kb, count=12)`
  2. 统计返回列表
- **预期结果**：
  - len(result) >= 10
  - 每条 SimDialog 结构完整
  - 5 种 intent 覆盖 ✓
  - 6 种 persona 覆盖 ✓
  - 每条 3-6 turns ✓
- **涉及模块**：sim_customer.py（端到端）

### TC-012: 端到端 — count 参数

- **来源**：eval-doc（#1）
- **优先级**：P1
- **前置条件**：fixture KB + mock LLM
- **操作步骤**：
  1. `await generate_sim_dialogs(..., count=5)`
  2. `await generate_sim_dialogs(..., count=20)`
- **预期结果**：
  - count=5 → 返回 5 条（persona/intent 覆盖尽力而为）
  - count=20 → 返回 20 条
- **涉及模块**：sim_customer.py

### TC-013: 端到端 — personas 过滤

- **来源**：eval-doc（#3）
- **优先级**：P1
- **前置条件**：fixture KB + mock LLM
- **操作步骤**：
  1. `await generate_sim_dialogs(..., personas=["angry-refund", "cross-border"])`
- **预期结果**：所有返回对话的 persona.id 仅为 "angry-refund" 或 "cross-border"
- **涉及模块**：sim_customer.py

### TC-014: 轮数后处理 — 截断过长

- **来源**：eval-doc（#8）
- **优先级**：P1
- **前置条件**：mock LLM 返回 8 轮对话
- **操作步骤**：
  1. Mock LLM 返回含 8 个 turn 的 JSON
  2. `generate_single_dialog(...)`
  3. 检查结果 turns 数量
- **预期结果**：turns 被截断为 6（max_turns），最后一轮为 agent 回复（自然结束）
- **涉及模块**：sim_customer.py

### TC-015: 轮数后处理 — 补充过短

- **来源**：eval-doc（#8）
- **优先级**：P1
- **前置条件**：mock LLM 返回 2 轮对话
- **操作步骤**：
  1. Mock LLM 返回含 2 个 turn 的 JSON
  2. `generate_single_dialog(...)`
- **预期结果**：重试生成或补充至 ≥3 turns（min_turns）
- **涉及模块**：sim_customer.py

### TC-016: 并发控制 — semaphore

- **来源**：eval-doc（#11）
- **优先级**：P1
- **前置条件**：mock LLM，count=12
- **操作步骤**：
  1. 用 spy 包装 mock LLM，记录并发调用数
  2. `await generate_sim_dialogs(..., count=12)`
  3. 检查最大并发数
- **预期结果**：任意时刻并发 LLM 调用 ≤6（semaphore 限制）
- **涉及模块**：sim_customer.py

### TC-017: 自定义 persona 热加载

- **来源**：eval-doc（#12）
- **优先级**：P2
- **前置条件**：sim_scenarios.yaml 含 6 个标准 persona
- **操作步骤**：
  1. 动态往 sim_scenarios.yaml 添加 `{"id": "vip-customer", "name_zh": "VIP客户", ...}`
  2. `load_sim_config("sim_scenarios.yaml")`
- **预期结果**：返回 7 个 persona（含新增的 vip-customer）
- **涉及模块**：sim_customer.py, sim_scenarios.yaml

### TC-018: SimDialog 序列化/反序列化

- **来源**：eval-doc（下游 T3B.4 需要 JSON 输出）
- **优先级**：P1
- **前置条件**：一条完整 SimDialog
- **操作步骤**：
  1. 构建 SimDialog fixture
  2. `dialog.to_dict()` → JSON string → `SimDialog.from_dict()`
- **预期结果**：round-trip 后所有字段一致
- **涉及模块**：sim_customer.py

### TC-019: 无效 language 参数

- **来源**：边界情况
- **优先级**：P2
- **前置条件**：无
- **操作步骤**：
  1. `await generate_sim_dialogs(..., language="xx")`
- **预期结果**：抛 ValueError，提示不支持的语言代码
- **涉及模块**：sim_customer.py

### TC-020: tenant 级 persona 覆盖

- **来源**：eval-doc（#12）+ YAML 模式一致性
- **优先级**：P2
- **前置条件**：tenant 目录含 `sim_scenarios_override.yaml`
- **操作步骤**：
  1. 准备 tenant override YAML（覆盖 angry-refund 的 traits）
  2. `load_sim_config("sim_scenarios.yaml", tenant_override="tenant/sim_scenarios_override.yaml")`
- **预期结果**：angry-refund persona 使用 tenant 覆盖值，其余 5 个不变
- **涉及模块**：sim_customer.py

## 统计

| 指标 | 值 |
|------|-----|
| 总用例数 | 20 |
| P0 | 6 (TC-001, 002, 003, 005, 006, 008, 011) |
| P1 | 10 (TC-004, 007, 009, 010, 012, 013, 014, 015, 016, 018) |
| P2 | 3 (TC-017, 019, 020) |
| 来源：eval-doc | 17 |
| 来源：边界/下游 | 3 |

## 风险标注

- **核心路径**：TC-011 端到端是最关键测试——它验证整个 pipeline 从 KB → 场景 → 分配 → 生成 → 输出的完整链路
- **mock 策略**：所有 LLM 调用使用 fixture JSON（预设对话模板），不调用真实 API。mock fixture 需要覆盖正常/过长/过短三种返回
- **KB fixture**：需要准备一个含 20+ 条目、3 个业务主题的 SQLite FTS5 测试数据库
- **无覆盖矩阵**：当前无 coverage-matrix 可对比，所有用例标注为新增覆盖
