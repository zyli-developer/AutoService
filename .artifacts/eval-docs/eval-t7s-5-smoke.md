# Eval: T7S.5 Fork-mode boot smoke test

Spec: [docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §3 + §8 step 3](../../docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md)
Batch: batch-14 (parallel with T7B.6 `/api/management/chat`; this task only touches `tests/fork_runtime/` and `.artifacts/`, never `autoservice/api_routes.py`).

## 预期行为

- Fresh tenant fork checkout 模拟：`tmp_path` 下 `.autoservice/config.local.yaml` 写入 `deployment_mode: tenant` + `tenant_id: B`，`plugins/B/config.json` 匹配。
- `web_gateway.create_app()` → `TestClient(app)` 进入 context 时 lifespan 跑起来：
  - `ensure_local_admin()` 被调用（spec §2.8, T1B.5 已接线）。
  - `plugins/_local_admin/config.json`、`souls/`、`kb/kb.db` 材料化。
  - `CCPool warmup` 在 `POOL_MODE=0` 下跳过，不报错。
  - `DreamScheduler.start()` 在 `DREAM_SCHEDULER_DISABLED=1` 下跳过，不报错。
- `tenant_context_middleware` 在 tenant 模式下：
  - `GET /t/B/chat` → 内部 rewrite 为 `/chat`（URL-flat fork routing, spec §3.2）。
  - `GET /t/other/chat` → 403 JSON `{"error": "cross-tenant access denied ..."}`。
- 已知路由（如 `/api/session/mode`）在完整启动后 **不返回 5xx**（具体 2xx / 4xx 无所谓，关键是框架无 crash）。
- `async with TestClient(app)` 正常退出：shutdown hooks（CCPool shutdown / DreamScheduler stop）不抛异常。

## 验收标准

对应 spec §8 Acceptance 第 3 步 "Fork 仓 `make setup && make run-web` 启动无报错" 的 pytest surrogate。5 条用例覆盖：

1. `test_tenant_mode_boot_creates_local_admin` — lifespan startup 创建 `plugins/_local_admin/` 全套文件；幂等前提被尊重（fresh fork 启动前该目录不存在）。
2. `test_tenant_mode_root_route_not_500` — 完整启动后 `GET /api/session/mode` `status_code < 500`（框架健康红线）。
3. `test_tenant_mode_self_tenant_url_prefix_rewrites` — `GET /t/B/chat` → 200 + `scope_path == "/chat"` + `request.state.tenant_id == "B"`（URL-flat 重写生效）。
4. `test_tenant_mode_cross_tenant_denies` — `GET /t/other/chat` → 403 + JSON 包含 `cross-tenant`（单租户 fork 红线）。
5. `test_tenant_mode_lifespan_shutdown_clean` — `async with TestClient(app)` 期间发请求后正常退出，shutdown 无异常。

## 关键 invariant

- **lifespan 红线**：tenant 模式下 startup + shutdown 全程不抛（CON-08 fork runtime 健康性）。
- **URL-flat 重写必须 end-to-end 贯通** — 不是单测 middleware，而是完整 create_app() 上 TestClient 跑，确保 CORS + TenantContext + 路由器三件装配后依然正确（spec §3.2 红线）。
- **env 门控必须生效**：`POOL_MODE=0` + `DREAM_SCHEDULER_DISABLED=1` 时不做任何真工作负载（不起 Claude SDK、不 schedule async timer）；如果这两个 env 没挡住触发点，说明 lifespan 的 opt-out 逻辑坏了。
- **跨租户拒绝不可被 bypass** — 单租户 fork 遇 `/t/<other>/` 前缀必须 403，不能 leak 到 404 或 200（CON-09 单租户边界）。
- **_local_admin 幂等** — T1B.4 已有单元测试覆盖，本 smoke test 的责任是验证它被 lifespan 钩子真正调用到，而不是只做 code path 验证。
- **不触 api_routes.py** — T7B.6 并行 owning 该文件，本 smoke test 只挂 `_attach_chat_echo` helper 在局部 app 实例上，不跨文件耦合。

## 测试边界（smoke vs full E2E）

- 本 smoke **不启动真 uvicorn**（TestClient 足够）、**不做网络 IO**（Anthropic SDK 不加载）、**不跑 real CCPool**（`POOL_MODE=0`）、**不 mount 前端 SPA**。
- spec §8 step 4 的 "browser hits /chat" 是 T8S.3 Full E2E 范围，本 smoke 只到 "handler 看到正确 scope_path" 为止。
- 挂在测试本地 `create_app()` 实例上的 `/chat` echo handler 是 URL-flat 重写的 observable surrogate，不进入生产 app。
