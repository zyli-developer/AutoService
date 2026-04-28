---
title: Cinnox SIP 接入 — 5 周可执行 PoC 计划
date: 2026-04-27
owner: yaosh
status: 待启动
---

# Cinnox SIP × AutoService Voice — 5 周 PoC 计划

> 本计划在 02 文档评审基础上写成，已采纳的决策：
> 5 周排期 / 单点 HK 部署 / 只申请 inbound / 沿用现有 `/ws/chat` cc_pool。

## 0. 总体里程碑

| Week | 主题 | 退出条件（可验证） |
|---|---|---|
| W1 | 基础设施 | 软电话拨打 jambonz 公网 IP，audio_fork 把 PCM 推到本地 echo WS |
| W2 | 服务端 controller + adapter | `make run-gateway` 后软电话拨打能跑完一整轮对话 |
| W3 | 性能调优 + 自测稳定性 | 单机 5 路并发 30 分钟连续通话，P50 延时 < 2.0s |
| W4 | Cinnox 联调 | Cinnox 测试号能拨入并跑完对话，延时合规 |
| W5 | 生产化 + demo | 监控 + runbook + demo 视频 + 客户接入文档 |

## 1. Week 1 — 基础设施（5 天）

### 1.1 任务

| # | 任务 | 输出 |
|---|---|---|
| 1.1.1 | 申请 HK 区云服务器（4-core 8GB，公网弹性 IP） | IP 记录到 `deploy/sip/README.md` |
| 1.1.2 | 安全组配置 | 5060/5061 (UDP+TCP)、10000-20000 (UDP)，源 IP 白名单 Cinnox 8 个 SBC |
| 1.1.3 | 部署 jambonz docker-compose | `docker compose up -d` 全栈起来 |
| 1.1.4 | 配 Let's Encrypt + TLS 5061 | `openssl s_client -connect host:5061` 通 |
| 1.1.5 | 创建 jambonz application: `cinnox-voicebot` | audio_fork verb 指向本地 echo WS |
| 1.1.6 | 写本地 echo WS（验证 audio_fork 协议） | 收到 PCM 直接回推，软电话听到自己声音 |
| 1.1.7 | 软电话自测 | Linphone 拨 `sip:test@<jambonz_ip>:5061`，能听到 echo |

### 1.2 文件结构（新增）

```
AutoService/
└── deploy/sip/
    ├── docker-compose.yml          # jambonz 全栈
    ├── .env.example
    ├── applications/
    │   └── cinnox-voicebot.json    # application 定义
    ├── carriers/
    │   └── cinnox-trunk.json       # Cinnox 8 IP 白名单
    ├── tls/
    │   └── README.md               # LE 续签说明
    ├── echo_ws.py                  # W1 临时 echo 服务，验证完删
    └── README.md                   # 部署 runbook
```

### 1.3 W1 退出条件

```bash
# 1. jambonz 健康
curl -k https://<host>:3000/api/Accounts | jq .

# 2. SIP OPTIONS ping 通
sipsak -s sip:<host>:5061 -O 1

# 3. echo 通话
linphone-cli -c sip:test@<host>:5061
# 听到自己声音 → 通过
```

### 1.4 W1 风险

| 风险 | 缓解 |
|---|---|
| 云厂商 5060/5061 端口出口被默认封 | 选 AWS / Azure / GCP 之类已知开放的；阿里云港区一般 OK；提前 ping 测 |
| LE 证书 jambonz 容器挂载方式不熟 | 提前看 jambonz 官方 `docs/installation` |
| audio_fork PCM 格式不是 16k mono S16LE | 抓包 wireshark 验证；jambonz 配置里强制 |

---

## 2. Week 2 — 服务端 controller + adapter（5 天）

### 2.1 设计原则（来自 02 文档）

1. **不动 ASRClient / DoubaoClient / protocol** —— 浏览器路径要继续工作
2. **TTSClient 加新方法 `synthesize_streaming`** —— 不重连版本，仅 SIP 路径用
3. **新增两个文件**：
   - `channels/web/voice/sip_controller.py` — 服务端编排（对应浏览器的 VoiceCallController.ts）
   - `channels/web/voice/sip_audio_route.py` — jambonz audio_fork WS endpoint

### 2.2 sip_audio_route.py 骨架（修正版）

```python
"""SIP audio gateway — bridges jambonz audio_fork → AutoService voice pipeline.

Wire protocol (jambonz audio_fork):
  - Text frame (1st):  {"event":"start","callSid":"...","from":"...","to":"..."}
  - Binary frames:      PCM 16-bit LE 16kHz mono in
  - Binary frames out:  PCM 16-bit LE 16kHz mono back to jambonz
  - Text frame (last):  {"event":"stop"}

This file is a THIN adapter. All conversation orchestration lives in
sip_controller.SipVoiceController (mirrors browser VoiceCallController).
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
        meta = json.loads(first)
        if meta.get("event") != "start":
            await ws.send_json({"error": "expected start event"})
            return

        controller = SipVoiceController(
            call_sid=meta.get("callSid"),
            caller=meta.get("from"),
            callee=meta.get("to"),
            ws=ws,
        )
        await controller.run()  # blocks until call ends or error
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
```

### 2.3 sip_controller.py 骨架（核心新代码）

```python
"""Server-side voice controller for SIP calls.

Mirrors frontend/apps/customer-chat/src/voice/VoiceCallController.ts.
States, comfort scheduling, and barge-in semantics are intentionally
kept identical so behavior matches the browser experience.
"""
import asyncio
import enum
import logging
import random

from fastapi import WebSocket

from .asr_client import ASRClient
from .config import COMFORT_TEXT, GREETING_TEXT
from .tts_client import TTSClient
from .resample import resample_24k_to_16k  # new util in W2
from .cc_chat_client import CCChatClient   # new thin client to /ws/chat

log = logging.getLogger(__name__)

COMFORT_POOL = ["稍等，我帮你查一下", "嗯，让我想一下", "好的"]


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

    async def run(self) -> None:
        self.asr = ASRClient()
        await self.asr.connect()
        self.tts = TTSClient()
        await self.tts.connect()
        self.cc = CCChatClient(call_sid=self.call_sid)
        await self.cc.connect()

        # Greeting
        await self._speak(GREETING_TEXT)
        self.state = State.LISTENING

        # Three concurrent loops
        self._tasks = [
            asyncio.create_task(self._pump_jambonz_to_asr()),
            asyncio.create_task(self._handle_asr_events()),
        ]
        try:
            done, pending = await asyncio.wait(
                self._tasks, return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for t in self._tasks:
                t.cancel()

    async def _pump_jambonz_to_asr(self) -> None:
        async for chunk in self.ws.iter_bytes():
            await self.asr.send_audio(chunk)

    async def _handle_asr_events(self) -> None:
        async for event in self.asr.receive():
            evt = event.get("type")
            if evt == "input_audio_buffer.speech_started":
                # barge-in: cancel any speaking
                if self.state == State.SPEAKING and self._tts_task:
                    self._tts_task.cancel()
                    self._tts_task = None
                    self.state = State.LISTENING
            elif evt == "conversation.item.input_audio_transcription.completed":
                text = event["transcript"]
                self.state = State.THINKING
                # comfort fire-and-forget
                comfort = random.choice(COMFORT_POOL)
                asyncio.create_task(self._speak(comfort))
                # call cc_pool LLM
                reply = await self.cc.send(text)
                # speak formal reply
                await self._speak(reply)
                self.state = State.LISTENING

    async def _speak(self, text: str) -> None:
        if self._tts_task and not self._tts_task.done():
            self._tts_task.cancel()
        self._tts_task = asyncio.create_task(self._do_speak(text))
        try:
            await self._tts_task
        except asyncio.CancelledError:
            pass

    async def _do_speak(self, text: str) -> None:
        self.state = State.SPEAKING
        async for pcm_24k in self.tts.synthesize_streaming(text):  # NEW method (W2.4)
            pcm_16k = resample_24k_to_16k(pcm_24k)
            await self.ws.send_bytes(pcm_16k)

    async def shutdown(self) -> None:
        for c in (self.asr, self.tts, self.cc):
            if c:
                try:
                    await c.close()
                except Exception:
                    pass
```

### 2.4 TTSClient 改造（新方法，旧不动）

```python
# channels/web/voice/tts_client.py — 追加，不动现有 synthesize()

class TTSClient:
    async def synthesize_streaming(self, text: str) -> AsyncGenerator[bytes, None]:
        """Streaming synthesis without per-call reconnect.

        Uses Doubao chat_tts_text protocol so multiple synthesize calls
        share one Doubao session. Saves the 300-500ms reconnect cost
        that synthesize() pays via _reopen().

        TODO(W2.4): verify chat_tts_text actually works without LLM
        context — we may need to inject a fake assistant message first.
        """
        await self._doubao.send_chat_tts_text(text, start=True, end=True)
        async for frame in self._receiver:
            event = frame.get("event")
            payload = frame.get("payload_msg")
            if event == EVENT_TTS_RESPONSE and isinstance(payload, bytes):
                yield payload
            elif event == EVENT_TTS_ENDED:
                break
            elif frame.get("message_type") == "SERVER_ERROR":
                raise RuntimeError(f"TTS error: {payload}")
```

### 2.5 cc_chat_client.py 骨架（连内部 /ws/chat）

```python
"""Internal WS client to AutoService /ws/chat (cc_pool LLM)."""
import json
import websockets

class CCChatClient:
    def __init__(self, call_sid: str):
        self.call_sid = call_sid
        self.ws = None

    async def connect(self) -> None:
        # Same-process loopback. Use UNIX socket if cross-process.
        self.ws = await websockets.connect("ws://127.0.0.1:8000/ws/chat")
        # TODO: send tenant/voice context

    async def send(self, user_text: str) -> str:
        await self.ws.send(json.dumps({
            "type": "user_text_submit", "text": user_text,
        }))
        chunks = []
        async for raw in self.ws:
            msg = json.loads(raw)
            if msg.get("type") == "bot_text_delta":
                chunks.append(msg["content"])
            elif msg.get("type") == "done":
                break
        return "".join(chunks)

    async def close(self) -> None:
        if self.ws:
            await self.ws.close()
```

### 2.6 重采样工具

```python
# channels/web/voice/resample.py — 新增
import audioop  # stdlib, fast enough for 16k↔24k mono

# audioop.ratecv state across chunks
_state_24_to_16 = {}

def resample_24k_to_16k(pcm_24k: bytes, key: str = "default") -> bytes:
    """24kHz mono S16LE → 16kHz mono S16LE."""
    state = _state_24_to_16.get(key)
    out, new_state = audioop.ratecv(pcm_24k, 2, 1, 24000, 16000, state)
    _state_24_to_16[key] = new_state
    return out
```

> 如果 PoC 阶段发现 audioop 太慢（实测每帧 > 5ms），换 scipy.signal.resample_poly。

### 2.7 W2 退出条件

```bash
# 1. 单元测试
uv run pytest tests/voice/test_sip_audio_route.py -v
uv run pytest tests/voice/test_sip_controller.py -v
uv run pytest tests/voice/test_resample.py -v

# 2. 端到端：软电话拨号 → 听到 greeting → 说话 → 听到 cc_pool 回复
make run-gateway
linphone-cli -c sip:test@<host>:5061
# → "您好，请问有什么可以帮你？"
# → 用户："你们有iPhone15吗"
# → 听到 cc_pool 答复
```

### 2.8 W2 风险

| 风险 | 缓解 |
|---|---|
| chat_tts_text 在没有 LLM 上下文时不工作 | 备份方案：保留 say_hello + reconnect，承担延时 |
| /ws/chat 同进程 loopback 行为异常 | 改 UNIX socket；最差情况直接函数调用 cc_pool |
| audioop 性能不够 | 上 scipy；最差用 sox 子进程 |
| 服务端 controller 状态机 bug 多 | 完全照抄浏览器版本的状态图 + 单元测试 |

---

## 3. Week 3 — 性能调优 + 自测稳定性（5 天）

### 3.1 任务

| # | 任务 | 验证 |
|---|---|---|
| 3.1.1 | ASR `end_smooth_window_ms` 调优（默认 1500 → 800） | turn 切换更快 |
| 3.1.2 | TTS 首块延时打点 | Prometheus metric `tts_first_byte_ms` |
| 3.1.3 | comfort 与正式回复时序压测 | 两个 TTS 请求并发不互相干扰 |
| 3.1.4 | barge-in 端到端验证 | 用户开口立即停 TTS（< 200ms） |
| 3.1.5 | 30 分钟连续通话 | 无内存泄漏、无 socket 泄漏 |
| 3.1.6 | 5 路并发通话（sipp） | 全部能跑完，延时不退化 |
| 3.1.7 | 生产 logging + tracing | 每个 callSid 全链路可查 |

### 3.2 延时预算（W3 末验证）

| 段 | 目标 P50 | 实测 |
|---|---|---|
| Cinnox SBC ↔ HK | < 100ms | TBD |
| audio_fork → backend | < 10ms | TBD |
| ASR final | < 400ms | TBD |
| cc_pool LLM 首字 | < 1000ms | TBD（视模型） |
| TTS 首块（streaming） | < 300ms | TBD |
| 重采样 + 推回 SBC | < 50ms | TBD |
| **合计** | **< 2.0s** | **目标** |

### 3.3 W3 退出条件

- 5 路并发 30 分钟无故障
- P50 延时 < 2.0s（电话场景）
- 单元测试 + 集成测试 ≥ 90% 通过

---

## 4. Week 4 — Cinnox 联调（5 天）

### 4.1 任务

| # | 任务 | 协作方 |
|---|---|---|
| 4.1.1 | 提交 SIP_Interconnection_Form（只 inbound） | Cinnox BD |
| 4.1.2 | Cinnox 配 trunk + 分配测试号 | Cinnox 工程 |
| 4.1.3 | 用 Cinnox 测试号实拨 | 联调 |
| 4.1.4 | codec 协商抓包验证（PCMA 优先） | tcpdump + wireshark |
| 4.1.5 | 测北京 / JP / SG SBC 路径 | Cinnox 协助 |
| 4.1.6 | 长通话稳定性（30 分钟 × 3 次） | 联调 |

### 4.2 SIP 表单填法（最终版，按 02 §1.3）

| 字段 | 值 |
|---|---|
| Service domain | 留默认 `Internal.cinnox.com` |
| Contact Email | `<TBD: 工程对接邮箱>` |
| Requested Service | ☑ **SIP In only**（不勾 Out） |
| Remark | "AI voicebot powered by AutoService voice gateway (Volcengine Doubao). Self-hosted jambonz SBC, HK region." |
| Signaling IP | `<HK 服务器公网 IP>`（单点） |
| Media IP | 同上 |
| Inbound Port | 5061 (TLS) + 5060 (UDP) |
| Support OPTIONS | ☑ YES |
| Codec | ☑ PCMU ☑ PCMA ☑ OPUS ☐ G729 |
| Encryption | ☑ YES (DTLS-SRTP) |
| DTMF | ☑ RFC2833 ☑ SIP Info |
| Toll-Free 号码 | 测试阶段从 Cinnox 借 1 个 HK 号 |

### 4.3 W4 退出条件

- Cinnox 测试号能正常拨入
- 通话延时 P50 < 2.5s（含 SBC 路径）
- 至少 1 个北京 / JP / SG 客户端实测通过

### 4.4 W4 风险

| 风险 | 缓解 |
|---|---|
| Cinnox 配置慢 | W3 末就提交表单；W4 全程跟进 |
| codec 协商失败 | sipp 提前抓 INVITE 验证；jambonz 强制 PCMA 优先 |
| 北京 SBC 延时太大 | 接受、记录；后续多区部署再优化 |

---

## 5. Week 5 — 生产化 + Demo（5 天）

### 5.1 任务

| # | 任务 | 输出 |
|---|---|---|
| 5.1.1 | 监控接入 | Prometheus jambonz exporter + grafana 看板 |
| 5.1.2 | Runbook | `docs/runbooks/sip-voice.md` |
| 5.1.3 | 客户接入文档 | `docs/integrations/cinnox-voice-sip.md` |
| 5.1.4 | systemd / docker-compose 自启 | 服务器重启自动恢复 |
| 5.1.5 | 故障演练 | 杀 jambonz / 杀 backend / 网络抖动 |
| 5.1.6 | Demo 视频录制 | mp4 给 BD 演示 |
| 5.1.7 | 写交付总结 | `docs/plans/2026-05-XX-sip-voice-poc-summary.md` |

### 5.2 W5 退出条件

- 单机重启后服务自动恢复
- 故障演练 3 个场景全部能 5 分钟内恢复
- BD 拿到 demo 视频能向 Cinnox 客户演示

---

## 6. 全程交付清单

```
AutoService/
├── channels/web/voice/
│   ├── sip_audio_route.py       # 新（W2）
│   ├── sip_controller.py        # 新（W2）核心
│   ├── cc_chat_client.py        # 新（W2）
│   ├── resample.py              # 新（W2）
│   ├── tts_client.py            # 修：加 synthesize_streaming（W2）
│   └── (其它不动)
├── channels/web/app.py          # 修：注册 /sip-audio（W2）
├── deploy/sip/
│   ├── docker-compose.yml       # 新（W1）
│   ├── applications/cinnox-voicebot.json
│   ├── carriers/cinnox-trunk.json
│   ├── tls/README.md
│   └── README.md
├── tests/voice/
│   ├── test_sip_audio_route.py  # 新（W2）
│   ├── test_sip_controller.py   # 新（W2）
│   └── test_resample.py         # 新（W2）
├── docs/runbooks/
│   └── sip-voice.md             # 新（W5）
├── docs/integrations/
│   └── cinnox-voice-sip.md      # 新（W5）
└── docs/plans/
    └── 2026-05-XX-sip-voice-poc-summary.md  # 新（W5）
```

## 7. 验收标准（W5 末）

- [ ] Cinnox 测试号拨入能正常对话
- [ ] P50 延时 < 2.5s（含 SBC 路径）
- [ ] barge-in 工作（用户开口 < 200ms 停 TTS）
- [ ] 5 路并发 30 分钟无故障
- [ ] 单元测试 + 集成测试通过
- [ ] 监控看板 + runbook 上线
- [ ] BD demo 视频录制完成

## 8. 不在本 PoC 范围

- Outbound（外呼） — 单独 issue
- 多区域部署 — 单点不达预期再讨论
- voice 接 customer-chat 完整 pipeline（多智能体 / instant-ack） — 后续
- 30 路并发生产容量 — PoC 只到 5 路
- 录音 / 合规留存 — 与 Cinnox / 法务确认后单独做
- 多租户 voice 隔离 — PoC 只服务一个租户
