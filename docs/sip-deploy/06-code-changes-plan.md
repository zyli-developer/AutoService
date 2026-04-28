---
title: AutoService SIP 接入 — 代码改动计划
date: 2026-04-28
owner: yaosh
status: 可执行（W2 开始）
target_branch: feat/sip-voice-cinnox
companion: 07-deployment-cinnox-integration.md
---

# 代码改动计划

> 配套部署文档：[07-deployment-cinnox-integration.md](07-deployment-cinnox-integration.md)
> 应用层代码部署在 **Mac (现有 CF Tunnel `autoservice.ezagent.chat`)**，
> SIP 终结部署在 **火山云 HK VPS**。本文档只讲代码，不讲部署。

## 0. 总览

| 文件 | 操作 | LOC | 说明 |
|---|---|---|---|
| `channels/web/voice/sip_audio_route.py` | 新增 | ~80 | jambonz audio_fork WS endpoint |
| `channels/web/voice/sip_controller.py` | 新增 | ~220 | 服务端编排状态机 |
| `channels/web/voice/cc_chat_client.py` | 新增 | ~50 | 进程内 /ws/chat client |
| `channels/web/voice/resample.py` | 新增 | ~30 | 24k↔16k PCM 重采样 |
| `channels/web/voice/tts_client.py` | 修改（追加） | +50 | 加 `synthesize_streaming()`，旧 API 不动 |
| `channels/web/voice/config.py` | 修改（追加） | +15 | 加 SIP_GREETING / COMFORT_POOL / SIP_ASR_OVERRIDES |
| `channels/web/app.py` | 修改 | +5 | 注册 `/sip-audio` endpoint + CF Access service token 验证 |
| `tests/voice/test_sip_audio_route.py` | 新增 | ~80 | adapter 框架测试 |
| `tests/voice/test_sip_controller.py` | 新增 | ~150 | 状态机 + barge-in 测试 |
| `tests/voice/test_resample.py` | 新增 | ~40 | 重采样正确性 + 跨 chunk state |
| `tests/voice/test_tts_streaming.py` | 新增 | ~50 | 验证 chat_tts_text 协议 |
| `tests/voice/test_cc_chat_client.py` | 新增 | ~40 | mock /ws/chat 跑通 |
| **合计** | | **~810 LOC** | 6 新文件 + 3 修改文件 + 5 测试文件 |

**严格不动**（保护浏览器路径）：
- `asr_client.py` / `asr_route.py` / `tts_route.py` / `doubao_client.py` / `protocol.py`
- 所有 frontend 代码
- `tts_client.py` 的现有 `synthesize()` 方法 + `_reopen()`
- `config.py` 的现有 `START_SESSION_CONFIG` / `GREETING_TEXT` / `COMFORT_TEXT`

---

## 1. 文件级实现

### 1.1 `channels/web/voice/resample.py`（新增，~30 LOC）

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

### 1.2 `channels/web/voice/cc_chat_client.py`（新增，~50 LOC）

```python
"""Internal client to AutoService /ws/chat (cc_pool LLM).

Loopback to the same uvicorn process. If cross-process is needed later,
swap the URL for a UNIX socket.
"""
import json
import logging
from typing import Optional

import websockets

log = logging.getLogger(__name__)

CC_CHAT_URL = "ws://127.0.0.1:8000/ws/chat"


class CCChatClient:
    def __init__(self, call_sid: str, caller: str):
        self.call_sid = call_sid
        self.caller = caller
        self.ws: Optional[websockets.WebSocketClientProtocol] = None

    async def connect(self) -> None:
        self.ws = await websockets.connect(CC_CHAT_URL, ping_interval=None)

    async def send(self, user_text: str) -> str:
        if self.ws is None:
            raise RuntimeError("CCChatClient not connected")
        await self.ws.send(json.dumps({
            "type": "user_text_submit",
            "text": user_text,
            "metadata": {
                "channel": "sip",
                "caller": self.caller,
                "call_sid": self.call_sid,
            },
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

### 1.3 `channels/web/voice/tts_client.py`（修改，追加 ~50 LOC）

在文件**末尾**追加方法，**现有 `synthesize()` 不动**：

```python
# ======================================================================
# SIP path additions — see docs/discuss/note-autoservice/06-code-changes-plan.md
# ======================================================================

class TTSClient:
    # ... 现有代码不动 ...

    async def synthesize_streaming(self, text: str):
        """Streaming TTS without per-call reconnect.

        Uses Doubao chat_tts_text protocol so multiple synthesize calls
        share one WebSocket session. Saves the 300-500ms reconnect cost
        that synthesize() pays via _reopen() between calls.

        IMPORTANT: chat_tts_text expects start/end flags. We send both
        true for one-shot synthesis. If Doubao requires LLM context
        first, fall back to synthesize() with the reconnect penalty.
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

> **W2 D3 必做的验证**：本地起 TTSClient，连续调用 `synthesize_streaming` 三次，
> 确认不需要 `_reopen()` 也能拿到 PCM。如果不行（chat_tts_text 拒绝 stand-alone），
> 退回 `synthesize()` + 接受重连开销，P50 目标改为 < 3.0s。

### 1.4 `channels/web/voice/config.py`（修改，追加 ~15 LOC）

```python
# ======================================================================
# SIP path config — see docs/discuss/note-autoservice/06-code-changes-plan.md
# ======================================================================

SIP_GREETING = "您好，欢迎致电 OpenClaw 客服，请问有什么可以帮您？"

COMFORT_POOL = [
    "稍等，我帮您查一下。",
    "好的，让我想想。",
    "嗯，我看看。",
]

# Tighter VAD window for telephony — phone users feel laggy with default 1500ms
SIP_ASR_OVERRIDES = {
    "asr": {
        "extra": {
            "end_smooth_window_ms": 800,
        },
    },
}
```

### 1.5 `channels/web/voice/sip_controller.py`（新增，~220 LOC，核心）

完整代码见 `docs/discuss/note-autoservice/04-final-executable-plan.md` §5.3。
关键设计：

- **状态机**：`IDLE / LISTENING / THINKING / SPEAKING / ENDING`
- **三个并发 task**：`_pump_jambonz_to_asr` / `_handle_asr_events` / `_speak`
- **comfort fire-and-forget**：ASR final 立即触发 comfort，不等 cc_pool
- **barge-in**：`speech_started` event → 立刻 cancel `_tts_task`
- **错误恢复**：cc_pool 异常 → 播 fallback 文本，不挂断
- **资源清理**：`shutdown()` 关掉 ASR/TTS/CC 三个 client

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
from .resample import reset as reset_resample, resample_24k_to_16k
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

    async def run(self) -> None:
        # 1. Bring up upstream connections
        self.asr = ASRClient()
        await self.asr.connect()
        self.tts = TTSClient()
        await self.tts.connect()
        self.cc = CCChatClient(call_sid=self.call_sid, caller=self.caller)
        await self.cc.connect()

        # 2. Greeting
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
        try:
            async for chunk in self.ws.iter_bytes():
                if self.asr:
                    await self.asr.send_audio(chunk)
        except Exception:
            log.exception("[%s] jambonz->asr pump failed", self.call_sid)

    async def _handle_asr_events(self) -> None:
        try:
            async for event in self.asr.receive():
                evt = event.get("type")

                if evt == "input_audio_buffer.speech_started":
                    if self.state == State.SPEAKING and self._tts_task:
                        log.info("[%s] barge-in: cancel TTS", self.call_sid)
                        self._tts_task.cancel()
                        self._tts_task = None
                        self.state = State.LISTENING

                elif evt == "conversation.item.input_audio_transcription.completed":
                    text = event.get("transcript", "").strip()
                    if not text:
                        continue
                    log.info("[%s] user: %s", self.call_sid, text)
                    self.state = State.THINKING

                    # comfort fire-and-forget
                    comfort = random.choice(COMFORT_POOL)
                    asyncio.create_task(self._speak(comfort), name="comfort")

                    try:
                        reply = await self.cc.send(text)
                    except Exception:
                        log.exception("[%s] cc_pool error", self.call_sid)
                        reply = "抱歉，我这边出了点问题，请稍后再说。"

                    log.info("[%s] bot: %s", self.call_sid, reply[:60])
                    await self._speak(reply)
                    self.state = State.LISTENING

                elif evt == "error":
                    log.error("[%s] asr error: %s", self.call_sid, event.get("error"))
        except Exception:
            log.exception("[%s] asr events failed", self.call_sid)

    async def _speak(self, text: str) -> None:
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
                pcm_16k = resample_24k_to_16k(pcm_24k, key=self.call_sid)
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
        reset_resample(self.call_sid)
        for c in (self.asr, self.tts, self.cc):
            if c is None:
                continue
            try:
                await c.close()
            except Exception:
                log.exception("[%s] close error", self.call_sid)
```

### 1.6 `channels/web/voice/sip_audio_route.py`（新增，~80 LOC）

```python
"""SIP audio gateway — bridges jambonz audio_fork → AutoService voice pipeline.

Wire protocol (jambonz audio_fork):
  - Text frame (1st):  {"event":"start","callSid":"...","from":"...","to":"..."}
  - Binary frames in:  PCM 16-bit LE 16kHz mono
  - Binary frames out: PCM 16-bit LE 16kHz mono (jambonz handles 16k→PCMA 8k)
  - Text frame (last): {"event":"stop"}

Thin adapter. All conversation logic lives in sip_controller.SipVoiceController.

Auth: relies on Cloudflare Access service token (jambonz attaches
CF-Access-Client-Id / CF-Access-Client-Secret headers). Validation is
done at CF edge before the request reaches uvicorn.
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
        log.info(
            "[/sip-audio] call sid=%s from=%s to=%s",
            controller.call_sid, controller.caller, controller.callee,
        )
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

### 1.7 `channels/web/app.py`（修改，+5 LOC）

```python
# 在现有 import 之后追加
from channels.web.voice.sip_audio_route import sip_audio_endpoint

# 在现有 endpoint 注册之后追加
@app.websocket("/sip-audio")
async def sip_audio_ws(ws: WebSocket):
    await sip_audio_endpoint(ws)
```

---

## 2. 测试计划

### 2.1 `tests/voice/test_resample.py`

```python
def test_24k_to_16k_basic_length():
    """24kHz 480 samples (20ms) → 16kHz 320 samples."""
    pcm_24k = b"\x00\x00" * 480
    out = resample_24k_to_16k(pcm_24k, key="test1")
    assert 300 <= len(out) // 2 <= 340  # ratecv 误差 ±10 samples

def test_state_preserved_across_chunks():
    """Resampling without state would create clicks at chunk boundaries."""
    chunk = b"\x10\x00" * 480
    out1 = resample_24k_to_16k(chunk, key="test2")
    out2 = resample_24k_to_16k(chunk, key="test2")
    # Compare last sample of out1 with first sample of out2 — should be smooth
    last = int.from_bytes(out1[-2:], "little", signed=True)
    first = int.from_bytes(out2[:2], "little", signed=True)
    assert abs(last - first) < 100  # 实际应 < 50

def test_reset_clears_state():
    resample_24k_to_16k(b"\x00\x00" * 480, key="test3")
    reset("test3")
    assert "test3" not in _state
```

### 2.2 `tests/voice/test_cc_chat_client.py`

mock /ws/chat 跑通完整 send/receive 循环。

### 2.3 `tests/voice/test_tts_streaming.py`

- 验证 `synthesize_streaming` 不调用 `_reopen()`
- 连续两次调用使用同一个 doubao session
- TTS_ENDED 后 generator 正常 return

### 2.4 `tests/voice/test_sip_audio_route.py`

mock jambonz WS：
- 发 `{"event":"start"}` → 进入 controller
- 发非 JSON → 返回 error，不挂
- 不发 start event → 返回 error
- 中途断开 → cleanup 跑完

### 2.5 `tests/voice/test_sip_controller.py`

mock ASR/TTS/CC client，验证：
- `IDLE → SPEAKING → LISTENING`（greeting 完成）
- `LISTENING → THINKING → SPEAKING`（一轮对话）
- `speech_started` 在 SPEAKING 时 → `_tts_task.cancel`，回到 LISTENING
- `speech_started` 在 LISTENING/THINKING 时 → 不影响
- comfort 与正式回复并发不互相干扰
- cc_pool 抛异常 → 播 fallback 文本，不退出 controller
- ASR 流结束 → controller `_handle_asr_events` 退出 → `run()` 返回

### 2.6 测试覆盖目标

| 模块 | 行覆盖目标 |
|---|---|
| `resample.py` | ≥ 95% |
| `cc_chat_client.py` | ≥ 90% |
| `tts_client.py` 新方法 | ≥ 85% |
| `sip_controller.py` | ≥ 80%（异步状态机难全覆盖） |
| `sip_audio_route.py` | ≥ 90% |

---

## 3. PR 拆分建议

| PR | 内容 | 依赖 | 大小 |
|---|---|---|---|
| **PR1** | `resample.py` + 测试 | 无 | ~70 LOC |
| **PR2** | `cc_chat_client.py` + 测试（mock /ws/chat） | 无 | ~90 LOC |
| **PR3** | `tts_client.py` 加 `synthesize_streaming` + 测试 + `config.py` 加 SIP_* | 无 | ~110 LOC |
| **PR4** | `sip_controller.py` + 测试 | PR1, PR2, PR3 | ~370 LOC |
| **PR5** | `sip_audio_route.py` + `app.py` 改动 + 测试 | PR4 | ~160 LOC |

每个 PR 独立可 review、可合并、可回滚。

PR1-3 可并行写。PR4 必须等前三个合并。PR5 收尾。

---

## 4. 验收标准（代码层）

### 单元测试
- [ ] 5 个测试文件全部跑过
- [ ] 总覆盖率 ≥ 85%（按上面目标）
- [ ] 所有 mypy 类型检查通过
- [ ] 所有 ruff lint 通过

### 集成测试（需要 Doubao 凭据）
- [ ] `synthesize_streaming` 实际能从 Doubao 拿到 PCM（W2 D3 验证）
- [ ] `cc_chat_client` 能跑通同进程 `/ws/chat`（mock LLM）
- [ ] 完整跑 `make run-gateway`，软电话拨号 jambonz 能完成一整轮对话

### 不破坏现有功能
- [ ] 浏览器 voice（`/asr` + `/tts`）回归测试全部通过
- [ ] customer-chat 前端 voice 用户路径手测通过
- [ ] 现有 `tts_client.synthesize()` 行为不变

---

## 5. 已知风险（代码层）

| 风险 | 概率 | 缓解 |
|---|---|---|
| `chat_tts_text` 不允许 stand-alone（要 LLM 上下文） | 中 | W2 D3 提早验证；fallback 用旧 `synthesize()` |
| `audioop.ratecv` 性能不够（>5ms/frame） | 低 | 换 `scipy.signal.resample_poly` |
| 同进程 `/ws/chat` loopback 行为异常 | 低 | 改 UNIX socket；最差直接函数调用 |
| controller 状态机在并发 task 下有 race | 中 | 完全照搬浏览器版本逻辑 + 单元测试覆盖所有迁移 |
| jambonz 推的 PCM 不是 16k mono LE（实测过才知） | 低 | W1 软电话验证时抓包确认 |

---

## 6. 与 04 文档的差异

本文档相对 04 文档（最终单文件可执行方案）的更新：

1. **删除 `deploy/sip/` 目录** —— 部署不在 AutoService 仓库，改在火山云 VPS 单独维护
2. **`/sip-audio` 加 CF Access service token 验证说明** —— 因为走 CF Tunnel 暴露
3. **PR 拆分细化** —— 5 个独立 PR 而不是一次性大 PR
4. **测试覆盖目标** —— 具体到模块行覆盖数字

部署相关全部移到 [07-deployment-cinnox-integration.md](07-deployment-cinnox-integration.md)。
