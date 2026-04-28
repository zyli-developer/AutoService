---
title: Cinnox SIP 接入提案评审
date: 2026-04-27
reviewer: yaosh
proposal_source: "外部团队提交，2026-04-26 收到"
---

# 对原 Cinnox SIP 提案的评审

> 原方案见用户对话原文（jambonz + audio_fork + sip_audio_route.py + 4 周计划）。
> 本文逐条核对，标 ✅（采纳）/ ⚠️（需调整）/ ❌（必须改）。

## 总体判断

**方向正确，细节需要重写。**

- 选 jambonz 作为 SIP 终结软件 ✅ —— 是开源里把 SIP RTP 桥接到
  WebSocket-backed pipeline 的最佳选择
- 选自部署而非 jambonz Cloud ✅ —— 避免和 Cinnox 谈三方 trunk
- "不重写现有 voice gateway" 的原则 ✅ —— 但前提是 SIP adapter 要能
  适配 split 模式，而提案写的代码恰恰违反了这一点
- sip_audio_route.py 草稿 ❌ —— 用了 3 个不存在的 API（详见 §3.1）
- "Doubao E2E 一体处理"的声称 ❌ —— 现有代码不是这个模式（见 01 文档 §2）
- 4 周排期 ⚠️ —— 漏掉了"服务端 voice controller"约 1 周工作量
- P50 < 1.2s 延时目标 ⚠️ —— 不修 TTSClient 重连开销做不到

---

## 1. ✅ 站得住脚的部分

### 1.1 jambonz 选型

jambonz audio_fork verb 的协议（首帧 JSON metadata + binary PCM 16k）
**确实**与我们 `/asr` 协议天然对齐，这是最大的工程便利。drachtio /
rtpengine / sbc-* / feature-server 全套 docker-compose 部署成熟。

### 1.2 不引入 Pipecat / LiveKit

正确。这两个是另一套 voice 编排框架，引入会和现有 split-mode 架构
正交、互相干扰。

### 1.3 SIP 接入表单的填法

提案给出的 codec 选择（PCMA + PCMU + OPUS，不勾 G729）、加密
（DTLS-SRTP + TLS 5061）、DTMF（RFC2833 + SIP Info）**全部正确**，
直接采纳。

### 1.4 8 个 SBC IP 加白名单

正确。注意安全组要同时开 5060/5061 (UDP+TCP) + 10000-20000 (UDP, RTP)。
本评估按用户决定走单点（HK），但 8 个 IP **全部加**白名单—— Cinnox
内部路由可能会从其它区出。

---

## 2. ⚠️ 需要调整的部分

### 2.1 部署区域

| 提案 | 调整 |
|---|---|
| "推荐 HK / SG，靠 Cinnox HK SBC" | 用户决定**单点 HK**。SG 不上。承担北京 / JP 区 SBC 的额外 50-80ms 单向延时。生产监控加按 Cinnox SBC 来源 IP 的延时打点 |

### 2.2 30 路并发的依据

提案"4-core 8GB 服务器支持 ≥ 30 路并发通话"**没有计算依据**。实际：

- jambonz / rtpengine：30 路 RTP 重采样大概 30-50% 单核占用，OK
- 60 个并发 Doubao WS（30 ASR + 30 TTS）：**未经验证**——Doubao
  realtime/dialogue API 的并发 quota 和按连接计费策略需要先和火山确认
- 服务端 voice controller 30 个并发 asyncio task：OK
- TLS 5061 连接 + LE 证书：OK

**建议**：PoC 阶段先按 ≤ 5 路并发验证，性能压测在 Week 4 单独做。
30 路只作为生产目标，不作为 PoC 通过条件。

### 2.3 "P50 < 1.2s"

提案的延时预算没有给出 budget breakdown。下面是基于现有 Doubao 实测
（split-mode 浏览器路径）的合理预期：

| 段 | P50 延时 | 备注 |
|---|---|---|
| Cinnox SBC ↔ HK 服务器 RTT | 30-100ms | 取决于主叫地理位置 |
| jambonz 接收 RTP → audio_fork 推 PCM | 5-10ms | rtpengine 重采样 |
| Doubao ASR 末字识别 → final 事件 | 200-500ms | end_smooth_window_ms=1500 默认偏保守 |
| `/ws/chat` cc_pool LLM 首字 | 500-1500ms | 取决于模型 + prompt |
| **TTSClient 重连开销** | **300-500ms** | **现有代码每次合成都中招** |
| Doubao TTS 首块 | 200-400ms | |
| TTS 24k → 16k → jambonz → 8k → SBC → 用户 | 50-80ms | |
| **合计 P50** | **1.3-3.0s** | 不修重连：1.6-3.5s |

**结论**：要做到 P50 < 1.2s，必须同时做到：
1. 修掉 TTSClient 重连（用 chat_tts_text 复用同一会话 / 或预热连接池）
2. 把 ASR `end_smooth_window_ms` 调到 800ms（电话场景容忍度更低）
3. cc_pool 用 streaming（首字延时降到 200ms）

如果不愿做这三项，P50 目标改为 **< 2.5s 现实可达**。

### 2.4 4 周排期

提案把"服务端 voice controller"工作量算到 sip_audio_route.py 的 80 LOC
里了，**严重低估**。实际拆开：

| 模块 | 提案估 | 实际 |
|---|---|---|
| sip_audio_route.py（薄 adapter） | 80 LOC | 100 LOC |
| 服务端 voice controller（comfort + 状态机 + barge-in） | 0 | 200 LOC |
| TTSClient 重连优化 | 0 | 50 LOC + Doubao API 验证 |
| 24k↔16k 重采样 | 0 | 30 LOC + 性能验证 |
| 测试 | 0 | 200 LOC |
| jambonz docker-compose + LE + 配置 | "Week 1" | OK |
| Cinnox 联调 | "Week 3" | OK，但要有备份测试号 |

调整为 **5 周排期**（详见 03 文档）。

---

## 3. ❌ 必须改的部分

### 3.1 提案 sip_audio_route.py 的 API 调用全错

提案草稿（节选）：

```python
await tts.send_text(GREETING_TEXT)               # ❌ 不存在
async for pcm_frame in tts.receive_audio():      # ❌ 不存在
await tts.interrupt()                             # ❌ 不存在
await ws.send_bytes(_resample_24k_to_16k(pcm_frame))  # ⚠️ 函数没实现
```

现有 TTSClient 的真实 API（`channels/web/voice/tts_client.py`）：

```python
class TTSClient:
    async def connect(self) -> None: ...
    async def synthesize(self, text: str) -> AsyncGenerator[bytes, None]: ...  # 唯一合成入口
    async def close(self) -> None: ...
```

也就是说每次合成是一次独立的 async generator，**不存在长连接的
"send_text / receive_audio" 模式**。`interrupt` 必须靠取消 outer
asyncio.Task。

### 3.2 "Doubao E2E 一体" 的误解

提案 §4.3 写："豆包 ASR + 对话 + TTS 一体处理, 流式 PCM 24kHz 回流"
—— 这和现有代码不符（见 01 文档 §2）。现有架构是：
- ASRClient 连一个 Doubao session 只取 ASR 事件
- TTSClient 连另一个 Doubao session 用 `say_hello` 触发 TTS
- LLM 走 `/ws/chat` → cc_pool（不是 Doubao）

提案如果要按"Doubao E2E"做，等于重写整条 voice 链；如果要"复用现
有 voice 链"，则必须照 split 模式接入（也就是新写 controller）。

**两条路二选一**：
- A. **接入 split 模式**（推荐 + 用户已选）：新写服务端 controller，
  用 ASR + cc_pool + TTS，工作量已计入 03 文档的 5 周。
- B. **接入真正的 Doubao E2E**：重写 voice 链，工作量 ~3 周，且会
  失去现有 cc_pool 的业务能力（多智能体、知识库、CRM 集成等）。
  **不推荐**。

### 3.3 缺少服务端 controller 的状态机

SIP 入口没有浏览器，**所有原本浏览器做的事情**都要在服务端做：

| 浏览器 VoiceCallController 做的 | SIP controller 必须做的 |
|---|---|
| 状态机 (idle/listening/thinking/speaking) | 同 |
| 监听 ASR final → 触发业务 | 同 |
| 调用 /ws/chat LLM | 同 |
| comfort-text 调度 | 同 |
| comfort 与正式回复的时序协调 | 同 |
| barge-in（speech_started → 中断 TTS） | 同 |
| 错误恢复 | 同 |
| 把 user/bot 文本插入 chat history | 改成持久化到 conv_engine（SQLite） |

设计建议（见 03 文档 §3）：新建 `channels/web/voice/sip_controller.py`，
把 `VoiceCallController.ts` 的逻辑用 Python 重写。可以参考其状态图，
连状态名都不要改。

### 3.4 "全程不修改 channels/web/voice/ 任何代码"

这条做不到。至少 TTSClient 必须修（重连开销）。最小修法：
- 加 `TTSClient.synthesize_streaming()` 新方法，不重连，用 `chat_tts_text` 多句协议
- 保留旧 `synthesize()` 不动，浏览器路径继续用

---

## 4. 风险补充（提案没列）

| 风险 | 影响 | 缓解 |
|---|---|---|
| Doubao realtime/dialogue API 并发 quota 上限未知 | 高峰期会卡 | 提前发邮件确认；PoC 准备压测脚本 |
| Doubao SLA 未明确 | 电信级 99.95% 可能达不到 | 只承诺 SLA "best effort"；告知 Cinnox |
| Cinnox 录音/合规要求 | 法务风险 | 与 Cinnox BD 确认是否需要服务端录音留存 |
| TLS 5061 证书续签失败 | 通话整体不可用 | LE 自动续签 + cron 监控；备用 5060 UDP 通道 |
| 单点服务器宕机 | 通话全断 | 接受单点风险；用户已确认；后续上备份 |
| 公网弹性 IP 被 ISP 封禁（5060 是常见 SIP 攻击端口） | 服务降级 | 安全组只白名单 Cinnox 8 IP；fail2ban 监控 |
| 长通话 ASR / TTS WS 中断 | 通话被剪断 | jambonz 配 keepalive；controller 加 reconnect 逻辑 |
| 浏览器 voice 回归 | 同样的 voice 接的客户都受影响 | 严格不动 split-mode 旧路径；新增不修改 |

---

## 5. 替代方案对比（提案拒绝的方案，补充理由）

| 方案 | 优势 | 为什么不选 |
|---|---|---|
| Asterisk + ARI | 老牌、生态丰富 | ARI 需要把 RTP 转 stasis app，再桥接到 WS，链路比 jambonz 多一跳 |
| FreeSWITCH + mod_audio_fork | 同样支持 audio_fork over WS | 部署比 jambonz 重；社区文档不如 jambonz 直白 |
| Twilio Programmable Voice | SaaS 省心 | 需要把 voice 流量转 Twilio，多一跳延时 + 国内合规问题 |
| LiveKit SIP | 现代、面向 voice agent | 整个 LiveKit 栈是另一套 orchestration，引入会和现有 split-mode 冲突 |
| Pipecat | Python 原生、开箱即用 voice agent | 同上，整套编排框架，与 split-mode 正交 |
| 自研 SIP（pjsip / aiortc） | 完全可控 | 6 个月起步，工作量爆炸 |

**结论**：jambonz 仍是首选，提案这部分 ✅。

---

## 6. 评审小结（一句话）

提案的方向（jambonz + audio_fork → 现有 voice pipeline）正确，但
**sip_audio_route.py 草稿是按错误的架构理解写的**，需要换成"接 split
模式 + 新写服务端 controller"的写法；同时**TTSClient 重连开销必须先
解决**，否则延时目标做不到。具体修正后的实施计划见 03 文档。
