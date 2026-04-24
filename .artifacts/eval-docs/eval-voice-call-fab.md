---
type: eval-doc
id: eval-doc-022
status: confirmed
producer: skill-5
created_at: "2026-04-22"
confirmed_at: "2026-04-22"
mode: simulate
feature: customer-chat voice call FAB (integrate cc-openclaw voice service)
submitter: li.zhenyu
related:
  - eval-doc-011  # T1B.5 floating button SDK (precedent for iframe pattern)
  - issue-002     # GitHub issue #79
---

# Eval: C 端 customer-chat 电话 FAB 对接 cc-openclaw 语音服务

## 基本信息

- 模式：simulate
- 提交人：li.zhenyu
- 日期：2026-04-22
- 状态：confirmed（2026-04-22 user reviewed on GitHub issue #79）

---

## 1. 任务目标

C 端访客（EndUser）在 customer-chat SPA 浮窗的 📞 按钮上点一下，弹出语音通话面板，和 cc-openclaw 里已实现的"豆包 E2E + CC actor"语音助手实时对话。

- **MVP（路线 A）**：iframe 内嵌 cc-openclaw 的 voice-web（`https://voice.ezagent.chat`），AutoService 只负责"开窗 + 透传上下文 + 关窗"，语音全链路保留在 cc-openclaw 内部。
- **不在本任务范围**：把 voice 升格为 AutoService 正式 channel（路线 B，voice_gateway 改接 channels/web）—— 作为后续任务。

---

## 2. 现有代码分析

### 2.1 已有能力

| 能力 | 状态 | 位置 |
|---|---|---|
| 电话 FAB icon（装饰占位） | ✅ 已渲染 | `frontend/apps/customer-chat/src/components/ChatFAB.tsx:12` |
| 浮动按钮 + iframe 模式的工程先例 | ✅ T1B.5 `@autoservice/embed-sdk` 已用 iframe 嵌 SPA | `frontend/packages/embed-sdk/src/iframe.ts` |
| i18n | ✅ `@autoservice/i18n` 可用于"正在接通/挂断"文案 | `frontend/packages/i18n/` |
| voice-web（Next.js + AudioWorklet + WS client） | ✅ 完整 | `~/cc-openclaw/voice-web/`（2026-04-22 已复制到 `li.zhenyu` 家目录，可读写；无 git 版本管）|
| voice_gateway（aiohttp, 豆包 E2E + 火山 Realtime） | ✅ 完整 | `~/cc-openclaw/voice_gateway/` |
| channel_server（CC actor bridge :8765） | ✅ 完整 | `~/cc-openclaw/channel_server/`（**当前未在跑**） |
| Cloudflare Tunnel → voice.ezagent.chat | ⚠️ 进程在跑，ingress 分流未核实 | 配置在 `~h2oslabs/.cloudflared/config.yml`（本地仍不可读；要 CF dashboard 确认） |

### 2.2 缺失（本任务要补）

| 缺口 | 位置 |
|---|---|
| 电话按钮 onClick → 打开语音浮层 | `ChatFAB.tsx:12` 改 `<div>` 为 `<button>`，加 `onCallClick` prop |
| `VoiceCallModal.tsx` 组件（iframe 容器 + 关闭控制） | `frontend/apps/customer-chat/src/components/VoiceCallModal.tsx` (NEW) |
| App 层 call 状态机（idle/open/calling/ended） | `frontend/apps/customer-chat/src/App.tsx` 新增 `isCallOpen` state |
| `buildVoiceIframeUrl()` — 拼 query params | `frontend/apps/customer-chat/src/lib/voice-iframe.ts` (NEW) |
| postMessage 协议（voice-web → AutoService 的 `as:voice:close/error`） | voice-web `page.tsx` 发、AutoService 监听 |
| voice-web 支持从 URL query 初始化 VoiceClient 配置 | cc-openclaw: `voice-web/src/app/page.tsx` 读 `URLSearchParams` |
| AutoService 响应头 `Permissions-Policy: microphone=(self "https://voice.ezagent.chat")` | 待定：customer-chat 的 nginx/CDN 配置（dev 不需要）|
| cc-openclaw Makefile 纳入 channel_server 启动 | `~/cc-openclaw/Makefile`（可直接改）|
| Cloudflare Tunnel ingress 路径分流验证（`/ws` → :8089） | ~h2oslabs/.cloudflared/config.yml（本机不可读；需 Cloudflare 控制台确认 ingress 规则）|

---

## 3. 架构设计（路线 A · iframe MVP）

### 3.1 交互时序

```
EndUser                customer-chat (AutoService)               voice-web (cc-openclaw)                voice_gateway    channel_server
   |                           |                                         |                                   |               |
   |---click 📞 FAB----------->|                                         |                                   |               |
   |                           |-- open VoiceCallModal                   |                                   |               |
   |                           |   iframe src= voice.ezagent.chat        |                                   |               |
   |                           |   ?tenant_id=&customer_id=&call_id=     |                                   |               |
   |                           |   &systemRole=&greeting=&comfortText=   |                                   |               |
   |                           |                                         |                                   |               |
   |<==microphone permission prompt (browser, in iframe)==|              |                                   |               |
   |---allow-------------------|-------------------------------------->  |                                   |               |
   |                           |                                         |-- WS wss://voice.ezagent.chat/ws->|               |
   |                           |                                         |   first frame {type:start,...}    |               |
   |                           |                                         |                                   |-- connect ->  |
   |                           |                                         |<-- greeting TTS (24kHz PCM) ----- |               |
   |<==audio playback==========|<== (iframe audio)                       |                                   |               |
   |                           |                                         |                                   |               |
   |---speak----------(mic)--->|                                         |--16kHz PCM binary --------------->|               |
   |                           |                                         |<-- ASR text events ---------------|               |
   |                           |                                         |                                   |-- query ->    |
   |                           |                                         |                                   |<-- response - |
   |                           |                                         |<-- chat + TTS --------------------|               |
   |<==audio playback==========|<== (iframe audio)                       |                                   |               |
   |                           |                                         |                                   |               |
   |---click "挂断"----------->|                                         |                                   |               |
   |                           |-- destroy iframe                        |                                   |               |
   |                           |   on postMessage 'as:voice:close'       |                                   |               |
```

### 3.2 URL query 协议（AutoService → voice-web）

```
https://voice.ezagent.chat/?
  embed=1
  &tenant_id=<tenant>
  &customer_id=<customer>
  &call_id=<uuid>              # 全链路 trace id，AutoService 生成
  &lang=zh-CN
  &mode=e2e                    # e2e 或 split
  &systemRole=<url-encoded>    # 可选，覆盖 default system role
  &greeting=<url-encoded>      # 可选，覆盖 default greeting
  &comfortText=<url-encoded>   # 可选，覆盖 "稍等我帮你查一下"
```

voice-web 改造（**cc-openclaw 侧本地改动**，当前无 upstream git，改动只在 `~/cc-openclaw` 生效）：`page.tsx` 在挂载时读 `URLSearchParams`，把 `tenant_id/customer_id/call_id` 透传给 `VoiceClient.start({...})` 的首帧 `{type:"start",...}`，gateway 侧 `Session` 把 `call_id` 注入日志 + ActorBridge 的 query metadata。

### 3.3 postMessage 协议（voice-web → customer-chat）

```typescript
// voice-web 发
{ type: 'as:voice:ready' }                               // iframe 内初始化完成
{ type: 'as:voice:state', state: 'greeting' | 'talking' | 'ending' }
{ type: 'as:voice:transcript', role, text, interim }     // 可选透传，给 AutoService 记录
{ type: 'as:voice:error', code, message }
{ type: 'as:voice:close' }                               // 用户在 iframe 内挂断

// customer-chat 发
{ type: 'as:voice:hangup' }                              // 外层挂断按钮
```

`targetOrigin` MVP 用 `'*'` + 类型白名单过滤；上线前收紧到 `https://voice.ezagent.chat`。

### 3.4 组件清单

```
frontend/apps/customer-chat/src/
  components/
    ChatFAB.tsx                 [edit] <div> 改 <button>，新 onCallClick prop
    VoiceCallModal.tsx          [new]  固定定位浮层；内嵌 iframe；关闭按钮；状态指示
  lib/
    voice-iframe.ts             [new]  buildVoiceIframeUrl + postMessage types
  App.tsx                       [edit] isCallOpen state + ChatFAB onCallClick + 挂载 VoiceCallModal
  index.css                     [edit] .web-voice-modal 样式
```

cc-openclaw 侧本地改动（在 `~/cc-openclaw` 直接编辑；当前无 git 管理，不走 PR）：
```
voice-web/src/app/page.tsx     [edit] 读 URLSearchParams；embed=1 时隐藏 dev 输入框
voice-web/src/lib/voice-client.ts  [edit] 把 tenant_id/customer_id/call_id 透传首帧
voice_gateway/session.py       [edit] 从首帧读 call_id，放进 logger extra + ActorBridge metadata
Makefile                       [edit] 补 channel_server target；或文档说明独立启动
```

### 3.5 iframe 权限策略

- iframe 标签：`<iframe allow="microphone" ...>`
- customer-chat 响应头（生产）：`Permissions-Policy: microphone=(self "https://voice.ezagent.chat")`
- dev 环境（localhost:5173 ↔ localhost:13036）：两边都是 secure context 的 localhost，无需 Permissions-Policy

### 3.6 运行模式

- **dev**：`make dev:customer`（:5173）+ cc-openclaw `make start` 起 voice-web(:13036) + gateway(:8089) + tunnel；在 SPA 里把 `VITE_VOICE_WEB_URL` 指到 `http://localhost:13036`
- **prod**：customer-chat 部署到 `chat.<tenant>.ezagent.chat`（或子路径），voice-web 保持 `https://voice.ezagent.chat`，两域 HTTPS

---

## 4. 关键设计决策

### D1. iframe vs 内联 voice-client
**决策**：**iframe**。
- 复用 cc-openclaw 已有的 voice-web UI（已做好 AudioWorklet、PCM 采集/播放、WS 协议）
- 零跨 repo 代码搬迁；cc-openclaw 自己迭代不破坏 AutoService
- 代价：跨 origin 通信走 postMessage；父页必须 HTTPS

### D2. 放不放到 `@autoservice/embed-sdk`
**决策**：**不放**。embed-sdk 是给第三方商户独立站用的（T1B.5），本任务是 customer-chat SPA 内部功能，直接写成 SPA 组件即可。

### D3. 用哪个 voice 模式
**决策**：**e2e 模式**。豆包一条 WS 完成 ASR+LLM+TTS，延迟最低；split 模式作为 fallback，路线 B 再切。

### D4. call_id 谁生成
**决策**：**AutoService 生成**（`crypto.randomUUID()`），URL 带给 voice-web，voice-web 首帧传给 gateway，gateway 注入 ActorBridge 的 query metadata。全链路可追。

### D5. Permissions-Policy 落在哪一层
**决策**：**customer-chat 的 HTTP 响应头**。SPA 只是静态资源，头由部署层的 nginx/CF Pages 设。dev 走 localhost 绕开。

### D6. 挂断是谁驱动
**决策**：**两端都可**。iframe 内有"挂断"按钮（voice-web 已有 Stop Call）；外层 Modal 也有"关闭"按钮。任一触发，postMessage 通知对端，双方各自清理。

---

## 5. Testcase 表格（simulate）

| # | 场景 | 前置条件 | 操作步骤 | 预期效果 | 模拟效果（基于代码分析） | 差异描述 | 优先级 |
|---|------|---------|---------|---------|------------------------|---------|--------|
| 1 | 点击电话 FAB 打开语音浮层 | customer-chat SPA 加载；voice-web 可达；父页 HTTPS（或 localhost） | 点击 📞 按钮 | VoiceCallModal 弹出，iframe src 带 tenant/customer/call_id 等 query | ChatFAB.tsx:12 改 `<button>` + onCallClick 后，触发 App.tsx 的 `setIsCallOpen(true)`；模拟可达，样式与现有 `.web-fab` 一致 | 无 | P0 |
| 2 | 浏览器首次请求麦克风权限 | 用户未授予过麦权限 | iframe 内 voice-client.start() 调用 getUserMedia | Chrome 弹授权弹窗 | `audio-capture.ts:8` 会直接 `navigator.mediaDevices.getUserMedia({audio:{sampleRate:16000,channelCount:1}})`；iframe `allow="microphone"` 到位即可正常弹窗 | 无 | P0 |
| 3 | 授权后播欢迎语 | 第 2 步允许麦 | 等待 2 秒内 | 豆包 TTS 播"你好，请问有什么可以帮你？" | `session.py:90-111` _connect_and_greet 流程：Doubao SayHello (event 300) → TTSResponse binary → 前端 audio-playback 调度播放 | 无 | P0 |
| 4 | 用户说话触发 ASR → CC actor 回应 → TTS 播放 | 第 3 步完成；channel_server :8765 在线 | 说"帮我查一下 iPhone 15 库存" | 界面显示实时转写；助手语音作答 | `session.py:226` EVENT_ASR_ENDED 触发 `_run_query`：安抚语打断 (line 270) → `bridge.query()` (actor_bridge.py:37) → `send_chat_rag_text()` (line 285) → 豆包继续 TTS。延迟约 2-4s | 无 | P0 |
| 5 | 用户主动打断助手说话 | 第 4 步助手正在 TTS | 用户在助手话没说完时再说话 | 助手立刻停止播放，切换到监听用户 | Doubao 支持 `ClientInterrupt (event 515)`；voice-client 有 `clear_audio` 处理。模拟可行但需验证前端打断触发时机 | 轻微风险：ASR 打断阈值未经真人测试 | P1 |
| 6 | 用户点"挂断"关闭通话 | 通话进行中 | 点击 Modal 关闭按钮或 iframe 内 Stop Call | iframe 销毁，WebSocket close，麦克风释放 | voice-client.ts:54 `stop()` → send `{type:"stop"}` + close WS；postMessage `as:voice:close` 通知父页 setIsCallOpen(false) | 无 | P0 |
| 7 | 浏览器麦克风权限被拒 | 用户在弹窗点"阻止" | 点击电话 FAB | Modal 打开，iframe 内显示"未授予麦克风权限"文案，引导去设置 | voice-client.ts `onError` 会触发；voice-web 当前只显示通用错误文案，**需要补一条针对 NotAllowedError 的提示** | 轻微差距：文案需新增 | P1 |
| 8 | WebSocket 连接失败 | gateway 未启动 或 tunnel /ws 路由错误 | 点击电话 FAB | Modal 显示"无法接通，请稍后重试"，不卡死 | voice-client.ts `onerror/onclose` 分支已覆盖；postMessage `as:voice:error` 通知父页 | 无 | P1 |
| 9 | channel_server 离线导致 LLM query 60s 超时 | gateway 通、channel_server 未启 | 说一句话 | 界面提示"助手暂时无法回复"，安抚语播完后不再有回复 | actor_bridge.py:37 query 60s timeout → raise；session.py 当前无 fallback 文案，**需要补** | 差距：需要 gateway 发 error 事件 | P1 |
| 10 | 多次快速打开/关闭 Modal | SPA 就绪 | 连续 5 次点击 FAB + 关闭 | 每次都能正常开/关；无 WS 泄漏、无音频残留 | Modal 销毁触发 iframe unmount；iframe 内 audio-playback.closePlayer 会 disconnect AudioContext。AutoService 侧需确保 VoiceCallModal 的 cleanup 在 useEffect return 里释放 postMessage listener | 轻微风险：postMessage listener 泄漏 | P1 |
| 11 | 未传 tenant_id/customer_id | AutoService 侧 session 未知 | 强制无参打开 iframe | voice-web 使用 default systemRole/greeting 正常工作，gateway 日志 call_id=anonymous | config.py 中 greeting/comfortText 有默认值；voice-web page.tsx 读 query param 时要 fallback | 轻微差距：voice-web 需加 fallback 逻辑 | P2 |
| 12 | 移动端 Safari 浏览器 | iPhone Safari，父页 HTTPS | 点击电话 FAB | AudioContext 需要 user-gesture 解锁；授权弹窗正常弹 | audio-playback.ts 的 AudioContext 创建时机要在 click 事件 handler 同步栈内。当前 voice-web 在 Start Call 按钮 click 里创建，iframe 嵌入后**首次点击是父页 FAB，不是 iframe 内按钮**，可能解锁失败 | 高风险：iOS Safari AudioContext 解锁可能需 iframe 内再 click | P2 |
| 13 | iOS 自动播放限制 | iOS Safari | 欢迎语 TTS 到达 | 无声（需要用户手势才能播放） | 同 TC-12；需要 iframe 内 "Tap to start" 过渡页 | 高风险：用户体验破损 | P2 |
| 14 | 通话过程中用户切到后台 | Android Chrome，通话中 | 按 Home 键 30 秒后回到前台 | 恢复播放/录音，或显示"已掉线，点击重连" | MediaStream track 可能被浏览器暂停；WS 可能断开。session.py 的 E2E 模式未实现重连 | 差距：重连逻辑缺 | P2 |

---

## 6. 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| Cloudflare Tunnel ingress 未分流 `/ws` → :8089 | 高 | 方案一：CF Dashboard 查/改 ingress 规则（要访问权限）。方案二：本机直连 `http://localhost:13036`（localhost 算 secure context）绕开 tunnel 验证 UI 层链路 |
| iOS Safari AudioContext 解锁 | 高 | voice-web `page.tsx` embed 模式加"Tap to start"一次性过渡按钮（在 iframe 内），把 getUserMedia + AudioContext resume 都放到这个 click handler |
| channel_server 未开机自启 | 中 | 补 `deploy/ai.openclaw.channel-server.plist`；在 `~/cc-openclaw/Makefile` 加 `channel-server` target 并让 `start` 依赖它（可直接本地改） |
| customer-chat 无 HTTPS 域 → 无法 iframe voice-web | 中 | 与部署团队对齐：customer-chat 域名方案（子域 `chat.ezagent.chat` 或 `voice.ezagent.chat/chat/*` 反代）|
| 跨 origin postMessage 被中间扩展劫持 | 低 | 上线前 `targetOrigin` 由 `*` 收紧到 `https://voice.ezagent.chat` + 消息类型白名单 |
| 豆包 API 配额/计费 | 低 | 生产切 AutoService 租户凭据；监控用量；设每日预算上限 |
| 语音记录是否入库、合规 | 中 | 当前 gateway 不落盘音频，仅 ASR 文本。若 AutoService 要记录，走路线 B 时再设计，MVP 阶段日志仅保留 call_id + 转写 |

---

## 7. 未决问题

1. **customer-chat 的域名策略**：独立子域（`chat.<env>.ezagent.chat`）还是挂在 `voice.ezagent.chat/chat/*` 下？前者更清晰；后者省一条 CF 规则但 SPA 构建时 basename 要处理。**Owner: @zyli-developer**，需要和部署团队对齐。
2. **Cloudflare Tunnel 路径分流现状**：`voice.ezagent.chat/ws` 是否已路由到 `localhost:8089`？`~h2oslabs/.cloudflared/config.yml` 仍不可读（tunnel 配置在机器级 ops 领域，不跟 cc-openclaw 代码走）。需要有 CF 控制台访问的人查 Zero Trust → Networks → Tunnels，或在本机直接 `http://localhost:13036` 验证 UI 层。
3. **跨 origin cookie**：MVP 不共享 AutoService 的 operator_session cookie；所有上下文用 URL query 传。若后续要让 voice-web 回调 AutoService 写转写记录，需设 `SameSite=None; Secure` + CORS credentials。
4. **浏览器兼容矩阵**：MVP 目标 Chromium 桌面通；iOS Safari / Android Chrome 降级策略（"请使用 Chrome 浏览器"还是做 Tap-to-Start）？
5. **语音 UI 与文字 IM 的切换**：同一 SPA 里文字聊天 Modal 和语音 Modal 是否互斥？当前 ChatFAB 返回两个按钮（📞 + 💬），推荐**互斥**（打开一个自动关另一个）但需要产品确认。
6. ~~**voice-web 的 embed 模式改造归属**：这是 cc-openclaw 的变更。谁在 cc-openclaw 提 PR？需要在两仓协调。~~ **(2026-04-22 更新)** cc-openclaw 已复制到 `~/cc-openclaw`，在本机直接改即可；当前无 git 管理，只影响本机 dev 环境，不走 upstream PR。
7. **session.py 的 fallback 文案**（TC-9）：channel_server 超时时是走豆包默认回复，还是 gateway 主动合成"助手暂时无法回复"？

---

## 8. 验收标准

### 预验证（0 代码成本，立刻可做）

核心技术假设是 "iframe + 麦克风 + AudioContext 播放 + 对 voice-web 现域的 WSS 能通"。这四件事在写任何代码前就能用现成的 `voice.ezagent.chat` 验证，避免等到联调才发现 CF Tunnel 的 `/ws` 没分流。

**步骤**：

1. 任选一个已经是 HTTPS 的页面（例：`https://example.com`）。访问后打开 DevTools → Console。
2. 粘贴并执行：
   ```js
   const f = document.createElement('iframe');
   f.src = 'https://voice.ezagent.chat';
   f.allow = 'microphone';
   f.style = 'position:fixed;right:20px;bottom:20px;width:420px;height:640px;z-index:99999;border:1px solid #ccc;background:#fff;';
   document.body.appendChild(f);
   ```
3. 在 iframe 内点 **Start Call**。观察：
   - a. 浏览器是否弹出麦克风授权提示（验证 `allow="microphone"` + secure context 条件 2/4 满足）
   - b. 授权后 DevTools → Network → WS 是否出现对 `wss://voice.ezagent.chat/ws` 的 101 握手（验证 CF Tunnel `/ws` 路径分流，即 Q2）
   - c. 是否听到豆包 TTS 欢迎语播放（验证 iframe 内 AudioContext 解锁 + 音频播放通路）
   - d. 对着麦说话，iframe 内是否实时出现 ASR 转写
   - e. 助手是否有语音回答（验证 channel_server 在线且 ActorBridge query 通）

**预期结果矩阵**：

| 观察点 | 通过 | 失败的含义 |
|---|---|---|
| (a) 弹麦权限 | ✅ | ❌ 父页 CSP 屏蔽 `frame-src voice.ezagent.chat`，换一个 CSP 宽松的页面再试 |
| (b) WSS 101 握手 | ✅ | ❌ CF Tunnel `/ws` 未分流到 :8089（Q2 坐实），需要补 ingress 规则 |
| (c) TTS 出声 | ✅ | ❌ 麦已授权但没声：gateway 到豆包连接失败 / 凭据过期 / AudioContext 未解锁 |
| (d) ASR 文本 | ✅ | ❌ 音频上行格式不对 / gateway 没接收 / voice_gateway 未启动 |
| (e) 助手回答 | ✅ | ❌ channel_server 未启动（:8765）或 `ActorBridge.query` 60s 超时 |

**本次验证通过的含义**：路线 A 的全部技术前提都成立，剩下工作只是"把 FAB 接 onClick + 做个 VoiceCallModal"这种纯前端实现，零技术未知。

**本次验证失败的含义**：优先修复 Q2 / channel_server 启动等 cc-openclaw 侧基建问题（现在可在 `~/cc-openclaw` 直接改），不要先改 AutoService 代码。

**测试人**：任何能访问 `voice.ezagent.chat` 的开发者，不需要 AutoService 代码权限。

**执行环境**：至少覆盖 Chrome 桌面；有条件再补 Android Chrome / iOS Safari（后者如果在此步就失败，需要 TC-12/TC-13 的 "Tap to Start" 过渡按钮方案上线前就实现）。

### 冒烟（P0）

- [ ] customer-chat SPA 加载，电话 FAB 显示且可点击（非装饰 div）
- [ ] 点击电话 FAB，VoiceCallModal 在 800ms 内弹出，iframe 加载 voice-web
- [ ] iframe URL 包含 `tenant_id` / `customer_id` / `call_id` / `embed=1`
- [ ] 授权麦克风后，欢迎语在 3s 内开始播放
- [ ] 说一句中文（例如"帮我查 iPhone 15 库存"），ASR 文本显示 + 助手语音作答（端到端 < 5s）
- [ ] 点挂断，iframe 销毁，麦克风指示灯在 1s 内熄灭
- [ ] gateway 日志里能按 `call_id` 串起完整一次通话（ASR 文本 + LLM query + TTS 事件）

### 边界（P1）

- [ ] 麦克风被拒时，Modal 内显示明确引导文案，不卡死（TC-7）
- [ ] gateway / channel_server / tunnel 任一不通时，用户看到"无法接通"而非无响应（TC-8、TC-9）
- [ ] 快速连续开关 Modal 5 次，无 WS 泄漏（devtools Network 中 ws 数量 ≤ 1）
- [ ] 用户主动打断助手说话，播放在 500ms 内停止（TC-5）

### 非功能

- [ ] 首次 TTS 播放 ≤ 3s（从授权到出声）
- [ ] ASR→TTS 端到端延迟 P50 ≤ 3s，P95 ≤ 6s
- [ ] 麦克风采样 16kHz 单声道，TTS 播放 24kHz，和 `voice_gateway/config.py` 一致

---

## 9. 不在范围

- 把 voice 做成 AutoService 的原生 channel（路线 B，voice_gateway 改指 channels/web WebSocket）
- 通话录音、转写归档、满意度调研（T6D 再议）
- 多语言语音（目前锁 zh-CN voice `zh_female_vv_jupiter_bigtts`）
- Operator 端看语音通话状态（后续 T2B）
- 计费接入（billing pipeline，后续 T3B/T6D）
- 移动端 APP 集成（独立任务）

---

## 10. 产出清单（供 Skill 2 test-plan-generator 消费）

### AutoService 侧

| # | 文件 | 动作 | 说明 |
|---|------|------|------|
| 1 | `frontend/apps/customer-chat/src/components/ChatFAB.tsx` | **edit** | `<div>` 改 `<button>`，新 `onCallClick` prop |
| 2 | `frontend/apps/customer-chat/src/components/VoiceCallModal.tsx` | **new** | 浮层容器 + iframe + 关闭按钮 + 状态指示 |
| 3 | `frontend/apps/customer-chat/src/lib/voice-iframe.ts` | **new** | `buildVoiceIframeUrl()`, postMessage 类型 |
| 4 | `frontend/apps/customer-chat/src/App.tsx` | **edit** | `isCallOpen` state；FAB 的 onCallClick；挂载 VoiceCallModal |
| 5 | `frontend/apps/customer-chat/src/index.css` | **edit** | `.web-voice-modal` 样式 |
| 6 | `frontend/apps/customer-chat/src/__tests__/VoiceCallModal.test.tsx` | **new** | 组件渲染/关闭/postMessage 测试 |
| 7 | `frontend/apps/customer-chat/src/__tests__/voice-iframe.test.ts` | **new** | URL 拼接 + fallback 测试 |
| 8 | `frontend/apps/customer-chat/vite.config.ts` | **edit** | `VITE_VOICE_WEB_URL` 环境变量 |
| 9 | （部署层）nginx/CF Pages 配置 | **edit** | `Permissions-Policy` 响应头 |

### cc-openclaw 侧（本地改动，**无 upstream git**，当前只影响 `~/cc-openclaw` dev 环境）

| # | 文件 | 动作 | 说明 |
|---|------|------|------|
| A | `voice-web/src/app/page.tsx` | **edit** | 读 URLSearchParams；embed=1 时精简 UI + 发 postMessage |
| B | `voice-web/src/lib/voice-client.ts` | **edit** | 把 tenant_id/customer_id/call_id 透传 start 首帧 |
| C | `voice_gateway/session.py` | **edit** | 从 start 首帧读 call_id，放 logger extra + actor_bridge metadata |
| D | `Makefile` | **edit** | 新增 `channel-server` target，`make start` 依赖它 |
| E | `README.md` | **edit** | embed 对接说明 + URL query schema |

---

## 11. 后续行动

- [x] eval-doc 生成
- [x] 用户 review 并把 status: draft → confirmed（2026-04-22）
- [x] eval-doc 已注册到 .artifacts/registry.json
- [x] GitHub issue 已创建（#79）
- [ ] Skill 2 消费本 eval-doc，生成 TC-001~014 对应 test-plan
- [ ] Skill 3 从 test-plan 产出 test-diff
- [ ] Skill 4 执行测试产出 e2e-report

---

## 12. Changelog

- **2026-04-22 (initial)** — eval-doc 生成（simulate），confirmed；14 TC；假设 cc-openclaw 只读、改动需走外部 PR。
- **2026-04-22 (path update)** — cc-openclaw 已复制到 `~/cc-openclaw`（`li.zhenyu` 家目录），可读写，但**无 git 管理**。所有"cc-openclaw 侧 PR"的表述更正为"cc-openclaw 侧本地改动"。Q6 已解决（不再需要两仓协调，但仍需正式版本管理策略）。`voice-web` / `voice_gateway` 已在新位置启动；`channel_server` 仍未启动。Cloudflare Tunnel ingress 验证与 tunnel 配置仍属 ops 领域，未变。

---

*eval-doc-022 · customer-chat voice call FAB · simulate · confirmed*
