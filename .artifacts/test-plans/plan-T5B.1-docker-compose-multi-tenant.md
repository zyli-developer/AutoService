---
type: test-plan
id: plan-T5B.1
status: draft
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-T5B.1 (simulate): docker-compose 多租户模板"
related:
  - eval-T5B.1
---

# Test Plan: T5B.1 docker-compose 多租户模板

## 触发原因

eval-T5B.1 模拟评估通过，需要为 docker-compose 多租户模板创建验证测试。
该任务产出全新文件（Dockerfile、compose 模板、nginx 配置），无现有 code-diff。
测试目标：验证模板渲染正确性、compose 文件结构合法性、NFR-4 同主机约束、多租户端口隔离。

## 用例列表

### TC-001: compose 模板渲染产出有效 YAML

- **来源**：eval-doc TC1
- **优先级**：P0
- **前置条件**：`deploy/docker-compose.tmpl.yaml` 存在；`envsubst` 可用
- **操作步骤**：
  1. 设置环境变量 `TENANT=demo PORT_OFFSET=0 ZCHAT_IMAGE=zchat/channel-server:latest`
  2. 运行 `envsubst < deploy/docker-compose.tmpl.yaml > /tmp/test-compose.yml`
  3. 用 `docker compose -f /tmp/test-compose.yml config` 验证语法
- **预期结果**：
  - 渲染成功，无 envsubst 未替换的 `${...}` 残留
  - `docker compose config` 无报错
  - 输出包含 6 个 service 定义：autoservice、customer-chat、operator-console、admin-portal、channel-server、bridges
- **涉及模块**：deploy/

### TC-002: 6 个 service 端口映射正确（默认偏移）

- **来源**：eval-doc TC1
- **优先级**：P0
- **前置条件**：TC-001 渲染成功的 compose 文件
- **操作步骤**：
  1. 用 `PORT_OFFSET=0` 渲染模板
  2. 解析 YAML 提取每个 service 的 ports 映射
- **预期结果**：
  - autoservice: `8000:8000`
  - customer-chat: `5173:80` (nginx 内部 80)
  - operator-console: `5174:80`
  - admin-portal: `5175:80`
  - channel-server: `9999:9999`
- **涉及模块**：deploy/docker-compose.tmpl.yaml

### TC-003: 多租户端口偏移隔离

- **来源**：eval-doc TC2
- **优先级**：P0
- **前置条件**：模板存在
- **操作步骤**：
  1. 用 `TENANT=demo PORT_OFFSET=0` 渲染 → compose-demo.yml
  2. 用 `TENANT=acme PORT_OFFSET=100` 渲染 → compose-acme.yml
  3. 提取两份文件所有宿主机端口
  4. 检查无交集
- **预期结果**：
  - demo: 8000/5173/5174/5175/9999
  - acme: 8100/5273/5274/5275/10099
  - 两组端口零重叠
- **涉及模块**：deploy/docker-compose.tmpl.yaml

### TC-004: NFR-4 同主机约束 — bridges 与 channel-server 共享网络栈

- **来源**：eval-doc TC3
- **优先级**：P0
- **前置条件**：TC-001 渲染成功的 compose 文件
- **操作步骤**：
  1. 解析渲染后的 compose YAML
  2. 检查 bridges service 的 `network_mode` 字段
- **预期结果**：
  - bridges service 有 `network_mode: "service:channel-server"`
  - bridges service 没有独立的 `ports` 映射（因为共享 channel-server 网络栈）
  - bridges service 没有独立的 `networks` 定义
- **涉及模块**：deploy/docker-compose.tmpl.yaml

### TC-005: autoservice 环境变量指向 channel-server service name

- **来源**：eval-doc TC4
- **优先级**：P0
- **前置条件**：TC-001 渲染成功的 compose 文件
- **操作步骤**：
  1. 解析渲染后 compose YAML 中 autoservice service 的 environment 段
  2. 检查 CHANNEL_SERVER_PORT 或等效连接配置
- **预期结果**：
  - autoservice environment 包含指向 channel-server 的 WS URL（如 `CHANNEL_SERVER_URL=ws://channel-server:9999`）
  - 不含 `ws://localhost:9999`（容器间不可用）
- **涉及模块**：deploy/docker-compose.tmpl.yaml, channels/web/websocket.py

### TC-006: Dockerfile 构建成功 — autoservice

- **来源**：eval-doc TC1/TC4
- **优先级**：P1
- **前置条件**：`deploy/autoservice.Dockerfile` 存在；Docker daemon 运行
- **操作步骤**：
  1. `docker build -f deploy/autoservice.Dockerfile -t autoservice-test .`
  2. `docker run --rm autoservice-test python -c "from channels.web.app import app; print('ok')"`
- **预期结果**：
  - 构建成功，无报错
  - 容器内可导入 app 模块
- **涉及模块**：deploy/autoservice.Dockerfile

### TC-007: Dockerfile 构建成功 — frontend (3 apps)

- **来源**：eval-doc TC5
- **优先级**：P1
- **前置条件**：`deploy/frontend.Dockerfile` 存在；Docker daemon 运行
- **操作步骤**：
  1. 对每个 app (customer-chat, operator-console, admin-portal)：
     `docker build -f deploy/frontend.Dockerfile --build-arg APP_NAME=<app> -t <app>-test .`
  2. `docker run --rm <app>-test ls /usr/share/nginx/html/index.html`
- **预期结果**：
  - 3 个 app 各自构建成功
  - nginx 目录下有 index.html（Vite build 产出）
- **涉及模块**：deploy/frontend.Dockerfile, frontend/

### TC-008: 凭据挂载 — 敏感文件不进镜像

- **来源**：eval-doc TC6
- **优先级**：P1
- **前置条件**：TC-001 渲染成功的 compose 文件
- **操作步骤**：
  1. 解析 compose YAML 中 autoservice service 的 volumes 段
  2. 检查 `.env`、`.feishu-credentials.json`、`.autoservice/` 的挂载方式
  3. 检查 Dockerfile 中无 COPY 敏感文件指令
- **预期结果**：
  - compose 中有 volume mount 将宿主机凭据目录映射到容器
  - autoservice Dockerfile 无 `COPY .env` / `COPY .feishu-credentials.json`
  - `.dockerignore` 排除 `.env`、`.feishu-credentials.json`、`.autoservice/`
- **涉及模块**：deploy/docker-compose.tmpl.yaml, deploy/autoservice.Dockerfile, deploy/.dockerignore

### TC-009: 健康检查定义

- **来源**：eval-doc TC7
- **优先级**：P1
- **前置条件**：TC-001 渲染成功的 compose 文件
- **操作步骤**：
  1. 解析 compose YAML 中各 service 的 healthcheck 段
  2. 检查 depends_on 中的 condition 字段
- **预期结果**：
  - channel-server 有 healthcheck（TCP 9999 或 HTTP）
  - autoservice 有 healthcheck（HTTP /health 或 TCP 8000）
  - autoservice `depends_on` channel-server `condition: service_healthy`
  - 前端 services `depends_on` autoservice
- **涉及模块**：deploy/docker-compose.tmpl.yaml

### TC-010: .env.tmpl 模板包含所有必需变量

- **来源**：eval-doc TC6/TC8
- **优先级**：P1
- **前置条件**：`deploy/.env.tmpl` 存在
- **操作步骤**：
  1. 读取 .env.tmpl 内容
  2. 检查必需变量是否都有声明（含注释说明）
- **预期结果**：
  - 包含：`TENANT`、`PORT_OFFSET`、`ZCHAT_IMAGE`、`ANTHROPIC_API_KEY`、`DEMO_PORT`、`CHANNEL_SERVER_URL`
  - 每个变量有注释说明用途和默认值
  - 敏感变量有 `# REQUIRED — no default` 标注
- **涉及模块**：deploy/.env.tmpl

### TC-011: deploy/ 目录结构完整性

- **来源**：eval-doc TC8
- **优先级**：P1
- **前置条件**：deploy/ 目录已创建
- **操作步骤**：
  1. 检查 deploy/ 下文件列表
- **预期结果**：
  - `deploy/docker-compose.tmpl.yaml` — 主 compose 模板
  - `deploy/autoservice.Dockerfile` — Python 后端 Dockerfile
  - `deploy/frontend.Dockerfile` — 前端 multi-stage Dockerfile
  - `deploy/.env.tmpl` — 环境变量模板
  - `deploy/.dockerignore` — 构建排除列表
  - `deploy/nginx/default.conf` — 前端 nginx 配置
- **涉及模块**：deploy/

### TC-012: 数据持久化 volume 定义

- **来源**：eval-doc 风险点 3
- **优先级**：P1
- **前置条件**：TC-001 渲染成功的 compose 文件
- **操作步骤**：
  1. 解析 compose YAML 中 autoservice 的 volumes 段
  2. 检查 .autoservice/ 运行时目录的挂载
- **预期结果**：
  - autoservice service 有 named volume 或 bind mount 映射 `.autoservice/` 到宿主机持久化目录
  - volume 路径使用 `${TENANT}` 变量实现租户隔离（如 `./data/${TENANT}/.autoservice`)
- **涉及模块**：deploy/docker-compose.tmpl.yaml

## 统计

| 指标 | 值 |
|------|-----|
| 总用例数 | 12 |
| P0 | 5 |
| P1 | 7 |
| P2 | 0 |
| 来源：eval-doc | 12 |
| 来源：code-diff | 0 |
| 来源：coverage-gap | 0 |
| 来源：bug-feedback | 0 |

## 风险标注

- **高风险**：TC-004 (NFR-4 `network_mode` 正确性) — 配置错误会导致 bridge 延迟放大 10×，直接违反 NFR-1
- **回归风险**：TC-005 (WS URL 容器化适配) — 现有代码默认 `localhost:9999`，容器化后必须改为 service name
- **覆盖未知**：无 coverage-matrix（新增功能，无历史覆盖）

## 测试实现说明

T5B.1 的测试为**静态验证 + Docker 构建验证**，不需要运行时 E2E：
- TC-001~005, 008~012: 解析 YAML 和 Dockerfile 的静态检查（pytest + PyYAML）
- TC-006~007: Docker 构建验证（需 Docker daemon，CI 环境可标记 `@pytest.mark.docker`）
