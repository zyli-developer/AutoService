# 环境变量与配置参考

运行时所有可配置项一览。**env var 在进程启动时读取**，改完要重启。`config.local.yaml` 也是启动时读。

扫描基准：`dev-a` 分支 HEAD（2026-04-23 晚）。**文档里说"默认值"都是代码里写的**，不包括 Makefile 强制设置的值。

---

## 第一档：你最常调的运行时开关

### `SOOTHE_PLACEHOLDER_ENABLED`

占位气泡文案来源。

- **默认**：`1`（ON）
- **ON**：1.5-2.5s 占位气泡从 [autoservice/soothe_templates.yaml](../autoservice/soothe_templates.yaml) 按 intent 选一条（"好的，我帮您看一下具体功能…" 之类）
- **OFF (`0`)**：退到静态 `"正在为您查询，请稍候..."`（message_router.py `_PLACEHOLDER_TEXT_ZH`）
- 代码位置：[autoservice/gateway/message_router.py:825](../autoservice/gateway/message_router.py#L825)

### `TRIAGE_AGENT_ENABLED`

低信心消息是否用 haiku 做二次分类确认。

- **默认**：`0`（OFF，commit `9c2f9b5` 改的）
- **ON**：信心 <0.6 时走 haiku 分类（budget 2s-15s，一般 超时不值）
- **OFF**：FastClassifier 关键词结果直接用，不二次确认
- 代码：[autoservice/model_router.py:42](../autoservice/model_router.py#L42)

### `TRIAGE_AGENT_TIMEOUT_S`

haiku 二次分类的超时预算（秒）。仅当 `TRIAGE_AGENT_ENABLED=1` 时生效。

- **默认**：未设 → 回落到类属性 `_TRIAGE_AGENT_TIMEOUT = 15.0`
- 代码：[autoservice/model_router.py:63](../autoservice/model_router.py#L63)

### `AUTH_DEV_MODE`

admin portal 开发模式：跳过 magic-link 邮件，免密登录。

- **默认**：未设（OFF）
- **ON (`1`)**：暴露 `/api/auth/dev-mode` 和 `/api/auth/dev-login`，任何能连到服务的人都能拿 admin session
- **仅本地用**。CLAUDE.md 明确禁止在生产/staging 设这个
- Makefile `run-web` 自动设 `=1`
- 代码：[autoservice/api_routes.py:1976](../autoservice/api_routes.py#L1976), [autoservice/operator_routes.py:42](../autoservice/operator_routes.py#L42)

### `DREAM_DEV_STUB`

Dream Engine 是否走假 stub（3秒 sleep + 3条种子 proposal，不调 LLM）。

- **默认**：未设（OFF，走真 LLM）
- **ON (`1`)**：所有 `/api/dream/trigger` 调用都走 `_run_dev_stub_dream`
- 场景：CI 没 `ANTHROPIC_API_KEY`、离线 demo、录屏要稳定输出
- 生产必须关
- 代码：[autoservice/api_routes.py:602](../autoservice/api_routes.py#L602)

### `DREAM_SCHEDULER_DISABLED`

后台 Dream 定时器是否启用。

- **默认**：未设（启用）
- **=1**：`DreamScheduler` 不启动。适合 CI、TestClient 冒烟
- 代码：[autoservice/web_gateway.py:465](../autoservice/web_gateway.py#L465)

### `POOL_MODE`

是否启用 cc_pool（共享 Claude 实例池）。

- **默认**：`1`（启用）
- **=0**：web_gateway 跳过 pool 初始化；feishu channel_server 也不启用 pool 路径
- 基本不需要关，除非跑某种 pool-less 测试
- 代码：[autoservice/web_gateway.py:87](../autoservice/web_gateway.py#L87), [channels/feishu/channel_server.py:1655](../channels/feishu/channel_server.py#L1655)

---

## 第二档：Web / 端口 / 路由

### `DEMO_PORT`

主服务监听端口（web_gateway / feishu web）。

- **默认**：`8000`
- 代码：[channels/web/app.py:66](../channels/web/app.py#L66), [autoservice/onboarding.py:597](../autoservice/onboarding.py#L597)

### `WEB_SCHEME`

URL 构建的 scheme（拼 magic-link / preview URL 用）。

- **默认**：`http`
- 生产应设 `https`
- 代码：[autoservice/onboarding.py:595](../autoservice/onboarding.py#L595)

### `WEB_HOST`

URL 构建的 hostname。

- **默认**：`localhost`
- 生产要改成真实域名
- 代码：[autoservice/onboarding.py:596](../autoservice/onboarding.py#L596)

### `IDLE_TIMEOUT_MINUTES`

客户 WebSocket 空闲超时（分钟）。

- **默认**：`15` (分钟) → 900 秒
- 代码：[channels/web/app.py:67](../channels/web/app.py#L67)

### `DEMO_ADMIN_KEY`

admin 操作的 API key。

- **默认**：随机生成（`secrets.token_urlsafe(10)`），每次启动不同
- 想固定的话 export 一个
- 代码：[channels/web/app.py:68](../channels/web/app.py#L68)

### `CHANNEL_SERVER_PORT`

Feishu channel MCP 服务器端口。

- **默认**：`9999`
- 代码：[channels/feishu/channel_server.py:1650](../channels/feishu/channel_server.py#L1650), [channels/web/app.py:120](../channels/web/app.py#L120)

---

## 第三档：Feishu 相关（不做飞书渠道可忽略）

| env | 默认 | 说明 |
|---|---|---|
| `FEISHU_ENABLED` | `true` | 是否启用飞书分流；`false`/`0`/`no` → 关 |
| `FEISHU_APP_ID` | 无 | 飞书应用 ID（`.feishu-credentials.json` 也可）|
| `FEISHU_APP_SECRET` | 无 | 飞书应用 secret |
| `ADMIN_CHAT_ID` | 无 | 飞书管理群 chat_id |
| `AUTOSERVICE_CHAT_ID` | `*`（全部）| 只处理指定 chat_id，`*` 表示通配 |
| `AUTOSERVICE_RUNTIME_MODE` | `production` | `production` / `discuss` 切换行为 |

---

## 第四档：成本 / 预算

### `COMPRESSION_DAILY_BUDGET_CENTS`

history compressor 每日花费预算（美分）。

- **默认**：`1000` 分 = 10 美元
- 代码：[autoservice/history_compressor.py:127](../autoservice/history_compressor.py#L127)

### `ANTHROPIC_API_KEY`

Anthropic API 密钥。cc_pool 底层的 Claude Agent SDK 会读这个。

- **默认**：无（本地 CLI 会用 `claude login` 缓存凭据时可不设）
- 代码：由 `claude_agent_sdk` 内部读取

### `SMTP_PASSWORD`

SMTP 密码。`config.local.yaml::auth.smtp.password_env` 字段指向哪个 env 就读哪个，默认指向 `SMTP_PASSWORD`。

- **默认**：`""`（空字符串 → 开发模式，邮件落 `.autoservice/logs/.eml` 文件不发真邮件）
- 代码：`config.local.yaml::auth.smtp.password_env`

---

## 第五档：cc_pool 深度参数（通过 `CC_POOL_*` 或 `config.local.yaml` 调）

cc_pool 每个 `PoolConfig` 字段都能用 env var 覆盖，命名是 `CC_POOL_<FIELD>`。代码见 [autoservice/cc_pool.py:345-362](../autoservice/cc_pool.py#L345-L362)。

支持的字段（env var = `CC_POOL_<FIELD_UPPERCASE>`，类型由代码自动转换）：

**int**: `MIN_SIZE`, `MAX_SIZE`, `WARMUP_COUNT`, `MAX_QUERIES_PER_INSTANCE`, `MAX_STICKY_BINDINGS`

**float**: `MAX_LIFETIME_SECONDS`, `HEALTH_CHECK_INTERVAL`, `CHECKOUT_TIMEOUT`, `STICKY_IDLE_TIMEOUT`

**str**: `CWD`, `PERMISSION_MODE`, `MODEL`, `CLI_PATH`, `FAST_MODEL`, `SLOW_MODEL`, `DREAM_MODEL`, `WARMUP_TENANT_ID`

**不支持 env 覆盖**（仅 YAML）：`INCLUDE_PARTIAL_MESSAGES`（bool）、`WARMUP_ROLES`（list）

### 常改字段速查

| 字段 | 当前 config.local.yaml 值 | 说明 |
|---|---|---|
| `min_size` | 1 | 最小热实例数 |
| `max_size` | 5 | 最大并发数 |
| `warmup_count` | 4 | 启动预创建实例数 |
| `max_queries_per_instance` | 50 | 单实例查询上限（到了回收）|
| `max_lifetime_seconds` | 3600 | 单实例最大存活秒数 |
| `health_check_interval` | 30 | 健康检查间隔（秒）|
| `checkout_timeout` | 30 | 池耗尽时等待秒数 |
| `permission_mode` | `default` | SDK 权限模式（`default` / `acceptEdits` / `plan` / `bypassPermissions`）|
| `model` | `claude-haiku-4-5` | 兜底模型（未设 tier 时用）|
| `include_partial_messages` | `true` | 启用 token 级 SDK 流式事件 |
| `fast_model` | `claude-haiku-4-5` | triage / translate 用 |
| `slow_model` | `claude-haiku-4-5` | customer / lead 用 |
| `dream_model` | `claude-opus-4-7` | dream agent 用 |
| `warmup_tenant_id` | `cinnox` | 启动就给这个 tenant 预热实例 |
| `warmup_roles` | `[triage, lead]` | 启动预开哪些 role 子池 |

---

## 第六档：`.autoservice/config.local.yaml` 完整结构

**这个文件 gitignored**，每台机器自己的配置。

```yaml
# 部署模式
deployment_mode: master            # master | tenant
tenant_id: null                    # master 留 null；tenant 模式必填

# fork 策略（M2 功能）
fork_creator: local                # local | github_api

# Dream Agent
dream:
  idle_threshold_min: 30           # 最后一次对话超过此分钟 → idle 触发
  cool_down_min: 60                # 单次 run_dream 后的硬冷却
  max_tool_turns: 10               # agent loop 工具调用轮数硬上限

# 管理员鉴权
auth:
  admin_emails: [...]              # admin 用户白名单
  smtp:
    host: ""                       # 空 = 开发模式（邮件落本地 .eml）
    port: 587
    user: ""
    password_env: "SMTP_PASSWORD"  # 读哪个 env 作为 SMTP 密码
    from: "AutoService <noreply@example.com>"

# CC Pool（见第五档）
cc_pool:
  min_size: 1
  max_size: 5
  warmup_count: 4
  max_queries_per_instance: 50
  max_lifetime_seconds: 3600
  health_check_interval: 30
  checkout_timeout: 30
  permission_mode: default
  model: claude-haiku-4-5
  include_partial_messages: true
  fast_model: claude-haiku-4-5
  slow_model: claude-haiku-4-5
  dream_model: claude-opus-4-7
  warmup_tenant_id: cinnox
  warmup_roles: ["triage", "lead"]

# Takeover 行为
takeover:
  idle_timeout_ms: 180000          # /hijack 后静默多久自动释放
  warning_ms: 10000                # 预警阶段长度
  offline_grace_ms: 60000          # operator 断线多久算真正离线
```

---

## 第七档：YAML 级文案 / 分类配置（不是 env）

### [autoservice/classify_intent.yaml](../autoservice/classify_intent.yaml)

意图分类关键词表 + 路由 + 阶段超时 + 信心阈值。
改了要重启服务。

- `intents.<name>.keywords`：关键词列表（substring 匹配）
- `intents.<name>.route_to`：`customer` / `lead` / `translate` / `direct`
- `intents.<name>.model_tier`：`fast` / `slow`
- `intents.<name>.priority`：`high` / `normal`
- `intents.<name>.direct_reply` / `direct_reply_en`：`route_to: direct` 时的模板回复
- `confidence.high/medium/low/uncertain`：信心阈值（目前 0.8 / 0.6 / 0.3 / 0.0）
- `model_tiers.fast.model` / `slow.model`：**注意**这里的模型名是"给文档看的"，**真实运行用的是 `config.local.yaml::cc_pool.{fast,slow,dream}_model`**。两处保持一致比较好。

### [autoservice/soothe_templates.yaml](../autoservice/soothe_templates.yaml)

占位气泡文案表。`(intent × lang)` → 候选 line 列表。详见文件头部注释。

- 改文案 → 重启立即生效
- 加新 intent 要和 classify_intent.yaml 对齐（不然启动日志 warning "unknown intent"）
- 每条 line ≤30 字（contract test 会断言）

### [agents/<role>/soul.md](../agents/)

各角色（customer/lead/triage/translate）的 system prompt。
- 改 soul 要重启进程重新注入（`_load_soul` 在实例创建时读）
- tenant-specific soul 覆盖在 `.autoservice/sandbox/<tenant>/souls/<role>_soul.md`，优先级高于 `agents/<role>/soul.md`

---

## 已知陈旧 / 无效配置

- **`PLACEHOLDER_ENABLED`**：Makefile `run-web` 和 `run-gateway` 里都设了 `=0`，**但当前代码没有地方读这个 env var**（`SOOTHE_PLACEHOLDER_ENABLED` 才是有效的）。设与不设都一样。是历史遗留，下次收拾 Makefile 时一并删。

---

## 常用启动组合

### 本地开发（最常用）

```bash
make start
```

等价于：所有开关默认，`TRIAGE_AGENT_ENABLED=0` 默认关，`SOOTHE_PLACEHOLDER_ENABLED=1` 默认开。

### 本地开发 + admin 免密登录

```bash
AUTH_DEV_MODE=1 make start
```

或用 `make run-web`（已经带了 `AUTH_DEV_MODE=1`）。

### 录屏 / 离线 demo（Dream 走 stub）

```bash
DREAM_DEV_STUB=1 AUTH_DEV_MODE=1 make start
```

### CI / 单元测试

```bash
DREAM_SCHEDULER_DISABLED=1 DREAM_DEV_STUB=1 pytest ...
```

### 临时关掉 soothe 静态映射表，回到 "正在为您查询…" 静态文案

```bash
SOOTHE_PLACEHOLDER_ENABLED=0 make start
```

### 临时开 haiku 二次分类（调试 FastClassifier 边界 case 用）

```bash
TRIAGE_AGENT_ENABLED=1 TRIAGE_AGENT_TIMEOUT_S=5 make start
```

### 非默认端口 / 非本地主机

```bash
DEMO_PORT=8080 WEB_HOST=demo.example.com WEB_SCHEME=https make start
```

---

## 读 env 的时机（影响你什么时候重启）

| 读取时机 | 典型 env | 改完需要 |
|---|---|---|
| **进程启动时读一次** | `SOOTHE_PLACEHOLDER_ENABLED`、`AUTH_DEV_MODE`、`DREAM_DEV_STUB`、`POOL_MODE`、`DEMO_PORT` 等大部分 | **重启进程** |
| **每次调用读一次** | `TRIAGE_AGENT_ENABLED`、`TRIAGE_AGENT_TIMEOUT_S` | 热切换可生效（但运行中 export 到已启动 shell 之外不会生效；还是重启稳） |
| **仅启动时从 YAML 读** | `config.local.yaml` 全部字段 | **重启进程** |

修改 `.autoservice/sandbox/<tenant>/souls/*.md` 或 `agents/<role>/soul.md` 后，**需要主 cc_pool 销毁重建实例**才生效。最简单的做法是 restart 进程；或等 sticky session 空闲 600s 后自然回收。
