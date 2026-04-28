---
title: 现有 AutoService Voice 架构梳理
date: 2026-04-27
status: 现状记录（基于 origin/dev 5a351be）
---

# 现有 AutoService Voice 架构

> 看这份的目的：评估 SIP 接入提案前，先把"现在到底有什么"讲清楚。
> 提案里多次出现"复用现有 Doubao E2E 一体对话"这种描述，与代码不符。

## 1. 仓库位置

```
AutoService/
├── channels/web/voice/                ← 后端 voice gateway（FastAPI）
│   ├── asr_route.py                   /asr WS endpoint
│   ├── tts_route.py                   /tts WS endpoint
│   ├── asr_client.py                  Doubao ASR adapter
│   ├── tts_client.py                  Doubao TTS adapter
│   ├── doubao_client.py               底层 WS 客户端
│   ├── protocol.py                    Doubao 二进制协议编/解
│   └── config.py                      Doubao 凭据 + 会话模板
└── frontend/apps/customer-chat/src/voice/   ← 前端 controller（编排者）
    ├── VoiceCallController.ts         状态机 + 业务编排
    ├── asr-client.ts                  /asr WS client
    ├── tts-client.ts                  /tts WS client
    ├── audio-capture.ts               麦克风 → PCM 16k
    ├── audio-playback.ts              PCM 24k → 扬声器
    └── VoiceStatusBar.tsx             UI
```

## 2. 实际架构 = Split 模式（浏览器编排）

```
浏览器 (VoiceCallController)
   │
   ├── WS /asr ────► AutoService FastAPI ────► Doubao session A (只用 ASR 事件)
   │                                                  └─ LLM/TTS 事件被丢弃
   │
   ├── WS /tts ────► AutoService FastAPI ────► Doubao session B (用 say_hello 触发 TTS)
   │
   └── WS /ws/chat ──► AutoService cc_pool (LLM 真正对话)
```

**关键事实：浏览器是唯一的 orchestrator。** 后端 `/asr` 和 `/tts` 是
两个 stateless WebSocket proxy，互不感知，**没有"对话"概念**。每次
"用户说一句话 → AI 回一句话"的完整 turn，**前端要执行 5 步**：

1. 麦克风 PCM → `/asr` → 收到 `{"type":"final","text":"..."}`
2. 把文本插入聊天记录（用户气泡）
3. `/ws/chat` → cc_pool 跑 LLM → 收到 `{"type":"bot_text_delta","content":"..."}`
4. 文本插入聊天记录（机器人气泡）
5. `/tts` → `{"type":"speak","text":"<bot reply>"}` → 收到 PCM 24k → 播放

中间还有 **comfort-text 填充器**（ASR final 立即播 "稍等我查一下" 掩盖
LLM 延时）、状态机、barge-in（自动打断）— **全部在浏览器里**。

## 3. /asr 协议契约（提案要兼容这个）

**入向（浏览器 → 后端）：**
| 帧 | payload | 时机 |
|---|---|---|
| text | `{"type":"start"}` | 连接后第一帧 |
| binary | PCM-S16LE 16kHz mono 20ms 帧（640 字节） | mic 持续 |
| text | `{"type":"stop"}` | graceful disconnect |

**出向（后端 → 浏览器）：**
| 帧 | payload | 含义 |
|---|---|---|
| text | `{"type":"partial","text":"..."}` | ASR 中间结果 |
| text | `{"type":"final","text":"..."}` | **turn 结束信号** |
| text | `{"type":"speech_started"}` | VAD 检出说话开始（barge-in 信号） |
| text | `{"type":"error","message":"..."}` | 上游错误 |

## 4. /tts 协议契约

**入向（浏览器 → 后端）：**
| 帧 | payload |
|---|---|
| text | `{"type":"speak","text":"..."}` |
| text | `{"type":"abort"}` |

**出向（后端 → 浏览器）：**
| 帧 | payload |
|---|---|
| binary | PCM-S16LE 24kHz chunks（一边合成一边推） |
| text | `{"type":"done"}` |
| text | `{"type":"error","message":"..."}` |

## 5. 几个隐藏在代码里的"坑"

### 5.1 TTSClient 每次合成都要重连（300-500ms 损失）

`channels/web/voice/tts_client.py:67-93`：

```python
async def _reopen(self) -> None:
    """Doubao's `say_hello` event only triggers TTS once per WebSocket
    connection; `chat_tts_text` requires conversational context that's
    absent in our split-mode use case. Workaround: fully reconnect
    between synthesize calls. Cost: ~300-500ms per call."""
```

**影响**：每个对话 turn 的 TTS 合成都要先重连 Doubao，**单 turn 多
300-500ms 延时**。SIP 通话因为没有 comfort-text 缓冲（comfort 也是个
TTS 调用，自己也要重连），这个开销会直接表现为"用户说完之后机器人
迟迟不开口"。

### 5.2 ASRClient 把 LLM/TTS 事件全丢了

`channels/web/voice/asr_client.py:81-118` — `receive()` 只 yield
`ASR_RESPONSE` / `ASR_INFO` / `ASR_ENDED`，连接里 Doubao 同时返回的
`CHAT_RESPONSE` / `TTS_RESPONSE` 全部 drop。所以提案里说"Doubao
E2E 一体处理"在现有代码里**没有真正用到**——E2E API 只被当作 ASR
transport。

### 5.3 浏览器有完整的状态机，后端没有

`frontend/apps/customer-chat/src/voice/VoiceCallController.ts`（~180 LOC）
管：
- 状态：`idle | preparing | listening | thinking | speaking | ending | error`
- comfort-text 调度（"稍等..."）
- comfort 与正式回复的时序协调
- 自动 barge-in（监听 `speech_started` → 中断当前 TTS）
- 错误恢复
- 鉴权/CRM 上下文注入

**这一层在 SIP 入口一样需要**——只是 client 是 jambonz 而不是浏览器。
提案里完全没提这一层，按代码量估应该是 ~150-250 LOC Python（参照
TS 版本约 180 LOC）。

## 6. 采样率链路

| 节点 | 采样率 | 来源 |
|---|---|---|
| 麦克风 capture | 16 kHz | `audio-capture.ts` |
| /asr 入向 | 16 kHz PCM 16-bit LE | 协议 |
| Doubao ASR | 16 kHz | `config.py:28-37` `audio_info.sample_rate` |
| Doubao TTS 输出 | 24 kHz PCM 16-bit LE | `config.py:18-26` `audio_config` |
| /tts 出向 | 24 kHz | 协议 |
| 浏览器 playback | 24 kHz | `audio-playback.ts` |

注意 **24k vs 16k 不一致**——TTS 出向是 24k，ASR 入向是 16k。SIP 入口
做重采样链时这点要单独处理（jambonz audio_fork 通常希望两个方向都是
16k）。

## 7. 部署模式

dev 分支已经把 voice 内嵌进 `autoservice.web_gateway`：
- `make run-gateway` 单进程同时服务 `/ws/customer` + `/asr` + `/tts`
- `DOUBAO_APP_ID` + `DOUBAO_ACCESS_TOKEN` 从 `.env` 读
- vite dev proxy 已配 `/asr`、`/tts` 同源

**对 SIP 接入的影响**：新增 `/sip-audio` endpoint 直接挂在同一个
`web_gateway` FastAPI app 上即可，不需要额外进程。

## 8. 与提案对照表

| 提案声称 | 现实 | 影响 |
|---|---|---|
| "Doubao E2E 一体处理" | Split 模式，Doubao 只当 ASR/TTS 用 | 重写编排层 |
| "tts.send_text(GREETING_TEXT)" | API 不存在，是 `synthesize(text)` async generator | 重写 sip_audio_route.py |
| "tts.receive_audio()" | API 不存在 | 同上 |
| "tts.interrupt()" | API 不存在；浏览器靠重新创建 task 中断 | 需要新增 |
| "全程不修改 channels/web/voice/ 任何代码" | 至少要修 `TTSClient._reopen` 才能达到延时目标 | 最小代价：加一个 streaming TTS 复用模式 |
| "P50 < 1.2s" | 需要重连优化 + ASR 配置调优才能接近 | 见下一份文档 |
