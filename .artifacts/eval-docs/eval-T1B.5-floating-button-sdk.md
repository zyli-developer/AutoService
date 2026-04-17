# eval-doc-008 · T1B.5 浮动按钮 SDK

> **Mode**: simulate · **Owner**: DevB · **Date**: 2026-04-16

---

## 1. 任务目标

为 AutoService 实现可嵌入任意独立站的浮动客服按钮 SDK（β4）：
- 商户只需一行 `<script>` 引入
- 点击浮标 → iframe 弹出 customer-chat SPA
- 按 domain 隔离（不同商户/domain 拿到不同的 WS 端点 + conversationId）
- 支持主题色、位置等基础定制
- T5B.5 会把此包发布到 npm（本任务只构建 UMD 产物，不发布）

---

## 2. 现有代码分析

### 2.1 已有能力

| 能力 | 状态 |
|---|---|
| customer-chat SPA | ✅ T1B.1~T1B.4 完成，可作为 iframe src |
| 前端 monorepo (pnpm workspace) | ✅ T0.6 骨架，可新增 package |
| Vite 构建 | ✅ 已用于 customer-chat |
| i18n 包 | ✅ T0.6 骨架（T1B.6 扩展中）|

### 2.2 缺失（T1B.5 新增）

| 缺口 | 位置 |
|---|---|
| `@autoservice/embed-sdk` 包 | `frontend/packages/embed-sdk/` (NEW) |
| 浮动按钮 + iframe 逻辑 | `embed-sdk/src/index.ts` |
| UMD 构建（IIFE 单文件） | `embed-sdk/vite.config.ts` |
| domain 隔离配置 | `EmbedConfig.domain` → iframe URL query |
| 主题配置接口 | `EmbedConfig.theme` |
| 测试 | `embed-sdk/src/__tests__/` |

---

## 3. 架构设计

### 3.1 SDK 使用方式（商户侧）

```html
<!-- 商户独立站 -->
<script
  src="https://cdn.autoservice.io/embed/v1/as-embed.js"
  data-domain="merchant-123"
  data-lang="zh-CN"
  data-theme-color="#0ea5e9"
  data-position="bottom-right"
></script>
```

SDK 自动初始化，无需额外 JS 调用。也支持手动初始化：
```javascript
window.AsEmbed.init({
  domain: 'merchant-123',
  lang: 'zh-CN',
  theme: { color: '#0ea5e9', position: 'bottom-right' }
});
```

### 3.2 包结构

```
frontend/packages/embed-sdk/
  package.json          @autoservice/embed-sdk
  vite.config.ts        IIFE 构建 → dist/as-embed.js
  tsconfig.json
  src/
    index.ts            主入口：自动检测 data-* 属性 + init()
    config.ts           EmbedConfig 接口 + 解析逻辑
    button.ts           浮动按钮 DOM 创建/销毁
    iframe.ts           iframe 弹窗创建/销毁 + postMessage 通信
    theme.ts            CSS 变量注入
    __tests__/
      config.test.ts    TC-071~074
      button.test.ts    TC-075~077
      iframe.test.ts    TC-078~080
      integration.test.ts TC-081~084
```

### 3.3 EmbedConfig 接口

```typescript
export interface EmbedTheme {
  color?: string;       // 主色（默认 #0ea5e9）
  position?: 'bottom-right' | 'bottom-left';  // 按钮位置（默认 bottom-right）
  zIndex?: number;      // z-index（默认 9999）
}

export interface EmbedConfig {
  domain: string;                    // 必填，商户标识
  chatUrl?: string;                  // customer-chat SPA URL（默认同域 /chat）
  lang?: string;                     // 语言（默认 zh-CN）
  theme?: EmbedTheme;
  onOpen?: () => void;               // iframe 打开回调
  onClose?: () => void;              // iframe 关闭回调
}
```

### 3.4 自动初始化逻辑

```typescript
// src/index.ts
function autoInit(): void {
  const script = document.currentScript as HTMLScriptElement | null;
  if (!script) return;
  
  const domain = script.getAttribute('data-domain');
  if (!domain) return;  // 无 domain 不初始化
  
  const config: EmbedConfig = {
    domain,
    lang: script.getAttribute('data-lang') ?? 'zh-CN',
    theme: {
      color: script.getAttribute('data-theme-color') ?? '#0ea5e9',
      position: (script.getAttribute('data-position') as EmbedTheme['position']) ?? 'bottom-right',
    },
  };
  init(config);
}

// DOMContentLoaded 或立即执行（取决于脚本加载时机）
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', autoInit);
} else {
  autoInit();
}
```

### 3.5 浮动按钮 DOM

```typescript
// src/button.ts
export function createButton(config: EmbedConfig, onClick: () => void): HTMLElement {
  const btn = document.createElement('button');
  btn.setAttribute('id', 'as-embed-btn');
  btn.setAttribute('aria-label', 'Open chat');
  btn.style.cssText = buildButtonStyle(config.theme);
  btn.innerHTML = CHAT_ICON_SVG;
  btn.addEventListener('click', onClick);
  document.body.appendChild(btn);
  return btn;
}

export function destroyButton(btn: HTMLElement): void {
  btn.removeEventListener('click', () => {});
  btn.remove();
}
```

按钮样式：
```typescript
function buildButtonStyle(theme: EmbedTheme = {}): string {
  const { color = '#0ea5e9', position = 'bottom-right', zIndex = 9999 } = theme;
  const side = position === 'bottom-right' ? 'right: 24px' : 'left: 24px';
  return `
    position: fixed; bottom: 24px; ${side};
    z-index: ${zIndex};
    width: 56px; height: 56px;
    border-radius: 50%; border: none; cursor: pointer;
    background-color: ${color};
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
  `.replace(/\s+/g, ' ').trim();
}
```

### 3.6 iframe 弹窗

```typescript
// src/iframe.ts
export function createIframe(config: EmbedConfig): HTMLElement {
  const container = document.createElement('div');
  container.id = 'as-embed-container';
  container.style.cssText = buildContainerStyle(config.theme);
  
  const iframe = document.createElement('iframe');
  iframe.src = buildIframeSrc(config);
  iframe.style.cssText = 'width:100%;height:100%;border:none;border-radius:12px;';
  iframe.setAttribute('allow', 'microphone');
  
  container.appendChild(iframe);
  document.body.appendChild(container);
  return container;
}

function buildIframeSrc(config: EmbedConfig): string {
  const base = config.chatUrl ?? '/chat';
  const params = new URLSearchParams({
    domain: config.domain,
    lang: config.lang ?? 'zh-CN',
    embed: '1',
  });
  return `${base}?${params}`;
}

export function showIframe(container: HTMLElement): void {
  container.style.display = 'block';
}

export function hideIframe(container: HTMLElement): void {
  container.style.display = 'none';
}
```

iframe 容器样式：
```
position: fixed; bottom: 96px; right/left: 24px;
width: 380px; height: 600px;
z-index: 9998; display: none;
box-shadow: 0 8px 32px rgba(0,0,0,0.2);
border-radius: 12px;
```

### 3.7 postMessage 通信（iframe → 宿主页）

```typescript
// customer-chat SPA 内部（App.tsx）
// 嵌入模式时通知宿主关闭 iframe
if (new URLSearchParams(window.location.search).get('embed') === '1') {
  window.parent.postMessage({ type: 'as:close' }, '*');
}

// SDK 侧监听
window.addEventListener('message', (ev) => {
  if (ev.data?.type === 'as:close') {
    hideIframe(iframeContainer);
  }
});
```

### 3.8 domain 隔离

`domain` 参数通过 iframe URL query 传入 customer-chat SPA。SPA 读取 `?domain=merchant-123` 后：
- 用于 WS 连接 URL（`ws://gateway/ws?domain=merchant-123`）
- 用于 sessionStorage key 隔离（`as_last_seen_merchant-123`）

> T1B.5 范围内只传递 domain 参数，SPA 侧的 domain 读取逻辑在联调时实现（目前 SPA 的 WS URL 来自构建配置）。

### 3.9 Vite 构建配置

```typescript
// vite.config.ts
import { defineConfig } from 'vite';
export default defineConfig({
  build: {
    lib: {
      entry: 'src/index.ts',
      name: 'AsEmbed',
      fileName: 'as-embed',
      formats: ['iife'],
    },
    rollupOptions: {
      output: { inlineDynamicImports: true },
    },
    outDir: 'dist',
  },
});
```

产物：`dist/as-embed.js`（IIFE，`window.AsEmbed` 暴露 `init()` 方法）

---

## 4. 关键设计决策

### D1. iframe vs Shadow DOM

**决策**：**iframe**。
- Shadow DOM 无法完全隔离 WS 连接、Zustand store、sessionStorage
- iframe 提供完整浏览上下文隔离，customer-chat SPA 无需改动
- 代价：跨 iframe 通信需 postMessage（简单可控）

### D2. 自动初始化时机

**决策**：**`DOMContentLoaded` + 立即执行二选一**（检测 `readyState`）。
- `<script>` async/defer 时 DOM 可能已加载 → 直接执行
- 同步加载时 → 监听 DOMContentLoaded

### D3. 样式注入方式

**决策**：**内联 style 字符串**（不引入 CSS 文件）。
- SDK 是单文件 IIFE，避免额外 CSS 资源请求
- 只有 2 个 DOM 元素（按钮 + iframe 容器），样式简单

### D4. 测试框架

**决策**：**Vitest + jsdom**（与 customer-chat 保持一致）。
- DOM API 用 `document.createElement` 等 jsdom 模拟
- postMessage 用 `vi.fn()` + `dispatchEvent` 测试

### D5. domain 隔离实现范围

**决策**：T1B.5 只负责**传递** domain 参数到 iframe URL；SPA 侧的 domain 读取（影响 WS URL）留给 M1 联调时补全，避免过度耦合 T1B.5 与后端配置。

---

## 5. 测试规划概览

| 分组 | TC 编号 | 文件 | P0 | P1 |
|---|---|---|---|---|
| A. config 解析 | TC-071~074 | config.test.ts | 3 | 1 |
| B. 按钮创建/销毁 | TC-075~077 | button.test.ts | 2 | 1 |
| C. iframe 创建/URL | TC-078~080 | iframe.test.ts | 2 | 1 |
| D. 集成（init + toggle） | TC-081~084 | integration.test.ts | 3 | 1 |

**共 14 个新用例**。embed-sdk 是独立包，不影响 customer-chat 的 82 个测试。

---

## 6. 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| `document.currentScript` 在 async 脚本中为 null | 中 | 增加 null guard；支持手动 `AsEmbed.init()` 备用 |
| iframe 被 CSP 阻止（X-Frame-Options） | 中 | customer-chat SPA 需设置 `Content-Security-Policy: frame-ancestors *`；T1B.5 文档说明 |
| 移动端 iframe 键盘弹出挤压布局 | 低 | 添加 `<meta name="viewport">` + `height: 100%` 处理；T2 优化 |
| postMessage `targetOrigin='*'` 安全性 | 低 | T1B.5 传递的消息类型（`as:close`）无敏感数据；T2 收紧 origin |

---

## 7. 不在范围

- npm 发布（T5B.5）
- 多实例（同页面多个 embed）— T2
- 访客身份识别（cookie）— T2
- 移动端原生 webview 集成 — T3
- customer-chat SPA 侧 `?domain` 读取逻辑 — M1 联调

---

## 8. 产出清单

| # | 文件 | 动作 | 说明 |
|---|---|---|---|
| 1 | `frontend/packages/embed-sdk/package.json` | **新建** | `@autoservice/embed-sdk`, Vitest 配置 |
| 2 | `frontend/packages/embed-sdk/tsconfig.json` | **新建** | 继承根 tsconfig |
| 3 | `frontend/packages/embed-sdk/vite.config.ts` | **新建** | IIFE 构建 |
| 4 | `frontend/packages/embed-sdk/src/config.ts` | **新建** | EmbedConfig + parseConfig |
| 5 | `frontend/packages/embed-sdk/src/button.ts` | **新建** | createButton / destroyButton |
| 6 | `frontend/packages/embed-sdk/src/iframe.ts` | **新建** | createIframe / showIframe / hideIframe / buildIframeSrc |
| 7 | `frontend/packages/embed-sdk/src/theme.ts` | **新建** | buildButtonStyle / buildContainerStyle |
| 8 | `frontend/packages/embed-sdk/src/index.ts` | **新建** | init() + autoInit() + window.AsEmbed |
| 9 | `frontend/packages/embed-sdk/src/__tests__/config.test.ts` | **新建** | TC-071~074 |
| 10 | `frontend/packages/embed-sdk/src/__tests__/button.test.ts` | **新建** | TC-075~077 |
| 11 | `frontend/packages/embed-sdk/src/__tests__/iframe.test.ts` | **新建** | TC-078~080 |
| 12 | `frontend/packages/embed-sdk/src/__tests__/integration.test.ts` | **新建** | TC-081~084 |
| 13 | `frontend/package.json` | **微调** | 添加 embed-sdk 到 workspaces（如未包含）|

---

*eval-doc-008 · T1B.5 · simulate · 待 review*
