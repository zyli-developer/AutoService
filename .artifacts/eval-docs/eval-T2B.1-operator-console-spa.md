# eval-doc-009 · T2B.1 operator-console SPA 骨架

> **Mode**: simulate · **Owner**: DevB · **Date**: 2026-04-16

---

## 1. 任务目标

基于 T0.6 已有的 operator-console 骨架，实现完整的工作台 SPA：
- **登录页**：operator 输入 token 认证后进入工作台
- **分队视图主布局**：侧边栏导航 + 主内容区（卡片列表占位）
- **WS `/ws/operator` 连接**：连接后自动发 `subscribe` 订阅 squad 事件
- **Squad store**：Zustand 管理 squadId、conversations、operatorId
- 为 T2B.2（分队卡片 UI）预留扩展点

---

## 2. 现有代码分析

### 2.1 已有（T0.6 骨架）

| 文件 | 内容 |
|---|---|
| `src/main.tsx` | Antd ConfigProvider + I18nextProvider + App 挂载 |
| `src/App.tsx` | 单页占位：Layout + Tag 显示 WS 状态 |
| `src/hooks/useWebSocket.ts` | 基础 WSClient 封装（无 subscribe、无 squad 逻辑）|
| `package.json` | antd ^5, zustand ^4, @autoservice/ws-client, i18n；**无 vitest** |
| `vite.config.ts` | 仅 react plugin，无 test 配置 |

### 2.2 缺失（T2B.1 需新增）

| 缺口 | 说明 |
|---|---|
| 登录页 + 路由 | `LoginPage` + `react-router-dom` 或轻量路由 |
| Squad store | Zustand `useOperatorStore`（operatorId, squads, wsStatus）|
| `useOperatorWS` hook | 扩展现有 hook：连接 `/ws/operator`、发 client_hello（operator_id + squads）、发 F6 subscribe |
| `SquadView` 布局 | Antd Layout（Sider + Content）；Content 内放 squad tabs + 卡片区占位 |
| Vitest 测试框架 | 与 customer-chat 保持一致：vitest + @testing-library/react + jsdom |

---

## 3. 架构设计

### 3.1 路由策略

使用**最轻量的内部路由**（无 react-router-dom），通过 Zustand store 的 `isLoggedIn` 状态切换：

```
App.tsx
  ├── isLoggedIn = false  →  <LoginPage />
  └── isLoggedIn = true   →  <WorkspacePage />
```

理由：operator-console 是内部工具，无 deep-link 需求；避免引入额外依赖。

### 3.2 登录页 (`LoginPage`)

```
+----------------------------------+
|   AutoService · 工作台登录        |
+----------------------------------+
|  Operator ID:  [____________]    |
|  Token:        [____________]    |
|                [  登 录  ]       |
+----------------------------------+
```

- `operatorId` + `token` 输入框
- 点击"登录"→ 保存到 store，`isLoggedIn = true`
- **本期不做真实鉴权**（M2 联调时后端提供 token 验证）；token 仅存 memory，用于 WS `Authorization` header（ws-client 的 `headers` 选项）
- 错误状态：空 operatorId 不允许提交

### 3.3 Operator Store (`useOperatorStore`)

```typescript
interface OperatorState {
  // 认证
  operatorId: string | null;
  token: string | null;
  isLoggedIn: boolean;
  
  // WS 状态
  wsStatus: 'idle' | 'connecting' | 'open' | 'closed';
  sessionId: string | null;
  
  // Squad 订阅
  squads: string[];              // 当前已订阅的 squad_id 列表
  activeSquadId: string | null;  // 当前选中的 squad tab
  subscriptions: Record<string, string>; // squad_id → subscription_id（来自 S13）
  
  // 操作
  login: (operatorId: string, token: string) => void;
  logout: () => void;
  setWsStatus: (s: OperatorState['wsStatus']) => void;
  setSessionId: (id: string) => void;
  addSquad: (squadId: string) => void;
  setActiveSquad: (squadId: string) => void;
  addSubscription: (squadId: string, subscriptionId: string) => void;
}

export const initialState = { /* 所有字段初始值，供测试 reset 用 */ };
```

### 3.4 `useOperatorWS` hook

```typescript
export function useOperatorWS(): { send: (frame: Envelope) => void }
```

连接流程：
1. `isLoggedIn = true` → `useEffect` 创建 `WSClient`，连接 `/ws/operator`
2. `onOpen(hello)` → `setSessionId(hello.session_id)` + `setWsStatus('open')`
3. 连接成功后，对 store 中每个 `squad_id` 发 F6 `subscribe`：
   ```json
   { "type": "subscribe", "payload": { "scope": { "squad_id": "<id>" } } }
   ```
4. `onFrame` 处理：
   - `S13 subscription_added` → `addSubscription(squad_id, subscription_id)`
   - `S8 event`（squad.assigned / squad.reassigned / conversation.* 等）→ 留 TODO，T2B.2 实现
5. `onClose` → `setWsStatus('closed')`
6. 心跳：`heartbeatMs: 20_000`（与 customer-chat 一致）

### 3.5 WorkspacePage 布局

```
+-----+------------------------------------------+
| 侧  |  [Squad-A] [Squad-B] [+ 添加 Squad]       |
| 边  |------------------------------------------+
| 栏  |                                           |
|     |   <SquadTabPane squadId="Squad-A">        |
| Logo|     [ 卡片列表区 — T2B.2 TODO ]           |
|     |                                           |
| 退  |   (暂显 WS 状态 + 原始 event 帧 JSON)     |
| 出  |                                           |
+-----+------------------------------------------+
```

组件树：
```
WorkspacePage
  ├── <Sider>
  │     ├── Logo
  │     ├── <Menu> (squad list)
  │     └── LogoutButton
  └── <Content>
        ├── ConnectionBanner (wsStatus)
        └── <Tabs> (activeSquadId)
              └── <TabPane key={squadId}>
                    <SquadPane squadId={squadId} />  ← T2B.2 扩展点
```

### 3.6 初始 Squad 列表

登录后，暂从 store 手动添加 squad（T2B.2 实现后改为从 server_hello 的 accepted_subscriptions 读取）。WorkspacePage 提供一个"添加 Squad ID"的简单输入框，供联调时手动订阅。

### 3.7 测试框架接入

operator-console 目前无 vitest。需新增：

```json
// package.json devDependencies
"vitest": "^1.5.0",
"@vitest/coverage-v8": "^1.5.0",
"@testing-library/react": "^14.0.0",
"@testing-library/user-event": "^14.0.0",
"jsdom": "^24.0.0"
```

```typescript
// vite.config.ts 增加 test 字段
test: {
  environment: 'jsdom',
  globals: true,
  setupFiles: ['src/__tests__/setup.ts'],
}
```

### 3.8 FakeWSClient（复用模式）

与 customer-chat 的 `fakeWSClient.ts` 结构一致，但 `triggerOpen` 时发送 operator 版 server_hello（`viewer_role: 'OPERATOR'`）。

---

## 4. 关键设计决策

### D1. 路由方式

**决策**：`isLoggedIn` 状态切换，不引入 react-router-dom。
- operator-console 无需 URL 深链接，单一 SPA 路由即可
- 减少依赖，与 customer-chat 风格一致

### D2. Squad 初始化方式

**决策**：手动输入 squadId（联调占位），不从配置文件读取。
- T2A.1（协议命令实现）完成后 server_hello.accepted_subscriptions 会带 squad 列表；T2B.2 时补接真实数据
- 骨架先打通 WS subscribe 链路

### D3. token 存储

**决策**：仅存 memory（Zustand），不存 localStorage。
- 安全性：operator token 不持久化，刷新需重新登录
- 开发期可后续升级为 SSO（不影响骨架设计）

### D4. Antd vs Tailwind

**决策**：全用 **Antd**（T0.6 骨架已引入，package.json 已有 antd ^5）。
- operator-console 是内部工具，Antd 组件库更适合 dashboard 类 UI
- customer-chat 用 Tailwind（面向客户），两个应用风格分开

### D5. 测试范围

**决策**：测试覆盖 store 逻辑 + WS hook 行为 + 登录组件，不测 Antd 内部样式。

---

## 5. 测试规划概览

| 分组 | TC 编号 | 文件 | P0 | P1 |
|---|---|---|---|---|
| A. store 初始状态与 actions | TC-001~005 | operatorStore.test.ts | 4 | 1 |
| B. 登录页交互 | TC-006~009 | LoginPage.test.tsx | 3 | 1 |
| C. useOperatorWS hook | TC-010~015 | useOperatorWS.test.tsx | 4 | 2 |
| D. WorkspacePage 集成 | TC-016~020 | integration.test.tsx | 3 | 2 |

**共 20 个新用例**（operator-console 独立包，全新测试文件）。

---

## 6. 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| `/ws/operator` 后端未实现（T2A.1 未完成） | 中 | 用 FakeWSClient mock；联调时替换真实 URL |
| Antd 组件在 jsdom 中渲染警告 | 低 | `setupFiles` 中 mock `window.matchMedia`（Antd 常见 jsdom 兼容 fix）|
| squad 列表为空（登录后无 squad 可订阅） | 低 | 提供手动输入框；默认加一个 "default" squad |

---

## 7. 不在范围

- 真实 OAuth/SSO 鉴权（T2A 联调时接入）
- 分队卡片 5 状态 UI（T2B.2）
- Copilot 侧栏（T2B.3）
- /hijack 按钮（T2B.4）
- 并发上限（T2B.6）、未读徽章（T2B.7）

---

## 8. 产出清单

| # | 文件 | 动作 | 说明 |
|---|---|---|---|
| 1 | `package.json` | **修改** | 新增 vitest + @testing-library/* devDeps |
| 2 | `vite.config.ts` | **修改** | 新增 test 配置（jsdom, globals, setupFiles）|
| 3 | `src/store/operatorStore.ts` | **新建** | Zustand store（含 initialState export）|
| 4 | `src/hooks/useOperatorWS.ts` | **新建** | 替换原 useWebSocket；含 subscribe 逻辑 |
| 5 | `src/components/LoginPage.tsx` | **新建** | 登录表单 |
| 6 | `src/components/WorkspacePage.tsx` | **新建** | 主工作台布局（Sider + Tabs + SquadPane）|
| 7 | `src/components/SquadPane.tsx` | **新建** | 单 squad 卡片区占位（T2B.2 扩展点）|
| 8 | `src/components/ConnectionBanner.tsx` | **新建** | 复用 customer-chat 风格，显示 WS 状态 |
| 9 | `src/App.tsx` | **重写** | isLoggedIn 切换 LoginPage / WorkspacePage |
| 10 | `src/__tests__/setup.ts` | **新建** | matchMedia mock + afterEach store reset |
| 11 | `src/__tests__/fakeWSClient.ts` | **新建** | 复用模式，triggerOpen 发 OPERATOR hello |
| 12 | `src/__tests__/operatorStore.test.ts` | **新建** | TC-001~005 |
| 13 | `src/__tests__/LoginPage.test.tsx` | **新建** | TC-006~009 |
| 14 | `src/__tests__/useOperatorWS.test.tsx` | **新建** | TC-010~015 |
| 15 | `src/__tests__/integration.test.tsx` | **新建** | TC-016~020 |

---

*eval-doc-009 · T2B.1 · simulate · 待 review*
