---
type: eval-doc
id: eval-T3A.2
status: draft
producer: skill-5
created_at: "2026-04-16"
mode: simulate
feature: "虚拟客户生成 pipeline (sim_customer.py)"
submitter: DevA
related:
  - T1A.4  # 4 role soul.md
  - T1A.5  # ModelRouter + FastClassifier
  - T2A.5  # i18n terminology
  - T3A.3  # Few-shot injection (downstream)
  - T3B.4  # Virtual rehearsal UI (downstream)
---

# Eval: T3A.2 — 虚拟客户生成 pipeline

## 基本信息
- 模式：模拟 (simulate)
- 提交人：DevA
- 日期：2026-04-16
- 状态：draft
- 验收标准：US-1.3 Gherkin — ≥10 条虚拟对话，persona 混搭，场景覆盖，AI 答

## 架构概述

```
autoservice/sim_customer.py          # 核心模块
autoservice/sim_scenarios.yaml       # 场景 + persona 配置（YAML 配置模式）
```

### 核心接口设计

```python
# --- 数据结构 ---
@dataclass
class Persona:
    id: str                     # e.g. "angry-refund"
    name_zh: str
    traits: list[str]           # 语言风格特征
    communication_style: str    # "aggressive" | "confused" | "polite" | ...

@dataclass
class Scenario:
    id: str                     # e.g. "return-policy"
    name_zh: str
    intent: str                 # maps to classify_intent.yaml intent
    keywords: list[str]         # KB-grounded keywords
    trap_question: str          # edge case outside KB

@dataclass
class SimTurn:
    role: str                   # "customer" | "agent"
    content: str
    metadata: dict              # intent, confidence, model_tier (agent turns only)

@dataclass
class SimDialog:
    id: str
    scenario: Scenario
    persona: Persona
    turns: list[SimTurn]        # 3-6 turns
    language: str               # ISO 639-1
    review_status: str          # "pending" | "approved" | "edited" | "flagged"

# --- 主 API ---
async def generate_sim_dialogs(
    tenant_id: str,
    kb_path: str,               # FTS5 DB path
    language: str = "zh",
    count: int = 12,
    personas: list[str] | None = None,  # None = use all 6
) -> list[SimDialog]:
    ...
```

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|----------|---------|--------|
| 1 | 基本生成：≥10 条对话 | KB 已导入 FTS5；4 role soul.md 已就位 | 调用 `generate_sim_dialogs(tenant_id, kb_path, count=12)` | 返回 ≥10 条 `SimDialog`，每条 3-6 turns | 可行。KB FTS5 查询提取场景关键词，Claude sonnet 生成客户语料，customer agent soul.md 约束下生成 AI 回复。现有 `model_router.py` 的 slow tier (sonnet) 可直接复用 | 无 | P0 |
| 2 | 场景覆盖：5 种 intent 均出现 | classify_intent.yaml 定义了 5 种 intent | 生成 12 条后统计 intent 分布 | 5 种 intent 至少各出现 1 次（product_inquiry, complaint, purchase_intent, language_barrier, general_question） | 可行。从 classify_intent.yaml 读取 5 种 intent，按比例分配场景数量（complaint/purchase 各 2-3 条，其余各 1-2 条），确保覆盖。需要显式分配而非随机 | 需要确定性分配策略而非纯随机，否则可能漏 intent | P0 |
| 3 | 6 种 persona 混搭 | 预定义 6 种 persona（angry-refund, price-sensitive, non-native-speaker, tech-illiterate, repeat-customer, cross-border） | 生成 12 条后统计 persona 分布 | 每条对话标注 persona，6 种至少各出现 1 次 | 可行。笛卡尔积 5 intent × 6 persona = 30 组合，取 12 条采样即可覆盖。每个 scenario 分配 2 个 persona（PRD 原文要求） | 无 | P0 |
| 4 | KB 场景提取 | KB 含 ≥3 个业务主题（如退款政策、产品功能、配送信息） | 系统自动从 KB 聚类出场景列表 | 返回 5-8 个场景，每个含关键词列表和描述 | 可行但有风险。FTS5 支持全文搜索，但不直接支持聚类。方案：用 LLM 读取 KB 高频词/文档标题，生成场景分类。依赖 KB 质量——空 KB 或单主题 KB 会退化 | KB 聚类需要 LLM 辅助而非纯 FTS5；需处理空 KB 边界 | P0 |
| 5 | trap question（陷阱题） | 每个场景定义 1 个 KB 外的边界问题 | 检查每条对话是否含 1 个 trap turn | 每条对话至少 1 个 trap question（KB 无法直接回答的问题），AI 应诚实表示"不确定"或升级 | 可行。在 SIM_CUSTOMER_PROMPT 中显式要求"插入 1 个超出 KB 范围的问题"。customer agent soul.md 已有反幻觉规则："未知则标注不确定" | 需验证 customer agent 在 trap question 下是否真的触发反幻觉规则而非编造答案 | P1 |
| 6 | AI 回复质量：遵循 soul.md 约束 | customer agent soul.md 含行为约束 + 反幻觉规则 | 审查 AI 回复是否引用 KB、是否有幻觉 | AI 回复 100% 基于 KB 事实；数字/价格精确匹配；无编造 | 可行。soul.md 反幻觉规则已明确："所有事实可追溯到 KB 条目"。但 sim_customer 是离线生成，不经过完整 ConversationEngine pipeline——需要直接调用 customer agent prompt 而非 LocalEngine | sim_customer 绕过 ConversationEngine，直接调用 LLM + soul.md prompt。需确保 prompt 组装一致性 | P0 |
| 7 | 多语言生成 | i18n/terms/ 含 21 语种术语 | 调用 `generate_sim_dialogs(..., language="en")` | 英文对话使用英文术语表；客户语言风格匹配英文习惯 | 可行。TermLoader.render_prompt_prefix(lang) 注入术语表到 prompt。SIM_CUSTOMER_PROMPT 需按 language 参数切换语言指令 | 仅 zh/en 需要 P0 测试；其余 19 语种为 P2 | P1 |
| 8 | 对话轮数控制：3-6 turns | 配置 min_turns=3, max_turns=6 | 生成 12 条对话，统计每条轮数 | 每条对话 3-6 turns（含客户 + AI 交替） | 可行。在 LLM prompt 中约束 `turns: (3, 6)`。但 LLM 可能不严格遵守——需要后处理截断或补充 | 需要 post-processing 验证轮数，LLM 可能偶尔生成 2 或 7 轮 | P1 |
| 9 | 空 KB 降级 | KB 为空或仅含极少内容（<3 条目） | 调用 generate_sim_dialogs | 返回通用场景（问候、基本咨询、投诉），并标注 `degraded=True` | 可行。检测 KB 条目数量 < 阈值 → 使用预置通用场景模板（类似 classify_intent.yaml 的 general_question）。降级对话仍有价值——展示 AI 基础能力 | 需要预置 fallback 场景列表（3-5 个通用场景），不依赖 KB | P1 |
| 10 | 生成幂等性 | 相同 tenant_id + kb_path + seed | 调用两次 generate_sim_dialogs，比较结果 | 相同 seed → 相同对话集（可复现） | 部分可行。LLM 调用本质非确定性。方案：设置 temperature=0 + seed 参数（Claude API 支持）。但即使如此也不能保证 100% 一致 | 近似幂等可接受；完全幂等不可能。记录 seed 用于调试即可 | P2 |
| 11 | 批量性能 | 需生成 12 条对话 | 测量总耗时 | ≤60s 完成 12 条对话生成（含 KB 查询 + LLM 调用） | 有风险。每条对话需 2 次 LLM 调用（1 次生成客户语料，1 次生成 AI 回复）。12 条 = 24 次 sonnet 调用。串行约 24 × 5s = 120s。方案：并发生成（asyncio.gather），预计 15-30s | 必须并发调用。串行不达标。需设置合理并发上限（如 4-6 并行）避免 rate limit | P1 |
| 12 | YAML 配置可扩展 | 管理员想添加自定义 persona | 编辑 sim_scenarios.yaml 添加新 persona 条目 | 新 persona 立即可用于下次生成 | 可行。YAML 配置热加载，遵循 alerts.yaml/rules.yaml 的 id-based 模式。persona 和 scenario 均可 tenant 级别覆盖 | 无 | P2 |

## 风险分析

### 技术风险

1. **KB 聚类质量** — FTS5 不提供原生聚类。需 LLM 辅助分析 KB 内容提取场景，质量依赖 KB 结构化程度。
   - 缓解：提供 fallback 通用场景；对 KB < 10 条目降级为通用模式

2. **AI 回复一致性** — sim_customer 绕过 ConversationEngine 直接调用 LLM。prompt 组装需与生产路径一致。
   - 缓解：从 soul.md 读取 system prompt，复用 TermLoader 注入术语，确保 prompt 模板共享

3. **并发 rate limit** — 12 条对话 × 2 次 LLM 调用 = 24 次。Claude API rate limit 可能触发。
   - 缓解：使用 semaphore 控制并发（4-6），带 exponential backoff

### 依赖风险

4. **KB 基础设施** — 当前无独立 KB 查询客户端类。sim_customer 需要直接查 FTS5。
   - 缓解：封装简单的 `kb_query(db_path, query)` 辅助函数，后续可提取为共享组件

## 后续行动

- [ ] eval-doc 已注册到 .artifacts/eval-docs/
- [ ] 用户已确认 testcase 表格 (status: draft → confirmed)
- [ ] test-plan 已生成（by skill-2）
