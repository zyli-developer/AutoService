# AutoService 产品级 PRD · v1.1

> 版本 v1.1 · 2026-04-15 · OneSync / ezagent42
> 相对 v1.0（2026-04-15 初版）的主要变更：
> ① 飞书渠道由 zchat 项目承接，AutoService 本期不再直接维护
> ② 客户接入统一改为"独立 Web 页"（web_bridge），作为 MVP 首发交互面
> ③ 引入 zchat 协议（Conversation/Mode/Gate/Timer/Event），对话引擎能力下沉
> ④ AutoService 职责聚焦为"业务层"：Agent 行为、CRM、知识库、计费、合规、Dream Engine
>
> v1.0 文档保留作为历史版本（`AutoService-PRD.md`）

---

## 1. Executive Summary

AutoService 是 OneSync 旗下 **OaaS (Organization-as-a-Service)** 框架下的第一个落地产品 —— 一个 7×24 的 AI 客服组织。我们为**中小商户**提供一套"AI 团队 + 人工 Copilot + 闲时自学习"的客服系统,让商户能在 **2 小时内自助上线**,把 80% 的重复咨询交给 AI,把人留给关键时刻。

**v1.1 产品边界调整**：
- **对话协作引擎下沉到 zchat 项目**（独立仓库 / 独立部署），AutoService 作为其首个 App 层接入
- **客户首发渠道为独立 Web 页**（商户独立站浮窗 → Web 聊天页，经 web_bridge 入 zchat）
- **飞书 / Lark 等 IM 渠道的交付由 zchat 完成**，AutoService 后续仅做 App 侧对接（飞书特有的卡片/审批等能力由 zchat bridge 暴露统一抽象接口）
- **人工客服工作区**本期同样走独立 Web 页（"客服 Web 工作台"），飞书版作为第二阶段交付

相较传统客服 SaaS,AutoService 的差异点仍是:**快慢双模型**消除"AI 慢"焦虑、**Copilot 默认**模式让人机协作像真实团队一样工作、**Dream Engine 闲时整理记忆**让系统每天醒来都比昨天聪明一点。目标是在稳态运行下把事实准确率维持在 92%,把首次响应压到 60 秒以内,把升级转结案率推到 89% 以上。

---

## 2. Problem Statement

（与 v1.0 §2 一致，此处省略复述）

**v1.1 补充**：AutoService 的"渠道适配复杂度"从 v1.0 的核心风险下移至 zchat。AutoService 只需一次对接 zchat Bridge API，即可享受 zchat 未来扩展的任何 IM 渠道（飞书/Lark/Slack/WhatsApp/微信），显著降低单一 App 对多平台的依赖风险。

---

## 3. Target Users & Personas

沿用 v1.0 §3 四类 Persona（商户管理员老陈 / 人工客服小李 / C 端客户 David / 平台运营），**仅行为描述更新**：

### Primary · 人工客服 "小李" · 行为更新
- v1.0: "打开 IM 工作区 → 盯 Agent 分队频道 → 点开进入 Copilot"
- **v1.1**: "打开**客服 Web 工作台** → 看分队卡片列表 → 点卡片进入 Copilot 侧边栏" （后续 zchat 接入飞书后可平滑切换到飞书客户端，体验一致）

### Primary · C 端客户 "David" · 行为更新
- v1.0: "点独立站浮动按钮 → 问问题"
- **v1.1**: "点独立站浮动按钮 → **弹出独立 Web 聊天页**（承载 web_bridge 与 zchat 的双向消息）→ 问问题" （体验不变；URL 和样式可按商户品牌定制）

---

## 4. Strategic Context

沿用 v1.0 §4，**增补 v1.1 技术路线**：

### 为什么现在拆出 zchat
- 客服只是人机协作的第一个场景；后续销售 / 教育 / 医疗咨询等场景都需要相同的"对话引擎"底座
- 单一 App 内维护多渠道适配器（飞书/Lark/Slack/WhatsApp）会让代码指数膨胀
- 通过 zchat **Channel-Server 协议**把 Mode / Gate / Timer / Event 下沉，使任何 App 只实现业务行为即可

### 竞争格局与差异化（v1.1 调整表格）

| 维度 | 传统客服 SaaS | 纯 LLM Bot | **AutoService v1.1** |
|---|---|---|---|
| 对话引擎 | 自研、厂商绑定 | 无 | **标准化协议 (zchat)**，渠道可插拔 |
| 上线时间 | 2–8 周 | 数天 | **2 小时自助** |
| 人机协作 | 割裂转接 | 无 | **Copilot 默认 + 角色翻转**（zchat Mode 协议保障） |
| 事实准确率 | N/A | 60–80% | **92% 稳态** |
| 自学习 | 无 | 无 | **闲时整理记忆 + 灰度** |
| 合规 | 手动 | 无 | **按地区自动预检** |

---

## 5. Solution Overview

### 5.1 系统分层（v1.1 新增）

```
┌─ AutoService App (本仓库) ───────────────────┐
│ · Agent soul.md × 4 角色 (fast/deep/triage/admin)
│ · 知识库 + CRM + 规则引擎 + 合规引擎
│ · Dream Engine · 计费引擎
│ · 合规规则库 (GDPR/CCPA/PIPL 16 条)
│ · 上线向导（Web 管理后台）
│ · channel-server 插件:
│     - autoservice_lifecycle.py  (客户生命周期)
│     - autoservice_metrics.py    (计费/SLA 埋点)
│     - autoservice_squad.py      (分队卡片)
│     - autoservice_cc_pool.py    (Agent 实例池生命周期)
└──────────────────────────────────────────────┘
          ↓↑ Bridge API (WebSocket JSON :9999)
┌─ zchat (独立仓库) ────────────────────────────┐
│ · channel-server: Conversation / Mode / Gate /
│   Timer / Event / CommandParser / MCP
│ · bridges/feishu_bridge.py  (承接飞书)
│ · bridges/web_bridge.py     (本期主力)
│ · ergo IRC 作为内部消息总线
└──────────────────────────────────────────────┘
          ↓ WSS                    ↓ WSS
      Feishu WSS (后续)         Browser WS (本期)
```

### 5.2 产品构成（v1.1 重新组织为 **AutoService 负责 / zchat 负责**）

**AutoService 负责（App 层）**

**模块 A · 业务入口与 Web 前端**
- C 端：商户独立站浮窗 → 独立 Web 聊天页（`customer-chat/`）
- 客服端：客服 Web 工作台（`operator-console/`，显示分队卡片、Copilot 侧栏）
- 商户管理员端：Web 管理后台（`admin-portal/`，上线向导、仪表盘、规则配置、提案审核）

**模块 B · AI 客服团队（4 个专精角色）**
- 客服 Agent（知识库问答 · 反幻觉 · 多轮记忆 · 情绪识别）—— `agents/customer/soul.md`
- 翻译 Agent（20+ 语言 · 自动检测 · 术语映射 · 双向流式）—— `agents/translate/soul.md`
- 线索收集 Agent（四要素提取 · 意向评估 · CRM 直通）—— `agents/lead/soul.md`
- 智能分流 Agent（信心评估 · 对话摘要 · 团队匹配 · SLA 守护）—— `agents/triage/soul.md`

**模块 C · 业务规则与数据**
- 知识库（RAG · FTS5 · 多租户隔离）
- CRM（客户档案 · 对话历史 · 线索）
- 业务规则引擎（升级条件、禁用词、合规约束）
- 计费引擎（订阅 zchat `mode.changed` 事件做接管次数统计）
- **cc-pool Agent 运行时**（Claude Code 实例池；sticky key 从 chat_id 升级为 conversation_id；通过 `autoservice_cc_pool` plugin 响应 `on_conversation_closed` 释放实例）

**模块 D · Dream Engine 闲时学习循环**
- 管理群配置学习规则（触发时机 / 覆盖范围 / 风险阈值 / 灰度策略）
- 对话记忆池（memory_pool.db）
- 业务低峰自动触发 · 回放 · 抽取提案
- 晨起推送 → 管理员审核 → 5%→25%→100% 灰度 → `/rollback` 撤回

**模块 E · 合规引擎**
- 16 条预置规则库（EU 6 GDPR / US 4 CCPA-COPPA / CN 6 PIPL-网信办）
- 预检不阻塞沙箱，对外开放前必须通过

---

**zchat 负责（Engine 层 · 本 PRD 不详细定义，见 zchat-plan）**

- **对话状态机**（Conversation + Mode: auto / copilot / takeover）
- **消息可见性 Gate**（public / side / system 强制路由）
- **Timer 管理**（7 类：onboard / placeholder / slow_query / takeover_wait / idle / close / first_reply）
- **Event Bus**（SQLite 持久化 + 查询，20+ 事件类型）
- **协议命令**（/hijack /release /copilot /resolve /abandon /status /dispatch /assign）
- **Bridge 适配**（feishu_bridge 现有 + web_bridge 本期主力）

### 5.3 核心用户流程

**对话级六步状态机**（由 zchat Mode 协议驱动；AutoService 通过事件订阅感知）：

| 步骤 | zchat 状态 | 触发 | AutoService 侧动作 |
|---|---|---|---|
| ①顾客触发 | conversation.created | 客户消息到达 web_bridge | lifecycle plugin: 创建 CRM 记录 |
| ②Agent 接洽 | mode=auto | triage → customer agent 路由 | 调 agent soul.md 生成回复 |
| ③对话监管 | mode=copilot | 客服点开分队卡片 | squad plugin: 推送侧栏信息 |
| ④人工提醒 | /hijack 或 @人工 | Agent 主动或客服抢单 | metrics plugin: 计 `escalation.requested` |
| ⑤角色翻转 | mode=takeover | 客服接管 | metrics plugin: 接管次数++ |
| ⑥副驾驶 | mode=takeover | AI 持续旁建议 | agent 以 side visibility 发建议 |

**商户生命周期**：阶段 A 自助上线（≤2h） → 阶段 B 日常运营（实时循环） → 阶段 C 闲时学习（夜间循环）—— 全部在 AutoService 侧实现，zchat 仅负责运行时对话。

### 5.4 关键设计决策（v1.1）

1. **C 端交互统一走独立 Web 页**（MVP），避免绑定任何 IM 平台
2. **人工客服工作台也是 Web**（MVP），与 zchat Bridge API 1:1 对齐；飞书端作为第二阶段平滑接入
3. **所有对话协作原语（Mode/Gate/Timer）由 zchat 统一提供**，AutoService 不自建状态机
4. **飞书特有能力（卡片/审批/Bitable）由 zchat feishu_bridge 暴露统一接口**；本 PRD v1.1 不承诺具体时间
5. **Dream Engine、合规、计费、Agent 行为定义 100% 在 AutoService 侧**
6. 对话内容默认加载历史上下文；新客户自动创建工作目录

---

## 6. Success Metrics

### 计费指标（★，产品价值承诺）

| 指标 | 定义 | 稳态目标 |
|---|---|---|
| ★ 接管次数 | zchat `mode.changed(→takeover)` 事件总数/月 | 阶梯计费 |
| ★ 客户满意度 CSAT | zchat `csat_response` 事件均值 | ≥ 4.5 / 5.0 |
| ★ 升级转结案率 | takeover 后 `conversation.resolved`(成功) / takeover 总数 | ≥ 89% |

### 运营指标

事实准确率 ≥ 92% · 平均首回 <60s · 接单等待 <180s · 会话时长 5–15 分钟 · AI 提议采纳率 · AI 消化率 ≥ 80%

### SLA（v1.1 明确 zchat Timer 映射）

| SLA | 阈值 | zchat Timer |
|---|---|---|
| onboard 首屏应答 | <3s | `sla_onboard` |
| 占位消息 | <1s | `sla_placeholder` |
| 慢查询续写 | <15s | `sla_slow_query` |
| 人工接单等待 | <180s | `takeover_wait` |
| 人工首次回复 | <60s | `first_reply` |
| 自助上线 | <2h | App 侧计时 |

### 非功能需求（v1.1 新增 · zchat 引入的延迟预算与部署约束）

相对 v1.0 "AutoService 直连"架构，v1.1 经 zchat 增加了 **feishu_bridge → Bridge API → channel-server → 内部 IRC** 等 3–4 跳。端到端净增 **10–30ms**（同主机部署），相对占位消息 1s SLA 占 <5%、相对 LLM 推理数百 ms 完全不敏感。但若配置错误可被放大数量级，故固化为非功能需求：

**NFR-1 · Bridge API 往返延迟 P95 ≤ 20ms**
- 埋点: `bridge_api.roundtrip_ms`
- 超阈值动作: 告警 + 自动降级到同步 fallback

**NFR-2 · channel-server EventBus 必须异步落盘**
- 热路径禁止等待 SQLite fsync；Event emit 采用 fire-and-forget + 批量 flush
- 超阈值动作: 超过 5ms 的 emit 调用告警

**NFR-3 · Plugin hook 单次执行 ≤ 50ms**
- 埋点: `plugin.hook_duration_ms` 按 plugin_name 分桶
- 实现: 慢活全部放 asyncio.create_task 后台执行，hook 本身立即返回

**NFR-4 · 强制同主机部署**
- channel-server 与所有 bridges（feishu_bridge / web_bridge）必须同 pod / 同主机 / localhost
- 跨主机部署需产品与 SRE 双重审批（会触发 RTT 10×）

**NFR-5 · Plugin 订阅细粒度化**
- 禁止 plugin 订阅 `message.*` 通配；必须按具体 event type 订阅，避免广播放大

**NFR-6 · 流式续写走 Coalescer**
- zchat feishu_bridge 的 CardRefreshCoalescer 必须启用（500ms 合并窗口）；AutoService 侧 Web 续写也走同级聚合

### 北极星指标
**每月升级转结案总数 × CSAT**

---

## 7. User Stories & Requirements

完整 user story 见 `AutoService-UserStories.md` v1.1（17 story，与 v1.0 一致；下方仅标注 v1.1 实现路径差异）。

### 实现路径映射（v1.1 更新）

| Story | 主要实现方 | 关键依赖 |
|---|---|---|
| US-1.1 上传资料生成 Agent | AutoService（admin-portal + kb_ingest） | — |
| US-1.2 一键权限 + 关联管理群 | **v1.1 调整**：管理群本期改为 **客服 Web 工作台的"通知中心"**；飞书管理群本期 out of scope，等 zchat feishu_bridge 成熟后接入 | zchat web_bridge |
| US-1.3 虚拟客户预演 | AutoService（admin-portal /wizard/step3） | sim_customer.py |
| US-1.4 合规预检 | AutoService（compliance.py + 16 条规则） | — |
| US-2.1 3 秒问候 | zchat（Mode=auto + sla_onboard Timer）+ AutoService（agent reply） | Bridge API |
| US-2.2 占位续写 | zchat（message.edit + Timer）+ AutoService（ModelRouter 快慢决策） | Bridge API |
| US-2.3 分队卡片 | AutoService（autoservice_squad.py plugin） | zchat Event Bus |
| US-2.4 Copilot 监管 | zchat（Mode=copilot + Gate）+ AutoService（Web 工作台 UI） | Bridge API |
| US-2.5 @人工 / /hijack | zchat（命令 + takeover_wait Timer） | — |
| US-2.6 角色翻转 | zchat（Mode=takeover + Gate）+ AutoService（接管次数计费） | mode.changed event |
| US-3.1 双账本仪表盘 | AutoService（admin-portal + metrics.py） | zchat Event Bus 查询 |
| US-3.2 管理群命令 | zchat（CommandParser）+ AutoService（业务响应） | — |
| US-3.3 SLA 告警 | AutoService（SLAAggregator + alerts.yaml） | zchat timer.expired 事件 |
| US-4.1~4.4 Dream Engine | 100% AutoService | — |

### Epic 假设（Hypothesis）

> **我们相信**: 如果中小商户能在 2 小时内自助上线一个"**Web 聊天页 + Copilot 默认 + Dream Engine 闲时自学习**"的 AI 客服系统,**那么**他们会获得 80% 重复咨询消化 + 92% 事实准确率 + 89% 升级结案率的稳态体验,**我们将看到** 付费留存 ≥ 70% 和 CSAT ≥ 4.5 作为证据。

### 约束与边缘情况（v1.1 补充）

- **反幻觉硬约束**: 查不到就转人工，禁止编造
- **合规硬约束**: GDPR / CCPA / PIPL 检查不阻塞沙箱，但阻塞对外开放
- **人工离线**: 超过 180s 未接单，卡片退回 Agent 并发安抚消息（由 zchat takeover_wait timer 触发）
- **并发上限**: 一个客服同时 Copilot ≤ 5 个对话（zchat `max_operator_concurrent=5` 协议级保障）
- **回滚**: `/rollback <proposal_id>` 立即撤回灰度中的梦境提案（AutoService 侧）
- **v1.1 新增** · **Web 页断线**: web_bridge 需维护重连 + 消息回放，客户刷新页面保持对话连续

---

## 8. Out of Scope（本版本不做）

- **飞书 / Lark 客户端作为首发渠道**（改为 zchat 第二阶段，具体时间由 zchat 项目决定）
- **其他 IM 渠道（微信/WhatsApp/Slack）** —— 全部交由 zchat 后续扩展
- **语音合成/识别的深度优化**
- **定制模型训练**
- **深度 CRM 双向写入**（本期只做单向推送线索）
- **白标**
- **移动端 App**（客户端 Web 页已是响应式；客服工作台本期只做桌面 Web）
- **PSTN 电话呼入**（延至 zchat 支持语音渠道后）

---

## 9. Dependencies & Risks

### 依赖（v1.1 调整）

| 类别 | v1.0 依赖 | v1.1 变化 |
|---|---|---|
| 对话引擎 | AutoService 自建 | **改为 zchat channel-server**（独立仓库） |
| IM 渠道 | 飞书为主 | **改为 Web 页为主**；飞书由 zchat 承接 |
| 基础设施 | 快慢双模型 · 多租户沙箱 · 灰度通道 | 同 v1.0 |
| 外部 | 20+ 语种 LLM | 同 v1.0 |
| 内部 OneSync | zchat v0.3.x（v1.0 仅作 IM 底层引用） | **升级为核心协议依赖**（channel-server + bridges） |
| 内部 OneSync | Socialware Role/Scope/Commitment/Flow | 同 v1.0 |
| 内部 OneSync | hackforger 设计系统"江峡泼墨" | 同 v1.0 |

### 风险与缓解（v1.1 更新）

| 风险 | 影响 | 缓解 |
|---|---|---|
| zchat 协议稳定性 | 本期阻塞核心链路 | 每周对齐 zchat 路线图；Bridge API 版本锁；契约测试 |
| **zchat 引入的延迟放大** | 占位 SLA(<1s) 劣化 | NFR-1~6（异步 EventBus + 同主机部署 + plugin timeout + 持续埋点监控） |
| zchat 交付延期 | AutoService 上线延期 | AutoService 先实现业务层逻辑（agent / Dream Engine / 合规），用 mock Bridge API 打通；切换成本低 |
| Web 端体验不及原生 IM | 商户认可度 | v1.1 以 Web 为 MVP 获首批 10 家内测；飞书端由 zchat 跟进做为差异化增值 |
| 反幻觉机制漏洞 | 高 | 双模型 cross-check + 知识库强约束 + 人工灰度 |
| 商户对"自助上线"期望过高 | 中 | 首屏明确标注"沙箱先行" |
| 闲时学习提案质量差 | 中 | 5% 灰度起步 + `/rollback` |
| 多租户数据串漏 | 致命 | zchat 每租户独立 project 进程隔离 + 每租户独立知识库 |
| SLA 达不成稳态 | 高 | 陪跑阶段承诺，不承诺首月达标 |

---

## 10. Open Questions

（沿用 v1.0 六条，**v1.1 新增**）：

1. **计费模式**: 阶梯 vs 订阅 + 超额 —— 定价团队 before Q3
2. **Copilot 提议采纳率**是否纳入计费?
3. **Agent 分队重分配**的原子性 —— zchat `/assign /reassign` 是否满足？
4. **闲时学习"做梦频率"**是每夜一次还是按对话量触发?
5. **PSTN 延迟预算**
6. **20+ 语种合规地区映射**按语言 vs 按商户地区（v1.1 采用按商户地区）
7. **v1.1 新增** · **客服工作台的 Web vs 飞书切换路径**：商户已有飞书工作环境的场景下，如何引导他们用 Web 工作台？是否需要双通道同时运行？
8. **v1.1 新增** · **zchat 跨租户事件查询的性能上限**：10k+ 对话/天 的租户的事件查询是否仍 <1s？

---

## 11. v1.0 → v1.1 Delta 汇总

| 条目 | v1.0 | v1.1 |
|---|---|---|
| 首发渠道 | 飞书 IM | 独立 Web 页（web_bridge） |
| 对话状态机 | AutoService 自建 `conversation.py` | zchat channel-server |
| 飞书卡片 / PATCH / 建群 | AutoService 自己调飞书 API | zchat feishu_bridge（后续） |
| 客服工作区 | 飞书分队群 | **Web 工作台**（MVP）；飞书端第二阶段 |
| SLA Timer | AutoService 实现 | zchat 7 类 Timer |
| Mode / Gate | 无显式协议 | zchat 协议级强制 |
| 计费指标来源 | App 内部计数 | zchat `mode.changed` 事件订阅 |
| AutoService 代码预计 | ~15000 行（含飞书） | **~13000 行（剥离 1845 + 新增 ~1100）** |

---

*文档所有者: Allen @ ezagent42 / OneSync · 基于 AutoService reveal.js deck v14/15 + zchat-plan v1.0 · 设计系统: 江峡泼墨*
