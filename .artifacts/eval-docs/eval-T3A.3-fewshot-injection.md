---
type: eval-doc
id: eval-T3A.3
status: draft
producer: skill-5
created_at: "2026-04-16"
mode: simulate
feature: "Few-shot 注入机制 (fewshot_override.yaml → soul.md 热加载)"
submitter: DevA
related:
  - T3A.2  # sim_customer pipeline (upstream)
  - T1A.4  # 4 role soul.md
  - T2A.5  # i18n terminology (parallel pattern)
---

# Eval: T3A.3 — Few-shot 注入机制

## 基本信息
- 模式：模拟 (simulate)
- 提交人：DevA
- 日期：2026-04-16
- 状态：draft
- 验收标准：ζ4 T4.10c — `tenant.fewshot_override.yaml` → soul.md 热加载

## 架构概述

```
autoservice/fewshot_loader.py            # 核心模块：加载 + 渲染 few-shot 到 prompt
plugins/<tenant>/fewshot_override.yaml   # 租户级覆盖文件（L3 可修改）
```

### 核心接口设计

```python
@dataclass
class FewshotExample:
    scenario: str          # e.g. "退款申请"
    customer_turns: list[str]
    agent_response: str    # merchant-approved response
    language: str          # ISO 639-1

class FewshotLoader:
    def __init__(self, override_path: str | Path | None = None) -> None: ...
    def load_examples(self, language: str | None = None) -> list[FewshotExample]: ...
    def render_prompt_section(self, language: str, max_tokens: int = 3000) -> str: ...
    def save_from_sim_dialogs(self, dialogs: list[SimDialog]) -> int: ...
```

### 集成点

sim_customer.py 的 `generate_single_dialog()` 生成 AI 回复时组装 system prompt：

```python
# 当前 (T3A.2):
system_prompt = f"{soul_content}\n\n{term_prefix}"

# 新增 (T3A.3):
fewshot_section = fewshot_loader.render_prompt_section(language)
system_prompt = f"{soul_content}\n\n{term_prefix}\n\n{fewshot_section}"
```

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|----------|---------|--------|
| 1 | YAML 加载：正常文件 | fewshot_override.yaml 含 3 条 example | `FewshotLoader(path).load_examples()` | 返回 3 个 FewshotExample dataclass，字段完整 | 可行。YAML 结构遵循 alerts.yaml/rules.yaml 模式（id-based, bilingual）。直接 yaml.safe_load 解析 | 无 | P0 |
| 2 | YAML 加载：文件不存在 | override_path 指向不存在的文件 | `FewshotLoader(path).load_examples()` | 返回空列表 `[]`（graceful fallback） | 可行。检查 `Path.is_file()` → 返回 `[]`。与 TermLoader 同模式 | 无 | P0 |
| 3 | YAML 加载：空文件 | fewshot_override.yaml 为空 | `FewshotLoader(path).load_examples()` | 返回空列表 | 可行。`yaml.safe_load` 返回 None → 返回 `[]` | 无 | P1 |
| 4 | 语言过滤 | YAML 含 zh + en 两种语言 example | `load_examples(language="zh")` | 仅返回 zh 的 example | 可行。遍历 examples 按 language 字段过滤 | 无 | P0 |
| 5 | prompt 渲染 | 3 条 zh example 已加载 | `render_prompt_section("zh")` | 返回格式化 markdown 字符串，含"参考对话示例"标题 + 每条 example 的客户问/AI答 | 可行。格式类似 TermLoader.render_prompt_prefix — markdown 表格或区块引用 | 无 | P0 |
| 6 | prompt 渲染：截断过长 | 20 条 example，max_tokens=500 | `render_prompt_section("zh", max_tokens=500)` | 在 token 上限内截断，保留前 N 条完整 example（不截断中间） | 可行。逐条累加字符估计（1 token~4 chars），超限时停止。与 TermLoader 同一截断策略 | 无 | P1 |
| 7 | prompt 渲染：无 example | 无 override 文件 | `render_prompt_section("zh")` | 返回空字符串 `""` | 可行。load_examples 返回 `[]` → 直接返回 `""` | 无 | P0 |
| 8 | 从 SimDialog 保存 | 3 条 SimDialog，review_status="edited" | `save_from_sim_dialogs(dialogs)` | 写入 fewshot_override.yaml，仅含 "edited" 状态的对话；返回保存数量 | 可行。过滤 review_status=="edited" 的 dialog → 提取最后一对 customer-agent turn → 写 YAML | 无 | P0 |
| 9 | 从 SimDialog 保存：跳过非 edited | 5 条 dialog（2 edited + 2 approved + 1 flagged） | `save_from_sim_dialogs(dialogs)` | 仅保存 2 条 edited 的；approved/flagged 不保存 | 可行。过滤条件明确 | 无 | P1 |
| 10 | 热加载：文件更新后立即生效 | 先加载得到 2 条 → 追加 1 条到 YAML → 再加载 | 两次调用 `load_examples()` | 第二次返回 3 条 | 可行。每次 load_examples 重新读文件（不缓存）。性能可接受——向导阶段低频调用 | 无 | P1 |
| 11 | 集成：system prompt 包含 few-shot section | soul.md + term + fewshot 三段拼接 | 检查 generate_single_dialog 传入的 system prompt | system prompt 包含 soul.md 内容 + 术语表 + few-shot section 三段 | 可行。修改 sim_customer.py 的 prompt 组装逻辑，新增 fewshot_section 拼接 | 需修改 sim_customer.py 的 generate_single_dialog | P0 |
| 12 | YAML schema 兼容 | fewshot_override.yaml 遵循项目 YAML 模式 | 检查 YAML 结构是否包含 version/metadata | 含 version 字段 + examples 数组，每条含 scenario/customer_turns/agent_response/language | 可行。遵循 alerts.yaml 模式 | 无 | P2 |

## 风险分析

### 技术风险

1. **prompt 膨胀** — few-shot examples 加上 soul.md + terms 可能超出 context 上限。
   - 缓解：max_tokens 截断；默认 3000 tokens (~12000 chars) 上限

2. **YAML 损坏** — 用户/前端生成的 YAML 格式可能错误。
   - 缓解：yaml.safe_load 异常捕获 → 返回空列表 + 日志告警

### 无风险项

- 热加载无需 restart（每次读文件，无缓存）
- 仅影响 customer agent prompt（其他 3 个 agent 不受影响）
- L3 tenant 可自由修改 YAML（符合 fork 层级规则）

## 后续行动

- [ ] eval-doc 已注册到 .artifacts/eval-docs/
- [ ] 用户已确认 testcase 表格 (status: draft → confirmed)
- [ ] test-plan 已生成（by skill-2）
