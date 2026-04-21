# Test diff: T7S.5 (batch-14 parallel — smoke half)

新增 **5 tests** across **1 new test file**.

## 新增文件

- `tests/fork_runtime/test_boot_smoke.py` — integration smoke test covering full tenant-mode boot cycle (5 cases, one pytest class `TestForkModeBootSmoke`)

## 覆盖的场景

From [eval-doc-018](../eval-docs/eval-t7s-5-smoke.md) 验收标准:

1. `test_tenant_mode_boot_creates_local_admin` — lifespan startup materialises `plugins/_local_admin/{config.json, souls/, kb/kb.db}` on fresh fork (spec §2.8 / T1B.5 hook 接线验证).
2. `test_tenant_mode_root_route_not_500` — `GET /api/session/mode` 启动后不返回 5xx（框架健康红线）.
3. `test_tenant_mode_self_tenant_url_prefix_rewrites` — `GET /t/B/chat` → 200 + `scope_path=="/chat"` + `tenant_id=="B"` end-to-end through full ASGI chain (spec §3.2 URL-flat).
4. `test_tenant_mode_cross_tenant_denies` — `GET /t/other/chat` → 403 JSON 含 `cross-tenant`（单租户 fork 边界）.
5. `test_tenant_mode_lifespan_shutdown_clean` — `async with TestClient(app)` 正常退出 + 一次请求验证 app loop 活着（startup + shutdown 全程无抛）.

## 已修 regression bug

无。

- `python -m pytest tests/fork_runtime/test_boot_smoke.py -v` → **5 passed**.
- `python -m pytest tests/fork_runtime/ tests/bootstrap/ tests/setup/ -q` → **49 passed, 0 failed**（含本 batch 新增 5 条）.

## 实现决策

- **env 门控选择**：沿用 batch-12 `test_tenant_context.py` 的 `POOL_MODE=0` + `DREAM_SCHEDULER_DISABLED=1` 组合。这两个 env 是 `web_gateway.py` 里已有的 opt-out hook（line 77: `_get_pool` / line 385: `_start_dream_scheduler`），不新增依赖。
- **不启 real uvicorn**：TestClient 已覆盖 lifespan + middleware + router 三件，真 uvicorn 只加进程边界，没有额外 smoke 价值。spec §8 step 3 的 "make run-web 启动无报错" 在 TestClient 上下文下等价可验证。
- **test fixture 共用 pattern**：`tenant_fork` fixture 镜像 `test_tenant_context.py::tenant_mode_cwd` + `test_lifespan_wire.py::tenant_mode_cwd`，但不 pre-create `plugins/_local_admin/` — 因为该 fixture 的语义是"fresh fork 检出完了 setup.sh 刚跑"，_local_admin 目录必须由 lifespan 来造（这是 invariant 1）。
- **`/chat` echo handler 局部注入**：为避免触碰 T7B.6 owning 的 `api_routes.py`，测试通过 `_attach_chat_echo(app)` 在本地 app 实例上挂一个 `/chat` echo 路由来观测 middleware rewrite 的效果。生产 `/chat` 路由由前端 SPA 挂载，超出本 smoke 边界。
- **不用 `GET /`**：`web_gateway.create_app()` 默认没有 `/` 路由，GET / 会 404 — 不如选已存在的 `/api/session/mode`（T5B.6）作为 "framework alive" probe。

## 边界说明（smoke vs full E2E）

- 本 smoke 不验证前端 SPA / 浏览器行为 / Magic-link 登录流程 — 那些属 T8S.3 Full E2E 范围。
- 本 smoke 不验证 real Anthropic SDK / real DreamScheduler timing — 用 env 门控跳过。
- 本 smoke **是** full boot chain 最弱先验证：lifespan 完整跑一遍 + 中间件端到端 + 关键内部租户被 provision。
