# Tenant Sandbox M2 — Fork Runtime & Dream Agent Design

> 2026-04-20 · M2 设计。承接 [M1 tenant-sandbox design](./2026-04-20-tenant-sandbox-design.md)。
>
> **一句话**：M1 产出 tarball + runbook 但没验证 fork 跑起来；M2 让 tarball → 真部署能对话、dream agent 真跑、A 能在 master 端和 `_master` 租户做自我迭代演示。

---

## 0. Scope 与和 M1 的连接

### 0.1 In scope

- **Tenant fork runtime 真跑**：fork 仓以 `deployment_mode=tenant` 启动，5-agent 栈全部使用 `plugins/<tid>/souls/*`，URL 无 `/t/<tid>/` 前缀
- **ForkCreator 自动化最小落地**：保留 `LocalTarballForkCreator` 为默认；新增 `GitHubApiForkCreator`（gh CLI subprocess 版）；`config.local.yaml.fork_creator` 切换
- **admin-portal TenantLayout** 最小闭环：`useSessionMode` 返 `tenant` → 渲染 TenantLayout，4 tab（Dashboard / Proposals / Billing / Chat）；无 wizard、无租户列表
- **Dream agent 升级为租户第 5 角色**：`soul_generator` 扩 5 角色（LLM 生成 `dream_soul.md`）；`proposal_pipeline` 改为 agent 驱动（带 soul、通过 cc_pool 跑、走 tool-use）；`DreamScheduler` 按 `config.json.dream.trigger` 自动唤醒
- **Master-as-tenant `_master` 自迭代**：Master 部署内置 `_master` 租户，A 的 ManagementChat 实际和 `_master` 的 customer agent 对话；`_master` 自己的 dream 看 A 的对话、提议改 `_master` 自己的 soul
- **Fork 端 `_local_admin` 对称**：fork 部署也内置 `_local_admin` 租户作为 B 的 admin 助手对话伙伴
- **Magic-link 鉴权**：admin-portal 登录（master + tenant 两端）；operator/client 继续裸奔
- **per-tenant skill 隔离**：fork 模式下 `make setup` 把 `plugins/<tid>/skills/` symlink 到 `.claude/skills/`
- **2 层 tier 模型 + subtenant 留痕**：`config.json.tier` 字段区分 `_master`(0) vs 普通租户(1)；`tier=2` subtenant 预留字段，M2 不实现

### 0.2 Out of scope（推到 M3+）

- Subtenant（tier=2）实体化（B 创建 C 的 wizard / whitelabel 能力）
- Operator / client 鉴权；团队邀请；RBAC
- 平台级 dream（看所有租户聚合信号提平台级改进，对应 brainstorm Q2-B）
- 商户自定义域 / wildcard DNS / `domain_routing` 表
- 合规模板按 `countries` 过滤（gap A-④）
- 沙盒 GC（超期未发布清理）
- OAuth / SSO / 2FA / passkey
- Dream proposal 自动落地（**永远不做**，红线）
- Dream 跨租户学习
- per-tenant CC 进程级隔离（单租户 fork 本身已进程级够用）
- 多管理员登录；管理员邀请
- E2E 脚本化（M3 稳定后）

### 0.3 M1 留位的激活点

| M1 留位 | M2 激活 |
|---|---|
| `souls/dream_soul.md` 静态模板 | 改由 `soul_generator` LLM 生成；静态模板降级为兜底常量 |
| `config.json.dream` 4 参数落盘 | `DreamScheduler` 实际按 trigger/risk/coverage 消费 |
| `ForkCreator` Protocol + `LocalTarballForkCreator` | 新增 `GitHubApiForkCreator` 实现 |
| `useSessionMode` 只做 master 分支 | 实现 tenant 分支；返回体扩展 tier/brand_name/authenticated_as |
| Cc_pool "池共享 + system prompt 传 soul"（Option 2A） | 对 `role="dream"` 同样适用；dream 独立小池（size=1） |

---

## 1. 架构总览

### 1.1 3 条并行链（M1 → M2）

```
                   M1 已完成                            M2 激活

      ┌─ Fork 链路 ─┐    /publish → tarball       →   解压到 fork 仓 plugins/<tid>/
      │             │    + LocalTarballForkCreator    make run-web 跑起来（tenant 模式）
      │             │    + runbook 手工步骤           + GitHubApiForkCreator（可选）
      │
      ├─ Dream 链路 ─┐   dream_soul.md 静态          →  Dream 升级为租户第 5 agent
      │              │   config.json.dream 落盘        soul_generator 扩 5 角色
      │              │   proposal_pipeline 不改        cc_pool 新增 role="dream"
      │                                                DreamScheduler 自动唤醒
      │                                                _master 内置（autoservice 自迭代）
      │
      └─ Admin 链路 ─┐   MasterLayout 骨架           →  TenantLayout 最小实现
                     │   useSessionMode master         4 tab 读 fork 自己数据
                     │   wizard 接 /publish            Magic-link 鉴权（两端）
                                                       per-tenant skill symlink
```

### 1.2 2 层 tier 模型（subtenant 留痕）

| Tier | 身份 | 部署 | 能力 |
|---|---|---|---|
| 0 | `platform_admin` = A（我们） | Master 主仓 | 管所有顶级租户；跑 `_master` 做自迭代 |
| 1 | `tenant_admin` = B | B 的 fork 仓 | 管自己；fork 启动时含 `_local_admin` 作 admin 助手 |
| 2 | `subtenant_admin` = C | — 预留字段，M2 不实现 — | — |

M2 执行上只走 A → B。但 `config.json.tier` / 鉴权中间件签名已按 3 层模型预埋，M3 加 subtenant 不用改数据 schema。

### 1.3 部署模式切换

Master 与 fork **代码完全一致**，通过 `.autoservice/config.local.yaml.deployment_mode` 区分（无自动 infer）：

```yaml
deployment_mode: master        # master | tenant
tenant_id: null                # tenant 模式必填
fork_creator: local            # local | github_api（仅 master 消费）
auth:
  admin_emails: []
  smtp:
    host: ""                   # 空 → 开发模式（log + .eml 落本地）
    port: 587
    user: ""
    password_env: "SMTP_PASSWORD"
    from: "AutoService <noreply@example.com>"
```

---

## 2. Dream Agent（核心 §）

### 2.1 现状 vs 目标

| 维度 | M1 占位 | M2 目标 |
|---|---|---|
| 入口 | `proposal_pipeline.run_once(mempool, db)` 函数 | `dream_agent.run_dream(tenant_id, ...)` agent loop |
| Prompt | [proposal_pipeline.py:52-73](../../../autoservice/proposal_pipeline.py#L52-L73) 硬编码 | 租户的 `souls/dream_soul.md`（LLM 生成） |
| 触发 | 手工调用 | `DreamScheduler` 按 `config.json.dream.trigger` 自动：`idle` / `scheduled` / `manual` |
| 能力 | 一次性 analyzer | Agent loop：查 KB、读对话、读历史 proposal、读 canary 状态、写 proposal |
| 隔离 | 全局单例 | Per-tenant：注入租户 soul + 指向租户 KB/memory/proposals |

### 2.2 Dream Agent 调用时序

```
config.json.dream.trigger=idle
         │
         ▼
DreamScheduler（autoservice/dream_scheduler.py）asyncio loop
  每 60s 扫所有 active 租户（_master + sandbox/* + fork 自己）
  per tenant 根据 trigger 配置决定是否该触发
    - idle：最后一次对话 > idle_threshold_min（默认 30）
    - scheduled：到点（简易 cron HH:MM）
    - manual：等 /api/dream/trigger
  触发时 spawn asyncio.create_task(run_dream(tid, ...))
         │
         ▼
DreamRun(tenant_id)
  1. cc_pool.acquire(role="dream", tenant_id=T)
     → CCClient with system_prompt = read(souls/dream_soul.md)

  2. 构造初始 context 消息：
     - 最近 N=20 条对话（memory_pool.recent(tid, 20)）
     - 最近 M=5 条历史 proposals（状态 accepted | rejected，带 review note）
     - config.json.dream.risk_threshold / coverage
     - Canary 当前状态（若有）

  3. Dream client.send(context) with tools:
     - kb_search(query: str) → 查自己租户的 kb.db
     - list_souls() → 返回 4 agent soul 摘要（不含自己）
     - emit_proposal(category, title, description, suggestion, evidence,
                     risk_level, target_role) → 写 proposals 表（status=draft）

  4. Agent loop（max_tool_turns=10 硬上限）：
     dream 可能调 kb_search 验证"这个场景 KB 是否覆盖"
     可能 list_souls 看现在 customer 是怎么说的再提改进
     最终调 emit_proposal N 次（0..M 条）

  5. run 结束写 runs.db 一条记录（tokens / duration / tool_calls）
     1h cool-down 硬写死（防抖动）
```

### 2.3 Soul 生成扩 5 角色

[soul_generator.py](../../../autoservice/soul_generator.py) 改动：

- `AGENT_ROLES = ("customer", "translate", "lead", "triage")` → 追加 `"dream"`
- `_KB_QUERIES["dream"]` = `["company mission and values", "known service gaps", "compliance boundaries"]`
- 新增 `_SOUL_TEMPLATE["dream"]`：自然语言描述 dream 的职责、4 个配置参数含义、可用工具说明
- 兜底：LLM 失败时回退到 `_FALLBACK_DREAM_SOUL` 常量（内嵌在 `soul_generator.py`，内容 = M1 的静态 `dream_soul_template.md` 等价文本）
- `_generation_meta.yaml` 标记 dream soul 是 `llm` 还是 `fallback`

M1 产物 [autoservice/dream_soul_template.md](../../../autoservice/dream_soul_template.md) 在 M2 被删除（其内容迁到 `soul_generator.py` 的 `_FALLBACK_DREAM_SOUL` 常量）；`/upload` 不再单独拷贝此文件。

### 2.4 proposal_pipeline 改造

[proposal_pipeline.py](../../../autoservice/proposal_pipeline.py) 的 `run_once()` **不删**，改为 `run_once_legacy()` 并标 deprecated（以防回归）。实际工作移到新建的 [dream_agent.py](../../../autoservice/dream_agent.py)：

```python
# dream_agent.py
async def run_dream(
    tenant_id: str,
    cc_pool: CCPool,
    mempool: MemoryPool,
    proposals_db: sqlite3.Connection,
    runs_db: sqlite3.Connection,
    max_tool_turns: int = 10,
) -> DreamRunResult: ...
```

**proposals 表 schema 迁移**（必须）：

```sql
ALTER TABLE proposals ADD COLUMN tenant_id TEXT NOT NULL DEFAULT '_master';
CREATE INDEX idx_proposals_tenant ON proposals(tenant_id);
```

Master 端多租户共享 proposals.db；fork 端单租户但 schema 对齐。迁移脚本 backfill 既有行 `tenant_id='_master'`。

**runs 表**（新建 `.autoservice/dream/runs.db`）：

```sql
CREATE TABLE dream_runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    proposals_count INTEGER NOT NULL,
    tool_calls INTEGER NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    status TEXT NOT NULL,   -- "completed" | "tool_limit" | "error"
    error_message TEXT
);
CREATE INDEX idx_runs_tenant ON dream_runs(tenant_id);
```

### 2.5 cc_pool role="dream"

[cc_pool.py](../../../autoservice/cc_pool.py) 改动：
- `create_cc_client(role, tenant_id)` 的 role 枚举扩到含 `"dream"`
- Dream 使用独立小池 `dream_pool`（**部署级 size=1**，全部署只允许 1 个 dream run 并发；多租户触发时排队。Dream run 不频繁（idle/scheduled trigger + 1h cool-down），串行化可接受；M3 观察到瓶颈再扩池）
- 不抢普通 agent 的 pool 名额
- Dream client 绑定 3 个 MCP tool：`kb_search` / `list_souls` / `emit_proposal`（复用现有 MCP 注入机制）
- Dream 模型选 `claude-opus-4-7[1m]`（长上下文吞历史对话 + proposal）；普通 agent 池保持 haiku/sonnet 配置不变

### 2.6 触发机制 API

```
POST /api/dream/trigger { tenant_id }
  → master tier=0 可任意；tenant 仅自己 → require_tenant_access 中间件
  → 200 { run_id }

GET /api/dream/runs?tenant_id=X&limit=20
  → 历史 run 列表（admin-portal Proposals tab 展示）
```

DreamScheduler 启动于 [web_gateway.py](../../../autoservice/web_gateway.py) 的 lifespan startup：

```python
@app.on_event("startup")
async def startup():
    bootstrap.ensure_master_tenant()   # master 模式
    bootstrap.ensure_local_admin()     # tenant 模式
    asyncio.create_task(dream_scheduler.loop())
```

### 2.7 `_master` 租户 bootstrap（master 端自迭代）

新建 [autoservice/master_tenant.py](../../../autoservice/master_tenant.py) 的 `ensure_master_tenant()`：

```python
def ensure_master_tenant():
    path = Path(".autoservice/sandbox/_master/")
    if (path / "config.json").exists():
        return
    path.mkdir(parents=True, exist_ok=True)
    write_config(path, {
        "tenant_id": "_master",
        "brand_name": "AutoService Platform",
        "industry": "platform-ops",
        "tier": 0,
        "parent_tenant_id": None,
        "status": "active",
        "channels": ["web"],
        "compliance": DEFAULT_COMPLIANCE,
        "soul": DEFAULT_SOUL_CFG,
        "dream": {
            "trigger": "idle",
            "coverage": "all",
            "risk_threshold": "medium",
            "canary": {"stages": [100], "observe_hours": 0},
        },
    })
    soul_generator.generate_and_save(
        tenant_id="_master",
        industry="platform-ops",
        brand_name="AutoService",
        languages=["zh", "en"],
        kb_db=None,
        target_dir=path / "souls",
        kind="platform",          # 影响 customer soul：admin 助手口吻，带工具调用指引
    )
    (path / "kb").mkdir(exist_ok=True)
    init_empty_kb(path / "kb" / "kb.db")
```

**A 的 ManagementChat 接入 `_master`**：

M1 的 `/api/management/chat` 现状是调 `DreamConfigSession` 或 stub LLM。M2 改为：
- 路由到 `cc_pool.acquire(role="customer", tenant_id="_master")`
- `_master` 的 customer agent 被赋予 **admin 工具集**：
  - `list_tenants()`
  - `read_proposals(tenant_id?, status?)`
  - `approve_proposal(id)` / `reject_proposal(id)`
  - `trigger_dream(tenant_id)`
  - `publish_sandbox(tenant_id)`
  - `read_wizard_state(tenant_id)`
- 工具返回结果用 M1 的 inline widget 机制（`proposal-card` / `metric` / `action-launch`）
- `_master` 自己的 dream 看这段对话，提议优化 `_master/souls/customer_soul.md`

### 2.8 Fork 端 `_local_admin`（对称自迭代）

Fork 仓启动时 `bootstrap.ensure_local_admin()` 与 master `_master` 对称：
- 位置 `plugins/_local_admin/`（注意：不是 `.autoservice/sandbox/`，因为 fork 仓无 sandbox 概念）
- `tier=0`（与 `_master` 同级）；但它仅在本 fork 内可见、不对外暴露
- `kind="fork"` 生成 soul：admin 助手口吻 + 工具 scope 到 B 自己（无 `list_tenants`，工具只读写 B 的 proposals/dream/wizard-state）
- B 在 TenantLayout 的 ChatTab 实际和 `_local_admin` 对话
- `_local_admin` 的 dream 优化 `_local_admin` 的 customer soul（= B 的 admin 助手进化）

---

## 3. Tenant Fork Runtime

### 3.1 部署模式识别

新建 [autoservice/bootstrap.py](../../../autoservice/bootstrap.py)：

```python
@cache
def get_deployment_mode() -> Literal["master", "tenant"]:
    cfg = yaml.safe_load(open(".autoservice/config.local.yaml"))
    mode = cfg.get("deployment_mode", "master")
    assert mode in ("master", "tenant")
    if mode == "tenant":
        tid = cfg["tenant_id"]
        tenant_cfg = json.load(open(f"plugins/{tid}/config.json"))
        assert tenant_cfg["tenant_id"] == tid, \
            f"tenant_id mismatch: config.local.yaml says {tid}, plugins/{tid}/config.json says {tenant_cfg['tenant_id']}"
    return mode

@cache
def get_tenant_id() -> str | None:
    cfg = yaml.safe_load(open(".autoservice/config.local.yaml"))
    return cfg.get("tenant_id")
```

### 3.2 TenantContext 中间件

[web_gateway.py](../../../autoservice/web_gateway.py) 的路由中间件按部署模式分叉：

```python
async def tenant_context_middleware(request, call_next):
    mode = get_deployment_mode()
    if mode == "tenant":
        self_tid = get_tenant_id()
        if request.url.path.startswith("/t/"):
            tid = _extract_tid_from_path(request.url.path)
            if tid != self_tid:
                return Response(status_code=404)
        request.state.tenant_id = self_tid
    else:
        request.state.tenant_id = (
            _extract_from_path_or_query(request) or "_master"
        )
    return await call_next(request)
```

WS 同理：fork 模式下若 `?tenant=` 不等于 `self_tid`，close(1008)。

### 3.3 tenant_root helper

所有按租户读的代码点（cc_pool 的 `_load_soul`、KB 的 `_get_kb_path`、memory_pool 的 tenant 过滤）统一复用：

```python
def tenant_root(tenant_id: str) -> Path:
    mode = get_deployment_mode()
    if mode == "tenant":
        return Path(f"plugins/{tenant_id}/")
    # master
    if tenant_id == "_master":
        return Path(".autoservice/sandbox/_master/")
    sandbox = Path(f".autoservice/sandbox/{tenant_id}/")
    if sandbox.exists():
        return sandbox
    archived = _newest_archived(tenant_id)
    if archived:
        return archived
    raise TenantNotFound(tenant_id)
```

### 3.4 fork_creator: github_api 实现

[publish.py](../../../autoservice/publish.py) 追加：

```python
class GitHubApiForkCreator:
    def __init__(self, gh_binary="gh", upstream="ezagent42/AutoService"):
        self.gh = gh_binary
        self.upstream = upstream

    def available(self) -> bool:
        """gh CLI 存在且已登录。"""
        try:
            run([self.gh, "auth", "status"], check=True, capture_output=True)
            return True
        except (FileNotFoundError, CalledProcessError):
            return False

    def create(self, tenant_id: str, artifact_path: Path) -> ForkResult:
        fork_name = f"AutoService-{tenant_id}"
        clone_dir = Path(f"/tmp/{fork_name}")
        # 1. gh repo fork --fork-name --clone
        run([self.gh, "repo", "fork", self.upstream,
             f"--fork-name={fork_name}", f"--clone={clone_dir}"], check=True)
        # 2. 解压 tarball（tarball 内容即 plugins/<tid>/...）
        run(["tar", "-xzf", str(artifact_path), "-C", str(clone_dir)], check=True)
        # 3. 写 config.local.yaml
        _write_fork_local_config(clone_dir, tenant_id)
        # 4. commit + push
        cwd = str(clone_dir)
        run(["git", "add", "plugins/", ".autoservice/config.local.yaml"], cwd=cwd, check=True)
        run(["git", "commit", "-m", f"Install tenant {tenant_id}"], cwd=cwd, check=True)
        run(["git", "push"], cwd=cwd, check=True)
        return ForkResult(
            repo_url=_get_repo_url(clone_dir),
            local_path=clone_dir,
            steps_executed=["fork", "unpack", "config", "commit", "push"],
        )
```

`/api/onboard/publish` 选择器：

```python
creator_name = config.get("fork_creator", "local")
if creator_name == "github_api":
    creator = GitHubApiForkCreator()
    if not creator.available():
        logger.warning("gh CLI unavailable, falling back to LocalTarballForkCreator")
        creator = LocalTarballForkCreator()
else:
    creator = LocalTarballForkCreator()
result = creator.create(tenant_id, artifact_path)
```

**`LocalTarballForkCreator` 的 runbook 补第 4 步**（M1 忘了）：解压后必须额外在 fork 仓 `.autoservice/config.local.yaml` 写 `deployment_mode: tenant` + `tenant_id: <tid>`，否则启动报错。

### 3.5 make setup 扩展

[Makefile](../../../Makefile) 的 `setup` target 改为调用 [scripts/setup.sh](../../../scripts/setup.sh)（新建），处理 mode 分支：

- Master 模式：保持 M1 行为（`.claude/skills/` → `skills/`；扫 `plugins/*/` 发现 plugin skills；`_example` 除外）
- Tenant 模式：`.claude/skills/` 仅 symlink `plugins/<tid>/skills/`（若存在）；plugin discovery 仅扫 `plugins/<tid>/`；跳过 `_local_admin`（本地管理助手不暴露 skill）

Windows 上用 directory junction（M1 已处理方式），Unix 真 symlink。

### 3.6 前端 deployment mode 分叉

[frontend/packages/shared/useSessionMode.ts](../../../frontend/packages/shared/useSessionMode.ts)（M1 stub）改为真实 fetch：

```ts
export function useSessionMode(): SessionMode | undefined {
  const { data } = useQuery(
    ['session-mode'],
    () => fetch('/api/session/mode').then(r => r.json()),
    { staleTime: Infinity }
  );
  return data;
}

type SessionMode =
  | { mode: "master"; authenticated: false }
  | { mode: "master"; authenticated: true; role: "platform_admin";
      authenticated_as: string }
  | { mode: "tenant"; authenticated: false }
  | { mode: "tenant"; authenticated: true; role: "tenant_admin";
      tenant_id: string; tier: 1; brand_name: string;
      authenticated_as: string };
```

[customer-chat/src/main.tsx](../../../frontend/apps/customer-chat/src/main.tsx) 与 [operator-console/src/main.tsx](../../../frontend/apps/operator-console/src/main.tsx) 根据 mode 切路由：

```tsx
const { mode } = useSessionMode() ?? {};
if (!mode) return <Splash />;
const routes = mode === 'tenant'
  ? [{ path: '/', element: <Redirect to={`/t/${selfTid}/chat`} /> },
     { path: '/chat', element: <App /> },                         // 裸路径兼容
     { path: '/t/:tenantId/chat', element: <App /> }]             // assertion 由后端中间件做
  : [{ path: '/t/:tenantId/chat', element: <App /> }];
```

[useTenantId.ts](../../../frontend/packages/shared/useTenantId.ts)：fork 模式从 `useSessionMode().tenant_id` 拿；master 从 URL params 拿。

### 3.7 memory_pool tenant 化

[memory_pool.py](../../../autoservice/memory_pool.py) 扩 `tenant_id` 列（迁移脚本 backfill 为 `_master`）；提供 `recent(tenant_id, limit)` / `last_message_at(tenant_id)` API。

- Master 部署下池内混有 `_master` + 所有 sandbox tenant 的对话 → 按 tenant 过滤
- Fork 部署下池内混有 `<self_tid>` + `_local_admin` 的对话（因为 fork 也有 internal tenant）→ 仍需按 tenant 过滤，不是"天然单租户"。Dream agent 读"B 的对话"和"B↔`_local_admin` admin 对话"是两个不同视角（`_local_admin` 的 dream 看后者，B 的 dream 看前者）

---

## 4. admin-portal TenantLayout

### 4.1 目录结构

```
frontend/apps/admin-portal/src/
├── App.tsx                     # 按 useSessionMode 分叉
├── layouts/
│   ├── MasterLayout.tsx        # M1
│   └── TenantLayout.tsx        # ★ 新建
├── components/shell/
│   ├── AdminShell.tsx          # M1（layout 无关）
│   ├── AdminTopbar.tsx         # 扩展
│   ├── AdminRail.tsx           # 扩展（variant prop）
│   └── AvatarMenu.tsx          # 扩展（+ Logout）
├── components/tenant/          # ★ 新目录
│   ├── DashboardTab.tsx        # 复用 master 的
│   ├── ProposalsTab.tsx        # 复用 master 的
│   ├── BillingTab.tsx          # 复用
│   └── ChatTab.tsx             # 和 _local_admin 对话
└── components/auth/            # ★ 新目录
    ├── LoginPage.tsx
    └── AuthGate.tsx
```

Shell 组件复用率 > 70%；tenant tab 组件直接复用 master 同名文件（数据源按 `/api/session/mode` 的 tenant_id 过滤，后端已 scope）。

### 4.2 Rail 图标集

| Slot | Master | Tenant | 路由 |
|---|---|---|---|
| 1 | 🗨 管理对话 → `_master` | 🗨 Chat → `_local_admin` | `/admin/chat` |
| 2 | 📊 Dashboard（平台聚合） | 📊 Dashboard（B 自己） | `/admin/dashboard` |
| 3 | ✨ Wizard | — 去除 — | `/master/tenants/new` |
| 4 | 💡 Proposals（全租户） | 💡 Proposals（B 自己） | `/admin/proposals` |
| 5 | 💳 Billing（平台） | 💳 Billing（B 自己） | `/admin/billing` |
| 6 | 🧑‍🤝‍🧑 Tenants 列表 | — 去除 — | `/master/tenants` |
| 底部 | ⋯ | ⋯ | — |

### 4.3 Topbar（tenant 模式）

- 左：violet dot + B 的 `brand_name`
- 中：空
- 右：⌘K 占位 + Avatar（显示 `authenticated_as`）

Avatar 菜单（tenant 模式）：
- Tenant ID: B
- Logout
- Version: 1.0.0

### 4.4 ChatTab：和 `_local_admin` 对话

Fork 内 `_local_admin` 作为 B 的 admin 对话伙伴；与 master 的 `_master` 结构对称：
- B 在 ChatTab 和 `_local_admin` 聊
- `_local_admin` 的 customer agent 工具集 scope 到 B 自己（无 `list_tenants`、无 `publish_sandbox`；只 `read_proposals` / `approve_proposal` / `trigger_dream` / `read_config` 等）
- `_local_admin` 的 dream 优化自己的 customer soul = B 的 admin 助手进化

ChatTab 实现 = 复用 M1 的 `ManagementChat` 组件，POST 端点从 `/api/management/chat` 改为 `/api/admin/chat`（新建，走 `require_tenant_access`，`tenant_id` 参数固定为 `_local_admin` or `_master`）。

### 4.5 AuthGate

M2 **master 和 tenant 都加** AuthGate。`App.tsx` 形如：

```tsx
const session = useSessionMode();
if (!session) return <Splash />;
if (!session.authenticated) return <LoginPage mode={session.mode} />;
return session.mode === 'master' ? <MasterLayout /> : <TenantLayout />;
```

LoginPage：Aurora 风格单页，email 输入 + "Send magic link"；提交后显示 "Check inbox (or server log in dev mode)"。

---

## 5. Magic-link 鉴权

### 5.1 存储

`.autoservice/auth/`：
- `sessions.db`（SQLite，下述 2 表）
- `smtp_outbox/<timestamp>.eml`（SMTP 未配时落本地文件）

```sql
CREATE TABLE login_tokens (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,       -- +10 min
    consumed INTEGER DEFAULT 0
);

CREATE TABLE sessions (
    cookie_id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    tier INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,       -- +30 days
    revoked INTEGER DEFAULT 0
);
```

### 5.2 API

- `POST /api/auth/request-login { email }`：防枚举返 200；email ∈ admin_emails 才真发；开发模式（SMTP 未配）打 log + 写 .eml；返回体 `{ delivered: "smtp" | "log" }`
- `GET /api/auth/verify?token=X`：一次性消费；set cookie `adm_s`（HttpOnly + SameSite=Lax + 30d）；302 到 `/admin`
- `POST /api/auth/logout`：清 cookie + revoked=1
- `GET /api/session/mode`：读 cookie 查 sessions，未登录返 `{ mode, authenticated: false }`

### 5.3 require_tenant_access 中间件

```python
INTERNAL_TENANT_PREFIX = "_"   # _master、_local_admin 等 deployment-internal bootstrap 租户

def require_tenant_access(target_tenant_id: str):
    def dep(request: Request):
        session = _load_session(request.cookies.get("adm_s"))
        if not session:
            raise HTTPException(401, "not authenticated")
        # Rule 1: 访问自己永远允许
        if target_tenant_id == session.tenant_id:
            request.state.session = session
            return session
        # Rule 2: tier=0 session（platform_admin）可跨任意顶级租户
        if session.tier == 0:
            request.state.session = session
            return session
        # Rule 3: 访问本部署的 internal 租户（以 _ 开头）允许
        #   —— master 下 _master；fork 下 _local_admin
        #   这是 ChatTab 能访问 _local_admin 的路径
        if target_tenant_id.startswith(INTERNAL_TENANT_PREFIX):
            request.state.session = session
            return session
        # Rule 4（M3 留痕位）：parent_tenant_id 链校验
        #   M2 走到这一步即拒绝
        raise HTTPException(403, "cross-tenant forbidden")
    return dep
```

关键点：fork 部署里 B（tier=1）能和 `_local_admin` 对话不是"跨租户"，而是访问 deployment-internal 租户。中间件靠 `_` 前缀识别。

### 5.4 保护范围

| Route | 鉴权 |
|---|---|
| `/admin/*`（SPA HTML） | ❌（前端 AuthGate 拦） |
| `/api/admin/*` | ✅ session cookie 必需（M2 把现有 admin-only API 迁入此命名空间） |
| `/api/management/chat`、`/api/admin/chat` | ✅ |
| `/api/onboard/publish` | ✅ 仅 `tier=0`（B 不能 publish） |
| `/api/dream/trigger` | ✅ `tenant_id` 必须 match session（或 tier=0） |
| `/chat`、`/operator`（客户+客服页面） | ❌ |
| `/ws/customer`、`/ws/operator` | ❌（沿用 M1 token 机制） |

### 5.5 SMTP 配置

宿主级别（`.autoservice/config.local.yaml.auth.smtp.*`），不是 per-tenant。fork 端 B 在 B 的 `config.local.yaml` 自己配 SMTP。

### 5.6 开发模式

SMTP `host` 为空时：
- Magic link 写 `logger.info` WARNING 级别醒目横幅
- 同时写 `.autoservice/auth/smtp_outbox/<ts>.eml`（`.eml` 格式，Outlook/Thunderbird 能看）
- `POST /api/auth/request-login` 返 `delivered: "log"`，前端 UI 提示 "Check server log / smtp_outbox/"

### 5.7 安全底线

- Token：`secrets.token_urlsafe(24)` → 32 字符
- Cookie：`secrets.token_urlsafe(36)` → 48 字符；HttpOnly + SameSite=Lax + Secure when HTTPS
- 防暴力：同 email 5 min 内限 3 次（内存 dict；多进程场景 M3 再上 SQLite 计数）
- 不做：2FA / SSO / OAuth / passkey（M3+）

---

## 6. 文件改动清单

### 6.1 后端

| 文件 | 改动 |
|---|---|
| 新建 [autoservice/bootstrap.py](../../../autoservice/bootstrap.py) | `get_deployment_mode` / `get_tenant_id` / `ensure_master_tenant` / `ensure_local_admin` |
| 新建 [autoservice/master_tenant.py](../../../autoservice/master_tenant.py) | `_master` + `_local_admin` bootstrap 共享逻辑 |
| 新建 [autoservice/dream_scheduler.py](../../../autoservice/dream_scheduler.py) | asyncio 后台 loop |
| 新建 [autoservice/dream_agent.py](../../../autoservice/dream_agent.py) | `run_dream()` agent loop + 工具定义 |
| 新建 [autoservice/auth.py](../../../autoservice/auth.py) | sessions.db、login_tokens、`require_tenant_access`、SMTP |
| 改 [autoservice/soul_generator.py](../../../autoservice/soul_generator.py) | 5 角色；dream 模板；fallback 常量 |
| 改 [autoservice/proposal_pipeline.py](../../../autoservice/proposal_pipeline.py) | schema 迁移；`run_once` → `run_once_legacy` |
| 改 [autoservice/cc_pool.py](../../../autoservice/cc_pool.py) | role="dream"；独立 dream_pool |
| 改 [autoservice/memory_pool.py](../../../autoservice/memory_pool.py) | tenant_id 列；`recent(tid)` / `last_message_at(tid)` |
| 改 [autoservice/api_routes.py](../../../autoservice/api_routes.py) | `/api/session/mode` 扩展；`/api/auth/*`；`/api/dream/*`；`/api/admin/*` 命名空间 |
| 改 [autoservice/publish.py](../../../autoservice/publish.py) | `GitHubApiForkCreator`；`LocalTarballForkCreator` runbook 补写 `config.local.yaml` 步骤 |
| 改 [autoservice/web_gateway.py](../../../autoservice/web_gateway.py) | lifespan startup；TenantContext 中间件按 mode 分叉 |
| 改 [autoservice/onboarding.py](../../../autoservice/onboarding.py) | 调 5 角色 `soul_generator`；不再拷贝静态 dream 模板 |
| 删 [autoservice/dream_soul_template.md](../../../autoservice/dream_soul_template.md) | 内容迁到 `soul_generator._FALLBACK_DREAM_SOUL` 常量 |
| 改 [autoservice/dream_config_dialog.py](../../../autoservice/dream_config_dialog.py) | 确认时触发 `dream_scheduler.refresh(tenant_id)` |

### 6.2 前端

| 文件 | 改动 |
|---|---|
| 新 [frontend/packages/shared/useTenantId.ts](../../../frontend/packages/shared/useTenantId.ts) | 真实现（M1 spec 预留） |
| 改 [frontend/packages/shared/useSessionMode.ts](../../../frontend/packages/shared/useSessionMode.ts) | 真 fetch；返回体扩展 |
| 新 [admin-portal/src/layouts/TenantLayout.tsx](../../../frontend/apps/admin-portal/src/layouts/TenantLayout.tsx) | §4.1 |
| 新 [admin-portal/src/components/tenant/ChatTab.tsx](../../../frontend/apps/admin-portal/src/components/tenant/ChatTab.tsx) | `_local_admin` 对话 |
| 新 [admin-portal/src/components/auth/LoginPage.tsx](../../../frontend/apps/admin-portal/src/components/auth/LoginPage.tsx) | — |
| 新 [admin-portal/src/components/auth/AuthGate.tsx](../../../frontend/apps/admin-portal/src/components/auth/AuthGate.tsx) | — |
| 改 [admin-portal/src/App.tsx](../../../frontend/apps/admin-portal/src/App.tsx) | `<AuthGate>` 包裹；mode 分叉 |
| 改 [admin-portal/src/components/shell/AdminRail.tsx](../../../frontend/apps/admin-portal/src/components/shell/AdminRail.tsx) | `variant` prop |
| 改 [admin-portal/src/components/shell/AdminTopbar.tsx](../../../frontend/apps/admin-portal/src/components/shell/AdminTopbar.tsx) | `brandName` + `authenticatedAs` props |
| 改 [admin-portal/src/components/shell/AvatarMenu.tsx](../../../frontend/apps/admin-portal/src/components/shell/AvatarMenu.tsx) | + Logout |
| 改 [customer-chat/src/main.tsx](../../../frontend/apps/customer-chat/src/main.tsx) | 按 mode 切路由 |
| 改 [operator-console/src/main.tsx](../../../frontend/apps/operator-console/src/main.tsx) | 同上 |

### 6.3 Makefile / scripts

| 文件 | 改动 |
|---|---|
| 改 [Makefile](../../../Makefile) | `setup` target 调 `scripts/setup.sh` |
| 新建 [scripts/setup.sh](../../../scripts/setup.sh) | 按 `deployment_mode` 分支 |

---

## 7. 实施顺序（8 阶段可独立验收）

| # | 阶段 | 产出 | 验证 |
|---|---|---|---|
| 1 | Bootstrap + `_master` 种子 | `bootstrap.py`、`master_tenant.py`、`soul_generator` 扩 5 角色 | 启动 master，`.autoservice/sandbox/_master/` 齐备 |
| 2 | proposals schema + memory_pool tenant 列 | 迁移 SQL + backfill | 既有测试通过；数据 backfill tenant_id='_master' |
| 3 | Dream agent 独立跑通 | `dream_agent.run_dream()` + cc_pool role="dream" + tool 定义 | 手工 `POST /api/dream/trigger {tenant_id:"_master"}` 产 proposal |
| 4 | DreamScheduler + dream_config sync | 后台 task + 配置刷新 | 设 idle=5min，5min 后 proposals 表新条目 |
| 5 | Auth (Magic-link) | `auth.py` + `require_tenant_access` + LoginPage + AuthGate | 本地跑通登录（SMTP 未配 → log 模式） |
| 6 | TenantLayout + ChatTab | fork 模式前端分叉；mock mode=tenant 本地渲染 | admin-portal 显示 TenantLayout |
| 7 | Fork 端真跑 | `deployment_mode=tenant` + URL 无前缀 + `make run-web` | 手工 fork 仓启动能聊 `/chat`、admin 登录 |
| 8 | GitHubApiForkCreator + E2E | gh CLI 集成 + 验收链路全走 | §8 acceptance 8 步通过 |

---

## 8. M2 Acceptance

走完以下链路即为 M2 完成：

1. **Master 跑向导创建租户 B** → publish tarball → 归档沙盒
2. **按 runbook 手工 fork**（或 `fork_creator=github_api` 自动 fork）：tarball 解压到 fork 仓 `plugins/B/`；`.autoservice/config.local.yaml` 已由 ForkCreator 写入 `deployment_mode=tenant` + `tenant_id=B`
3. **Fork 仓 `make setup && make run-web` 启动** 无报错
4. **浏览器访问 `http://fork-host:8000/chat`**（无 `/t/<tid>/` 前缀）能对话
5. **admin-portal 走 magic-link 登录** → TenantLayout 显示 B 的 4 tab
6. **对话 5 轮后，Dream agent 按 `dream.trigger=idle` 自动触发** → `proposals` 表出现新条目；`dream_runs` 表有 run 记录
7. **回 Master 打开 `http://master:8000/admin/chat`** → 和 `_master` 对话 → `_master` dream 产生平台级 proposal
8. **在 admin-portal Proposals tab approve/reject** 一条 proposal → 状态持久化

---

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| Dream agent 成本爆炸（idle 判定过宽反复唤醒） | `idle_threshold_min=30` 默认；`run_dream` 结束后 1h cool-down 硬写死 |
| Dream 死循环（LLM 不调 `emit_proposal` 只反复查 KB） | `max_tool_turns=10` 硬上限；超限强制 finalize |
| `_master` 自迭代 feedback loop 偏移 | proposal 必须 `status='draft'` + A review 才 accept；dream 不能自动落地 soul 改动（红线） |
| proposals 表迁移破坏既有数据 | `ALTER TABLE ... DEFAULT '_master'` + 迁移脚本 backfill；先跑 M1 测试 baseline |
| Fork 仓漏写 `config.local.yaml` | `bootstrap.get_deployment_mode()` 启动 assert 报错信息明确指向漏做的步骤 |
| cc_pool dream client 抢 customer 名额 | `role="dream"` 独立 `dream_pool`（size=1），不入普通池 |
| Admin-portal AuthGate 首帧闪现 | `AuthGate` loading 态渲染 `<Splash />`，`useSessionMode` 完成后才判断 |
| Magic-link token 开发时 http 嗅探 | 开发模式不处理；部署 runbook 加 HTTPS 强制警告 |
| `GitHubApiForkCreator` 失败后部分状态残留 | 失败不自动 `gh repo delete`（需人工确认）；返回失败明确指向需清理的 fork 名 |
| `ManagementChat` 从 stub LLM 改走 `_master` 后既有逻辑回归 | Phase 1 写好 _master bootstrap 测试；Phase 6 tenant 分叉前先保 master 行为无回归 |

---

## 10. 未来路径（M3+）

- **Subtenant（tier=2）实体化**：B 的 whitelabel 能力——B 的 admin 开启 `allow_subtenant=true` 升级为 ControlLayout、跑 wizard 创建 C、`/publish` 走"fork 内 emplace"模式把 C 的物料落到 `plugins/C/`
- **Operator 鉴权 + 团队邀请 + RBAC**：多角色登录、邀请链接、per-tenant operator 列表
- **平台级 dream**（Q2-B）：master 端特殊 platform dream agent 看所有租户聚合信号、提议平台级改进（框架 bug / skill 优化 / cc_pool 策略调参）
- **Dream proposal 半自动**：低风险 proposal 在人 A review 后可"接受并自动应用"（仍需人触发，不做全自动）
- **商户自定义域 / wildcard DNS / `domain_routing` 表**
- **合规模板按 `countries` 过滤**（gap A-④）
- **沙盒 GC**：超期未发布清理 + 归档检查
- **OAuth / SSO / 2FA**
- **E2E 脚本化**（Playwright）
- **Dream 跨租户学习**（1 个租户的脱敏经验供别租户参考，待隐私合规评估）

---

*2026-04-20 · 基于 brainstorm：D（dream 升级为租户第 5 角色，B 留 M3）+ Master-as-tenant `_master` 内置 + Fork 端 `_local_admin` 对称 + 2 层 tier 模型（subtenant 留痕字段）+ Magic-link 最小鉴权 + `GitHubApiForkCreator` 最小落地*
