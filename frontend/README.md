# AutoService Frontend Monorepo

> T0.6 产出 · pnpm workspace + React + Vite + TypeScript + i18n

## 布局

```
frontend/
├── apps/
│   ├── customer-chat/      # C 端聊天 SPA (Tailwind + Radix, :5173)
│   ├── operator-console/   # 工作台 (Ant Design, :5174)
│   └── admin-portal/       # 管理后台 (Ant Design, :5175)
└── packages/
    ├── ws-client/          # 共享 WebSocket 客户端（消费 T0.2 契约 · zod 运行时校验）
    └── i18n/               # react-i18next + 22 语种占位（T1B.6 填充）
```

## 快速开始

```bash
pnpm install            # 安装所有依赖
pnpm dev:customer       # 启 customer-chat (http://localhost:5173)
pnpm dev:operator       # 启 operator-console (http://localhost:5174)
pnpm dev:admin          # 启 admin-portal (http://localhost:5175)
pnpm typecheck          # 全仓库 TS 校验
pnpm build:all          # 构建三个 app
```

## 契约依赖

`packages/ws-client/src/types.ts` 与 `docs/contracts/frontend-ws-schema.md v1.0` 同步维护。
契约 bump 版本时必须同步本包 `version` 字段，否则 CI 阻挡（M1 前加脚本）。

## 技术选型说明

| 层 | 选型 | 理由 |
|---|---|---|
| 包管理 | pnpm workspace | 严格 hoisting 杜绝幽灵依赖 |
| 构建 | Vite 5 + React 18 + TS 5 | HMR 快，生态标准 |
| customer-chat UI | Tailwind + Radix | C 端 bundle 预算 &lt;200KB gzip |
| operator/admin UI | Ant Design 5 | 工作台重表格/表单 |
| 状态 | Zustand | 与后台规模匹配 |
| WS | 原生 WebSocket | T0.2 契约基于原生帧 |
| 运行时校验 | zod | 与 TS 类型同源 |
| i18n | react-i18next | namespace 懒加载支持 22 语种 |
| 测试 | Vitest | 与 Vite 零摩擦 |
