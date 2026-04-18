---
type: coverage-matrix
id: coverage-matrix-2026-04-18
status: draft
created_at: "2026-04-18"
trigger: "全功能 E2E 测试任务 (user request)"
scope: "3 web apps + 2 linkage flows"
---

# Coverage Matrix — 2026-04-18 Full E2E Coverage

## 概要

本次 E2E 覆盖 3 个 web 应用（customer-chat / operator-console / admin-portal）
的所有用户可见功能 + 2 个跨端联动场景。Runner 为 agent-browser + ffmpeg。

## 应用 × 功能矩阵

### customer-chat (5173)

| 功能 | 单测 plan | E2E plan | E2E TC | 优先级 |
|---|---|---|---|---|
| 商户落地页 + FAB | T1B.5 | e2e-customer-chat | C01 | P0 |
| ChatModal 打开 + 握手 | T1B.1 | e2e-customer-chat | C02 | P0 |
| 消息发送 + 乐观渲染 | T1B.1, T1B.2 | e2e-customer-chat | C03 | P0 |
| AI 流式回复 | T1B.3 | e2e-customer-chat | C04 | P1 |
| 多轮上下文 | — | e2e-customer-chat | C05 | P1 |
| 断线重连 + replay | T1B.4 | e2e-customer-chat | C06 | P0 |
| 自动滚底 | T1B.1 | e2e-customer-chat | C07 | P1 |
| CSAT 评分 | plan-T6C.1 | e2e-customer-chat | C08 | P2 |
| Modal 关闭再开状态 | — | e2e-customer-chat | C09 | P2 |

### operator-console (5174)

| 功能 | 单测 plan | E2E plan | E2E TC | 优先级 |
|---|---|---|---|---|
| 登录页 | T2B.1 | e2e-operator-console | O01, O02 | P0 |
| 工作台 + 侧边栏 | T2B.1 | e2e-operator-console | O03 | P0 |
| Squad 订阅 | T2B.2 | e2e-operator-console | O04 | P0 |
| 对话列表 + 未读 | plan-T6A.2 | e2e-operator-console | O05 | P0 |
| IM 视图 + 消息历史 | — | e2e-operator-console | O06 | P0 |
| 坐席发消息 | — | e2e-operator-console | O07 | P0 |
| **Hijack/Release 双态按钮** 🆕 | — | e2e-operator-console | O08, O10 | P0 |
| **TAKEOVER 倒计时** 🆕 | — | e2e-operator-console | O09 | P0 |
| **预警横幅 + warning 阶段** 🆕 | — | e2e-operator-console | O11, O12 | P0 |
| **继续接管 ack** 🆕 | — | e2e-operator-console | O13 | P0 |
| **自动释放（idle）** 🆕 | — | e2e-operator-console | O14, O15 | P0 |
| **离线自动释放** 🆕 | — | e2e-operator-console | O16 | P0 |
| 多对话并发 takeover | — | e2e-operator-console | O17 | P1 |

### admin-portal (5175)

| 功能 | 单测 plan | E2E plan | E2E TC | 优先级 |
|---|---|---|---|---|
| 登录页 | AdminWorkspace.test.tsx | e2e-admin-portal | A01, A02 | P0 |
| 5 tab 导航 | AdminWorkspace.test.tsx | e2e-admin-portal | A03 | P1 |
| 退出登录 | — | e2e-admin-portal | A04 | P2 |
| Wizard Stepper | plan-T3B.* | e2e-admin-portal | A05 | P0 |
| Step1 上传 + 生成 4 角色 | plan-T3B.2 | e2e-admin-portal | A06–A08 | P0 |
| Step2 渠道配置 | ChannelConfigStep.test | e2e-admin-portal | A09, A10 | P0 |
| Step3 虚拟预演 | plan-T3B.4 + VirtualRehearsalStep.test | e2e-admin-portal | A11–A13 | P0 |
| Step4 合规检查 | ComplianceCheckStep.test | e2e-admin-portal | A14 | P0 |
| Step5 上线就绪 | — | e2e-admin-portal | A15 | P0 |
| Dashboard 图表 | DashboardTab.test | e2e-admin-portal | A16–A19 | P0/P1 |
| 管理群聊 | NotificationsTab.test | e2e-admin-portal | A20 | P1 |
| 提案 | ProposalsTab.test | e2e-admin-portal | A21 | P1 |
| 账单 | BillingTab.test | e2e-admin-portal | A22 | P1 |
| Tab 切换持久化 | — | e2e-admin-portal | A23 | P2 |

### 联动场景（cross-app）

| 场景 | E2E plan | TC | 优先级 |
|---|---|---|---|
| 客户→坐席消息穿透 | linkage-message-flow | L01–L05 | P0 |
| Squad 过滤 | linkage-message-flow | L06 | P0 |
| 坐席重连对话恢复 | linkage-message-flow | L07 | P1 |
| 客户离线重连 replay | linkage-message-flow | L08 | P1 |
| 多客户并发 feed | linkage-message-flow | L09 | P1 |
| **TAKEOVER 完整生命周期** 🆕 | linkage-takeover | T01–T10 | P0 |

## 优先级合计

| 优先级 | 用例数 | 说明 |
|---|---|---|
| P0 | 42 | 必须通过 |
| P1 | 22 | 目标通过 |
| P2 | 4 | 可接受失败 |
| **总计** | **68** | |

## 新功能覆盖（🆕 最近 5 个 commit 引入）

来源 commit: `f9d916a`, `7015140`, `882ee4c`, `940bc10`, `7e3dd29`

| 功能 | E2E 用例 |
|---|---|
| TAKEOVER pill + 实时倒计时 chip | O08, O09, T01 |
| takeoverArmedAt + idleMs 存 store | O09, T01 |
| gateway 推 takeover_timer_armed 帧 | O09, T01 |
| client_hello 带 operator_id 路由 | O12, T04, T07 |
| demote debug prints + cancel stale grace task | T07, T08 |

## 执行顺序建议

1. **预热**: customer-chat E2E（最快，验证基础设施）
2. **独立**: operator-console E2E（需要在 customer-chat 对话建立后跑）
3. **最长**: admin-portal E2E（Wizard 慢）
4. **联动**: linkage-message-flow（需同时开两端）
5. **最后**: linkage-takeover（需改 config 重启 gateway）

## 退出准则

- **总通过**: 所有 P0 用例 pass
- **可发布**: P0 + 80% P1 pass
- **重大回归**: 任一标 🆕 的新功能用例 fail → 高优先 issue

## 已知跳过/降级

- TC-C08 CSAT 若 backend 未触发 → 跳过
- TC-L06 Squad 过滤若后端未实现 → 降级只验 subscribe 帧
- TC-T09 多 operator 竞争 → MVP 不做锁，只记录观察
