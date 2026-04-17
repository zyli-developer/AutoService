---
type: test-plan
id: test-plan-T3A.3
status: draft
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-T3A.3 confirmed — Few-shot 注入机制"
related:
  - eval-T3A.3
---

# Test Plan: T3A.3 Few-shot 注入机制

## 触发原因

eval-T3A.3 已确认，需要为 `autoservice/fewshot_loader.py` 生成可执行测试。
测试目标文件：`tests/sim_customer/test_fewshot_loader.py`

## 用例列表

### TC-001: YAML 加载正常文件

- **来源**：eval-doc（#1）
- **优先级**：P0
- **前置条件**：fewshot_override.yaml 含 3 条 example
- **操作步骤**：`FewshotLoader(path).load_examples()`
- **预期结果**：返回 3 个 FewshotExample，每个含 scenario/customer_turns/agent_response/language
- **涉及模块**：fewshot_loader.py

### TC-002: YAML 加载 — 文件不存在

- **来源**：eval-doc（#2）
- **优先级**：P0
- **前置条件**：path 指向不存在的文件
- **操作步骤**：`FewshotLoader(path).load_examples()`
- **预期结果**：返回 `[]`
- **涉及模块**：fewshot_loader.py

### TC-003: YAML 加载 — 空文件

- **来源**：eval-doc（#3）
- **优先级**：P1
- **前置条件**：fewshot_override.yaml 为空
- **操作步骤**：`FewshotLoader(path).load_examples()`
- **预期结果**：返回 `[]`
- **涉及模块**：fewshot_loader.py

### TC-004: YAML 加载 — 格式损坏

- **来源**：风险分析
- **优先级**：P1
- **前置条件**：fewshot_override.yaml 含无效 YAML
- **操作步骤**：`FewshotLoader(path).load_examples()`
- **预期结果**：返回 `[]`（不抛异常）
- **涉及模块**：fewshot_loader.py

### TC-005: 语言过滤

- **来源**：eval-doc（#4）
- **优先级**：P0
- **前置条件**：YAML 含 2 条 zh + 1 条 en
- **操作步骤**：`load_examples(language="zh")`
- **预期结果**：返回 2 条 zh example
- **涉及模块**：fewshot_loader.py

### TC-006: 语言过滤 — None 返回全部

- **来源**：eval-doc（#4）
- **优先级**：P1
- **前置条件**：YAML 含 zh + en
- **操作步骤**：`load_examples(language=None)`
- **预期结果**：返回全部 example
- **涉及模块**：fewshot_loader.py

### TC-007: prompt 渲染 — 正常

- **来源**：eval-doc（#5）
- **优先级**：P0
- **前置条件**：3 条 zh example
- **操作步骤**：`render_prompt_section("zh")`
- **预期结果**：返回非空 markdown 字符串，含标题 + 每条 example 的客户问/AI答
- **涉及模块**：fewshot_loader.py

### TC-008: prompt 渲染 — 无 example

- **来源**：eval-doc（#7）
- **优先级**：P0
- **前置条件**：无 override 文件
- **操作步骤**：`render_prompt_section("zh")`
- **预期结果**：返回 `""`
- **涉及模块**：fewshot_loader.py

### TC-009: prompt 渲染 — 截断过长

- **来源**：eval-doc（#6）
- **优先级**：P1
- **前置条件**：20 条 example
- **操作步骤**：`render_prompt_section("zh", max_tokens=200)`
- **预期结果**：字符串长度 ≤ 200*4=800 chars；包含完整 example（不截断中间）
- **涉及模块**：fewshot_loader.py

### TC-010: save_from_sim_dialogs — 仅保存 edited

- **来源**：eval-doc（#8, #9）
- **优先级**：P0
- **前置条件**：5 条 SimDialog（2 edited + 2 approved + 1 flagged）
- **操作步骤**：`save_from_sim_dialogs(dialogs)`
- **预期结果**：写入 YAML 仅含 2 条；返回 2
- **涉及模块**：fewshot_loader.py

### TC-011: save_from_sim_dialogs — YAML 可再加载

- **来源**：eval-doc（#8）
- **优先级**：P0
- **前置条件**：保存 2 条 edited dialog
- **操作步骤**：save → load_examples
- **预期结果**：load 返回 2 条 FewshotExample，内容与原 dialog 一致
- **涉及模块**：fewshot_loader.py

### TC-012: 热加载 — 文件更新后立即生效

- **来源**：eval-doc（#10）
- **优先级**：P1
- **前置条件**：YAML 含 2 条 example
- **操作步骤**：load → 追加 1 条 → load again
- **预期结果**：第二次返回 3 条
- **涉及模块**：fewshot_loader.py

### TC-013: FewshotExample round-trip

- **来源**：健壮性
- **优先级**：P2
- **前置条件**：一条 FewshotExample
- **操作步骤**：to_dict → from_dict
- **预期结果**：round-trip 后字段一致
- **涉及模块**：fewshot_loader.py

## 统计

| 指标 | 值 |
|------|-----|
| 总用例数 | 13 |
| P0 | 7 |
| P1 | 4 |
| P2 | 1 |
| 来源：eval-doc | 11 |
| 来源：边界/健壮性 | 2 |

## 风险标注

- **核心路径**：TC-010/011 save→load round-trip 是最关键链路
- **集成**：TC-007 prompt 渲染格式需与 sim_customer.py 的 system prompt 组装兼容
