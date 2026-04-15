# Batch 1 Kickoff · 骨架并行搭建

> 2026-04-15 · **AI 快车道：2 小时完成**（Wed 12:30-14:30）
> M0 通过后立即启动，与午休并行
> 目标: 3 个骨架任务并行搭好，为 Phase 1 核心开发铺底
> 执行方式: **无需 pair**；A/B 各自在自己的 worktree 独立跑
>
> **时间说明**：原计划 1-2 天，因 AI 并发执行压缩为 **2 小时**。DevA 串行 T0.4→T0.5 约 1.5h，DevB 独立 T0.6 约 1.5h，尾段 30 分钟联调。

---

## 0. 前置条件（M0 必须通过）

开始 Batch 1 前确认（直接验证 dev 分支文件，不依赖 task-status 行状态）：

```bash
# A. Protocol 包已落地
ls autoservice/conversation_engine/__init__.py \
   autoservice/conversation_engine/protocol.py \
   autoservice/conversation_engine/types.py \
   autoservice/conversation_engine/events.py \
   autoservice/conversation_engine/errors.py

# B. 契约文档齐全
ls docs/contracts/conversation-engine.md \
   docs/contracts/frontend-ws-schema.md \
   docs/contracts/test-vectors/events.json

# C. 契约测试全绿
pytest tests/contract/ -v
```

三项均通过 = M0 达成。

**task-status.md 滞后修正（DevA 开工前第一件事）**：
当前 task-status.md 中 T0.2/T0.3 可能仍标 ⬜，但实际交付已完成。DevA 用 Edit 把 T0.2 和 T0.3 改为 🟩 并填 Owner（若之前已有 owner 保留；否则填 DevA），然后 commit `task: T0.2/T0.3 → completed (status catch-up)`。**不改 T0.4/T0.5/T0.6**（那是下面要做的新任务）。

未通过则回到 `batch-0-kickoff.md` 补完。

---

## 1. 任务分配

> **路径约定**（与 M0 实际交付对齐）：LocalEngine 与 Protocol 同包，不新建 `autoservice/engine/`。
> T0.4 只在 `autoservice/conversation_engine/` 里**新增 `local_engine.py`**，复用现有 `protocol.py` / `types.py` / `events.py` / `errors.py`。

| 任务 | Owner | 类型 | 依赖 | 预期产出 |
|---|---|---|---|---|
| T0.4 LocalEngine 骨架 | **DevA** | 🟢 Green | T0.1 | `autoservice/conversation_engine/local_engine.py` (单文件，含 Protocol 合规空壳) |
| T0.5 WebSocket 服务端骨架 | **DevA** | 🟢 Green | T0.2 | `autoservice/web_gateway.py` FastAPI + WS + `autoservice/gateway/` |
| T0.6 前端 monorepo 骨架 | **DevB** | 🟢 Green | T0.2 | `frontend/` pnpm workspace + 3 app stub |

**并行策略**: 
- DevA 串行做 T0.4 → T0.5（同一技术栈可复用上下文）
- DevB 独立做 T0.6
- 两人**不需要同屏**；各自 commit + push，尾段 30 分钟联调对齐

---

## 2. DevA · T0.4 LocalEngine 骨架

在 `AutoService-dev-a` worktree 打开 CC，贴：

```
启动任务 T0.4 LocalEngine 骨架（🟢 Green，A 线）。

**前置检查**（验证 M0 实际交付）:
1. 确认 autoservice/conversation_engine/ 下已有 protocol.py / types.py / events.py / errors.py / __init__.py
2. 确认 docs/contracts/ 下已有 conversation-engine.md / frontend-ws-schema.md / test-vectors/
3. 跑 pytest tests/contract/ -v 全绿
4. 任一不满足 → 停住报告（说明 M0 尚未完整交付）

**步骤**:
1. Edit task-status.md T0.4 → 🟦，Owner 改为 DevA，commit "task: T0.4 → in_progress (DevA)"
2. 读 autoservice/conversation_engine/protocol.py 了解完整 ConversationEngine 接口签名
3. 读 autoservice/conversation_engine/types.py / events.py / errors.py 了解已定义的枚举和异常
4. 读 docs/contracts/conversation-engine.md 作为语义参考
5. 进入 dev-loop:
   a. skill-5-feature-eval simulate 模式：起草 eval-doc
      - 模拟场景：LocalEngine 被初始化 → create_conversation → send_reply → switch_mode → resolve 的完整流程
      - 产出 .artifacts/eval-docs/eval-T0.4-local-engine-skeleton.md
      - 注册到 registry
   b. 停住等我 review eval-doc

**特别约束（关键 · 避免与 T0.1 已有文件冲突）**:
- **只新增一个文件**: autoservice/conversation_engine/local_engine.py
- **不要动**: __init__.py / protocol.py / types.py / events.py / errors.py（M0 已产出，改动视为契约漂移）
- local_engine.py 含:
  - `class LocalEngine:` 实现 protocol.ConversationEngine（Protocol 或 ABC 按 T0.1 定义而定）
  - 每方法体 `raise NotImplementedError("T1A.x: <简述>")`，用对应的 T1A.x 任务 ID 作为 hint
  - 直接 `from .types import Mode, Visibility, TimerType` 等（复用 T0.1 枚举，不要重复定义）
  - 直接 `from .events import Event, EventType` 等
  - 直接 `from .errors import ...`
- 最后在 autoservice/conversation_engine/__init__.py 末尾追加一行 `from .local_engine import LocalEngine`（保持 T0.1 已有 export 不动）
- 不新建 autoservice/engine/ 目录

每步汇报，不跳步。
```

**eval-doc 通过后继续：**

```
继续 T0.4:
1. skill-2-test-plan-generator 基于 eval-doc 产出 test-plan
   - test-plan 重点：接口合规测试（Protocol 方法签名匹配）+ 枚举完整性
   - 不测业务逻辑（因为是空骨架）
2. 产出后停住让我确认
```

**test-plan 通过后继续：**

```
继续 T0.4:
1. skill-3-test-code-writer 基于 test-plan 写单测
   - 放 tests/conversation_engine/test_local_engine.py（新建 tests/conversation_engine/ 目录 + __init__.py）
2. 创建 autoservice/conversation_engine/local_engine.py 并在 __init__.py 追加 export
3. skill-4-test-runner 跑 pytest tests/conversation_engine/ 和 tests/contract/（确保 T0.3 测试仍然全绿，未因 __init__.py 改动受影响）
4. 全绿 → 归档（§3 归档模板）
5. 红 → 定位原因并修复；若 tests/contract/ 回归失败，优先回退 __init__.py 的改动
```

**归档：**

```
T0.4 dev-loop 全绿，归档：
1. Edit task-status.md T0.4 → 🟩
2. "关联"列填 4 个 artifact ID（从 registry.json 查）
3. commit "feat(T0.4): LocalEngine skeleton with Protocol-compliant stubs"
4. 任务完成不要 push，等 T0.5 一起
5. 输出下一个任务（应为 T0.5）的启动建议
```

---

## 3. DevA · T0.5 WebSocket 服务端骨架

T0.4 完成后继续在同一 worktree 贴：

```
启动任务 T0.5 WebSocket 服务端骨架（🟢 Green，A 线）。

**前置**:
1. 读 docs/plans/task-status.md 确认 T0.4 🟩 + T0.5 ⬜
2. Edit T0.5 → 🟦 (DevA)，commit "task: T0.5 → in_progress (DevA)"

**步骤**:
1. 读 docs/contracts/frontend-ws-schema.md (T0.2 产物) 所有消息类型
2. 读 autoservice/conversation_engine/protocol.py (T0.1 产物) 了解 Engine 接口签名
3. 读 autoservice/conversation_engine/local_engine.py (T0.4 产物) 确认可实例化
4. 读 docs/contracts/test-vectors/events.json 作为入消息样本
5. 进入 dev-loop:
   a. skill-5-feature-eval simulate: 模拟前端 WS 连接 → 发 client_hello → 收 welcome → 发 customer_message → 收 agent_reply（或 not_implemented error）的握手流程
   b. 停住等 review

**产出文件**:
- autoservice/web_gateway.py: FastAPI app + 3 路 WebSocket 端点（/ws/customer, /ws/operator, /ws/admin）
- autoservice/gateway/__init__.py
- autoservice/gateway/message_router.py: 按 T0.2 schema 分发消息到 Engine 方法
- autoservice/gateway/connection.py: 维护 session_id → conversation_id 映射

**特别约束**:
- 引用 Engine 统一走 `from autoservice.conversation_engine import ConversationEngine`（Protocol/ABC），而非具体 LocalEngine，方便 M5 切换 ZchatEngine
- 启动时注入：`engine: ConversationEngine = LocalEngine()`（可配置）
- 每条入消息过 schema 校验（用 T0.3 的 test-vectors 作为参考 validator）
- Engine 方法抛 NotImplementedError 时，gateway 返回标准 error 消息（按 T0.2 schema 的 error 消息类型），不崩
- 心跳：客户端 ping → 服务端 pong（按 schema）
- 连接管理：维护 session_id → conversation_id 映射（内存 dict 即可，M5 再考虑持久化）
- CORS：默认允许 localhost:5173-5175（T0.6 的 3 个 app 端口）

每步汇报。
```

**标准 dev-loop 流程同 T0.4**（review → plan → test → code → run → 归档）。

---

## 4. DevB · T0.6 前端 monorepo 骨架

在 `AutoService-dev-b` worktree 打开 CC，贴：

```
启动任务 T0.6 前端 monorepo 骨架（🟢 Green，B 线）。

**前置**:
1. 读 docs/plans/task-status.md 确认 T0.6 ⬜
2. Edit T0.6 → 🟦 (DevB)，commit "task: T0.6 → in_progress (DevB)"

**技术选型决策**（需我在第一步确认）:
1. 包管理: pnpm workspace（推荐）vs npm workspace vs yarn？
2. 框架: React + Vite（推荐）vs Vue + Vite vs Next.js？
3. UI 库: MUI vs Ant Design（推荐 AD，中文场景友好）vs Tailwind + Radix？
4. 状态管理: Zustand（推荐）vs Redux Toolkit vs Pinia（Vue）？
5. WS 客户端: 原生 WebSocket 封装 vs socket.io-client？
   - **强约束**: 必须兼容 T0.2 原生 WS schema，不能依赖 socket.io 协议

起草决策 + 理由 → 停住让我批（3 分钟内给答复）
```

**决策后继续：**

```
决策已定：{pnpm / React / Ant Design / Zustand / 原生 WS}

进入 dev-loop:
1. skill-5-feature-eval simulate: 模拟 frontend 目录被创建 → 3 个 app 可 `pnpm dev` 独立启动 → 共享 packages/ws-client 跑通握手的场景
2. 产出 eval-doc → 停住 review
```

**eval-doc 通过后：**

```
继续 T0.6:

**目标目录结构**:
```
frontend/
├── package.json              # workspace root
├── pnpm-workspace.yaml
├── tsconfig.base.json
├── apps/
│   ├── customer-chat/        # T1B.1 扩展此目录
│   │   ├── package.json
│   │   ├── vite.config.ts
│   │   ├── src/
│   │   │   ├── App.tsx
│   │   │   ├── main.tsx
│   │   │   └── hooks/useWebSocket.ts   # 用 packages/ws-client
│   │   └── index.html
│   ├── operator-console/     # T2B.1 扩展
│   │   └── (同上骨架)
│   └── admin-portal/         # T3B.1 扩展
│       └── (同上骨架)
└── packages/
    ├── ws-client/            # 共享 WebSocket 客户端（消费 T0.2 schema）
    │   ├── package.json
    │   ├── src/
    │   │   ├── client.ts     # WebSocket 封装 + 重连 + 心跳
    │   │   ├── types.ts      # 从 docs/contracts/frontend-ws-schema.md 同步的 TS 类型
    │   │   └── index.ts
    │   └── tests/
    ├── ui-components/        # 共享 UI 组件（骨架）
    │   └── (空)
    └── i18n/                 # 22 语种占位（T1B.6 填）
        └── locales/
            ├── en.json
            └── zh-CN.json
```

**特别约束**:
- 三个 app 的 vite.config.ts 各自端口（customer:5173 / operator:5174 / admin:5175），方便本地 `pnpm dev` 并跑
- ws-client/types.ts 从 T0.2 schema 手工对齐（M1 前可以考虑加自动生成脚本）
- 每个 app 的 App.tsx 只渲染 "T1B.x TODO" 占位，连上 ws-client 打印 welcome 消息即可
- 所有 app 共用 tsconfig.base.json
- 根目录 package.json 提供 scripts: `dev:customer`, `dev:operator`, `dev:admin`, `build:all`, `test`, `lint`

**验收标准**（跑在 skill-4-test-runner 后）:
1. `pnpm install` 成功
2. `pnpm dev:customer` 起服务，浏览器打开可见 "T1B.x TODO"
3. customer app 尝试连 ws://localhost:9999/ws/customer（不要求连上，因为 T0.5 可能还没跑起来，看到 reconnect 日志即可）
4. 所有 TS 类型校验通过 `pnpm -r exec tsc --noEmit`

按顺序执行。
```

**标准 dev-loop + 归档同 T0.4**。

---

## 5. 两人联调检查点（Wed 14:00-14:30）

### 验证跨线能连通

- **DevA** 在自己的 worktree 启动 web_gateway：
  ```bash
  cd AutoService-dev-a
  python -m autoservice.web_gateway  # 默认 :9999
  ```

- **DevB** 在自己的 worktree 启动 customer-chat：
  ```bash
  cd AutoService-dev-b/frontend
  pnpm dev:customer  # :5173
  ```

- 打开 http://localhost:5173，F12 观察 WS 连接到 `ws://localhost:9999/ws/customer`
- 期望：客户端发 `client_hello`，服务端返 `welcome`（或 `error: not_implemented` 但至少格式符合 schema）
- **不期望**：连不上、schema 不匹配、5xx

若联通 → Batch 1 M0.5 小里程碑达成。

### 若不联通

标注 ⚠️ blocked 的任务，开 GitHub Issue 描述：
- A 看到什么日志
- B 看到什么错误
- 预期 schema vs 实际收到的

常见问题：
- 端口错（T0.5 默认 9999，T0.6 默认连 9999，改任一都要同步）
- schema 字段遗漏（回 T0.2 加字段 → 走契约漂移流程 `cc-prompt-templates §8`）
- CORS（T0.5 需加 `fastapi.middleware.cors` 允许 :5173-5175）

---

## 6. Batch 1 验收

Batch 1 完成标准：

- [ ] task-status.md 中 T0.2/T0.3/T0.4/T0.5/T0.6 均为 🟩（T0.1 已在 M0 标完）
- [ ] `pytest tests/contract/ tests/conversation_engine/ tests/gateway/` 全绿（注意 tests/contract/ 必须仍全绿）
- [ ] `pnpm --filter "./apps/*" test` 全绿
- [ ] 跨线联调（§5）：WS 握手成功
- [ ] 所有 artifact 注册到 `.artifacts/registry.json`
- [ ] Phase 0 完整完成（6/6 任务 🟩）

然后双方在 task-status.md 看 Phase 0 行应为：
```
| P0 | 6 | 0 | 0 | 6 | 0 |
```

---

## 7. 转入 Batch 2

Phase 0 全绿后，按 `cc-prompt-templates §12.1` "我该做什么？" 询问 CC：

**DevA** 应被推荐启动:
- T1A.1 Mode/Gate 最小实现
- T1A.2 Timer 最小实现
- T1A.3 EventBus 最小实现
（三个可串行或并行，取决于代码耦合度；建议串行 T1A.1→T1A.2→T1A.3，避免 merge 冲突）

**DevB** 应被推荐启动:
- T1B.1 customer-chat SPA 骨架（基于 T0.6 已有 stub）
- T1B.6 多语言 UI 框架（与 T1B.1 并行）

之后进入常态开发节奏（用 `cc-prompt-templates §1` 启动模板），Milestone-end 5 分钟同步机制生效。

---

## 8. 回滚预案

若 Batch 1 遇到重大阻塞（例：发现 T0.1 Protocol 遗漏方法，或 T0.2 schema 不足）：

1. 停下所有 Batch 1 工作
2. 走契约漂移流程（`cc-prompt-templates §8.1`）
3. 在 PR 中开子分支修 `autoservice/conversation_engine/protocol.py` 或 `docs/contracts/frontend-ws-schema.md`
4. 双方同意后更新契约 → 更新 test-vectors → 更新 tests/contract/ 下对应用例 → pytest tests/contract/ 必须仍全绿
5. Batch 1 从头或从被影响点继续

**关键约束**：`autoservice/conversation_engine/` 下 T0.1 已产出的 4 个文件（protocol/types/events/errors）视为 M0 冻结契约，任何改动都走漂移流程，不得在 Batch 1 中顺手改。唯一允许的动作是在 `__init__.py` 末尾追加 `LocalEngine` export。

---

## 附：时间预估参考（AI 快车道）

| 任务 | AI 实际耗时 | 主要风险 |
|---|---|---|
| T0.4 LocalEngine 骨架 | 20-30 min | Protocol 有模糊处需要回 T0.1 澄清 |
| T0.5 WS gateway 骨架 | 30-45 min | schema 某些消息类型边界不清 |
| T0.6 前端 monorepo | 30-45 min（含依赖安装）| 技术选型决策延迟 |
| 联调 § 5 | 15-30 min | CORS / 端口 / schema 细节 |
| **合计（并行）** | **1.5-2h** | 目标 Wed 14:30 前完成 |

*AI 执行时长极短；真实瓶颈是人审决策窗口——本阶段决策点仅 T0.6 技术选型一处，预留 5 分钟即可。*

---

*v1.0 · 2026-04-15 · 仅用于 Batch 1 一次性 kickoff；Phase 0 完成后归档*
