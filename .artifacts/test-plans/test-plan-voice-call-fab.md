---
type: test-plan
id: test-plan-004
status: executed
producer: skill-2
created_at: "2026-04-22"
confirmed_at: "2026-04-22"
executed_at: "2026-04-22"
trigger: "eval-doc-022 (customer-chat voice call FAB) — confirmed on 2026-04-22"
related:
  - eval-doc-022
  - "issue:79"
decisions_frozen:
  D1: "iframe 嵌入 cc-openclaw voice-web（路线 A MVP），不内联 voice client"
  D2: "上下文通过 URL query 传给 voice-web（tenant_id/customer_id/call_id/systemRole/greeting/comfortText/mode/lang/embed）"
  D3: "postMessage 协议：voice-web → parent 发 as:voice:ready/state/transcript/error/close；parent → voice-web 发 as:voice:hangup"
  D4: "UX 为两次点击（父页 FAB + iframe 内 Start Call）；iOS Safari 依赖 iframe 内用户手势解锁 AudioContext"
  D5: "14 个 TC 按 unit / integration / manual-device-test 分层；依赖真实 gateway 的 E2E 默认 skip（RUN_VOICE_E2E=1 开启）"
  D6: "Permissions-Policy 响应头落在部署层（nginx/CF Pages），不纳入 CI"
  D7: "cc-openclaw 侧改造（voice-web page.tsx 读 query、session.py 读 call_id、Makefile 补 channel-server）为外部 PR，不在本仓 test 范围"
---

# Test Plan: customer-chat voice call FAB

## 触发原因

eval-doc-022 定义了 14 个 testcase（§5）和 9 个新增/改动产品文件（§10 AutoService 侧）。本 plan 把 14 个 TC 转成标准 TC-ID，按测试类型分三组（unit / integration / manual-device-test），并标注每个 TC 依赖的外部服务和 CI 运行策略。

- 所有 TC 保留 eval-doc §5 的原始编号映射（TC-1 → TC-022-001，以此类推）
- CI 必跑：7 个（P0 × 5 + P1 × 2）
- 需真实外部服务：4 个（默认 skip，`RUN_VOICE_E2E=1` 开启）
- Manual/device-test：3 个（iOS Safari、Android 背景切换）

## 测试文件规划

```
frontend/apps/customer-chat/src/__tests__/
  voice-iframe.test.ts          新建 (TC-022-011, TC-022-002-url)       unit
  ChatFAB.test.tsx              扩展 (TC-022-001)                        unit
  VoiceCallModal.test.tsx       新建 (TC-022-006, TC-022-007, TC-022-010) integration
  VoiceCallModal.postmsg.test.tsx  新建 (TC-022-008)                     integration

frontend/apps/customer-chat/tests-e2e/      （新建目录，Playwright 或空壳）
  voice-call.spec.ts            新建 (TC-022-002, 003, 004, 005, 009)   E2E (RUN_VOICE_E2E=1)

docs/manual-tests/                           （新建）
  voice-call-ios-safari.md      新建 (TC-022-012, TC-022-013)           manual
  voice-call-android-bg.md      新建 (TC-022-014)                        manual
```

目标：unit/integration 共 **7 个 CI 必跑用例全绿**；E2E 5 个 + manual 3 个由负责人在对应环境跑。customer-chat 现有测试套件不受影响。

---

## 用例列表

### 分组 A · Unit（纯前端离线，CI 必跑，TC-022-001、007、011）

#### TC-022-001: ChatFAB 电话按钮点击触发 onCallClick
- **文件**: `frontend/apps/customer-chat/src/__tests__/ChatFAB.test.tsx`
- **映射**: eval-doc §5 TC-1
- **优先级**: P0
- **类型**: unit (Vitest + jsdom)
- **依赖**: 无
- **CI**: 必跑
- **前置**: 渲染 `<ChatFAB onCallClick={fn} onClick={fn2} />`
- **步骤**:
  1. `render(<ChatFAB onClick={vi.fn()} onCallClick={vi.fn()} />)`
  2. 断言电话按钮是 `<button>` 且有 `aria-label` 含"语音"/"voice"
  3. `fireEvent.click(screen.getByRole('button', { name: /voice|语音/i }))`
- **预期**: `onCallClick` 被调用 1 次；原 💬 按钮（`onClick`）不受影响
- **覆盖产品文件**: `frontend/apps/customer-chat/src/components/ChatFAB.tsx`（§10 #1 edit）

#### TC-022-007: VoiceCallModal 未授权麦克风时显示引导文案
- **文件**: `frontend/apps/customer-chat/src/__tests__/VoiceCallModal.test.tsx`
- **映射**: eval-doc §5 TC-7
- **优先级**: P1
- **类型**: unit（mock postMessage）
- **依赖**: 无
- **CI**: 必跑
- **前置**: 挂载 `<VoiceCallModal open={true} onClose={fn} ctx={mockCtx} />`
- **步骤**:
  1. 挂载后派发 `window.postMessage({type:'as:voice:error',code:'NotAllowedError',message:'麦克风被拒'},'*')`
  2. 等待 state 更新
- **预期**: Modal 内出现引导文案（含"麦克风"/"权限"/"设置"三词之一）；Modal 不自动关闭；`onClose` 未被调用
- **覆盖产品文件**: `frontend/apps/customer-chat/src/components/VoiceCallModal.tsx`（§10 #2 new）

#### TC-022-011: buildVoiceIframeUrl 缺少 tenant/customer 时回退到 anonymous
- **文件**: `frontend/apps/customer-chat/src/__tests__/voice-iframe.test.ts`
- **映射**: eval-doc §5 TC-11
- **优先级**: P2
- **类型**: unit
- **依赖**: 无
- **CI**: 必跑
- **步骤**:
  1. `buildVoiceIframeUrl({ baseUrl:'https://voice.ezagent.chat', call_id:'abc-123' })`
  2. `buildVoiceIframeUrl({ baseUrl:'https://voice.ezagent.chat', tenant_id:'t1', customer_id:'c1', call_id:'abc-123', mode:'e2e', lang:'zh-CN' })`
- **预期**:
  - (1) URL 含 `embed=1&call_id=abc-123`，不含 `tenant_id` / `customer_id`
  - (2) URL 含全部参数且 call_id 正确
- **覆盖产品文件**: `frontend/apps/customer-chat/src/lib/voice-iframe.ts`（§10 #3 new）

#### TC-022-011-b: buildVoiceIframeUrl 正确 URL-encode 非 ASCII 字符
- **文件**: 同上
- **映射**: eval-doc §5 TC-11（扩展）
- **优先级**: P1
- **类型**: unit
- **依赖**: 无
- **CI**: 必跑
- **步骤**: `buildVoiceIframeUrl({baseUrl:'...', greeting:'你好，请问有什么可以帮你？'})`
- **预期**: URL 中 `greeting=` 后为 `%E4%BD%A0...`（不是乱码，可用 `new URL(...).searchParams.get('greeting')` 反解得到原字符串）
- **覆盖产品文件**: 同上

### 分组 B · Integration（mock voice-web 侧，CI 必跑，TC-022-006、008、010）

#### TC-022-006: 父页挂断触发 iframe 销毁 + 事件监听清理
- **文件**: `frontend/apps/customer-chat/src/__tests__/VoiceCallModal.test.tsx`
- **映射**: eval-doc §5 TC-6
- **优先级**: P0
- **类型**: integration
- **依赖**: 无
- **CI**: 必跑
- **步骤**:
  1. 挂载 `<VoiceCallModal open={true} onClose={fn} ctx={mockCtx} />`
  2. 断言 `document.querySelector('iframe')` 存在
  3. 模拟用户点挂断按钮
  4. rerender `open={false}`
  5. 断言 `document.querySelector('iframe')` 不存在
  6. 派发 `window.postMessage({type:'as:voice:ready'},'*')` —— 此时 Modal 已卸载，listener 应已清理
- **预期**: iframe 卸载后，postMessage 不再改 Modal state（通过 console 无 warning 或内部 state 设置器未被调用断言）；`onClose` 被调 1 次
- **覆盖产品文件**: `frontend/apps/customer-chat/src/components/VoiceCallModal.tsx`（§10 #2）、`App.tsx`（§10 #4）

#### TC-022-008: WebSocket 连接失败时显示"无法接通"
- **文件**: `frontend/apps/customer-chat/src/__tests__/VoiceCallModal.test.tsx`
- **映射**: eval-doc §5 TC-8
- **优先级**: P1
- **类型**: integration
- **依赖**: 无（mock postMessage as:voice:error）
- **CI**: 必跑
- **步骤**:
  1. 挂载 `<VoiceCallModal open={true}>`
  2. 派发 `window.postMessage({type:'as:voice:error',code:'ws_connect_failed',message:'...'},'*')`
- **预期**: Modal 显示"无法接通，请稍后重试"类文案；出现"重试"按钮；Modal 不自动关闭
- **覆盖产品文件**: `VoiceCallModal.tsx`

#### TC-022-010: 连续 5 次打开/关闭 Modal 无 listener 泄漏
- **文件**: `frontend/apps/customer-chat/src/__tests__/VoiceCallModal.postmsg.test.tsx`
- **映射**: eval-doc §5 TC-10
- **优先级**: P1
- **类型**: integration
- **依赖**: 无
- **CI**: 必跑
- **步骤**:
  1. spy `window.addEventListener` / `window.removeEventListener`
  2. 循环 5 次：`rerender(open=true)` → `rerender(open=false)`
  3. 统计 `'message'` 的 add/remove 计数
- **预期**: `addEventListener('message', ...)` 次数 === `removeEventListener('message', ...)` 次数（差值 0）；每次循环末 `document.querySelector('iframe')` 为 null
- **覆盖产品文件**: `VoiceCallModal.tsx`

### 分组 C · E2E（需真实外部服务，默认 skip，TC-022-002、003、004、005、009）

说明：这组 TC 需要 cc-openclaw 侧 `voice_gateway` / `channel_server` / 豆包凭据都就绪。通过 `RUN_VOICE_E2E=1 pnpm test:e2e` 开启；CI 默认 skip。**前置**是 eval-doc §8 预验证步骤全部通过（绿）。

#### TC-022-002: 真实浏览器弹麦克风授权提示
- **文件**: `frontend/apps/customer-chat/tests-e2e/voice-call.spec.ts`
- **映射**: eval-doc §5 TC-2
- **优先级**: P0
- **类型**: E2E (Playwright, headed, Chromium)
- **依赖**: voice-web 可达；iframe allow=microphone 生效
- **CI**: skip 默认；`RUN_VOICE_E2E=1` 开启
- **步骤**:
  1. Playwright `launch({ args: ['--use-fake-ui-for-media-stream'] })` —— 自动允许
  2. 或 `context.grantPermissions(['microphone'])`
  3. 访问 customer-chat dev 站 → 点击 📞 FAB → 等 iframe 加载 → 在 iframe 内点 Start Call
- **预期**: 1 秒内 `navigator.mediaDevices.getUserMedia` 被调用；无 `NotAllowedError` 抛出
- **覆盖产品文件**: 全链路

#### TC-022-003: 授权后在 3 秒内听到欢迎语 TTS
- **文件**: 同 voice-call.spec.ts
- **映射**: eval-doc §5 TC-3
- **优先级**: P0
- **类型**: E2E
- **依赖**: voice_gateway + 豆包 API + DOUBAO_APP_ID/ACCESS_TOKEN 有效
- **CI**: skip 默认
- **步骤**: 同 TC-022-002，授权后
- **预期**: 3 秒内 AudioContext 有非零 sampleRate 的 buffer source 被调度（通过 `audioContext.getOutputTimestamp()` 或 DOM 状态 `state === 'greeting' → 'talking'` 判定）；iframe 内 state badge 显示"greeting"或"talking"

#### TC-022-004: ASR → LLM → TTS 端到端延迟 P50 ≤ 3s
- **文件**: 同上
- **映射**: eval-doc §5 TC-4
- **优先级**: P0
- **类型**: E2E
- **依赖**: voice_gateway + channel_server（:8765）+ CC actor 在线 + 豆包 API
- **CI**: skip 默认
- **步骤**: 通过 Playwright `mediaSource` 或预录音频 pipe 到 fake mic，说"帮我查 iPhone 15 库存"
- **预期**: ASR 转写出现在 UI；2-4 秒内 bot 响应 TTS 开始播放；call_id 在 gateway 日志能串起全链路（验收时查日志）

#### TC-022-005: 用户说话打断正在播放的 TTS
- **文件**: 同上
- **映射**: eval-doc §5 TC-5
- **优先级**: P1
- **类型**: E2E
- **依赖**: 同 TC-022-004
- **CI**: skip 默认
- **步骤**: TC-022-003 欢迎语播到第 1 秒时，发声（fake mic 注入音频）
- **预期**: 500ms 内 TTS 停止播放（前端接收 `clear_audio` 消息）

#### TC-022-009: channel_server 离线时 60s 超时 + 降级文案
- **文件**: 同上
- **映射**: eval-doc §5 TC-9
- **优先级**: P1
- **类型**: E2E
- **依赖**: voice_gateway 在线、channel_server **故意不启动**
- **CI**: skip 默认
- **前置**: 测试前 `kill` 掉 channel_server
- **步骤**: 走完授权 → 说一句话 → 等 60s+
- **预期**: gateway 记录 `ActorBridge.query timeout`；前端 Modal 出现"助手暂时无法回复"类降级文案（**此文案需在 cc-openclaw 侧 PR 补实现**，见 eval-doc §7 Q7）
- **已知 gap**: 当前 `session.py` 无 fallback 文案路径，TC 会失败 —— 作为 cc-openclaw 侧 PR 的验收门槛

### 分组 D · Manual / Device-test（不进 CI，负责人手工跑，TC-022-012、013、014）

#### TC-022-012: iOS Safari AudioContext 解锁
- **文件**: `docs/manual-tests/voice-call-ios-safari.md`
- **映射**: eval-doc §5 TC-12
- **优先级**: P2（但上线前必须通过）
- **类型**: manual (真机)
- **设备**: iPhone iOS 17+（Safari）
- **依赖**: HTTPS 父页 + voice-web + 全链路
- **CI**: 不进 CI
- **步骤**: 真机访问 customer-chat 页面 → 点 📞 → iframe 加载 → 点 Start Call → 允许麦 → 确认能听到欢迎语
- **预期**: AudioContext 成功 resume 到 `running`（可在 iframe 内加调试按钮打印 state）；欢迎语声音可听
- **已知风险**: `addModule('/pcm-processor.js')` 是异步的，跨 await 后 activation 可能失效。如失败，需要 voice-web 侧增加 iframe 内的"Tap to Start"过渡按钮，把 AudioContext 创建 + resume 放进这个按钮的同步 click 栈

#### TC-022-013: iOS 自动播放策略兼容
- **文件**: 同上
- **映射**: eval-doc §5 TC-13
- **优先级**: P2
- **类型**: manual
- **设备**: 同上
- **步骤**: 同 TC-022-012，重点观察授权后 TTS 首包到达 → 是否真实出声
- **预期**: 有声音；若无声，进入 TC-022-012 的 Tap to Start 方案

#### TC-022-014: Android 后台切换恢复
- **文件**: `docs/manual-tests/voice-call-android-bg.md`
- **映射**: eval-doc §5 TC-14
- **优先级**: P2
- **类型**: manual
- **设备**: Android Chrome（Pixel 或同等）
- **步骤**: 通话中按 Home 键 30s → 回前台
- **预期**: 方案 A：自动恢复录音 + 播放；方案 B（MVP 接受）：显示"已掉线，点击重连"并提供重连按钮；**完全无响应或卡死为 fail**
- **已知 gap**: 当前 voice-web 无重连逻辑，TC 会 fail → 作为路线 B 升级项

---

## 统计

| 指标 | 值 |
|---|---|
| 新增 TC | 15（14 源 TC + 1 扩展 TC-022-011-b）|
| CI 必跑 | 7（P0 × 2 + P1 × 3 + P2 × 2）|
| E2E skip 默认 | 5（P0 × 3 + P1 × 2）|
| Manual device-test | 3（P2 × 3，上线前手动通过）|
| 新建测试文件 | 4 个 `.test.*` + 1 个 `.spec.ts` + 2 个 manual markdown |
| 扩展测试文件 | 1（`ChatFAB.test.tsx`）|
| 影响现有 customer-chat 测试 | **0**（新文件 + 新组件）|

## 覆盖矩阵（产品文件 → TC）

| 产品文件（§10） | 动作 | 被哪些 TC 覆盖 | 备注 |
|---|---|---|---|
| `ChatFAB.tsx` | edit | TC-022-001 | ✅ |
| `VoiceCallModal.tsx` | new | TC-022-006, 007, 008, 010 | ✅ |
| `voice-iframe.ts` | new | TC-022-011, 011-b | ✅ |
| `App.tsx` | edit | TC-022-006（间接） | ⚠️ 只间接测 isCallOpen state；不深测 |
| `index.css` | edit | — | ❌ 样式不测（视觉 regression 放 manual） |
| `__tests__/VoiceCallModal.test.tsx` | new | self | meta |
| `__tests__/voice-iframe.test.ts` | new | self | meta |
| `vite.config.ts` | edit `VITE_VOICE_WEB_URL` | — | ❌ 环境变量通过 E2E 的 dev 起站验证 |
| 部署层 Permissions-Policy 头 | edit | — | ❌ 手工 curl 验证 |

**盲点**：
1. `index.css` 样式 —— 交由设计 review + manual screenshot 对比
2. `vite.config.ts` 的 `VITE_VOICE_WEB_URL` —— dev 起站后目测 iframe src 正确即可
3. 部署层响应头 —— 用 `curl -I https://chat.<domain>/ | grep Permissions-Policy` 手工验证

---

## Skill 3 实现约束

1. **使用 Vitest + jsdom 环境**：与 customer-chat 现有测试一致
2. **React 19 + @testing-library/react**：仓库既有选型，照搬
3. **postMessage 测试**：用 `window.dispatchEvent(new MessageEvent('message', {data, origin}))` 构造；不要直接 `window.postMessage()`（jsdom 异步）
4. **iframe 元素**：jsdom 不实际加载 iframe 内容，用 `screen.getByRole('region', {name:/voice/i})` 找容器，或给 iframe 加 `data-testid="voice-iframe"` 便于选择
5. **MSW 不必要**：本任务无真实 fetch/WS 调用（mock postMessage 足够）；避免引入
6. **`beforeEach` 清理**：`document.body.innerHTML=''; vi.restoreAllMocks(); window.removeEventListener('message', ...);`
7. **E2E 可先交付空壳 spec**：`voice-call.spec.ts` 可以先放 `test.skip('...', ...)` 占位，等 eval-doc §8 预验证通过后再填实现
8. **Manual markdown**：列出设备、步骤、截图位、pass/fail 记录字段，给 QA 照着跑
9. **CI 配置**：现有 `package.json` 的 `test` 脚本跑 Vitest，新加测试自动被拾取；无需改配置
10. **E2E 独立 script**：`package.json` 新加 `test:e2e: "RUN_VOICE_E2E=${RUN_VOICE_E2E:-0} playwright test"` 或等效命令；只有设置 `RUN_VOICE_E2E=1` 才跑
11. **不改 cc-openclaw 代码**：本 test-plan 只测 AutoService 侧；cc-openclaw 侧的 page.tsx/voice-client/session.py/Makefile 改动走 cc-openclaw 仓库自己的 PR 与测试

---

## 风险与依赖

| 风险 | 等级 | 缓解 |
|---|---|---|
| CI 环境没 Chromium → Playwright E2E 无法跑 | 低 | E2E 默认 skip，CI 只跑 unit/integration |
| `window.postMessage` 在 jsdom 异步 → 测试 flaky | 中 | 统一用 `dispatchEvent(new MessageEvent(...))` |
| TC-022-009 需 cc-openclaw 先补 fallback 文案才能通过 | 中 | TC 先写，允许 fail 直到 cc-openclaw PR 合并 |
| TC-022-012/013 在开发机上不能测 | 高 | 真机测试明确交付到具体设备 owner，不阻塞主 PR |

---

## 后续行动

- [x] 用户 review test-plan，批准后 status: draft → confirmed（2026-04-22）
- [ ] Skill 3 (test-code-writer) 按本 plan 产出 test-diff（含上述文件的实际代码）
- [ ] Skill 4 (test-runner) 跑 CI 必跑的 7 个用例，产出 e2e-report
- [ ] E2E 组（5 个）等 eval-doc §8 预验证通过后补充 Playwright 实现
- [ ] Manual 组（3 个）上线前由设备 owner 完成

---

*test-plan-004 · customer-chat voice call FAB · confirmed*
