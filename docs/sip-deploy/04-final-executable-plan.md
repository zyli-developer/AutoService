---
title: Cinnox SIP × AutoService Voice — 最终可执行方案（单文件版）
date: 2026-04-27
owner: yaosh
status: 可执行
target_branch: feat/sip-voice-cinnox
duration: 5 周
---

# 最终可执行方案

> 这是一份 self-contained 的实施方案，直接拿去就能开工。
> 背景与评审请见同目录 01 / 02 / 03 文档；本文不再展开。

---

## 0. 一页目标

**做什么：** 把 AutoService voice 暴露为 SIP endpoint，让 Cinnox 客户
通过电话号码可以与现有 voicebot 对话。

**怎么做：** 单 HK 服务器跑 jambonz，audio_fork 把 RTP 转成 PCM
WebSocket 推到 AutoService 新增的 `/sip-audio` endpoint；后端新增
`SipVoiceController` 编排 ASR → cc_pool → TTS。

**不做什么：** outbound、多区域、多智能体编排、录音留存。

**验收：** Cinnox 测试号能拨入并完成对话，P50 延时 < 2.5s，5 路并发
30 分钟稳定。

---

## 1. 架构

```
PSTN ──► Cinnox SBC (8 IPs) ──SIP/RTP──► HK 服务器 (单点)
                                              │
                            ┌─────────────────┴─────────────────┐
                            │                                     │
                            ▼                                     ▼
                  ┌────────────────────┐              ┌──────────────────────┐
                  │ jambonz (docker)    │              │ AutoService          │
                  │ ├─ drachtio (SIP)   │              │ web_gateway (FastAPI)│
                  │ ├─ rtpengine (RTP)  │ audio_fork   │                      │
                  │ ├─ sbc-in/out       │ ──WS PCM──►  │ /sip-audio (新)      │
                  │ └─ feature-server   │ 16k mono      │   └─ SipVoiceController│
                  └────────────────────┘ ◄──WS PCM──   │       ├─ ASRClient   │
                          ▲                            │       ├─ CCChatClient │
                          │                            │       │   └─ /ws/chat │
                          └────────RTP back to caller──│       └─ TTSClient   │
                                                       └──────────────────────┘
                                                                │
                                                                ▼
                                              ┌─────────────────────────────────┐
                                              │ Doubao realtime/dialogue API     │
                                              │ wss://openspeech.bytedance.com/  │
                                              └─────────────────────────────────┘
```

---

## 2. 已确定的决策

| # | 项 | 选择 | 备注 |
|---|---|---|---|
| 1 | 排期 | 5 周 | W1 基础设施 / W2 应用 / W3 自测 / W4 联调 / W5 上线 |
| 2 | 部署 | 单点 HK | 接受北京/JP 50-80ms 单向延时 |
| 3 | Cinnox 申请 | 仅 inbound | outbound 后续单独走 |
| 4 | 对话引擎 | 沿用 `/ws/chat` cc_pool | 不引入多智能体 |
| 5 | SIP 终结软件 | jambonz (自部署) | 非 jambonz Cloud |
| 6 | TTS 优化 | 新增 `synthesize_streaming`，旧 API 不动 | 修掉每次 reconnect 的 300-500ms 损失 |
| 7 | 重采样 | audioop（stdlib） | 不够快再换 scipy |
| 8 | LLM 调用方式 | 进程内同源 WebSocket loopback | 简单、零修改 |
| 9 | 编码 | PCMA / PCMU / OPUS（不 G729） | DTLS-SRTP + TLS 5061 |
| 10 | DTMF | RFC2833 + SIP Info | in-band 不用 |

---

## 3. 文件清单

```
AutoService/                              # branch: feat/sip-voice-cinnox
│
├── channels/web/voice/
│   ├── sip_audio_route.py    [NEW]      ~80 LOC, jambonz audio_fork WS endpoint
│   ├── sip_controller.py     [NEW]      ~220 LOC, 服务端编排状态机
│   ├── cc_chat_client.py     [NEW]      ~50 LOC, 进程内 /ws/chat client
│   ├── resample.py           [NEW]      ~30 LOC, 24k↔16k 重采样
│   ├── tts_client.py         [MODIFY]   +50 LOC, 加 synthesize_streaming
│   ├── asr_client.py                    不动
│   ├── doubao_client.py                 不动
│   ├── protocol.py                      不动
│   └── config.py             [MODIFY]   +10 LOC, 加 SIP_GREETING / COMFORT_POOL
│
├── channels/web/app.py       [MODIFY]   +5 LOC, 注册 /sip-audio
│
├── deploy/sip/               [NEW DIR]
│   ├── docker-compose.yml               jambonz 全栈
│   ├── .env.example                     凭据示例
│   ├── applications/
│   │   └── cinnox-voicebot.json         application 定义
│   ├── carriers/
│   │   └── cinnox-trunk.json            Cinnox 8 IP 白名单
│   ├── tls/
│   │   └── README.md                    LE 续签
│   ├── echo_ws.py                       W1 临时 echo 验证（W2 末删）
│   └── README.md                        部署 runbook
│
├── tests/voice/
│   ├── test_sip_audio_route.py   [NEW]
│   ├── test_sip_controller.py    [NEW]
│   ├── test_resample.py          [NEW]
│   └── test_tts_streaming.py     [NEW]
│
└── docs/
    ├── runbooks/sip-voice.md            [NEW W5]
    └── integrations/cinnox-voice-sip.md [NEW W5]
```

---

## 4. 5 周排期（每天可执行）

### Week 1 — 基础设施

| 天 | 任务 | 退出 |
|---|---|---|
| 1 | 申请 HK 4-core 8GB 弹性 IP；安全组：5060/5061 (UDP+TCP) + 10000-20000 UDP + 源 IP 白名单 Cinnox 8 IP | `nc -zv <ip> 5060` 通 |
| 2 | 部署 jambonz docker-compose（按 §6.1）；起服务 | `curl -k https://<ip>:3000/api/Accounts` 200 |
| 3 | 配 LE TLS 5061；jambonz 挂载证书 | `openssl s_client -connect <ip>:5061` 见证书 |
| 4 | 创建 application 指向临时 echo WS（按 §6.2、§6.3） | jambonz console 看到 application |
| 5 | 软电话自测 echo | Linphone 拨 `sip:test@<ip>:5061` 听到自己声音 |

### Week 2 — 应用层

| 天 | 任务 | 退出 |
|---|---|---|
| 1 | 起分支 `feat/sip-voice-cinnox`；写 `resample.py`（按 §5.4）+ 单元测试 | `pytest tests/voice/test_resample.py` 通过 |
| 2 | 写 `cc_chat_client.py`（按 §5.5）；本地 mock /ws/chat 跑通 | 单元测试通过 |
| 3 | 改 `tts_client.py` 加 `synthesize_streaming`（按 §5.6）；验证 chat_tts_text 协议 | 拿到 PCM 流，无 reconnect 延时 |
| 4 | 写 `sip_controller.py`（按 §5.3）核心状态机 + barge-in | 单元测试覆盖所有状态迁移 |
| 5 | 写 `sip_audio_route.py`（按 §5.2）+ 注册到 app.py；软电话端到端联调 | 拨号 → greeting → 对话 → 听到 cc_pool 回复 |

### Week 3 — 自测稳定性

| 天 | 任务 | 退出 |
|---|---|---|
| 1 | ASR `end_smooth_window_ms` 从 1500 调到 800 | turn 切换感觉更快 |
| 2 | 接入 Prometheus metrics（按 §7） | grafana 看到 5 个核心指标 |
| 3 | barge-in 端到端验证 | 用户开口 < 200ms 停 TTS |
| 4 | 30 分钟连续单路通话 | 无内存泄漏、无 socket 泄漏 |
| 5 | 5 路并发（sipp 脚本 §8） | 全部跑完，P50 < 2.0s |

### Week 4 — Cinnox 联调

| 天 | 任务 | 退出 |
|---|---|---|
| 1 | 提交 SIP_Interconnection_Form（按 §6.4） | 邮件已发 Cinnox BD |
| 2 | Cinnox 配 trunk + 测试号下发；我方更新 carriers | OPTIONS ping 双向通 |
| 3 | 实拨测试号 | 一个完整对话跑通 |
| 4 | codec 协商抓包 + 北京/JP/SG 路径测 | 至少 1 个区域客户端通过 |
| 5 | 长通话稳定（30min × 3） | 无掉线 |

### Week 5 — 生产化

| 天 | 任务 | 退出 |
|---|---|---|
| 1 | systemd / docker-compose 自启脚本 | 服务器 reboot 后自动恢复 |
| 2 | 故障演练：杀 jambonz / 杀 backend / 网络抖动 | 5 分钟内恢复 |
| 3 | 写 runbook + 客户接入文档 | docs 文件 commit |
| 4 | 录 demo 视频 | mp4 文件给 BD |
| 5 | 写 PoC 总结 + PR 合并 dev | PR review 通过 |

---

## 5. 完整代码骨架（可直接复制起步）

### 5.1 channels/web/app.py 改动

```python
# 在现有 from ... import 之后加
from channels.web.voice.sip_audio_route import sip_audio_endpoint

# 在现有 endpoint 注册之后加
@app.websocket("/sip-audio")
async def sip_audio_ws(ws: WebSocket):
    await sip_audio_endpoint(ws)
```

### 5.2 channels/web/voice/sip_audio_route.py（新）

```python
"""SIP audio gateway — bridges jambonz audio_fork → AutoService voice pipeline.

Wire protocol (jambonz audio_fork):
  - Text frame (1st):  {"event":"start","callSid":"...","from":"...","to":"..."}
  - Binary frames in:  PCM 16-bit LE 16kHz mono
  - Binary frames out: PCM 16-bit LE 16kHz mono (jambonz resamples to PCMA 8k)
  - Text frame (last): {"event":"stop"}

Thin adapter. All conversation logic lives in sip_controller.SipVoiceController.
"""
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .sip_controller import SipVoiceController

log = logging.getLogger(__name__)


async def sip_audio_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    log.info("[/sip-audio] jambonz connected")

    controller: SipVoiceController | None = None
    try:
        first = await ws.receive_text()
        try:
            meta = json.loads(first)
        except json.JSONDecodeError:
            await ws.send_json({"error": "expected JSON start frame"})
            return
        if meta.get("event") != "start":
            await ws.send_json({"error": "first frame must be event=start"})
            return

        controller = SipVoiceController(
            call_sid=meta.get("callSid", "unknown"),
            caller=meta.get("from", "unknown"),
            callee=meta.get("to", "unknown"),
            ws=ws,
        )
        log.info("[/sip-audio] call sid=%s from=%s to=%s",
                 controller.call_sid, controller.caller, controller.callee)
        await controller.run()
    except WebSocketDisconnect:
        log.info("[/sip-audio] jambonz disconnected")
    except Exception:
        log.exception("[/sip-audio] error")
    finally:
        if controller is not None:
            await controller.shutdown()
        if ws.client_state != WebSocketState.DISCONNECTED:
            try:
                await ws.close()
            except Exception:
                pass
        log.info("[/sip-audio] cleanup done")
```

### 5.3 channels/web/voice/sip_controller.py（新，核心）

```python
"""Server-side voice controller for SIP calls.

Mirrors frontend/apps/customer-chat/src/voice/VoiceCallController.ts.
States, comfort scheduling, and barge-in semantics are intentionally
identical so behavior matches the existing browser experience.
"""
import asyncio
import enum
import logging
import random

from fastapi import WebSocket

from .asr_client import ASRClient
from .cc_chat_client import CCChatClient
from .config import COMFORT_POOL, SIP_GREETING
from .resample import resample_24k_to_16k
from .tts_client import TTSClient

log = logging.getLogger(__name__)


class State(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ENDING = "ending"


class SipVoiceController:
    def __init__(self, call_sid: str, caller: str, callee: str, ws: WebSocket):
        self.call_sid = call_sid
        self.caller = caller
        self.callee = callee
        self.ws = ws
        self.state = State.IDLE

        self.asr: ASRClient | None = None
        self.tts: TTSClient | None = None
        self.cc: CCChatClient | None = None

        self._tts_task: asyncio.Task | None = None
        self._tasks: list[asyncio.Task] = []
        self._resample_key = call_sid  # per-call resample state

    async def run(self) -> None:
        # 1. Bring up upstream connections
        self.asr = ASRClient()
        await self.asr.connect()
        self.tts = TTSClient()
        await self.tts.connect()
        self.cc = CCChatClient(call_sid=self.call_sid, caller=self.caller)
        await self.cc.connect()

        # 2. Greeting (state stays IDLE during)
        await self._speak(SIP_GREETING)
        self.state = State.LISTENING

        # 3. Bridge audio + drive turns
        self._tasks = [
            asyncio.create_task(self._pump_jambonz_to_asr(), name="jambonz->asr"),
            asyncio.create_task(self._handle_asr_events(), name="asr-events"),
        ]
        try:
            await asyncio.wait(self._tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in self._tasks:
                if not t.done():
                    t.cancel()

    async def _pump_jambonz_to_asr(self) -> None:
        """Forward inbound PCM frames from jambonz to Doubao ASR."""
        try:
            async for chunk in self.ws.iter_bytes():
                if self.asr:
                    await self.asr.send_audio(chunk)
        except Exception:
            log.exception("[%s] jambonz->asr pump failed", self.call_sid)

    async def _handle_asr_events(self) -> None:
        """React to ASR events: detect turn-end, run LLM, speak reply."""
        try:
            async for event in self.asr.receive():
                evt = event.get("type")

                if evt == "input_audio_buffer.speech_started":
                    if self.state == State.SPEAKING and self._tts_task:
                        log.info("[%s] barge-in: cancelling TTS", self.call_sid)
                        self._tts_task.cancel()
                        self._tts_task = None
                        self.state = State.LISTENING

                elif evt == "conversation.item.input_audio_transcription.completed":
                    text = event.get("transcript", "").strip()
                    if not text:
                        continue
                    log.info("[%s] user: %s", self.call_sid, text)
                    self.state = State.THINKING

                    # comfort fire-and-forget (don't await)
                    comfort = random.choice(COMFORT_POOL)
                    asyncio.create_task(self._speak(comfort), name="comfort")

                    # Call cc_pool
                    try:
                        reply = await self.cc.send(text)
                    except Exception as e:
                        log.exception("[%s] cc_pool error", self.call_sid)
                        reply = "抱歉，我这边出了点问题，请稍后再说。"

                    log.info("[%s] bot: %s", self.call_sid, reply[:60])
                    await self._speak(reply)
                    self.state = State.LISTENING

                elif evt == "error":
                    log.error("[%s] asr error: %s", self.call_sid, event.get("error"))
        except Exception:
            log.exception("[%s] asr events handler failed", self.call_sid)

    async def _speak(self, text: str) -> None:
        """Synthesize and stream PCM to jambonz. Cancels any in-flight TTS."""
        if self._tts_task and not self._tts_task.done():
            self._tts_task.cancel()
            try:
                await self._tts_task
            except (asyncio.CancelledError, Exception):
                pass

        self._tts_task = asyncio.create_task(self._do_speak(text), name="tts")
        try:
            await self._tts_task
        except asyncio.CancelledError:
            pass

    async def _do_speak(self, text: str) -> None:
        prev_state = self.state
        self.state = State.SPEAKING
        try:
            async for pcm_24k in self.tts.synthesize_streaming(text):
                pcm_16k = resample_24k_to_16k(pcm_24k, key=self._resample_key)
                await self.ws.send_bytes(pcm_16k)
        except asyncio.CancelledError:
            log.info("[%s] tts cancelled", self.call_sid)
            raise
        except Exception:
            log.exception("[%s] tts failed", self.call_sid)
        finally:
            if self.state == State.SPEAKING:
                self.state = prev_state if prev_state != State.IDLE else State.LISTENING

    async def shutdown(self) -> None:
        self.state = State.ENDING
        for c in (self.asr, self.tts, self.cc):
            if c is None:
                continue
            try:
                await c.close()
            except Exception:
                log.exception("[%s] close error", self.call_sid)
```

### 5.4 channels/web/voice/resample.py（新）

```python
"""Audio resampling utility for SIP voice path.

Doubao TTS outputs 24kHz; jambonz audio_fork expects 16kHz mono on the
return leg. We use stdlib audioop which is fast enough for 16k↔24k mono.
If profiling shows > 5ms per frame, switch to scipy.signal.resample_poly.
"""
import audioop

# Per-call ratecv state. Without preserving state across chunks, you get
# audible clicks at 20ms boundaries.
_state: dict[str, tuple] = {}


def resample_24k_to_16k(pcm_24k: bytes, key: str) -> bytes:
    """24kHz mono S16LE → 16kHz mono S16LE."""
    state = _state.get(key)
    out, new_state = audioop.ratecv(pcm_24k, 2, 1, 24000, 16000, state)
    _state[key] = new_state
    return out


def reset(key: str) -> None:
    """Drop ratecv state for a finished call."""
    _state.pop(key, None)
```

### 5.5 channels/web/voice/cc_chat_client.py（新）

```python
"""Internal client to AutoService /ws/chat (cc_pool LLM)."""
import json
import logging

import websockets

log = logging.getLogger(__name__)

CC_CHAT_URL = "ws://127.0.0.1:8000/ws/chat"


class CCChatClient:
    def __init__(self, call_sid: str, caller: str):
        self.call_sid = call_sid
        self.caller = caller
        self.ws = None

    async def connect(self) -> None:
        self.ws = await websockets.connect(CC_CHAT_URL, ping_interval=None)
        # If /ws/chat needs auth or session init, send it here.
        # For now, default tenant context comes from the loopback.

    async def send(self, user_text: str) -> str:
        if self.ws is None:
            raise RuntimeError("CCChatClient not connected")
        await self.ws.send(json.dumps({
            "type": "user_text_submit",
            "text": user_text,
            "metadata": {"channel": "sip", "caller": self.caller, "call_sid": self.call_sid},
        }))
        chunks: list[str] = []
        async for raw in self.ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            t = msg.get("type")
            if t == "bot_text_delta":
                chunks.append(msg.get("content", ""))
            elif t == "done":
                break
            elif t == "error":
                raise RuntimeError(msg.get("message", "cc_pool error"))
        return "".join(chunks)

    async def close(self) -> None:
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
```

### 5.6 channels/web/voice/tts_client.py 改动（追加，旧不动）

```python
# 在文件末尾追加；现有 synthesize() 保持不变（浏览器路径继续用）

class TTSClient:
    # ... 现有代码 ...

    async def synthesize_streaming(self, text: str):
        """Streaming TTS without per-call reconnect.

        Uses Doubao chat_tts_text protocol so multiple calls share one
        WebSocket session. Saves the 300-500ms reconnect cost that
        synthesize() pays via _reopen() between calls.

        NOTE: chat_tts_text expects start/end flags; we send both true
        for one-shot. If Doubao requires LLM context first, fall back
        to synthesize() (with the reconnect penalty).
        """
        if self._receiver is None:
            raise RuntimeError("TTSClient not connected")

        log.info("TTS streaming: %r", text[:60])
        await self._doubao.send_chat_tts_text(text, start=True, end=True)

        async for frame in self._receiver:
            event = frame.get("event")
            payload = frame.get("payload_msg")

            if event == EVENT_TTS_RESPONSE and isinstance(payload, bytes):
                yield payload
            elif event == EVENT_TTS_ENDED:
                return
            elif frame.get("message_type") == "SERVER_ERROR":
                raise RuntimeError(
                    f"Doubao TTS error {frame.get('code')}: {payload}"
                )
```

### 5.7 channels/web/voice/config.py 改动（追加）

```python
# 在文件末尾追加

SIP_GREETING = "您好，欢迎致电 OpenClaw 客服，请问有什么可以帮您？"

COMFORT_POOL = [
    "稍等，我帮您查一下。",
    "好的，让我想想。",
    "嗯，我看看。",
]

# Tighter VAD window for telephony — longer windows feel laggy on a phone
SIP_ASR_OVERRIDES = {
    "asr": {
        "extra": {
            "end_smooth_window_ms": 800,
        },
    },
}
```

---

## 6. 部署配置

### 6.1 deploy/sip/docker-compose.yml

```yaml
# Reference: https://www.jambonz.org/docs/installation/docker
# This is a starting template. Pin image versions in production.
version: "3.8"
services:
  drachtio:
    image: drachtio/drachtio-server:latest
    network_mode: host
    volumes:
      - ./drachtio.conf.xml:/etc/drachtio.conf.xml
    restart: unless-stopped

  rtpengine:
    image: drachtio/rtpengine:latest
    network_mode: host
    environment:
      - PUBLIC_IP=${PUBLIC_IP}
    restart: unless-stopped

  jambonz-api-server:
    image: jambonz/jambonz-api-server:latest
    ports: ["3000:3000"]
    environment:
      - JAMBONES_MYSQL_HOST=mysql
      - JAMBONES_REDIS_HOST=redis
      - JWT_SECRET=${JWT_SECRET}
    depends_on: [mysql, redis]
    restart: unless-stopped

  jambonz-feature-server:
    image: jambonz/feature-server:latest
    network_mode: host
    environment:
      - JAMBONES_MYSQL_HOST=127.0.0.1
      - JAMBONES_REDIS_HOST=127.0.0.1
      - DRACHTIO_HOST=127.0.0.1
      - RTPENGINE_HOST=127.0.0.1
    depends_on: [drachtio, rtpengine]
    restart: unless-stopped

  jambonz-sbc-inbound:
    image: jambonz/sbc-inbound:latest
    network_mode: host
    environment:
      - DRACHTIO_HOST=127.0.0.1
      - JAMBONES_MYSQL_HOST=127.0.0.1
    depends_on: [drachtio, mysql]
    restart: unless-stopped

  jambonz-sbc-outbound:
    image: jambonz/sbc-outbound:latest
    network_mode: host
    environment:
      - DRACHTIO_HOST=127.0.0.1
      - JAMBONES_MYSQL_HOST=127.0.0.1
    depends_on: [drachtio, mysql]
    restart: unless-stopped

  mysql:
    image: mysql:8
    environment:
      - MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
      - MYSQL_DATABASE=jambones
    volumes: [mysql_data:/var/lib/mysql]
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    restart: unless-stopped

volumes:
  mysql_data:
```

### 6.2 deploy/sip/applications/cinnox-voicebot.json

```json
{
  "name": "cinnox-voicebot",
  "call_hook": {
    "url": "wss://<host>/sip-audio",
    "method": "GET"
  },
  "speech_synthesis_vendor": "default",
  "speech_recognizer_vendor": "default",
  "audio_fork": {
    "ws_url": "wss://<host>/sip-audio",
    "sample_rate": 16000,
    "mix_type": "mono"
  }
}
```

> jambonz application 通过 admin API 或 console 创建。本 JSON 是
> 配置参考；实际通过 `curl -X POST https://<host>:3000/api/Applications`
> 注册（W1 D4）。

### 6.3 deploy/sip/carriers/cinnox-trunk.json

```json
{
  "name": "cinnox-trunk",
  "vendor": "Cinnox",
  "is_active": true,
  "smpp_inbound_password": null,
  "register_username": null,
  "tech_prefix": null,
  "diversion": null,
  "sip_gateways": [
    {"ipv4": "101.200.218.11",  "port": 5060, "inbound": true, "outbound": false, "netmask": 32},
    {"ipv4": "47.94.144.113",   "port": 5060, "inbound": true, "outbound": false, "netmask": 32},
    {"ipv4": "18.163.244.252",  "port": 5060, "inbound": true, "outbound": false, "netmask": 32},
    {"ipv4": "18.163.63.169",   "port": 5060, "inbound": true, "outbound": false, "netmask": 32},
    {"ipv4": "3.115.111.125",   "port": 5060, "inbound": true, "outbound": false, "netmask": 32},
    {"ipv4": "35.76.7.104",     "port": 5060, "inbound": true, "outbound": false, "netmask": 32},
    {"ipv4": "3.1.89.69",       "port": 5060, "inbound": true, "outbound": false, "netmask": 32},
    {"ipv4": "122.248.201.73",  "port": 5060, "inbound": true, "outbound": false, "netmask": 32}
  ]
}
```

> Cinnox 8 个 SBC IP 全部白名单。注意 `outbound: false` —— PoC 阶段
> 只接 inbound。outbound 字段保留以便后续启用。

### 6.4 Cinnox SIP_Interconnection_Form 填法

| 字段 | 值 |
|---|---|
| Service domain | 留默认 `Internal.cinnox.com` |
| Service ID | 留空（Cinnox 团队会给） |
| Contact Email | `<工程对接邮箱>` |
| Requested Service | ☑ **SIP In only** |
| Remark / Use case | "AI voicebot powered by AutoService voice gateway with Volcengine Doubao realtime dialogue API. Self-hosted jambonz SBC, HK region." |
| Signaling IP | `<HK 公网 IP>` |
| Media IP | `<同上>` |
| Inbound Signaling Port | 5061 (TLS) + 5060 (UDP) |
| Support OPTIONS Ping | ☑ YES |
| Codec | ☑ PCMU ☑ PCMA ☑ OPUS ☐ G729 |
| Encryption | ☑ YES (DTLS-SRTP) |
| DTMF | ☑ RFC2833 ☑ SIP Info |
| Toll-Free 号码 | 测试阶段从 Cinnox 借 1 个 HK 号 |
| Genesys Domain | 留空 |

---

## 7. 监控与可观测性

### 7.1 关键 metrics（Prometheus）

| metric | 类型 | 含义 |
|---|---|---|
| `sip_active_calls` | gauge | 当前活跃通话数 |
| `sip_call_duration_seconds` | histogram | 通话时长 |
| `sip_asr_first_final_ms` | histogram | 用户开口到 ASR final 的延时 |
| `sip_cc_first_byte_ms` | histogram | ASR final 到 cc_pool 首字 |
| `sip_tts_first_byte_ms` | histogram | TTS 调用到首块 PCM |
| `sip_e2e_response_ms` | histogram | 用户结束说话到机器人开口 |
| `sip_doubao_reconnects_total` | counter | Doubao session 重连次数 |
| `sip_barge_in_total` | counter | barge-in 触发次数 |

### 7.2 日志格式

每条 log 必须含 `call_sid`，方便单通话全链路 trace：

```
[<call_sid>] state=listening user="iPhone15 多少钱"
[<call_sid>] cc_pool first_byte=320ms
[<call_sid>] tts first_byte=180ms
[<call_sid>] state=speaking
[<call_sid>] barge-in -> cancel tts
```

### 7.3 grafana 看板（W5）

- 在线通话数（实时）
- P50/P95/P99 e2e 延时
- 5 分钟 Doubao 重连率（> 1/min 报警）
- 通话失败率
- jambonz CPU / 内存

---

## 8. 验证脚本

### 8.1 软电话单路 echo（W1 D5）

```bash
linphone-cli -c sip:test@<host>:5061
# 预期：听到自己的声音
```

### 8.2 完整对话（W2 D5）

```bash
make run-gateway  # 起 AutoService
linphone-cli -c sip:test@<host>:5061
# 预期：
#   1. 听到 greeting
#   2. 自己说 "iPhone15 多少钱"
#   3. 听到 cc_pool 答复
```

### 8.3 5 路并发压测（W3 D5）

```bash
# sipp 脚本（保存为 deploy/sip/test/sipp_uac.xml）
sipp -sf sipp_uac.xml -m 5 -r 1 <host>:5061 -t tn
# 预期：
#   - 5 路全部接通
#   - 各路通话音频不串扰
#   - P50 e2e < 2.0s
```

### 8.4 30 分钟稳定性（W3 D4 / W4 D5）

```bash
# 软电话保持通话 30 分钟，每分钟说一句话
# 预期：
#   - 无掉线
#   - jambonz 内存增长 < 100MB
#   - AutoService 进程内存增长 < 50MB
#   - 无 socket 泄漏 (lsof -p <pid> | wc -l 稳定)
```

---

## 9. 回滚方案

| 失败场景 | 回滚动作 |
|---|---|
| W1 jambonz 部署不通 | 检查云厂商 5060 端口；最差换云厂商 |
| W2 chat_tts_text 不工作 | 退回 `synthesize()` + reconnect，承担延时 |
| W2 进程内 /ws/chat loopback 失败 | 改 UNIX socket；最差直接函数调用 cc_pool |
| W3 audioop 性能不够 | 换 scipy.signal.resample_poly |
| W3 P50 > 3s | 接受降级；改 SLA 承诺为 P50 < 3.5s |
| W4 Cinnox trunk 配不通 | 同时申请备用方案（直接 SIP 软电话联调） |
| W4 大延时区域不可用 | 接受单点限制；记录到 follow-up |
| 任何阶段单点服务器宕机 | PoC 阶段接受；生产前加备机 |

---

## 10. 验收 Checklist（W5 末打勾）

### 功能
- [ ] Cinnox 测试号能拨入
- [ ] 听到 greeting
- [ ] 用户说话能被识别（ASR final 准确率 > 90%）
- [ ] cc_pool 回复能正常播放
- [ ] barge-in 工作（用户开口 < 200ms 停 TTS）
- [ ] 主动挂断 / 对方挂断都能正常清理资源

### 性能
- [ ] P50 e2e 延时 < 2.5s
- [ ] P95 e2e 延时 < 4.0s
- [ ] 5 路并发 30 分钟无故障
- [ ] 长通话 30 分钟无掉线
- [ ] 无内存泄漏（30min 增长 < 50MB）
- [ ] 无 socket 泄漏

### 工程
- [ ] 单元测试 + 集成测试 ≥ 90% 通过
- [ ] grafana 看板 5 个核心指标可见
- [ ] runbook 写完
- [ ] 客户接入文档写完
- [ ] systemd / docker-compose 自启验证
- [ ] 故障演练 3 个场景全部 5 分钟内恢复
- [ ] PR 合并到 dev

### 交付
- [ ] demo 视频 mp4 给 BD
- [ ] PoC 总结文档
- [ ] 已知问题 / follow-up 列表

---

## 11. Follow-ups（PoC 后单独 issue）

1. **Outbound 外呼** — 申请 Cinnox SIP Out 配额；jambonz 加 outbound application
2. **多区域部署** — 北京 + JP 各加一个备机；GeoDNS 路由
3. **接入 customer-chat 完整 pipeline** — multi-bubble / instant-ack / 评分
4. **30 路并发生产容量** — 服务器扩容 + Doubao quota 协商
5. **录音 / 合规留存** — 与 Cinnox / 法务确认后实现
6. **多租户 voice 隔离** — 按主叫号码或 SIP header 路由到不同 cc_pool tenant
7. **服务端 controller 抽出共用** — 与未来其它 SIP carrier 共用（Twilio / 国内电信）

---

## 12. 与现有 voice 路径的兼容性

**严格不动的部分**（保护浏览器路径）：
- `channels/web/voice/asr_client.py`
- `channels/web/voice/asr_route.py`
- `channels/web/voice/doubao_client.py`
- `channels/web/voice/protocol.py`
- `channels/web/voice/tts_route.py`
- `channels/web/voice/tts_client.py` 现有的 `synthesize()` 方法
- `channels/web/voice/config.py` 现有的 `START_SESSION_CONFIG` / `GREETING_TEXT` / `COMFORT_TEXT`
- 所有 frontend 代码

**只新增 / 追加**：
- 新文件：`sip_audio_route.py`, `sip_controller.py`, `cc_chat_client.py`, `resample.py`
- `tts_client.py` 追加 `synthesize_streaming()` 方法
- `config.py` 追加 `SIP_GREETING`, `COMFORT_POOL`, `SIP_ASR_OVERRIDES`
- `app.py` 追加 `/sip-audio` endpoint 注册

**这意味着**：浏览器 voice 完全不会回归。SIP 路径出问题随时可以
去注册 endpoint 而不影响其它流量。
