# AutoService M3 PRD

> **版本**：v1.0 · 正式
>
> **发布**：2026-04-21
>
> **作用域**：M3 里程碑（承接 M2 tenant-sandbox + triage dispatch）
>
> **前置**：[M2 tenant-sandbox design](../superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md)、[M3 triage dispatch design](../superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md)
>
> **源**：基于 draft [docs/plans/m3/2026-04-21-m3-prd-draft.md](../plans/m3/2026-04-21-m3-prd-draft.md)（A 2026-04-21 拍板"全部 P0+P1+P2"后转正）

---

## 1. 背景与目标

### 1.1 M2 交付基线

- Tenant sandbox fork runtime（`plugins/<tid>/souls/*` 全链路）
- 5 agent role 完整（customer / lead / translate / triage / dream）
- Dream agent + DreamScheduler 后台自动运行
- `_master` + `_local_admin` 内置租户
- Magic-link admin 鉴权（admin-portal 两端）
- **Triage 分流 dispatch**（2026-04-21 设计：customer 消息按意图路由到 customer/lead/translate）

### 1.2 M3 核心目标

**"让 M2 MVP 能真正开门做生意"**。具体：

1. **生产就绪**：operator 鉴权 + RBAC + 团队邀请（无此则任何商户都不敢部署）
2. **商业扩展**：subtenant 实体化（B 做 whitelabel/代理，开出 C）
3. **Triage 收尾**：兑现 M2 承诺的 handoff + SLA 监控；DB 化配置
4. **合规适配**：按 `tenant.countries` 过滤合规模板（PRD gap A-④ 收尾）
5. **Dream 扩展**：platform-level dream + 半自动 apply（**红线不动**：永不全自动）
6. **运营工具链**：沙盒 GC + Playwright E2E

### 1.3 非目标（明确推 M4+）

OAuth / SSO / 2FA / passkey；translate modality wrapper；path-2 summary-seeded 切换；合规规则热更新；Dream 跨租户学习；商户自定义域 + wildcard DNS；Dream 任何"自动 accepted"变体（**永不，CON-04 红线**）

---

## 2. Epic 清单（全量进 M3）

### Epic E1 · Identity & RBAC

**目标**：operator/client/admin 多层身份系统上线，支持 per-tenant 团队管理。

| Story | 描述 | 优先级 |
|-------|------|-------|
| **E1.1** | Operator 鉴权：登录 + session（SQLite）+ 强制 WS 握手校验 | P0 |
| **E1.2** | Per-tenant operator 列表 + CRUD | P0 |
| **E1.3** | Operator 团队邀请链接（magic-link 复用） | P0 |
| **E1.4** | RBAC 粗粒度三级：viewer / responder / admin + 权限矩阵 | P1 |
| **E1.5** | 多管理员登录（1 tenant 多 tenant_admin） | P1 |
| **E1.6** | Admin 邀请 admin 链接 | P2 |

**约束**：
- Session 存储用 SQLite（沿用 `.autoservice/database/sessions.db`；不引 Redis）
- RBAC 权限矩阵写死在代码里（非 runtime config）
- Operator session 和现有 magic-link cookie 分离 cookie 名（`operator_session` vs 现有 `admin_session`）

### Epic E2 · Subtenant 多层架构（tier_2 实装）

**目标**：B 的 tenant 可以再开 C（whitelabel / 代理模式），URL 走 `/t/<b>/t/<c>/`。

| Story | 描述 | 优先级 |
|-------|------|-------|
| **E2.1** | B 的 admin-portal 加 "Enable subtenant" 开关 | P1 |
| **E2.2** | 开关打开 → B 升级为 ControlLayout（仿 master layout） | P1 |
| **E2.3** | B 跑 subtenant 创建 wizard（ingest → soul gen → publish） | P1 |
| **E2.4** | `/publish` 走"fork 内 emplace"把 C 物料落到 `plugins/B/plugins/C/` | P1 |
| **E2.5** | C 租户计费归 B 账上（tier_2 费率；B 的月账单列 C 用量） | P2 |
| **E2.6** | C 租户合规独立于 B（C 可单独过 country filter） | P2 |

**约束**：
- URL 路径：`/t/<b_tenant_id>/t/<c_tenant_id>/...` —— 保留层级语义
- 计费归属：**归 B**——B 拿走 C 的钱，平台对 B 收 tier_2 费率
- B 能否看 C 的对话：默认不能；需 C 授权才可（M3.5 拓展）

### Epic E3 · Triage Dispatch 增强

**目标**：兑现 [M3 triage dispatch §0.2](../superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md) 标注的"M3 收尾"项。

| Story | 描述 | 优先级 |
|-------|------|-------|
| **E3.1** | **SLA 精细监控**：pool busy metrics 探测 + 等待时长 + per-tenant SLA 阈值告警 | P1 |
| **E3.2** | Handoff 协议：agent soul 约定 `<handoff to="X">`，parser 识别触发 re-triage | P1 |
| **E3.3** | DB-backed `classify_intent` 配置 + admin UI 关键词编辑器 | P2 |
| **E3.4** | 对话历史压缩服务（超 20 条 → LLM 摘要 → re-seed 用摘要） | P2 |

**约束**：
- **SLA 先做**（E3.1），Handoff（E3.2）后做——SLA 是 M2 承诺项，Handoff 依赖 agent 成熟度
- E3.3 的 admin UI 作为 admin-portal 扩展，不独立页面
- E3.4 历史压缩服务是通用基础设施，M3 只做 triage re-seed 用例；广泛铺开到 dream/triage agent 本身留 M4+

### Epic E4 · 合规深化

**目标**：PRD gap A-④ 收尾——合规模板按 `tenant.countries` 过滤。

| Story | 描述 | 优先级 |
|-------|------|-------|
| **E4.1** | 合规模板按 `tenant.countries` 过滤（当前 16 条一视同仁） | P1 |
| **E4.2** | 新增国家合规规则集（按需加 JP / SG / AU 等 3-5 国） | P2 |

**约束**：
- 国家代码用 ISO 3166-1 alpha-2
- 规则仍硬编码在仓库（热更新 M4+）

### Epic E5 · Dream 扩展

**目标**：Dream 产更有用的 proposal，但**红线不动**——永不自动应用。

| Story | 描述 | 优先级 |
|-------|------|-------|
| **E5.1** | Platform-level dream：master 端特殊 agent，看所有租户聚合信号，提议平台级改进（skill 优化 / cc_pool 策略） | P2 |
| **E5.2** | Dream proposal 半自动 apply：低风险 proposal 在 A review 后"点按钮一键应用"（仍需 A 触发，不自动） | P2 |

**红线约束**：
- `dream_agent.emit_proposal(status='draft')` 硬编码不动
- E5.2 的"apply 按钮"走独立函数 `apply_proposal(pid, admin_user_id)`——审计 admin 身份 + 对应 proposal 状态必须 `status='accepted'`（review 先置为 accepted，再 apply）
- **任何尝试让 dream agent 直接写 accepted/applied 的 PR 一律拒收**

### Epic E6 · 运营与部署

**目标**：支持规模化内测（5-10 租户）。

| Story | 描述 | 优先级 |
|-------|------|-------|
| **E6.1** | 沙盒 GC：超期未发布的沙盒归档清理 | P2 |
| **E6.2** | E2E Playwright 脚本化：17 story 自动化 | P2 |

**约束**：
- GC 默认 30 天未发布归档；可 tenant config 调
- Playwright 17 story 覆盖沿用 [旧 M5 Batch 14 的场景](../plans/batches-M1-to-M5-kickoff.md#L271-L296)，不重新设计
- Playwright 吃紧可退 **M3.5 迷你冲刺**（不阻塞 M3 gate）

---

## 3. 优先级 × 依赖

### 3.1 全量 P0/P1/P2 一览（18 story）

```
P0 (3)：E1.1 / E1.2 / E1.3  ─── 身份系统三件套
P1 (8)：E1.4 / E1.5 / E2.1-E2.4 / E3.1 / E3.2 / E4.1
P2 (7)：E1.6 / E2.5 / E2.6 / E3.3 / E3.4 / E4.2 / E5.1 / E5.2 / E6.1 / E6.2
```

### 3.2 依赖图

```
E1.1 Operator 鉴权 ──┬─▶ E1.2 CRUD
                    ├─▶ E1.3 邀请
                    ├─▶ E1.4 RBAC ──┬─▶ E2.2 ControlLayout ─▶ E2.3 Wizard ─▶ E2.4 Publish
                    │               │                                       │
                    │               └─▶ E1.6 Admin 邀请                      ├─▶ E2.5 计费
                    │                                                       └─▶ E2.6 合规
                    └─▶ E1.5 多管理员

E3.1 SLA 监控   ──────────────（独立，依赖 M2 cc_pool 懒子池）
E3.2 Handoff 协议 ────────────（独立，依赖 M2 triage dispatch）
E3.3 DB 化配置 ──▶ E3.4 历史压缩（独立）

E4.1 Country filter ─▶ E4.2 新国家规则集

E5.1 Platform dream ──┬─（独立，依赖 M2 dream 稳定）
E5.2 半自动 apply ────┘

E6.1 GC ─────────────（独立）
E6.2 Playwright ─────（独立，依赖 E1 完成——需要登录态）
```

---

## 4. 批次规划与时间线

### 4.1 批次表（8 批次 + gate）

| 批次 | 内容 | 预估 | 依赖 |
|------|------|------|------|
| **B-M3-0** | 契约冻结（Auth protocol / RBAC schema / Subtenant tier_2 schema / SLA metrics schema） | 1 天 | M2 完成 |
| **B-M3-1** | E1.1 + E1.2 + E1.3（身份 P0） | 2 天 | B-M3-0 |
| **B-M3-2** | E1.4 + E1.5（RBAC + 多管理员 P1） | 1.5 天 | B-M3-1 |
| **B-M3-3** | E2.1 + E2.2 + E2.3 + E2.4（Subtenant 核心 P1） | 3 天 | B-M3-2 |
| **B-M3-4** | E3.1 SLA + E3.2 Handoff（Triage 增强 P1） | 2 天 | M2 triage 稳定 |
| **B-M3-5** | E4.1 Country filter（合规 P1） | 1 天 | B-M3-0 |
| **B-M3-6** | E1.6 + E2.5 + E2.6 + E3.3 + E3.4 + E4.2 + E5.1 + E5.2 + E6.1（P2 批次） | 4 天 | B-M3-2/3 |
| **B-M3-7** | E6.2 Playwright E2E（P2 尾批，可退 M3.5） | 2 天 | B-M3-1 之后可并行 |
| **M3 gate** | smoke test + merge + tag v1.2.0 | 0.5 天 | 全部批次完成 |

**总预估**：**17 天**（B-M3-0 到 B-M3-7 合计 16.5 天 + 0.5 天 gate）

### 4.2 并行机会

- B-M3-4（Triage 增强）独立于 B-M3-1/2/3，可从 M3 开工 **Day 1** 并行启动
- B-M3-5（合规）独立，可从 M3 开工 Day 1 并行启动
- B-M3-7（Playwright）依赖 E1 完成，可从 B-M3-2 完成后并行

**压缩后关键路径**：B-M3-0 → B-M3-1 → B-M3-2 → B-M3-3 → B-M3-6 → gate，约 **12 天**。带并行批次（B-M3-4/5/7）就绪后，整体 M3 **12-14 天可收**。

### 4.3 里程碑时间线（参考 M2 节奏）

假设 2026-04-22 开工：

| 里程 | 日期 | 内容 |
|------|------|------|
| M3 kickoff | 04-22 | B-M3-0 启动 |
| Auth 上线 | 04-25 | B-M3-1 完成，operator 可登录 |
| RBAC 上线 | 04-27 | B-M3-2 完成 |
| Subtenant demo | 05-01 | B-M3-3 完成，B 可创建 C 做演示 |
| P1 全绿 | 05-02 | B-M3-4 + B-M3-5 完成 |
| P2 全绿 | 05-06 | B-M3-6 + B-M3-7 完成 |
| **M3 gate** | 05-07 | smoke test + merge + tag v1.2.0 |

如 B-M3-7 Playwright 推到 M3.5，gate 可提前到 05-05。

---

## 5. 已拍板决策（2026-04-21 A 确认）

| # | 决策 | 结论 | 理由 |
|---|------|-----|------|
| 1 | M3 完成定义 | 全部 P0+P1+P2 | A 明示；P3 明确推 M4+ |
| 2 | Session 存储 | SQLite | 沿用 `.autoservice/database/sessions.db`；不引 Redis（减少部署依赖） |
| 3 | RBAC 粒度 | 粗粒度三级（viewer/responder/admin） | 快速落地；permission matrix 推 M4+ |
| 4 | Subtenant URL | `/t/<b>/t/<c>/` | 保留层级语义；`/s/<c>/` 会失去 B→C 归属 |
| 5 | Subtenant 计费归属 | 归 B（tier_2 费率 B 收 C） | whitelabel 商业模式标配 |
| 6 | Triage Handoff vs SLA | **SLA 先**、Handoff 后 | SLA 是 M2 承诺项；Handoff 依赖 agent 成熟度 |
| 7 | Playwright E2E | 纳入 P2（E6.2） | 吃紧可退 M3.5，不阻塞 gate |

---

## 6. 成功标准（M3 gate 验收）

### 6.1 功能验收

- [ ] Operator 能登录、看到只属于自己 tenant 的 conversation（E1.1-E1.4）
- [ ] Tenant admin 能邀请 operator 团队成员（E1.3）
- [ ] 1 tenant 内能有 ≥2 个 admin，权限一致（E1.5）
- [ ] B 开启 subtenant → 跑 wizard → 创建 C → C 的 URL `/t/<b>/t/<c>/` 可访问并对话（E2.1-E2.4）
- [ ] B 的月账单里显示 C 用量 + 按 tier_2 费率计价（E2.5）
- [ ] Triage SLA 监控：pool 等待超阈值 → operator-console 告警（E3.1）
- [ ] Agent 输出 `<handoff to="lead">` → 自动 re-triage 切 role（E3.2）
- [ ] admin-portal 能编辑 classify_intent 关键词，热生效（E3.3）
- [ ] 对话 ≥20 条后切 role → 新 role 看到摘要而非全量历史（E3.4）
- [ ] 合规模板按 tenant.countries 过滤：US tenant 不看到 EU-only 规则（E4.1）
- [ ] Platform dream 能跑 + 产 platform-level proposal（E5.1）
- [ ] A 在平台 admin 点"应用" → proposal 真的落盘 + audit log（E5.2）
- [ ] 沙盒 30 天未发布自动归档（E6.1）
- [ ] Playwright 17 story 全绿或明确退 M3.5（E6.2）

### 6.2 非功能验收

- [ ] M2 全量回归绿（dream / triage / customer 对话 / magic-link admin）
- [ ] Operator WS 握手失败率 < 1%
- [ ] RBAC 决策 P95 < 5ms
- [ ] Subtenant 创建 wizard P95 < 60s
- [ ] M3 新增代码 test coverage ≥ 80%

### 6.3 文档与审计

- [ ] 每个 Epic 有对应 design spec 进 `docs/superpowers/specs/`
- [ ] `.artifacts/` 按 dev-loop 规范产 eval-doc / test-plan / test-diff / e2e-report
- [ ] M3 gate 后 tag `v1.2.0-mvp` 并更新 README

---

## 7. 与既有 spec 的边界

| Spec | 关系 |
|------|------|
| [M2 tenant-sandbox design](../superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md) | M3 所有 Epic 基于 M2 基线；不动 M2 交付物 |
| [M3 triage dispatch design](../superpowers/specs/2026-04-21-multi-role-triage-dispatch-design.md) | 本 PRD Epic E3 承接此 spec §0.2 延后项；其他 Epic 正交 |
| [Admin-portal web layout](../superpowers/specs/2026-04-18-admin-portal-web-layout-design.md) | E1 / E2 前端落地走 admin-portal；扩 operator login + ControlLayout + Subtenant wizard |
| [Takeover-release design](../superpowers/specs/2026-04-17-takeover-release-design.md) | E1.4 RBAC 影响 operator 能否 /hijack；需考虑权限矩阵 |

---

## 8. 不属于 M3 的候选项（放到 M4+ parking lot）

（保留自 draft §7，避免遗漏）

- OAuth / SSO / 2FA / passkey
- Translate modality wrapper
- Path 2 summary-seeded 切换
- 合规规则热更新（runtime 可改）
- Dream 跨租户学习（隐私评估未完）
- 商户自定义域 + wildcard DNS + domain_routing 表
- 多语言 UI 扩展（新增 ja/es/...）
- 知识库版本管理 + 回滚
- 对话质量评分（CSAT 模型 / 流失预警）
- 服务端压测 + 性能基线
- 跨 region 部署架构

---

## 8.1 Errata · 2026-04-21（Epic E2 全量 descope 到 M4+）

> **最终结论（A 2026-04-21 确认）**：**整个 Epic E2（所有 E2.1–E2.6）从 M3 移出，推迟到 M4+**。
>
> **证据链**：
> - [AutoService-PRD-v1.1.md](AutoService-PRD-v1.1.md) §8 Out of Scope 第 5 条：**"白标"明确不做**
> - [AutoService-UserStories-v1.1.md](AutoService-UserStories-v1.1.md) 17 个 user story **零条涉及 subtenant / tier_2 / 白标 / referral**
> - 源 v1.1 §5.2 AutoService 模块构成 A–E **无任何多层租户模块**
> - 本 M3 PRD（v1.0，2026-04-21）的 Epic E2 是**超 v1.1 范围的 scope 扩张**，未经 v1.2 PRD 或正式 addendum 授权
> - 按"PRD 没有就不做"原则（与 revshare% / B 端颗粒度同样处理），整个 E2 应当 descope
>
> **E2 拟过渡方案（平级 referral + Admin 审批）亦不采用**。M4+ 如需重启 whitelabel，必须先出 v1.2 PRD 或 M3 addendum 明确覆盖 v1.1 §8 的白标 OoS 条款。

### 过程记录（两阶段修正）

本次 errata 经历两步。先标记"架构修正"（嵌套→平级 referral），随后在查阅源 PRD v1.1 时发现 **Epic E2 整体就不在 v1.1 范围内**，故升级为**整体 descope**。以下记录供追溯：

**第一次修正（被第二次取代）**：Epic E2 从 "嵌套 tier_2" 改为 "平级 peer + referral 关系表 + Admin 审批"，消除 `/t/<b>/t/<c>/`、`plugins/B/plugins/C/`、ControlLayout、revshare% 等组件。

**第二次修正（最终决定）**：整个 Epic E2 descope 到 M4+，即便是平级 referral 方案也不在 M3 范围内。

### E2 处置总览（最终）

| Story | 原描述 | 处置 |
|----|----|----|
| **E2.1** | B admin-portal "Enable subtenant" 开关 | **DEFERRED_M4** |
| **E2.2** | B 升级 ControlLayout | **DEFERRED_M4** |
| **E2.3** | B 跑 subtenant 创建 wizard | **DEFERRED_M4** |
| **E2.4** | fork-内 emplace `plugins/B/plugins/C/` | **DEFERRED_M4** |
| **E2.5** | C 用量归 B、按 tier_2 费率 | **DEFERRED_M4** |
| **E2.6** | C 合规独立于 B | **DEFERRED_M4**（即便保留也天然被 E4.1 覆盖） |

### 决策覆盖

- **§5 决策 1（全部 P0+P1+P2）隐式收窄**：从 22 story 降为 **16 in-scope story**（E1:6 + E3:4 + E4:2 + E5:2 + E6:2），P0 仍 3、P1 从 9 降到 **5**、P2 从 10 降到 **8**
- **§5 决策 4（URL `/t/<b>/t/<c>/`）撤销**（随 E2 整体 descope）
- **§5 决策 5（tier_2 计费归 B）撤销**（v1.1 §8 白标 OoS）
- **CON-03 / CON-07 / CON-09 全部 DEFERRED_M4**（E2 衍生约束）
- **§4 批次表 B-M3-3（Subtenant 核心 3 天）删除**
- **§6.1 功能验收的 E2 相关 5 条删除**（operator 看 C、subtenant 创建、月账单 C 用量、handoff 不相关于 E2、合规按 countries 仍保留在 E4.1）

### 架构影响（最终）

- **关键路径缩短**：原预估 12-14 天 → **7-9 天**
- **Red-tier 任务清零**（原 E2.4 唯一 Red-tier 任务消失）
- **E1 RBAC 不再被 E2 阻塞**
- **§8 parking lot 新增条目**：`Subtenant / Whitelabel / Referral（完整 Epic E2 内容）`

### M4+ 重启前置条件

任何重启 subtenant / whitelabel / referral 的需求（包括本 errata 第一次修正提出的"平级 peer + Admin 审批"方案），必须满足：
1. 出 **v1.2 PRD** 或 **M3 addendum** 明确**覆盖 v1.1 §8 白标 OoS 条款**
2. 新增至少 3-5 个正式 user story（加入 UserStories v1.2）
3. 商业模型明确 revshare 计算公式 / 合同签约主体 / 合规归属 / 售卖合约
4. 架构决策：平级 + referral 表（本次方案）默认作为起点，但可被 v1.2 重新评估

### 下游文档修正（已完成）

- [docs/plans/m3/2026-04-21-prd-structure.yaml](../plans/m3/2026-04-21-prd-structure.yaml) —— E2 stories 全部 DEFERRED_M4，summary counts 更新
- [docs/plans/m3/2026-04-21-gap-analysis.yaml](../plans/m3/2026-04-21-gap-analysis.yaml) —— GAP-E2.* 全部标 DEFERRED_M4，critical path 移除 E2 依赖

---

## 9. 下一步

1. **M3 brainstorm**：针对每个 Epic 的关键设计点（比如 RBAC schema、Subtenant URL 路由机制、SLA metrics schema）走 `superpowers:brainstorming`→`writing-plans` 流程
2. **批次 B-M3-0 启动**：契约冻结（四个 schema）——第一优先，其他批次等契约签完再开
3. **在 `docs/plans/m3/` 建执行计划**：对齐 M2 的 `docs/plans/m2/` 结构（tasks.yaml / execution-plan.yaml / task-status.md）
4. **CLAUDE.md 里的 "plans_dir" 指向切换**：M2 gate 后 `project.yaml → plans_dir` 切 `docs/plans/m3`

---

## 附录 A · 术语表

| 术语 | 定义 |
|------|------|
| **Tier 0** | 平台（A 的 master 仓） |
| **Tier 1** | B 租户（fork 仓） |
| **Tier 2** | C 租户（B 的 subtenant，物料在 `plugins/B/plugins/C/`） |
| **Operator** | 客服员工——per-tenant，通过 operator-console 接入 |
| **Tenant admin** | 租户的管理员（B 或 C 的 admin）——通过 admin-portal 接入 |
| **Platform admin** | 平台管理员 = A——通过 master admin-portal 接入 |
| **Handoff** | Agent soul 主动输出 `<handoff to="X">` 触发 role 切换 |
| **SLA** | 目标 role pool 的等待时长阈值，超过即告警 |

---

*v1.0 · 2026-04-21 · A 拍板"全部 P0+P1+P2" + 6 项 delegate 决策后正式转正*
