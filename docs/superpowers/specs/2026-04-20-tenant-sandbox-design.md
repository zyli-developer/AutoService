# Tenant Sandbox & Deployment Model Design

> 2026-04-20 · 作用：确立 AutoService 的**双部署形态（Master / Tenant fork）**、**两层角色（平台方 A / 租户 B）**、**沙盒作为过渡产物**的架构，并把 admin 向导从"草稿生成器"升级为真正的沙盒 provisioning 链路
>
> 上游：
> - [docs/plans/2026-04-18-prd-full-journey-gap.md](../../plans/2026-04-18-prd-full-journey-gap.md) — P0 缺项 A-① / A-③ / B-⑦ / S1 / S2 / S4 / S6 / C-⑫
> - [docs/prd/autoservice-full-journey.html](../../prd/autoservice-full-journey.html) — 三幕 PRD

---

## 0. 问题与目标

### 0.1 为什么做这件事

当前 admin 向导实现和 PRD "沙箱先行 · 对外开放由商户拍板"的语义脱节；**更根本**的是，整个仓库没有显式区分"平台方视角"和"租户视角"，admin-portal 默认所有人看同一组数据，导致多租户语义混乱。

具体症状（10 处）：

| # | 现象 | 代码位置 |
|---|---|---|
| 1 | Step 0 生成的 4 角色 soul 草稿**不落盘**（`save_drafts()` 函数存在但没被调用） | [autoservice/onboarding.py:319-331](../../../autoservice/onboarding.py#L319-L331) |
| 2 | Step 4 "一键对外"按钮**无 onClick、无后端端点** | [frontend/apps/admin-portal/src/components/wizard/WizardTab.tsx:51](../../../frontend/apps/admin-portal/src/components/wizard/WizardTab.tsx#L51) |
| 3 | Step 1 渠道勾选**不进 config.json** | [onboarding.py:347-396](../../../autoservice/onboarding.py#L347-L396) |
| 4 | Step 2 预演对话审核结果**完全不持久化** | [api_routes.py:604-687](../../../autoservice/api_routes.py#L604-L687) |
| 5 | Step 0 上传的公司资料**没进 KB**（只临时抽文本送 soul_generator） | [onboarding.py:256-344](../../../autoservice/onboarding.py#L256-L344) |
| 6 | `/activate` **不幂等**，二次调用覆盖 config.json | [onboarding.py:360-385](../../../autoservice/onboarding.py#L360-L385) |
| 7 | cc_pool 无 per-tenant 加载能力 | [autoservice/cc_pool.py](../../../autoservice/cc_pool.py) |
| 8 | 三端前端**不读 tenant_id**，硬编码 `ws://localhost:8000/...` | [customer-chat/src/App.tsx:19](../../../frontend/apps/customer-chat/src/App.tsx#L19) 等 |
| 9 | Dream Engine 的 4 个配置参数（trigger/coverage/risk/canary）**只在内存**，从不落盘 | [api_routes.py:347-388](../../../autoservice/api_routes.py#L347-L388) |
| 10 | admin-portal 没有"平台方 / 租户方"模式概念，所有租户/平台信息混在同一组路由 | [frontend/apps/admin-portal/src/components/shell/AdminRail.tsx:12-18](../../../frontend/apps/admin-portal/src/components/shell/AdminRail.tsx#L12-L18) |

根因：**沙盒未作为一等实体** + **部署形态未区分 Master vs Tenant fork**。

### 0.2 本设计的 scope

**In scope (M1, local)：**
- 双部署模型确立（Master 主仓 / Tenant fork），但 **M1 只实现 Master 端**
- 沙盒目录 schema（`.autoservice/sandbox/<tenant_id>/`），Dream Engine **留位**（`souls/dream_soul.md` + `config.json.dream`）但 pipeline 不改造
- 向导各步骤产物落盘（souls / kb / rehearsal / config / dream 配置）
- Master 端 runtime 按 `tenant_id` 注入对应 soul（仅 soul 隔离，skills 走全局）
- Master 端三端 URL path 化 `/t/<tenant_id>/{chat|operator|admin}` + WS `?tenant=` 路由
- `/publish` 端点产出 tarball + 操作手册（**模拟 fork**，不跑 git）
- Publish 完成后沙盒归档到 `.autoservice/archived/<tid>_<ts>/`

**Out of scope：**
- Tenant fork 端部署（fork 单租户模式的实际运行，M2）
- admin-portal 双模式切换（`/api/session/mode` + MasterLayout/TenantLayout，M2）
- Dream Engine 升级为"带 soul 的独立 agent"（`soul_generator` 扩 5 角色 + `proposal_pipeline` 读 tenant soul，M2）
- 真 git fork 自动化（M2，留 `ForkCreator` 抽象接口）
- 团队邀请 / tenant_admin / operator 鉴权体系（M2）
- 线上域名 / wildcard DNS / 商户自定义域（M3+，见 §5.5）
- per-tenant skill 文件隔离 / per-tenant CC 进程（M2）

---

## 1. 架构总览（双部署模型）

### 1.1 两种部署形态

```
┌─────────────────────────────────────────────────────────────────────┐
│  MASTER 部署（本仓，A = 平台方运营）                                │
│  ───────────────────────────────────────────────────────────────── │
│  admin-portal = MasterLayout（有 wizard + 租户管理 + 代入预览）    │
│                                                                     │
│  .autoservice/sandbox/<tenant_id>/      ← 沙盒期：A 为 B 筹备       │
│    souls/, kb/, rehearsal.json, config.json                         │
│                                                                     │
│  预览/团队试用 URL (for tenant B during sandbox phase):             │
│    /t/<tenant_id>/chat        (B 的客户视角)                        │
│    /t/<tenant_id>/operator    (B 的客服视角)                        │
│    /master/tenants/<id>/preview (A 的管控视角)                      │
└────────────┬────────────────────────────────────────────────────────┘
             │ /api/onboard/publish → 生成 tarball + runbook
             │ 沙盒目录归档 → .autoservice/archived/<tid>_<ts>/
             ↓
             │ M1: A 按 runbook 手工 git fork
             │ M2: ForkCreator 自动化
             ↓
┌─────────────────────────────────────────────────────────────────────┐
│  TENANT FORK 部署（AutoService-B 独立仓，B = 租户方运营）           │
│  ───────────────────────────────────────────────────────────────── │
│  admin-portal = TenantLayout（无 wizard，只看自己数据）            │
│                                                                     │
│  plugins/<tenant_id>/       ← 沙盒 tarball 解压到这里               │
│    souls/, kb/, rehearsal_baseline.json, config.json, plugin.yaml   │
│                                                                     │
│  单租户 URL（无 /t/<tid>/ 前缀）:                                   │
│    /chat         /operator          /admin                          │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 角色层级（只有 2 层）

```
A = platform_admin (本仓 Master 部署)
    ├─ 能通过 wizard 创建 B/C/D/...
    ├─ 能"代入" B 的视角做 support / debug
    └─ 不存在"A 的租户"这回事 —— A 是平台方自己

B = tenant_admin (B 的 fork 部署)
    ├─ 只看自己 (B) 的数据
    ├─ 不能创建子租户（无 wizard）
    └─ 可以有自己的 operator 团队 (M2 的邀请流)
```

### 1.3 沙盒的"过渡"语义

- 沙盒存在于 **Master 端** `.autoservice/sandbox/<tid>/`，是 A 为 B 筹备时的临时工作区
- 沙盒也供 B 的试用团队（M2 的邀请流，或 M1 的简单 token）**实际对话测试**
- `/publish` 触发后：沙盒内容打 tarball → A 人工（M1）或自动（M2）建 B 的 fork → **沙盒目录移动到 `.autoservice/archived/<tid>_<ts>/`**
- B 的 fork 部署起来后，B 团队从 Master 的 `/t/<tid>/*` 迁移到 B 自己域名下的 `/chat /operator /admin`
- Master 端不再服务该 tenant 的对话流量（但保留 archive 供审计）

---

## 2. 沙盒目录 Schema

### 2.1 目录布局

```
.autoservice/sandbox/<tenant_id>/
├── config.json                        # 租户元信息 + 合规 + 渠道 + dream 配置
├── souls/
│   ├── customer_soul.md               # 客户接待 agent 人格
│   ├── translate_soul.md              # 翻译 agent
│   ├── lead_soul.md                   # 线索 agent
│   ├── triage_soul.md                 # 分流 agent
│   ├── dream_soul.md                  # Dream Engine（M1 占位，见 §2.5）
│   └── _generation_meta.yaml          # 生成来源 / KB hit 数 / warning
├── kb/
│   └── kb.db                          # tenant 独立 FTS5 SQLite
└── rehearsal.json                     # 预演对话 + 审核状态（12 条）
```

### 2.2 `config.json` 扩展

在现有 16 条合规字段基础上追加：

```jsonc
{
  "tenant_id": "tenant_8f3a12bd",
  "brand_name": "mystore",
  "industry": "ecommerce",
  "created_at": "2026-04-20T10:30:00Z",
  "status": "sandbox",              // sandbox | published_pending_fork | archived
  "channels": ["web"],              // ← 新：修复 bug #3
  "compliance": { ... 原 16 条 },
  "soul": { ... 原 4 开关 },
  "dream": {                        // ← 新：修复 bug #9，M1 只落盘不执行
    "trigger": "idle",              // idle | scheduled | manual
    "coverage": "all",              // all | sampled | category-specific
    "risk_threshold": "medium",     // low | medium | high
    "canary": { "stages": [5, 25, 100], "observe_hours": 24 }
  }
}
```

> `countries` 字段（gap A-④ 合规模板按国家过滤）**不在 M1 scope**，M2 同合规 filter 一起做。

`status` 转换：
- `sandbox` → `published_pending_fork`：由 `/publish` 翻转；沙盒进入只读
- `published_pending_fork` → `archived`：由归档步骤翻转并物理移动到 `.autoservice/archived/`

### 2.3 `rehearsal.json` 格式

```jsonc
{
  "generated_at": "2026-04-20T10:45:00Z",
  "demo_mode": false,
  "dialogs": [
    {
      "id": "d1",
      "scenario": "complaint",
      "persona": "angry-refund",
      "language": "zh",
      "turns": [
        { "role": "customer", "text": "..." },
        { "role": "agent", "text": "..." }
      ],
      "review_status": "approved",       // pending | approved | flagged
      "review_note": "",
      "reviewed_at": "2026-04-20T10:48:00Z"
    }
  ]
}
```

### 2.4 KB 构建（修复 bug #5）

Step 0 `/upload` 新增 ingest 步骤：

```
抽文本（已有）
  → 分块（4000 char, 200 overlap，已有）
  → 写入 .autoservice/sandbox/<tenant_id>/kb/kb.db
    表：kb_chunks(id, content, source_name, section, domain)
    FTS5 索引：kb_fts
  → 返回 chunk 总数给 UI
```

KB 查询路径优先级：
```
.autoservice/sandbox/<tenant_id>/kb/kb.db   (沙盒)
  fallback → plugins/<tenant_id>/kb/kb.db   (fork 已发布)
  fallback → .autoservice/database/knowledge_base/kb.db  (全局共享)
```

### 2.5 Dream Engine 的 M1 留位策略

**目标**：Dream Engine 架构定位是**独立 agent = 企业自我进化引擎**（和 customer/translate/lead/triage 同级）。但当前实现是 Python pipeline（`proposal_pipeline.py` 等），不带 soul。M2 要做的改造是 `soul_generator` 扩 5 角色 + `proposal_pipeline` 读 tenant soul。

**M1 留位做法**：
1. 沙盒 `souls/dream_soul.md` 写一个**静态默认模板**（非 LLM 生成，内容就是当前 pipeline 的硬编码行为的自然语言描述），让 publish tarball 的产物结构对齐 M2 的预期
2. `config.json.dream` 正式落盘 4 个参数（修复 bug #9 的主要目的）
3. `proposal_pipeline.py` / `dream_config_dialog.py` 代码**不改**——仍读内存；但 `/api/management/chat` 收到 `/dream-config` 命令时**额外把结果 sync 到沙盒 config.json.dream**（单向写入，read 仍走内存）
4. M2 来做真正的"dream agent reads tenant soul"改造

这个策略让 publish tarball 结构一步到位，同时保留 M1 的改动最小。

---

## 3. 向导步骤落盘行为变更（Master 端）

### 3.1 Step 0 `/upload`（修复 bug #1, #5）

新增三个磁盘动作：

1. **写 KB**：抽出的文本块写入 `.autoservice/sandbox/<tenant_id>/kb/kb.db`
2. **写 souls**：调 `soul_generator.save_drafts()` 把 4 个 `*_soul.md` + `_generation_meta.yaml` 写入 `.autoservice/sandbox/<tenant_id>/souls/`；同时拷贝静态 `dream_soul.md` 模板
3. **写 config 骨架**：此时先写 `config.json` 的 `tenant_id / brand_name / industry / status:"sandbox" / created_at`，合规和 dream 字段留默认

> **目录位置调整**：`soul_generator.save_drafts` 的目标从原 `plugins/<tenant_id>/souls_draft/` 改为 `.autoservice/sandbox/<tenant_id>/souls/`——因为 `plugins/` 是 fork 发布后才占据的位置。

### 3.2 Step 1 `/activate`（修复 bug #3, #6）

改为幂等 merge 而非覆盖：

```python
def activate_sandbox(tenant_id, channels):
    path = f".autoservice/sandbox/{tenant_id}/config.json"
    cfg = json.loads(Path(path).read_text())       # Step 0 已写
    cfg["channels"] = channels                     # 修复 bug #3
    cfg.setdefault("compliance", DEFAULT_COMPLIANCE)
    cfg.setdefault("soul", DEFAULT_SOUL_CFG)
    cfg.setdefault("dream", DEFAULT_DREAM_CFG)
    Path(path).write_text(json.dumps(cfg, indent=2))
    return build_urls(tenant_id, channels)         # URL path 形态，见 §5
```

### 3.3 Step 2 `/rehearsal/generate` + 新增 `/rehearsal/review`（修复 bug #4）

- `/rehearsal/generate` 产出后**落盘** `.autoservice/sandbox/<tenant_id>/rehearsal.json`（初始全 `review_status: "pending"`）
- 新增 `POST /api/rehearsal/review`：`{tenant_id, dialog_id, review_status, review_note}` → 更新 rehearsal.json 对应条目
- 前端刷新时读 rehearsal.json 还原审核进度

### 3.4 Step 3 `/compliance/check` — 不变

纯只读；保留 advisory-only（不阻断向导）；阻断发生在 `/publish` gate。

### 3.5 Dream Engine 配置落盘（修复 bug #9）

`/api/management/chat` 收到 `/dream-config` 的确认命令时，把 `DreamConfigSession` 的 4 参数 sync 到 `.autoservice/sandbox/<tenant_id>/config.json.dream`。读取链路不改（仍从内存读），只加单向写入，避免改动 dream pipeline。

### 3.6 Step 4 — 新增 `/publish` 端点

见 §6。

---

## 4. 运行时加载（Master 端沙盒的 soul 注入）

### 4.1 路由层

`TenantContext` 中间件：
- HTTP：从 URL path `/t/<tenant_id>/...` 提取
- WS：从 query `?tenant=<tenant_id>` 提取
- 挂到 `request.state.tenant_id`

### 4.2 Session → soul 注入

[cc_pool.py](../../../autoservice/cc_pool.py) 的 `create_cc_client()` 接收 optional `tenant_id`：

```python
def create_cc_client(self, role: str, tenant_id: str | None = None):
    soul = _load_soul(tenant_id, role) if tenant_id else DEFAULT_SOULS[role]
    return CCClient(system_prompt=soul, ...)

def _load_soul(tenant_id: str, role: str) -> str:
    # 沙盒期
    p = Path(f".autoservice/sandbox/{tenant_id}/souls/{role}_soul.md")
    if p.exists():
        return p.read_text()
    # 已归档（审计访问）
    # Fork 期不走这条路径——fork 仓直接读自己的 plugins/<tid>/souls/
    return DEFAULT_SOULS[role]
```

**cc_pool 本身不分池**——池仍全局共享，只是每次 `create_cc_client` 返回的 client 实例带 tenant 专属 system prompt。这是 Option 2A 的核心简化。

> **注入时机**：soul 作为 session 第一条 system/user 消息传入，**不在 CC 进程启动阶段烘焙**。这样 pool 里已 warm 的 worker 保持 generic，领到任务时才绑定 tenant。如果现有 `cc_pool` 必须在启动时固定 system prompt（具体在 writing-plans 阶段核实），则改为"按 tenant 维护小池 + LRU 回收"，但仍不改变 §4.1 的路由层接口。

### 4.3 KB 查询

KB 查询工具统一接受 `tenant_id`，按 §2.4 优先级查。沿用 [api_routes.py:565-573](../../../autoservice/api_routes.py#L565-L573) 的 `_get_kb_path()` 模式扩展到所有 KB 读取点。

---

## 5. 部署模式与 URL 设计

### 5.1 双部署的关键差异

| 维度 | Master（本仓，A 运营） | Tenant fork（B 运营，M1 不实现） |
|---|---|---|
| 租户数 | N（A 筹备的所有 B/C/D…） | 1（仅自己） |
| admin 布局 | MasterLayout | TenantLayout |
| URL 前缀 | `/master/*` + `/t/<tid>/*` | 无前缀 `/chat` `/admin` |
| wizard | ✅ | ❌ |
| 租户列表 | ✅ | ❌ |
| 代入预览 | ✅（A 可切换看任意 B） | ❌ |
| 自身数据 | 通过代入上下文 | 天然单租户 |
| 部署来源 | 本仓直接跑 | `/publish` tarball 解压后的 fork 仓 |

### 5.2 Master 端路由（M1 实现）

| 角色 | URL | tenant 提取 |
|---|---|---|
| A 租户列表 | `http://localhost:8000/master/tenants` | （无） |
| A 新建租户向导 | `http://localhost:8000/master/tenants/new` | （创建过程中生成） |
| A 代入 B 的预览 | `http://localhost:8000/master/tenants/<tid>/preview` | path |
| 客户体验（for B 团队/A 验证） | `http://localhost:8000/t/<tid>/chat` | path |
| 客服工作台预览 | `http://localhost:8000/t/<tid>/operator` | path |
| WS（客户） | `ws://localhost:8000/ws/customer?tenant=<tid>` | query |
| WS（客服） | `ws://localhost:8000/ws/operator?tenant=<tid>` | query |

前端三个 app 引入通用 hook（修复 bug #8）：

```ts
// frontend/packages/shared/useTenantId.ts
export function useTenantId(): string | null {
  const { tenantId } = useParams();
  return tenantId ?? new URLSearchParams(location.search).get("tenant");
}
```

所有 WS/API 连接点读 `useTenantId()`；硬编码地址全部替换。路由：
- customer-chat: `/t/:tenantId/chat` → App
- operator-console: `/t/:tenantId/operator` → WorkspacePage
- admin-portal: 保留当前 `/admin/*` 路由；新增 `/master/*` 路由组

### 5.3 admin-portal 双模式（**设计，M1 只做 Master**）

目标：同一份代码，运行时切换：
```
GET /api/session/mode
→ {"mode": "master", "role": "platform_admin"}    ← Master 部署
或
→ {"mode": "tenant", "role": "tenant_admin",      ← Tenant fork 部署
   "tenant_id": "B"}
```

**前端逻辑（M1 只实现 master 分支）**：
```tsx
// App.tsx
const { mode } = useSessionMode();
return mode === "master" ? <MasterLayout /> : <TenantLayout />;
```

**MasterLayout 路由**（M1 实现）：
```
/master/tenants            → TenantListTab
/master/tenants/new        → WizardTab（当前 WizardTab 迁移到这）
/master/tenants/:id/preview → TenantPreviewTab（iframe 嵌入 /t/<tid>/chat）
/admin/*                    → 原有 tab 组（Dashboard/Proposals/Billing/ManagementChat）
                              M1 保持不变，显示平台级数据（不过滤到特定 tenant）；
                              tenant 过滤是 M2 的事（含 admin-portal TenantLayout 上线）
```

> M1 对 `/admin/*` 的 4 个 tab **不做改造**——它们继续读平台级聚合数据。原因是：真正的 per-tenant tab 数据消费场景是 Tenant fork 部署里 B 自己看自己的数据，而 Master 里 A 要看某个具体 B 的数据只是偶发的 support 需求，M1 先通过 `/master/tenants/:id/preview` 的 iframe 预览满足 90% 场景。

**TenantLayout 路由**（M2 实现，M1 只留 stub）：
```
/admin/dashboard /admin/proposals /admin/billing /admin/management-chat
                              数据直接是 fork 仓 config.json.tenant_id 的
```

### 5.4 Tenant fork 端 URL（**设计，M1 不实现**）

Fork 仓单租户部署，URL 无前缀：
```
/chat           /operator           /admin/<subtab>
ws://.../ws/customer    ws://.../ws/operator
```

后端的 `tenant_id` 来自 fork 仓的 `plugins/<tid>/config.json`（启动时加载为 `ENV["TENANT_ID"]`），不再从 URL 提取。为兼容 path 形式（例如 subdomain + path 路由），fork 也接受 `/t/<tid>/*` 形态并做 assertion：URL 里的 tid 必须等于 fork 自己的 tid。

### 5.5 生产期主域名设计（**只设计不实现**，M3+）

| 场景 | URL 形态 | 路由机制 |
|---|---|---|
| 客户聊天嵌入商户自家站 | `<script src="autoservice.com/sdk.js" data-tenant="X">` | SDK 初始化读 `data-tenant` → WS 回 `autoservice.com/ws/customer?tenant=X` |
| 客服工作台（平台托管） | `console.autoservice.com/t/<tid>` | Wildcard DNS + ingress path 路由 |
| 商户管理（默认） | `admin.autoservice.com/t/<tid>` | 同上 |
| 商户管理（自定义域） | 商户 CNAME → `autoservice.com`，边缘读 Host header → 查域名→tid 映射 | 需额外 `domain_routing` 表（M3+） |

Sandbox 的 path-based URL 和生产的 "subdomain + path" 前端代码一致（`useTenantId()` hook 屏蔽差异），部署时 ingress 配置不同。

---

## 6. Publish Gate

### 6.1 `POST /api/onboard/publish`

入参：`{tenant_id, override_compliance_critical?: bool, signer?: str}`

```python
def publish(tenant_id, override=False, signer=None):
    # 1. Gate 检查
    gate = _check_publish_gate(tenant_id)
    if gate.blocked and not (override and signer):
        return 409, gate

    # 2. 打包
    archive_path = _build_publish_archive(tenant_id)

    # 3. 发布记录
    record = _write_publish_record(tenant_id, archive_path, gate)

    # 4. 冻结沙盒 config
    _freeze_sandbox(tenant_id, status="published_pending_fork")

    # 5. 生成操作手册
    runbook_path = _write_runbook(tenant_id, archive_path)

    # 6. 归档沙盒目录
    _archive_sandbox(tenant_id)    # .autoservice/sandbox/<tid>/ → .autoservice/archived/<tid>_<ts>/

    return 200, {
        "artifact": archive_path,
        "runbook": runbook_path,
        "record": record,
        "archived_to": f".autoservice/archived/{tenant_id}_{ts}/",
    }
```

### 6.2 Gate 条件

| 检查项 | 来源 | 失败后果 |
|---|---|---|
| 合规 `risk_level` ≠ `critical` | 调用 `ComplianceEngine.scan()` | 拒绝；可 `override=true + signer=<email>` 放行，记入 record |
| 12 条预演全部 `review_status` ≠ `pending` | 读 `rehearsal.json` | 拒绝（无 override） |
| 4 soul 文件齐全（不含 dream，dream 是 M1 占位） | 读 `souls/*.md` | 拒绝（防御性） |
| KB chunks ≥ 50 | 查 `kb/kb.db` `COUNT(*)` | 警告但放行 |

### 6.3 打包产物

`archive_path` = `.autoservice/published/tenant_<tid>_publish_<YYYYMMDD-HHMMSS>.tar.gz`

内容（解压后，即 fork 仓 `plugins/<tenant_id>/` 的样子）：

```
plugins/<tenant_id>/
├── plugin.yaml                      # 自动生成
├── config.json                      # 从 sandbox 复制
├── souls/
│   ├── customer_soul.md
│   ├── translate_soul.md
│   ├── lead_soul.md
│   ├── triage_soul.md
│   ├── dream_soul.md                # M1 静态模板
│   └── _generation_meta.yaml
├── kb/kb.db
├── rehearsal_baseline.json          # 审核过的 12 条作为回归基线
└── README.md                        # 自动生成：租户元信息 + 部署步骤
```

**`plugin.yaml` 自动生成（M1 最小化）**：
```yaml
name: <tenant_id>
version: 1.0.0
description: Tenant plugin for <brand_name> (<industry>)
mode: production
mcp_tools: []          # 沙盒阶段无自定义工具
http_routes: []
```

### 6.4 发布记录 + 归档

`.autoservice/published/<tenant_id>.json`

```jsonc
{
  "tenant_id": "tenant_8f3a12bd",
  "published_at": "2026-04-20T14:32:10Z",
  "source_sandbox_archived_to": ".autoservice/archived/tenant_8f3a12bd_20260420-143210",
  "artifact": ".autoservice/published/tenant_8f3a12bd_publish_20260420-143210.tar.gz",
  "artifact_sha256": "...",
  "runbook": ".autoservice/published/tenant_8f3a12bd_PUBLISH_RUNBOOK.md",
  "status": "awaiting_fork",
  "pre_publish_checks": {
    "compliance_risk": "low",
    "compliance_override": false,
    "rehearsal_reviewed": 12,
    "souls_saved": 4,
    "kb_chunks": 342
  }
}
```

### 6.5 操作手册（auto-generated markdown）

```markdown
# Tenant <tenant_id> 发布手册

本文件由 /api/onboard/publish 于 <timestamp> 自动生成。

## 手动步骤（M1）

1. Fork 主仓:
   gh repo fork ezagent42/AutoService --fork-name AutoService-<tenant_id>

2. Clone 新 fork:
   git clone git@github.com:<your>/AutoService-<tenant_id>.git

3. 解压 tenant 内容:
   tar -xzf <artifact_path> -C AutoService-<tenant_id>/

4. 验证:
   cd AutoService-<tenant_id> && make check && make run-web

5. 冒烟测试:
   访问 http://localhost:8000/chat 对话一条（Tenant fork 模式，无 /t/<tid>/ 前缀）

6. 部署（参照 infra 文档）
```

### 6.6 ForkCreator 抽象（M2 预留）

```python
class ForkCreator(Protocol):
    def create(self, tenant_id: str, artifact_path: Path) -> ForkResult: ...

class LocalTarballForkCreator:           # M1 默认
    """产出 tarball + runbook，不实际建仓。"""

class GitHubApiForkCreator:               # M2 占位
    """调 gh CLI / GitHub API 自动 fork + push + 触发 CI。"""
    raise NotImplementedError
```

`/publish` 调 `ForkCreator.create()`；M1 注入 `LocalTarballForkCreator`，M2 切到 `GitHubApiForkCreator` 时 `/publish` 端点零改动。

---

## 7. 冻结、归档与回滚

### 7.1 冻结

`_freeze_sandbox(tenant_id, status="published_pending_fork")`：
- 写 `config.json.status`
- **不改 FS 权限**（跨平台麻烦），改由所有沙盒写路径（Step 1~3 的落盘、/rehearsal/review、/dream-config sync 等）统一检查 status：≠ `"sandbox"` 则返回 409

### 7.2 归档

`_archive_sandbox(tenant_id)`：
- 把 `.autoservice/sandbox/<tid>/` 物理移动到 `.autoservice/archived/<tid>_<ts>/`
- 归档目录保留 config.json 的 `status` 更新为 `archived`
- Master runtime 的 `/t/<tid>/*` 在归档后返回 410 Gone + 指引用户去 fork 域名

### 7.3 回滚（解归档）

`POST /api/onboard/unfreeze`：`{tenant_id, reason}` → 把归档目录移回沙盒，status 改回 `sandbox`。M1 实现，用于本地调试/误发布。

---

## 8. 明确 YAGNI

| 不做 | 原因 |
|---|---|
| Tenant fork 部署实际运行 | M2；M1 验证 Master 端链路 + tarball 产物 |
| admin-portal TenantLayout 实现 | M2；M1 只在代码里留 mode 分支 stub |
| Dream Engine 升级为"带 soul 的独立 agent" | M2；M1 只落盘 dream 配置 + souls/dream_soul.md 静态模板 |
| 真 git fork 自动化 | M2 |
| 团队邀请 / tenant_admin / operator 鉴权 | M2 |
| per-tenant skill 文件隔离 / per-tenant CC 进程 | M2 |
| 租户 DB/进程隔离 | 目录隔离 M1 已够；见 gap S1 |
| wildcard DNS / ingress 配置 | M3+ |
| 商户自定义域 CNAME | M3+；需 `domain_routing` 表 |
| 沙盒 GC（清理超期未发布） | M2 运维工具 |
| 多并发沙盒资源上限 | 监控/限流，观察到瓶颈再做 |
| 合规模板按 `countries` 过滤（gap A-④） | M2，需同时改前端表单 |

---

## 9. 对现有代码的具体改动清单

### 后端

| 文件 | 改动 |
|---|---|
| [autoservice/onboarding.py](../../../autoservice/onboarding.py) | `/upload` 调 `save_drafts()` + KB ingest + 拷贝 `dream_soul.md` 模板；`/activate` 改幂等 merge；URL 模板改 path 形态 |
| [autoservice/soul_generator.py](../../../autoservice/soul_generator.py) | `save_drafts` 目标目录从 `plugins/<tid>/souls_draft/` 改到 `.autoservice/sandbox/<tid>/souls/` |
| [autoservice/api_routes.py](../../../autoservice/api_routes.py) | 新增 `/api/session/mode`、`/api/rehearsal/review`、`/api/onboard/publish`、`/api/onboard/unfreeze`；`/rehearsal/generate` 落盘；`_get_kb_path()` 加 sandbox 前缀；`/api/management/chat` 在 `/dream-config` 确认时 sync 到 `config.json.dream` |
| [autoservice/cc_pool.py](../../../autoservice/cc_pool.py) | `create_cc_client(role, tenant_id=None)` + `_load_soul()` |
| 新增 [autoservice/publish.py](../../../autoservice/publish.py) | `_build_publish_archive` / `_check_publish_gate` / `_write_publish_record` / `_write_runbook` / `_archive_sandbox` / `ForkCreator` 协议 + `LocalTarballForkCreator` |
| 新增 [autoservice/dream_soul_template.md](../../../autoservice/dream_soul_template.md) | 静态模板，`/upload` 时拷贝到沙盒 |

### 前端

| 文件 | 改动 |
|---|---|
| 新增 `frontend/packages/shared/useTenantId.ts` | 通用 hook |
| 新增 `frontend/packages/shared/useSessionMode.ts` | 调 `/api/session/mode`；M1 master 分支可用，tenant 分支 stub |
| [frontend/apps/customer-chat/src/App.tsx](../../../frontend/apps/customer-chat/src/App.tsx) | 路由 `/t/:tenantId/chat` + `useTenantId()` 替换硬编码 |
| [frontend/apps/operator-console/src/components/WorkspacePage.tsx](../../../frontend/apps/operator-console/src/components/WorkspacePage.tsx) | 同上，`/t/:tenantId/operator` |
| [frontend/apps/admin-portal/src/App.tsx](../../../frontend/apps/admin-portal/src/App.tsx) | 根据 `useSessionMode` 渲染 `MasterLayout`（M1）或 `TenantLayout` stub |
| 新增 `frontend/apps/admin-portal/src/layouts/MasterLayout.tsx` | 带 wizard + 租户列表 + `/master/*` 路由 |
| 新增 `frontend/apps/admin-portal/src/layouts/TenantLayout.tsx` | M1 只是 stub（渲染"feature not available in M1"） |
| 新增 `frontend/apps/admin-portal/src/components/master/TenantListTab.tsx` | 列出所有沙盒租户，点击进入 preview |
| 新增 `frontend/apps/admin-portal/src/components/master/TenantPreviewTab.tsx` | 代入某 tenant 视角，嵌入 customer-chat iframe (`/t/<tid>/chat`) |
| [frontend/apps/admin-portal/src/components/wizard/WizardTab.tsx](../../../frontend/apps/admin-portal/src/components/wizard/WizardTab.tsx) | 路由从 `/admin/wizard` 迁到 `/master/tenants/new`；Step 4 "一键对外"接 `/onboard/publish`；Step 2 审核接 `/rehearsal/review` |

---

## 10. M1 成功验收

走完以下链路即为 M1 完成（不含 UI 美观度）：

1. **A 打开 Master**：访问 `http://localhost:8000/master/tenants` 看到空租户列表
2. **A 走向导**：`/master/tenants/new` → Step 0 上传 → Step 1 渠道 → Step 2 预演 + 审核 → Step 3 合规 → Step 4 沙盒就绪
3. **沙盒产物齐全**：`.autoservice/sandbox/<tid>/` 下 `souls/` 有 4 个 md + `dream_soul.md` 占位、`kb/kb.db` 有 >0 chunk、`rehearsal.json` 有 12 条全 reviewed、`config.json` status=`sandbox` 且 `channels`、`dream` 字段正确
4. **Master 沙盒预览可用**：访问 `/t/<tid>/chat` 能对话，WS 日志可见 `tenant_id=<id>` 上下文
5. **多租户隔离**：同时启两个沙盒 X 和 Y，`/t/X/chat` 和 `/t/Y/chat` 的 agent 用各自 soul（回复风格可肉眼区分）
6. **A 代入预览**：`/master/tenants/<tid>/preview` 能嵌入展示 `/t/<tid>/chat`
7. **Dream 配置落盘**：在 ManagementChat 里走完 `/dream-config`，`config.json.dream` 有 4 参数
8. **Publish 完整产物**：Step 4 点"一键对外" → 后端产 tarball + runbook + record → 沙盒物理移动到 `.autoservice/archived/<tid>_<ts>/` → `/t/<tid>/chat` 开始返回 410
9. **Fork 手工验证**：tarball 解压得到的 `plugins/<tid>/` 手工 git mv 到一个 fork 仓，`make check` 通过（不要求实际跑起来，那是 M2）

---

## 11. 里程碑

- **M1（本 spec）**：Master 端沙盒链路 + path URL + 模拟 publish + soul 注入 + Dream 配置落盘 + 双模式骨架（只 master）
- **M2**：Tenant fork 模式完整实现 + ForkCreator 自动化 + admin-portal TenantLayout + Dream Engine 升级为带 soul 独立 agent + per-tenant skill 隔离 + 团队邀请与鉴权 + 沙盒 GC
- **M3+**：线上 wildcard DNS / ingress / 商户自定义域 / `domain_routing` 表 / 合规模板 by `countries`

---

*2026-04-20 · 基于 brainstorm：Option A（沙盒=目录、发布=fork）+ Option 2A（仅 soul 隔离）+ URL path 形态 + 模拟 publish tarball + Master/Tenant 双部署模型（M1 只做 Master）+ Q1-B/Q4-B/Q5-B（Dream/双模式/邀请均 M1 留位、M2 实现）*
