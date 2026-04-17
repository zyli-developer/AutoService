---
type: test-plan
id: test-plan-007
status: confirmed
producer: skill-2
created_at: "2026-04-16"
trigger: "eval-doc-008 (T1B.5 浮动按钮 SDK) — confirmed"
related:
  - eval-doc-008
  - "task:T1B.5"
decisions_frozen:
  D1: "iframe 隔离，customer-chat SPA 零改动"
  D2: "一行 <script data-domain='...'> 自动初始化"
  D3: "Vite IIFE 构建 → dist/as-embed.js（window.AsEmbed）"
  D4: "domain 通过 iframe URL query 传入，SPA 侧读取留 M1 联调"
  D5: "14 个新测试 TC-071~084，独立包，不影响 customer-chat 原 82 个"
---

# Test Plan: T1B.5 浮动按钮 SDK

## 触发原因

eval-doc-008 定义了 13 个新文件（embed-sdk 独立包）。
本 plan 共 **14 个用例**，覆盖：config 解析、浮动按钮 DOM、
iframe URL 构建、自动初始化、开关切换、postMessage 响应。

## 测试文件规划

```
frontend/packages/embed-sdk/src/__tests__/
  config.test.ts        新建 (TC-071~074)
  button.test.ts        新建 (TC-075~077)
  iframe.test.ts        新建 (TC-078~080)
  integration.test.ts   新建 (TC-081~084)
```

目标：embed-sdk **14/14 全绿**；customer-chat 原 82 个测试**不受影响**。

---

## 用例列表

### 分组 A · config 解析（TC-071 ~ TC-074）

#### TC-071: parseConfig 从 data-* 属性解析基础配置
- **文件**: `config.test.ts`
- **优先级**: P0
- **步骤**:
  1. 创建一个 `<script>` element，设置 `data-domain="m-001"`, `data-lang="en"`, `data-theme-color="#ff0000"`, `data-position="bottom-left"`
  2. 调用 `parseScriptConfig(scriptEl)`
- **预期**:
  ```
  { domain: 'm-001', lang: 'en', theme: { color: '#ff0000', position: 'bottom-left' } }
  ```
- **涉及**: `src/config.ts`

#### TC-072: parseConfig 缺省值正确
- **文件**: `config.test.ts`
- **优先级**: P0
- **步骤**: script 只设 `data-domain="m-002"`，无其他 data-*
- **预期**: `{ domain: 'm-002', lang: 'zh-CN', theme: { color: '#0ea5e9', position: 'bottom-right' } }`

#### TC-073: parseConfig 缺 domain → 返回 null
- **文件**: `config.test.ts`
- **优先级**: P0
- **步骤**: script 无 `data-domain` 属性
- **预期**: `parseScriptConfig(scriptEl) === null`

#### TC-074: buildIframeSrc 含 domain + lang + embed=1
- **文件**: `config.test.ts`
- **优先级**: P1
- **步骤**: `buildIframeSrc({ domain: 'm-003', lang: 'en', chatUrl: '/chat' })`
- **预期**: 返回字符串含 `domain=m-003`、`lang=en`、`embed=1`

### 分组 B · 浮动按钮 DOM（TC-075 ~ TC-077）

#### TC-075: createButton 追加到 document.body
- **文件**: `button.test.ts`
- **优先级**: P0
- **步骤**: `createButton({ domain: 'm-001', theme: { color: '#0ea5e9' } }, vi.fn())`
- **预期**: `document.getElementById('as-embed-btn')` 存在；style 含 `background-color`

#### TC-076: createButton 点击调用 onClick 回调
- **文件**: `button.test.ts`
- **优先级**: P0
- **步骤**:
  1. `const onClick = vi.fn()`
  2. `const btn = createButton(config, onClick)`
  3. `btn.click()`
- **预期**: `onClick` 被调用 1 次

#### TC-077: destroyButton 从 DOM 移除按钮
- **文件**: `button.test.ts`
- **优先级**: P1
- **步骤**:
  1. `const btn = createButton(config, vi.fn())`
  2. `destroyButton(btn)`
- **预期**: `document.getElementById('as-embed-btn') === null`

### 分组 C · iframe 创建/URL（TC-078 ~ TC-080）

#### TC-078: createIframe 追加到 body，初始隐藏
- **文件**: `iframe.test.ts`
- **优先级**: P0
- **步骤**: `createIframe({ domain: 'm-001', chatUrl: '/chat', lang: 'zh-CN' })`
- **预期**: `document.getElementById('as-embed-container')` 存在；container `style.display === 'none'`

#### TC-079: showIframe / hideIframe 切换 display
- **文件**: `iframe.test.ts`
- **优先级**: P0
- **步骤**:
  1. `const container = createIframe(config)`
  2. `showIframe(container)` → `container.style.display !== 'none'`
  3. `hideIframe(container)` → `container.style.display === 'none'`
- **预期**: 两步分别通过

#### TC-080: iframe src 包含正确 URL 参数
- **文件**: `iframe.test.ts`
- **优先级**: P1
- **步骤**: `createIframe({ domain: 'm-abc', chatUrl: 'https://chat.example.com', lang: 'en' })`
- **预期**: iframe element 的 `src` 含 `domain=m-abc` 和 `lang=en` 和 `embed=1`

### 分组 D · 集成（TC-081 ~ TC-084）

#### TC-081: init() 创建按钮和 iframe 容器
- **文件**: `integration.test.ts`
- **优先级**: P0
- **步骤**: `init({ domain: 'm-001', chatUrl: '/chat' })`
- **预期**: `#as-embed-btn` 存在；`#as-embed-container` 存在

#### TC-082: 点击按钮 → iframe 显示
- **文件**: `integration.test.ts`
- **优先级**: P0
- **步骤**:
  1. `init({ domain: 'm-001', chatUrl: '/chat' })`
  2. `document.getElementById('as-embed-btn')!.click()`
- **预期**: `#as-embed-container` style.display 非 'none'

#### TC-083: 再次点击按钮 → iframe 隐藏（切换）
- **文件**: `integration.test.ts`
- **优先级**: P0
- **步骤**:
  1. init → 点击按钮（打开）→ 再次点击（关闭）
- **预期**: `#as-embed-container` style.display 恢复 'none'

#### TC-084: postMessage as:close → iframe 隐藏
- **文件**: `integration.test.ts`
- **优先级**: P1
- **步骤**:
  1. `init({ domain: 'm-001', chatUrl: '/chat' })`
  2. 点击按钮打开 iframe
  3. `window.dispatchEvent(new MessageEvent('message', { data: { type: 'as:close' } }))`
- **预期**: `#as-embed-container` style.display === 'none'

---

## 统计

| 指标 | 值 |
|---|---|
| 新增用例 | 14 |
| 目标 | **14/14**（embed-sdk 独立包）|
| P0 | 10 |
| P1 | 4 |
| 新建测试文件 | 4 |
| 影响 customer-chat 测试 | **0**（独立包）|

## Skill 3 实现约束

1. **embed-sdk 是独立 pnpm 包**：有自己的 `package.json` + `vitest.config.ts`（或在 `vite.config.ts` 中配置 test 字段）
2. **测试环境**：jsdom（DOM API 可用）；无需 React
3. **`beforeEach` 清理 DOM**：`document.body.innerHTML = ''` 防止测试间 DOM 残留
4. **`document.currentScript` 不可在 jsdom 中自动设置**：`autoInit()` 的测试通过手动调用 `init()` 覆盖，autoInit 本身通过 TC-081 间接验证
5. **window.AsEmbed 挂载**：`init()` 执行后 `window.AsEmbed` 存在（TC-081 可顺带断言）
6. **不修改 customer-chat 任何文件**
