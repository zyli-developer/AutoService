# AutoService User Stories

> 配套 AutoService-PRD.md v1.0 · 按 Mike Cohn 格式 + Gherkin 验收标准
> 17 个 story 分为 4 个 Epic

---

## Epic 1 · 自助上线(商户视角 · 一次性)

### US-1.1 · 上传基础信息生成初版 Agent
**As a** 商户管理员老陈,
**I want** 只填官网 URL 并上传几份产品资料,
**so that** 系统自动解析并生成初版 4 个 Agent,不用学 prompt 工程。

**Acceptance Criteria (Gherkin)**:
```gherkin
Given 我刚注册 AutoService 并进入上线向导的步骤 1
When 我填入公司官网 URL 并上传产品目录 PDF 和历史对话 CSV
Then 系统在 15 分钟内完成 CI 解析
And 自动生成 4 个角色的初版 Agent(客服/翻译/线索收集/智能分流)
And 向我展示"Agent 初始化完成"的可跳转步骤 2 按钮

Given 上传的文件格式不受支持
When 我点击下一步
Then 系统明确提示哪个文件格式有问题
And 不阻塞其他文件的解析
```

### US-1.2 · 一键勾选权限并关联 IM 管理群
**As a** 商户管理员老陈,
**I want** 勾 4 个权限复选框就自动把 Agent 接入我的 IM 管理群,
**so that** 我不用手动配 webhook。

**Acceptance Criteria**:
```gherkin
Given 我完成步骤 1,进入权限配置页
When 我勾选"管理对话""查看客户档案""发送通知""调用业务系统"4 项
Then 系统在 5 秒内建好 IM 管理群
And 4 个 Agent 自动进入该群作为成员
And 显示"已配置 4/4"且步骤 2 标记完成
```

### US-1.3 · 虚拟客户预演逐条审阅
**As a** 商户管理员老陈,
**I want** 系统生成典型客户对话让我逐条 ✓ 通过 / ✎ 修改,
**so that** 上线前我对 AI 的回答心里有数。

**Acceptance Criteria**:
```gherkin
Given 步骤 2 完成后
When 我进入步骤 3 · 虚拟客户预演
Then 系统自动生成至少 10 条覆盖主要业务场景的虚拟对话
And 每条都展示"虚拟客户问 / AI 答"两栏
And 每条下方都有 ✓ 通过 和 ✎ 修改 按钮
And 所有条目处理完毕后步骤 3 标记完成
```

### US-1.4 · 合规预检不阻塞沙箱
**As a** 商户管理员老陈,
**I want** 合规预检显示风险但不阻塞我在沙箱里试用,
**so that** 我能先让团队内部用起来。

**Acceptance Criteria**:
```gherkin
Given 我的目标客户覆盖欧盟、美国、中国
When 系统运行合规预检
Then 展示 GDPR/CCPA/个保法三项检查结果及风险等级
And 即使存在未通过项,沙箱内部功能仍可用
And 明确提示"对外开放前需通过所有合规项"
And 整个上线向导在 2 小时内可完成
```

---

## Epic 2 · 实时对话(6 步状态机 · 三视角)

### US-2.1 · C 端客户 3 秒内看到问候
**As a** C 端客户 David,
**I want** 点开聊天按钮后 3 秒内看到问候语,
**so that** 我知道系统"活着"且会理我。

```gherkin
Given 我在商户独立站点击右下角浮动聊天按钮
When 聊天窗打开
Then 我在 3 秒内看到 Agent 的问候消息
And 如果我是老客户,问候语会引用我的历史上下文
And 如果是新客户,系统在后台为我创建工作目录
```

### US-2.2 · 复杂查询看到占位不空等
**As a** C 端客户 David,
**I want** 问复杂问题时先看到"稍等,正在查询..."占位,
**so that** 我不觉得被晾着。

```gherkin
Given 我问了一个需要查 CRM 或知识库的复杂问题
When Agent 识别为复杂查询
Then 我在 1 秒内看到占位消息("稍等,正在为您查询...")
And 慢模型在背景 5-15 秒内完成查询
And 最终答复通过续写替换原占位消息(而非新发一条)
And 我感知上是"一条完整且即时的回答"
```

### US-2.3 · Agent 接洽后在分队频道发实时卡片
**As a** 人工客服小李,
**I want** 所有我负责的 Agent 接洽客户后,把进行中的对话以卡片形式推到我的 Agent 分队频道,
**so that** 我不用点开也能掌握全局。

```gherkin
Given 我的 Agent 分队下管辖 agent1 和 agent2
When agent2 接入了一个新客户 B
Then 我的 Agent 分队内立即出现一张"卡片 #2 · 客户 B"
And 卡片随对话进展实时刷新最新摘要
And 我无需点开即可从摘要判断是否需要介入
And 频道内同时显示未读对话数徽章
```

### US-2.4 · 点开卡片进入对话监管模式
**As a** 人工客服小李,
**I want** 点开卡片后弹出聊天窗进入对话监管模式,默认 Agent driver 而我只在窗内提建议,
**so that** 我能在不打扰客户体验的情况下观察并引导 AI。

```gherkin
Given 我在 Agent 分队看到一张进行中的对话卡片
When 我点击该卡片
Then 弹出实时聊天窗,标题显示"默认 copilot 模式 · agent 作为 driver"
And 聊天窗显示客户说的话和 Agent 拟回复的草稿
And 我的输入框明确提示"输入建议给 agent(不会发给客户)"
And 客户端感知不到我已经在看
And 我提的建议对 agent 可见但不会直接发给客户
```

### US-2.5 · 两种方式触发人工提醒
**As a** 系统,
**I want** 支持 Agent 主动 `@人工` 求助 和 人工 `/hijack` 抢单两种人工提醒触发方式,
**so that** 无论 AI 先察觉还是人先察觉都能顺滑衔接。

```gherkin
Given 一个对话正在 Copilot 模式运行
When agent 判断超出处理范围
Then agent 发送 "@客服小李 请接管 #2" 的消息到 Agent 分队
And 开始 180 秒的人工接单等待计时
And 超时后卡片退回 agent 并向客户发出安抚消息

Given 人工客服看到客户问题棘手
When 他在聊天窗输入 "/hijack #2"
Then 系统立即启动角色翻转流程
```

### US-2.6 · 角色翻转后 Agent 退居副驾驶
**As a** C 端客户 David,
**I want** 从 AI 切到人工时感受不到断层,
**so that** 我不用重新说一遍我的问题。

```gherkin
Given 对话进入 HumanTakeover 状态
When 人工客服发出第一条消息
Then 消息中自动带入 agent 整理好的客户背景和历史上下文
And 人工首次回复在 60 秒内发出
And Agent 退到侧栏继续提供副驾驶建议(对客户隐藏)
And 客户从头到尾看到的是一个连贯的对话流
And 此次角色翻转计入"接管次数"计费指标
```

---

## Epic 3 · 双账本与仪表盘(商户视角)

### US-3.1 · 商户查看 AI 团队与人工双账本
**As a** 商户管理员老陈,
**I want** 在一张仪表盘上同时看到 4 个 Agent 的状态和人工客服的绩效,
**so that** 我能评估整个客服小分队(AI + 人)的效率。

```gherkin
Given 我登录商户工作区
When 我进入运营仪表盘
Then 顶部展示 4 个 Agent 的状态(在线/待命 + 今日处理量)
And 中部展示 3 个 ★ 计费指标(接管次数/CSAT/升级转结案率)
And 中部另展示 3 个辅助指标(平均首回/会话时长/接单等待)
And 底部展示接管次数趋势图和人工客服 Leaderboard
And 时间切片可选 今日/本周/本月/本季度
```

### US-3.2 · 管理员命令行快速操作
**As a** 商户管理员老陈,
**I want** 在 IM 管理群里用斜杠命令快速查状态和派单,
**so that** 我不用进 Web 后台。

```gherkin
When 我输入 /status
Then 群里返回当前所有进行中对话的列表

When 我输入 /dispatch <chat_id> <agent>
Then 指定 agent 被派发到该对话

When 我输入 /review
Then 返回昨日工作统计(接管数/CSAT/SLA 达成率)
```

### US-3.3 · SLA 超时自动告警
**As a** 平台运营,
**I want** 任何一项 SLA 连续 5 分钟未达标时自动发告警到相关租户管理群,
**so that** 问题能在客户投诉前被发现。

```gherkin
Given 某租户的人工接单等待 5 分钟滚动平均 > 180s
When 监控命中阈值
Then 告警消息自动推送到该租户管理群
And 同时在平台侧计入 SLA 事件日志
And 告警内附带一键 /dispatch 快捷按钮
```

---

## Epic 4 · 闲时学习(夜间循环)

### US-4.1 · 在管理群配置 Dream Engine 学习规则
**As a** 商户管理员老陈,
**I want** 在管理群里和 Dream Engine 对话配置夜间学习的规则,
**so that** 我能决定系统如何学习、学什么、学到什么程度才能上线,而不用面对一堆不可理解的配置项。

**Acceptance Criteria**:
```gherkin
Given 我在管理群中 @Dream Engine 请求配置学习规则
When Dream Engine 响应
Then 它以对话形式依次询问 4 个参数:
  | 参数       | 含义                                              |
  | 触发时机   | 什么条件下启动夜间学习(如 QPS < 白天均值的 20%)  |
  | 覆盖范围   | 允许学习的内容类型(话术 / FAQ / 升级流程等)      |
  | 风险阈值   | 中风险以上提案是否需要二次确认                    |
  | 灰度策略   | 灰度比例曲线(如 5% → 25% → 100%)                  |
And 每个参数都提供一个推荐默认值
And 我可以用自然语言逐条回复或一次性全部回复

Given 我已回复全部 4 个参数
When Dream Engine 保存规则
Then 返回"规则已保存 ✓"确认消息
And 规则从当晚起生效
And 规则与平台预置的合规模板**叠加生效**(合规模板作为守门约束不可覆盖)

Given 规则已保存后
When 我想查看或修改当前规则
Then 输入 /rules show 可随时查看当前生效的全部参数
And 输入 /rules edit <参数> 可修改单项
And 每次修改都在管理群留下可追溯的审计记录

Given 我未配置任何规则
When 夜间循环到来
Then 系统使用平台默认规则启动(但仅限低风险覆盖范围)
And 次日在管理群提示"建议您尽快配置专属规则"
```

### US-4.2 · Dream Engine 在业务低峰自动启动
**As a** 系统,
**I want** 在业务低峰时段按商户配置的规则自动触发 Dream Engine 回放白天对话,
**so that** 不抢用户对话的 GPU 也不需要额外预算。

```gherkin
Given 租户的对话 QPS 连续 30 分钟低于白天均值的 20%(或商户自定义阈值)
When 系统判定为业务低峰
Then 自动触发 Dream Engine 启动
And 读取白天的临时记忆池
And 执行回放 + 抽取经验 + 发现盲区的流水线
And 抽取范围严格按商户配置的"覆盖范围"参数约束
And 白天流量突增时可被中断,不影响用户感知
```

### US-4.3 · 晨起推送提案到管理群由商户拍板
**As a** 商户管理员老陈,
**I want** 夜间产生的话术和知识提案清晨推送到我的管理群让我一键通过,
**so that** 我保有最终决策权但只需很少时间。

```gherkin
Given 昨夜 Dream Engine 产生了若干提案
When 第二天早上 9 点前
Then 所有提案以卡片形式推送到管理群
And 每张卡片显示提案来源对话、影响范围、风险等级
And 卡片附带 ✓ 通过 / ✎ 修改 / ✗ 驳回 三个按钮
And 通过的提案进入灰度发布流程
And 平台合规规则以"策略模板"形式已经过预审,不再二次打扰
And 根据我之前配置的"风险阈值"参数,中风险以上的提案需要我二次确认
```

### US-4.4 · 提案灰度发布与一键回滚
**As a** 商户管理员老陈,
**I want** 通过的提案按我配置的灰度策略渐进上线,出问题能一键撤回,
**so that** 学习不会变成风险源。

```gherkin
Given 一个提案被通过
When 进入灰度发布
Then 按商户配置的灰度策略执行(默认 5% → 25% → 100%)
And 每阶段观察 24 小时核心指标
And 如果 CSAT 和升级转结案率无显著下跌
Then 自动进入下一阶段
And 全程在管理群可见进度

Given 任一阶段发现问题
When 管理员输入 /rollback <proposal_id>
Then 该提案立即从所有流量中撤回
And 管理群收到回滚确认消息
And 本次提案进入"待复盘"队列
```

---

## 共用约束(所有 story 适用)

- **反幻觉硬约束**: 任何 Agent 查不到明确答案时,不得编造,必须转人工或明确表达"不确定"
- **多语言**: 客户用任意支持语言提问,Agent 以同语言回复
- **上下文加载**: 老客户进来默认加载历史;新客户自动创建工作目录
- **设计系统**: 所有客户端和工作区 UI 遵循"江峡泼墨"设计系统

---

*17 个 Story · 基于 AutoService-PRD.md v1.0 · 下一步: 按 Epic 拆分子模块 PRD*
