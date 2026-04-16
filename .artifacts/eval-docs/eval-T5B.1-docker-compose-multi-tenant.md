---
type: eval-doc
id: eval-T5B.1
status: draft
producer: skill-5
created_at: 2026-04-16
mode: simulate
feature: docker-compose 多租户模板
submitter: DevB
related:
  - T5B.2 (同主机部署约束)
  - T5B.3 (租户创建脚本)
  - T1B.5 (浮窗 SDK)
---

# Eval: T5B.1 docker-compose 多租户模板

## 基本信息
- 模式：模拟
- 提交人：DevB
- 日期：2026-04-16
- 状态：draft

## Feature 描述

创建 docker-compose 多租户模板，包含以下服务：
1. **autoservice** — Python FastAPI web 服务 (port 8000)，连接 channel-server (ws://localhost:9999)
2. **customer-chat** — React SPA (port 5173)，C 端客户聊天界面
3. **operator-console** — React SPA (port 5174)，客服工作台
4. **admin-portal** — React SPA (port 5175)，管理后台
5. **channel-server** — zchat 对话引擎 (port 9999)，外部依赖
6. **bridges** — feishu_bridge + web_bridge，必须与 channel-server 同主机 (NFR-4)

模板需支持：
- 租户变量替换（tenant name、端口偏移、域名、凭据路径）
- NFR-4 同主机约束（channel-server + bridges 在同一 network_mode 或同一 service）
- 被 T5B.3 `create-tenant.sh` 消费，一键生成租户实例

## 代码分析

### 现有架构
- `channels/web/app.py`: FastAPI, port 8000 (`DEMO_PORT` env), 连接 channel-server ws://localhost:9999 (`CHANNEL_SERVER_PORT` env)
- `channels/web/websocket.py`: WebChannelBridge 维护到 channel-server 的 WS 长连接
- `frontend/apps/customer-chat/`: Vite React, port 5173
- `frontend/apps/operator-console/`: Vite React, port 5174
- `frontend/apps/admin-portal/`: Vite React, port 5175
- `frontend/pnpm-workspace.yaml`: monorepo (apps/* + packages/*)
- `templates/create-tenant.sh`: L3 fork 脚本（git fork 方式，尚未包含容器编排）
- 无现有 Dockerfile 或 docker-compose 文件

### 关键环境变量
- `DEMO_PORT` (default 8000) — autoservice web 端口
- `CHANNEL_SERVER_PORT` (default 9999) — channel-server 端口
- `ANTHROPIC_API_KEY` — Claude API 密钥
- `.feishu-credentials.json` — 飞书凭据
- `.autoservice/config.local.yaml` — 本地 API keys

## Testcase 表格

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果 | 差异描述 | 优先级 |
|---|------|---------|---------|---------|---------|---------|--------|
| 1 | 单租户模板渲染 | 模板文件存在 + envsubst 可用 | 用 `TENANT=demo PORT_OFFSET=0` 渲染 docker-compose 模板 | 生成有效 docker-compose.yml，6 个 service 定义齐全，端口映射正确 (8000/5173/5174/5175/9999) | 可行。模板用 `${TENANT}` 变量 + envsubst 渲染；Dockerfile 需为 autoservice (Python) 和 frontend (Node multi-stage build) 分别编写。channel-server 使用外部镜像占位。 | 无。现有项目结构清晰，pyproject.toml + pnpm-workspace.yaml 提供完整构建信息。 | P0 |
| 2 | 多租户端口隔离 | 两个租户 demo + acme | 分别用 `PORT_OFFSET=0` 和 `PORT_OFFSET=100` 渲染，同主机 `docker compose up` | 两套服务端口不冲突：demo (8000/5173/5174/5175)，acme (8100/5273/5274/5275) | 可行。通过 `PORT_OFFSET` 偏移 + docker-compose `ports` 映射实现。内部容器端口不变，仅宿主机端口偏移。 | 无。标准 docker-compose 端口映射模式。 | P0 |
| 3 | NFR-4 同主机约束 | channel-server + bridges 服务定义 | 检查生成的 compose 文件中 channel-server 与 bridges 的网络配置 | channel-server 和 bridges 在同一 network 且通过 localhost 通信（同 pod 语义） | 可行。方案：bridges 与 channel-server 使用 `network_mode: "service:channel-server"` 共享网络栈，或合并为单一容器。前者更灵活，后者更简单。建议用 `network_mode` 方案。 | 需设计决策：`network_mode` vs 合并容器。两者均满足 NFR-4，建议 `network_mode` 以保持服务可独立升级。 | P0 |
| 4 | autoservice 连接 channel-server | autoservice 容器启动 | autoservice 通过 `CHANNEL_SERVER_PORT` 环境变量连接 channel-server | WebChannelBridge 成功建立 WS 连接到 channel-server:9999 | 可行。`channels/web/websocket.py:26` 已通过 `CHANNEL_SERVER_URL` 配置。compose 中通过 service name DNS 解析 (`channel-server:9999`)。需将 `ws://localhost:9999` 改为 `ws://channel-server:9999`（或通过 env 注入）。 | 需注意：当前代码默认 `ws://localhost:9999`，容器化后需改为 service name。已有 `configure()` 函数和 env var 支持，改动最小。 | P0 |
| 5 | 前端 SPA 构建 + 静态服务 | frontend monorepo 代码 | `docker build` 前端镜像 (multi-stage: pnpm build → nginx serve) | 3 个 SPA 各自构建成功，nginx 正确服务静态文件 | 可行。multi-stage build: stage 1 用 node:20 + pnpm install + build；stage 2 用 nginx:alpine 拷贝 dist/。3 个 app 可共享 base image，用 build arg 区分 app name。 | 需注意 pnpm workspace 依赖：packages/ws-client、packages/i18n、packages/ui-components 是内部依赖，构建时需整个 monorepo context。 | P1 |
| 6 | 凭据和密钥挂载 | 宿主机有 `.env` + `.feishu-credentials.json` | docker compose up | 敏感文件通过 volume mount 或 docker secrets 注入容器 | 可行。建议用 `env_file` + `volumes` 挂载凭据目录。模板中用 `${TENANT_DATA_DIR}` 指向租户专属数据目录。 | 无。标准 docker secrets/volume 模式。 | P1 |
| 7 | 健康检查和依赖启动顺序 | 所有服务定义完整 | `docker compose up` | channel-server 先启动并健康 → autoservice 启动 → 前端启动 | 可行。用 `depends_on` + `healthcheck` 实现。channel-server healthcheck 可检查 9999 端口；autoservice healthcheck 检查 `/health` 端点（需确认是否存在，不存在则添加）。 | 需确认 autoservice 是否有 `/health` 端点。若无需新增简单 health check route。channel-server 作为外部服务需 healthcheck 策略。 | P1 |
| 8 | 模板文件结构 | — | 检查产出的文件组织 | 清晰的模板目录结构：Dockerfile(s) + docker-compose.tmpl.yaml + .env.tmpl + README | 产出结构建议：`deploy/docker-compose.tmpl.yaml` (主模板) + `deploy/autoservice.Dockerfile` + `deploy/frontend.Dockerfile` + `deploy/.env.tmpl` (环境变量模板) + `deploy/nginx/` (前端 nginx 配置) | 无。新建 `deploy/` 目录符合项目约定（不污染根目录）。 | P1 |
| 9 | T5B.3 租户创建脚本集成 | create-tenant.sh 存在 | create-tenant.sh 调用模板渲染 + docker compose up | 脚本能自动渲染模板并启动租户服务栈 | 可行但属于 T5B.3 范围。T5B.1 仅需确保模板格式兼容 envsubst/sed 替换。在模板中标注 `# T5B.3: 此处由 create-tenant.sh 替换` 注释。 | T5B.1 产出模板，T5B.3 产出脚本。接口约定：变量命名 + 替换机制需在 T5B.1 中确定。 | P2 |
| 10 | 开发模式 (dev) vs 生产模式 (prod) | — | 使用不同 profile 启动 | dev 模式挂载源码热更新，prod 模式用构建产物 | 可行。用 docker compose profiles: `--profile dev` 启用源码挂载 + 热更新端口；`--profile prod` 用构建镜像。或提供两份 override 文件。 | 建议用 `docker-compose.override.yml` (dev) + 基础文件 (prod) 模式，更符合 docker compose 约定。 | P2 |

## 风险点

1. **channel-server 镜像来源未定**: zchat channel-server 是外部项目（T5A.1 对齐中），镜像地址需占位。建议用 `${ZCHAT_IMAGE}` 变量。
2. **前端 monorepo 构建上下文**: pnpm workspace 内部依赖需整个 repo 作为 build context，可能导致镜像构建缓慢。建议用 `.dockerignore` 排除不必要文件。
3. **数据持久化**: `.autoservice/` 运行时数据 (logs, cache, db) 需 volume 持久化，否则容器重启丢失。

## 后续行动

- [ ] eval-doc 已注册到 .artifacts/eval-docs/
- [ ] 用户已确认 testcase 表格 (status: draft → confirmed)
