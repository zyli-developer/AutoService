---
type: eval-doc
id: eval-doc-T3A.1
status: draft
producer: skill-5
created_at: 2026-04-16
mode: simulate
feature: "soul.md 自动生成器"
submitter: DevA
related:
  - T1A.4   # 4 角色 soul.md 定义（已完成，是本任务的输入模板）
  - T3B.2   # 向导 Step1 资料上传（下游消费方，调 soul.md 生成 API）
  - T3A.2   # 虚拟客户生成 pipeline（同期任务，共享 KB 上下文）
---

# Eval: soul.md 自动生成器 (T3A.1)

## 基本信息
- 模式：模拟
- 提交人：DevA
- 日期：2026-04-16
- 状态：draft

## Feature 描述

从商户上传的知识库（KB）内容 + 租户配置，自动生成 4 份 soul.md 草稿（customer / translate / lead / triage），供管理员在上线向导 Step1 审阅和微调。

**核心需求**：
1. 输入：已通过 `kb_ingest.py` 导入的 KB 数据（产品文档、FAQ、价目表等）+ 租户基础配置（行业、语言、品牌名等）
2. 处理：基于 KB 内容，用 AI（Claude）分析商户的产品特征、常见问题模式、行业特性，填充 soul.md 各章节
3. 输出：4 份 soul.md 草稿，结构与 T1A.4 定义的模板一致
4. API：提供 HTTP/函数接口供 T3B.2 前端调用

**关键约束**：
- 基于 `kb_ingest` 现有 API（`kb_search.py` 的 `search()` 函数）
- soul.md 结构必须与现有 4 份模板兼容（角色定位 / 行为约束 / 反幻觉规则 / 多轮交互 / 升级条件 / 输出格式）
- 生成结果是"草稿"，需人工审阅后才生效

## 架构分析

### 现有可复用组件
| 组件 | 路径 | 复用方式 |
|------|------|----------|
| KB 搜索 API | `skills/knowledge-base/scripts/kb_search.py` → `search()` | 提取产品/FAQ/价格等 KB 内容 |
| KB in-process 调用 | `channels/web/plugin_kb.py` → `presearch_kb()` | 参考 lazy-load 模式 |
| soul.md 模板 | `agents/{customer,translate,lead,triage}/soul.md` | 作为生成的结构模板 |
| agent.yaml 配置 | `agents/*/agent.yaml` | 参考配置结构 |
| 术语加载器 | `autoservice/i18n/term_loader.py` | 翻译 Agent 术语注入 |

### 建议实现方案
- 新建 `autoservice/soul_generator.py` — 核心生成逻辑
- 新建 `autoservice/soul_generator_api.py` 或在 `channels/web/app.py` 注册路由 — HTTP API 供前端调用
- 使用 Claude API（通过 `socialware/claude.py`）将 KB 内容 + 模板 → 生成 soul.md

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|----------|---------|--------|
| 1 | 基础生成：从 KB 生成 4 份 soul.md | KB 已导入至少 1 个产品文档（≥10 chunks） | 调用 `generate_souls(tenant_id="demo", config={industry:"ecommerce", brand:"TestShop", languages:["zh","en"]})` | 返回 4 份 soul.md 字典，每份包含完整 6 节（角色定位/行为约束/反幻觉/多轮交互/升级条件/输出格式），内容与 KB 产品信息一致 | 可行。`kb_search.py` 的 `search()` 可按 domain 过滤检索 KB chunks，传入 Claude 做 prompt-based 生成。T1A.4 的 4 份 soul.md 提供结构模板。 | 无重大差异。需设计多轮 KB 查询策略：先查产品概述、再查 FAQ、再查价格，分别注入不同 soul.md 章节 | P0 |
| 2 | 行业适配：不同行业生成不同行为约束 | KB 含电商 vs SaaS 两种行业数据 | 分别用 `industry:"ecommerce"` 和 `industry:"saas"` 调用生成 | 电商版 customer soul 强调退换货/物流/售后；SaaS 版强调订阅管理/功能咨询/技术支持。lead soul 的四要素提取策略不同 | 可行。通过 prompt 注入行业上下文，Claude 可区分行业特征并生成差异化内容。KB 搜索的 domain 字段可辅助过滤 | 需要设计行业 prompt 模板（industry-specific prompt segments），这是生成质量的关键 | P0 |
| 3 | KB 为空或不足时的降级 | KB 为空或仅有 < 3 chunks | 调用 `generate_souls(tenant_id="new_tenant", ...)` | 返回基于 T1A.4 通用模板的 soul.md（仅填入品牌名和语言），并标注 `[需补充]` 占位符；不编造产品信息 | 可行。检查 `search()` 返回结果数量，≤ 阈值时回退到模板填充模式（品牌名/行业名替换），不调用 Claude 生成产品相关内容 | 无。这是重要的防幻觉措施 | P0 |
| 4 | 术语注入：翻译 Agent 术语表自动填充 | KB 含产品术语、`i18n/` 下有术语 YAML | 生成 translate 角色的 soul.md | translate soul.md 的"术语一致性"节自动列出 KB 中提取的 Top-20 高频产品术语及其标准翻译 | 可行。`autoservice/i18n/term_loader.py`（T2A.5 产出）已有术语加载机制。可复用其 YAML 读取逻辑，将术语列表注入 translate soul.md | 需从 KB 中自动提取术语（当前术语表是手动维护的），可能需要额外的术语提取步骤 | P1 |
| 5 | HTTP API：前端调用生成接口 | Web channel 已启动 | `POST /api/soul/generate` body: `{tenant_id, config}` | 返回 `{status:"ok", souls:{customer:"...", translate:"...", lead:"...", triage:"..."}, warnings:[]}` | 可行。`channels/web/app.py` 已有插件路由注册机制。新增路由即可。需考虑生成耗时（Claude API 调用 ~5-15s），建议返回 202 + 轮询或 SSE | 差异：同步 vs 异步。生成涉及多次 Claude 调用，同步可能超时。建议用 202 + task_id 模式或 SSE 流 | P0 |
| 6 | 幂等性：重复生成不丢失人工修改 | 管理员已手动编辑过 soul.md | 再次调用 `generate_souls()` | 返回新草稿但不覆盖已有文件；或提供 diff 视图让管理员合并 | 可行。文件写入策略：生成到 `plugins/<tenant>/souls_draft/` 临时目录，不直接覆盖 `agents/*/soul.md`。前端展示 diff | 需要设计"草稿 vs 已发布"的文件管理策略 | P1 |
| 7 | 多语言：生成中文/英文 soul.md | 租户配置 `languages: ["zh", "en"]` | 调用生成并指定主语言 | soul.md 内容用指定主语言撰写。多语言术语仍保留原文+翻译格式 | 可行。Claude prompt 中指定输出语言即可。T2A.5 的 22 语种术语 YAML 可作为多语言术语参考 | 无重大差异 | P1 |
| 8 | triage 角色适配：自动识别意图类别 | KB 含多种产品线/服务类型 | 生成 triage soul.md | triage soul.md 的"五类意图"节根据 KB 内容自动调整意图分类（如 KB 有技术文档则增加 `technical_support` 意图） | 可行但需仔细设计。当前 triage 的 5 类意图是固定的（T1A.4 定义），自动扩展需要修改意图识别逻辑。建议初版保持 5 类不变，仅调整各类的描述和关键词 | 差异：初版不应自动扩展意图类别，避免与 ModelRouter（T1A.5）的 `classify_intent.yaml` 不一致。仅定制描述文本 | P1 |
| 9 | 超大 KB：性能边界 | KB 含 1000+ chunks | 调用生成 | 在 30s 内完成生成，不超出 Claude context window | 需关注。1000 chunks 全量传入 Claude 会超出 context。需要 KB 摘要策略：(1) 先 search top-K 代表性 chunks, (2) 生成产品摘要, (3) 用摘要而非原始 chunks 生成 soul.md | 差异：不能直接传入全部 KB，需要摘要中间层。这是技术实现的关键设计点 | P1 |
| 10 | 错误处理：Claude API 失败 | Claude API 返回错误或超时 | 调用生成 | 返回友好错误信息 + 回退到模板填充模式（同 TC-3 降级策略） | 可行。`socialware/claude.py` 已有错误处理基础设施 | 无 | P2 |

## 风险与依赖

| 风险 | 影响 | 缓解 |
|------|------|------|
| Claude context window 限制 | 大 KB 无法全量传入 | KB 摘要中间层：先 search + summarize，再生成 |
| 生成质量不稳定 | 不同运行产出不同 soul.md | 使用 temperature=0 + structured prompt + 模板约束 |
| 生成耗时长 | 前端超时 | 异步 API（202 + 轮询）或 SSE |
| 与 T1A.5 ModelRouter 的意图分类不一致 | triage 路由出错 | 初版不自动扩展意图类别，保持与 classify_intent.yaml 一致 |

## 建议实现文件清单

| 文件 | 说明 |
|------|------|
| `autoservice/soul_generator.py` | 核心生成逻辑：KB 查询 → 摘要 → prompt → Claude → soul.md |
| `autoservice/soul_templates/` | 4 个角色的 prompt 模板（Jinja2 或 f-string） |
| `tests/test_soul_generator.py` | 单元测试 + 集成测试 |

## 后续行动

- [ ] eval-doc 已注册到 .artifacts/eval-docs/
- [x] eval-doc 已写入 .artifacts/eval-docs/eval-T3A.1-soul-generator.md
- [ ] 用户已确认 testcase 表格 (status: draft → confirmed)
