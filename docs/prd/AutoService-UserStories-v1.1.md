# AutoService User Stories · v1.1

> 配套 `AutoService-PRD-v1.1.md` · 2026-04-15 · Mike Cohn + Gherkin
> 17 story 分 4 Epic；相对 v1.0 仅更新"飞书→Web"/"自建→zchat"的交互面描述
> 实现路径映射表见 PRD v1.1 §7

---

## Epic 1 · 自助上线（商户视角）

### US-1.1 · 上传基础信息生成初版 Agent
**As a** 商户管理员老陈, **I want** 只填官网 URL 并上传几份产品资料, **so that** 系统自动解析并生成初版 4 个 Agent。

```gherkin
Given 我刚注册 AutoService 并进入 admin-portal 上线向导步骤 1
When 我填入公司官网 URL 并上传产品目录 PDF 和历史对话 CSV
Then 系统在 15 分钟内完成 CI 解析
And 自动生成 4 个角色的 soul.md (客服/翻译/线索收集/智能分流)
And 向我展示"Agent 初始化完成"的步骤 2 按钮

Given 上传的文件格式不受支持
When 我点击下一步
Then 系统明确提示哪个文件格式有问题且不阻塞其他文件的解析
```

### US-1.2 · 配置首发渠道并关联通知中心（v1.1 调整）
**As a** 商户管理员老陈, **I want** 一键配置"独立 Web 页"作为首发渠道并绑定通知中心, **so that** 我不用等飞书审批流程就能开始测试。

```gherkin
Given 我完成步骤 1，进入步骤 2 · 渠道配置
When 我勾选"独立 Web 聊天页 (首发)"和"管理员通知中心"
Then 系统在 5 秒内生成该商户的 web_bridge 挂载点和独立聊天页 URL
And 生成管理员 Web 工作台的登录链接
And 显示"已配置 2/2"且步骤 2 标记完成
And 管理员收到一封含 URL 和凭据的邮件

Given 我已配置好渠道并想稍后接入飞书
When 系统提示"飞书渠道将在 zchat-feishu-bridge 就绪后可一键开启"
Then 我可以点击"加入等待列表"留存后续通知
```

### US-1.3 · 虚拟客户预演逐条审阅
**As a** 商户管理员老陈, **I want** 系统生成典型客户对话让我逐条 ✓ / ✎, **so that** 上线前我对 AI 的回答心里有数。

```gherkin
Given 步骤 2 完成后
When 我进入步骤 3 · 虚拟客户预演
Then 系统自动生成 ≥10 条覆盖主要业务场景的虚拟对话
And 每条展示"虚拟客户问 / AI 答"两栏
And 每条下方有 ✓ 通过 / ✎ 修改 / ⚠ 标记 按钮
And 所有 ⚠ 必须降级为 ✓/✎ 才能进入步骤 4
```

### US-1.4 · 合规预检不阻塞沙箱
**As a** 商户管理员老陈, **I want** 合规预检显示风险但不阻塞沙箱, **so that** 我能先让团队内部用起来。

```gherkin
Given 我的目标客户覆盖欧盟、美国、中国
When 系统运行合规预检
Then 展示 GDPR/CCPA/PIPL 三项检查结果及风险等级（16 条规则）
And 即使存在未通过项,沙箱内部功能仍可用
And 明确提示"对外开放前需通过所有合规项"
And 整个上线向导在 2 小时内可完成
```

---

## Epic 2 · 实时对话（6 步状态机 · 三视角）

### US-2.1 · C 端客户 3 秒内看到问候（v1.1 调整）
**As a** C 端客户 David, **I want** 点开聊天按钮后 3 秒内看到问候语, **so that** 我知道系统"活着"。

```gherkin
Given 我在商户独立站点击右下角浮动聊天按钮
When 独立 Web 聊天页弹出并通过 web_bridge 连上 zchat
Then 我在 3 秒内看到 Agent 的问候消息（zchat `sla_onboard` timer 保障）
And 如果我是老客户,问候语会引用我的历史上下文
And 如果是新客户,AutoService lifecycle plugin 为我创建工作目录
And 页面刷新后对话连续（web_bridge 断线重连 + 消息回放）
```

### US-2.2 · 复杂查询看到占位不空等（v1.1 调整）
**As a** C 端客户 David, **I want** 问复杂问题时先看到"稍等,正在查询..."占位, **so that** 我不觉得被晾着。

```gherkin
Given 我问了一个需要查 CRM 或知识库的复杂问题
When ModelRouter 识别为复杂查询
Then 我在 1 秒内看到占位消息（zchat `sla_placeholder` timer 保障）
And 慢模型在 5-15 秒内完成查询（`sla_slow_query` timer）
And 最终答复通过 zchat `message.edit` 原地续写（而非新发一条）
And 超时 → 自动升级并发安抚文案
```

### US-2.3 · Agent 接洽后分队通知（v1.1 调整）
**As a** 人工客服小李, **I want** 所有我负责的 Agent 接洽客户后,把进行中对话以卡片形式推到我的**客服 Web 工作台**, **so that** 我不用点开也能掌握全局。

```gherkin
Given 我登录客服 Web 工作台,我的分队下管辖 agent1 和 agent2
When agent2 接入了一个新客户 B（zchat emit `conversation.created`）
Then AutoService squad plugin 收到事件 → 在我的工作台实时出现"卡片 #2 · 客户 B"
And 卡片随对话进展实时刷新摘要（每 3 条 public 消息自动刷新）
And 我无需点开即可从摘要判断是否需要介入
And 工作台顶部显示未读对话数徽章
```

### US-2.4 · 点开卡片进入对话监管（v1.1 调整）
**As a** 人工客服小李, **I want** 点开卡片后弹出聊天窗进入对话监管（Copilot）, **so that** 我能在不打扰客户体验的情况下观察并引导 AI。

```gherkin
Given 我在工作台看到一张进行中的对话卡片
When 我点击该卡片
Then 工作台弹出聊天窗,zchat mode 切换 `auto→copilot`（自动 emit `operator_join`）
And 标题显示"Copilot 模式 · agent 作为 driver"
And 聊天窗左侧显示客户-Agent public 对话；右侧侧栏显示 Agent 拟回复草稿
And 我的输入框明确提示"输入建议给 agent（不会发给客户）"
And 客户端感知不到我已经在看
And 我的建议被 zchat Gate 降级为 `side` 可见性，仅 Agent 可见
```

### US-2.5 · 两种方式触发人工提醒
**As a** 系统, **I want** 支持 Agent `@人工` 求助 和 人工 `/hijack` 抢单。

```gherkin
Given 一个对话正在 Copilot 模式运行
When agent 判断超出处理范围
Then agent 通过 MCP tool `request_operator` 触发（zchat emit `escalation.requested`）
And 启动 180s 的 `takeover_wait` timer
And 超时后 zchat 自动切回 mode=auto 并向客户发安抚消息

Given 人工客服看到客户问题棘手
When 他在工作台聊天窗输入 /hijack
Then zchat 命令解析 → 立即切 mode=takeover
```

### US-2.6 · 角色翻转后 Agent 退居副驾驶
**As a** C 端客户 David, **I want** 从 AI 切到人工时感受不到断层。

```gherkin
Given 对话进入 mode=takeover
When 人工客服发出第一条消息（首回 <60s，zchat `first_reply` timer）
Then 消息自动带入 Agent 整理的客户背景和历史上下文
And Agent 退到副驾驶,在 thread 内发 `[AI建议]`（Gate 降级为 side,客户不可见）
And 客户从头到尾看到的是一个连贯的对话流
And 此次 mode 转换 emit `mode.changed(→takeover)` → AutoService metrics plugin 计入"接管次数"
And 对话 resolve 时 zchat 发 csat_request → 客户评分 → emit `csat_response`
```

---

## Epic 3 · 双账本与仪表盘

### US-3.1 · 商户查看双账本（v1.1 调整）
**As a** 商户管理员老陈, **I want** 在 admin-portal 看到 4 个 Agent 和人工客服的双账本。

```gherkin
Given 我登录 admin-portal
When 我进入运营仪表盘
Then 顶部展示 4 个 Agent 的状态（在线/待命 + 今日处理量）
And 中部展示 3 个 ★ 计费指标（接管次数/CSAT/升级转结案率，数据源：AutoService metrics plugin 订阅 zchat 事件聚合）
And 中部展示 3 个辅助指标（平均首回/会话时长/接单等待）
And 底部展示接管次数趋势图和人工客服 Leaderboard
And 时间切片可选 今日/本周/本月/本季度
```

### US-3.2 · 管理员命令行快速操作（v1.1 调整）
**As a** 商户管理员老陈, **I want** 在**通知中心**里用斜杠命令快速查状态和派单。

```gherkin
When 我在通知中心输入 /status
Then 返回当前所有进行中对话的列表（zchat `/status` command）

When 我输入 /dispatch <conversation_id> <agent_role>
Then zchat 命令解析 → 指定 agent 接管

When 我输入 /review
Then AutoService 返回昨日工作统计（接管数/CSAT/SLA 达成率）
```

### US-3.3 · SLA 超时自动告警（v1.1 调整）
**As a** 平台运营, **I want** 任何一项 SLA 连续 5 分钟未达标时自动告警。

```gherkin
Given 某租户的人工接单等待 5 分钟滚动 P95 > 180s
When AutoService SLAAggregator（订阅 zchat `timer.expired` 事件）命中阈值
Then 告警消息自动推送到该租户通知中心
And 同时在平台侧计入 SLA 事件日志
And 告警内附带一键 /dispatch 快捷按钮
```

---

## Epic 4 · 闲时学习（夜间循环）

### US-4.1 · 在通知中心配置 Dream Engine 学习规则（v1.1 调整）
**As a** 商户管理员老陈, **I want** 在通知中心和 Dream Engine 对话配置规则。

```gherkin
Given 我在通知中心 @Dream Engine 请求配置学习规则
When Dream Engine 响应
Then 它以对话形式依次询问 4 个参数（触发时机/覆盖范围/风险阈值/灰度策略）
And 每个参数都提供推荐默认值
And 我可以用自然语言逐条回复或一次性全部回复

Given 我已回复全部 4 个参数
When Dream Engine 保存规则
Then 返回"规则已保存 ✓"
And 规则从当晚起生效
And 规则与平台预置的合规模板叠加生效（合规模板不可覆盖）

Given 规则已保存后
When 我想查看或修改
Then 输入 /rules show 可查看
And 输入 /rules edit <参数> 可修改单项
And 每次修改都在通知中心留下可追溯审计

Given 我未配置任何规则
When 夜间循环到来
Then 系统使用平台默认规则启动（仅限低风险覆盖范围）
And 次日在通知中心提示"建议您尽快配置专属规则"
```

### US-4.2 · Dream Engine 业务低峰自动启动
**As a** 系统, **I want** 业务低峰时按规则自动触发 Dream Engine。

```gherkin
Given 租户对话 QPS 连续 30 分钟低于白天均值 20%
When 系统判定为业务低峰
Then 自动触发 Dream Engine 启动
And 读取白天的临时记忆池
And 执行回放 + 抽取经验 + 发现盲区
And 严格按商户配置的"覆盖范围"参数约束
And 白天流量突增时可被中断，不影响用户感知
```

### US-4.3 · 晨起推送提案（v1.1 调整）
**As a** 商户管理员老陈, **I want** 夜间产生的话术和知识提案清晨推送到通知中心让我一键通过。

```gherkin
Given 昨夜 Dream Engine 产生了若干提案
When 第二天早上 9 点前
Then 所有提案以卡片形式推送到通知中心（Web 或后续飞书）
And 每张卡片显示提案来源对话、影响范围、风险等级
And 卡片附带 ✓ 通过 / ✎ 修改 / ✗ 驳回 三个按钮
And 通过的提案进入灰度发布流程
And 平台合规规则以"策略模板"形式预审过,不再二次打扰
And 中风险以上提案需要我二次确认
```

### US-4.4 · 提案灰度发布与一键回滚
**As a** 商户管理员老陈, **I want** 通过的提案按配置渐进上线，出问题能一键撤回。

```gherkin
Given 一个提案被通过
When 进入灰度发布
Then 按商户配置执行（默认 5% → 25% → 100%）
And 每阶段观察 24 小时核心指标（CSAT/升级转结案率/AI 消化率/接单等待/投诉率 5 项）
And 5 项全部不劣化 → 自动进入下一阶段
And 任一项恶化超过 2× 阈值 → 自动回滚

Given 任一阶段发现问题
When 管理员输入 /rollback <proposal_id> <reason>
Then 该提案立即从所有流量中撤回
And 通知中心收到回滚确认
And 本次提案进入"待复盘"队列
```

---

## 共用约束（所有 story 适用）

- **反幻觉硬约束**: Agent 查不到明确答案时,不得编造,必须转人工或明确"不确定"
- **多语言**: 客户用任意支持语言提问,Agent 以同语言回复（22 语种术语表）
- **上下文加载**: 老客户自动加载历史;新客户自动创建工作目录
- **设计系统**: 三个 Web 前端（customer-chat / operator-console / admin-portal）均遵循"江峡泼墨"
- **协议保障**: Mode / Gate / Timer / 可见性路由由 zchat 协议级强制,App 层不自管
- **断线重连**: Web 前端全部支持断线重连 + 消息回放

---

*17 Story · 基于 AutoService-PRD-v1.1.md · 配套 zchat-plan v1.0*
