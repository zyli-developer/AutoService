---
type: test-plan
id: test-plan-008
status: confirmed
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-doc-009 (T2B.1 operator-console SPA 骨架) — confirmed"
related:
  - eval-doc-009
  - "task:T2B.1"
decisions_frozen:
  D1: "isLoggedIn 状态切换路由，不引入 react-router-dom"
  D2: "Squad ID 手动输入占位，T2B.2 接 server_hello.accepted_subscriptions"
  D3: "Token 仅存 memory（Zustand），不持久化"
  D4: "全 Antd，operator-console 内部工具风格"
  D5: "20 个用例 TC-001~020，operator-console 独立包"
---

# Test Plan: T2B.1 operator-console SPA 骨架

## 触发原因

eval-doc-009 定义了 15 个新文件（store / hooks / components / tests）。
本 plan 共 **20 个用例**，覆盖：
Operator store 逻辑、登录页交互、useOperatorWS WS 连接与 subscribe、WorkspacePage 集成。

## 测试文件规划

```
frontend/apps/operator-console/src/__tests__/
  setup.ts                  新建（matchMedia mock + afterEach store reset）
  fakeWSClient.ts           新建（OPERATOR viewer_role hello）
  operatorStore.test.ts     新建（TC-001~005）
  LoginPage.test.tsx        新建（TC-006~009）
  useOperatorWS.test.tsx    新建（TC-010~015）
  integration.test.tsx      新建（TC-016~020）
```

目标：**20/20 全绿**。

---

## 用例列表

### 分组 A · Operator Store（TC-001 ~ TC-005）

#### TC-001: 初始状态正确
- **文件**: `operatorStore.test.ts`
- **优先级**: P0
- **步骤**: `const s = useOperatorStore.getState()`
- **预期**:
  ```
  isLoggedIn === false
  operatorId === null
  token === null
  wsStatus === 'idle'
  squads === []
  activeSquadId === null
  subscriptions === {}
  ```

#### TC-002: login() 更新 isLoggedIn + operatorId + token
- **文件**: `operatorStore.test.ts`
- **优先级**: P0
- **步骤**: `useOperatorStore.getState().login('op-001', 'tok-xyz')`
- **预期**: `isLoggedIn === true`, `operatorId === 'op-001'`, `token === 'tok-xyz'`

#### TC-003: logout() 重置 isLoggedIn 为 false
- **文件**: `operatorStore.test.ts`
- **优先级**: P0
- **步骤**: login → logout
- **预期**: `isLoggedIn === false`, `operatorId === null`, `wsStatus === 'idle'`

#### TC-004: addSquad() 追加 squadId；setActiveSquad() 更新 activeSquadId
- **文件**: `operatorStore.test.ts`
- **优先级**: P0
- **步骤**:
  1. `addSquad('sq-A')` → `squads === ['sq-A']`
  2. `addSquad('sq-A')` （重复）→ `squads === ['sq-A']`（幂等）
  3. `setActiveSquad('sq-A')` → `activeSquadId === 'sq-A'`

#### TC-005: addSubscription() 更新 subscriptions map
- **文件**: `operatorStore.test.ts`
- **优先级**: P1
- **步骤**: `addSubscription('sq-A', 'sub-001')` → `subscriptions['sq-A'] === 'sub-001'`

---

### 分组 B · LoginPage 交互（TC-006 ~ TC-009）

#### TC-006: 初始渲染显示登录表单
- **文件**: `LoginPage.test.tsx`
- **优先级**: P0
- **步骤**: `render(<LoginPage />)`
- **预期**: 存在 `input[placeholder*="Operator ID"]`（或 data-testid="input-operator-id"）和 `input[type="password"]`（或 data-testid="input-token"）及提交按钮

#### TC-007: 填写表单点击登录 → store.isLoggedIn === true
- **文件**: `LoginPage.test.tsx`
- **优先级**: P0
- **步骤**:
  1. render `<LoginPage />`
  2. `userEvent.type(operatorIdInput, 'op-001')`
  3. `userEvent.type(tokenInput, 'tok-xyz')`
  4. `userEvent.click(submitBtn)`
- **预期**: `useOperatorStore.getState().isLoggedIn === true`, `operatorId === 'op-001'`

#### TC-008: operatorId 为空时点击登录无效（按钮 disabled 或无操作）
- **文件**: `LoginPage.test.tsx`
- **优先级**: P0
- **步骤**: 不填 operatorId，点击登录按钮
- **预期**: `useOperatorStore.getState().isLoggedIn === false`

#### TC-009: token 为空时可以登录（token 可选）
- **文件**: `LoginPage.test.tsx`
- **优先级**: P1
- **步骤**: 填 operatorId，不填 token，点击登录
- **预期**: `isLoggedIn === true`（token 为空字符串可接受）

---

### 分组 C · useOperatorWS hook（TC-010 ~ TC-015）

> 使用 FakeWSClient（connect=no-op，triggerOpen 发 OPERATOR server_hello）

#### TC-010: 未登录时不发起 WS 连接
- **文件**: `useOperatorWS.test.tsx`
- **优先级**: P0
- **步骤**: render hook，store.isLoggedIn = false
- **预期**: `fakeInstance.connectCallCount === 0`（或 WSClient 构造函数未被调用）

#### TC-011: 登录后 wsStatus 变为 'connecting' → triggerOpen 后变为 'open'
- **文件**: `useOperatorWS.test.tsx`
- **优先级**: P0
- **步骤**:
  1. store.login('op-001', 'tok')
  2. render hook → wsStatus = 'connecting'
  3. `act(() => fakeInstance.triggerOpen(operatorHello))`
- **预期**: `wsStatus === 'open'`, `sessionId` 非 null

#### TC-012: triggerOpen 后，store 中每个 squad 都发出 F6 subscribe 帧
- **文件**: `useOperatorWS.test.tsx`
- **优先级**: P0
- **步骤**:
  1. store.login + store.addSquad('sq-A') + store.addSquad('sq-B')
  2. render hook + triggerOpen
- **预期**: `fakeInstance.sendCalls` 包含两个 `type === 'subscribe'` 帧，payload.scope.squad_id 分别为 'sq-A' / 'sq-B'

#### TC-013: 收到 S13 subscription_added → store.subscriptions 更新
- **文件**: `useOperatorWS.test.tsx`
- **优先级**: P0
- **步骤**:
  1. login + addSquad('sq-A') + render hook + triggerOpen
  2. `fakeInstance.pushFrame({ type: 'subscription_added', payload: { subscription_id: 'sub-001', scope: { squad_id: 'sq-A' } } })`
- **预期**: `useOperatorStore.getState().subscriptions['sq-A'] === 'sub-001'`

#### TC-014: WS close → wsStatus 变为 'closed'
- **文件**: `useOperatorWS.test.tsx`
- **优先级**: P1
- **步骤**: login + render hook + triggerOpen + `fakeInstance.pushClose(1001)`
- **预期**: `wsStatus === 'closed'`

#### TC-015: logout() → WS 连接关闭（client.close() 被调用）
- **文件**: `useOperatorWS.test.tsx`
- **优先级**: P1
- **步骤**: login + render hook + triggerOpen → `act(() => store.logout())`
- **预期**: `fakeInstance.closeCalled === true`（或 wsStatus = 'idle'）

---

### 分组 D · WorkspacePage 集成（TC-016 ~ TC-020）

#### TC-016: 未登录时渲染 LoginPage
- **文件**: `integration.test.tsx`
- **优先级**: P0
- **步骤**: render `<App />`（store 初始状态）
- **预期**: 屏幕有登录表单（operatorId input），无 Sider / Tabs

#### TC-017: 登录后渲染 WorkspacePage（含侧边栏和 WS 状态）
- **文件**: `integration.test.tsx`
- **优先级**: P0
- **步骤**:
  1. render `<App />`
  2. 填写登录表单 + 点击登录
- **预期**: 登录表单消失；出现 `data-testid="workspace-page"` 或侧边栏元素；出现 WS 连接状态指示

#### TC-018: 添加 Squad → Tab 出现
- **文件**: `integration.test.tsx`
- **优先级**: P0
- **步骤**:
  1. 登录后，在 WorkspacePage 输入 squad id "sq-A" → 点击"添加"
- **预期**: 出现 tab key="sq-A"（或含 "sq-A" 文字的 tab）

#### TC-019: 点击 Tab → activeSquadId 切换
- **文件**: `integration.test.tsx`
- **优先级**: P1
- **步骤**:
  1. 登录 + 添加 sq-A + 添加 sq-B
  2. 点击 sq-B tab
- **预期**: `useOperatorStore.getState().activeSquadId === 'sq-B'`

#### TC-020: 点击退出登录 → 回到 LoginPage
- **文件**: `integration.test.tsx`
- **优先级**: P1
- **步骤**:
  1. 登录进入 WorkspacePage
  2. 点击"退出"按钮
- **预期**: 重新显示登录表单；`isLoggedIn === false`

---

## 统计

| 指标 | 值 |
|---|---|
| 新增用例 | 20 |
| 目标 | **20/20** |
| P0 | 13 |
| P1 | 7 |
| 新建测试文件 | 6 |

## Skill-3 实现约束

1. **Vitest 接入**：先在 `package.json` + `vite.config.ts` 加 vitest 配置，再写测试
2. **`beforeEach` store reset**：`useOperatorStore.setState(initialState)` 防止测试间状态污染
3. **matchMedia mock**（setup.ts）：
   ```typescript
   Object.defineProperty(window, 'matchMedia', {
     writable: true,
     value: vi.fn().mockImplementation(query => ({
       matches: false, media: query, onchange: null,
       addListener: vi.fn(), removeListener: vi.fn(),
       addEventListener: vi.fn(), removeEventListener: vi.fn(),
       dispatchEvent: vi.fn(),
     })),
   });
   ```
4. **FakeWSClient server_hello**：`viewer_role: 'OPERATOR'`，`session_id: 'test-op-session'`
5. **addSquad 幂等**：TC-004 验证重复 addSquad 不增加重复项
6. **TC-015 logout 关闭 WS**：hook 在 `useEffect` cleanup 中调用 `client.close()`；logout 时 isLoggedIn→false 触发 effect 重新执行，关闭旧连接
7. **不测 Antd 内部样式**：只断言 data-testid 或文字内容，不断言 className
