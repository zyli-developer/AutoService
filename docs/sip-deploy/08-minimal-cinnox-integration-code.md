---
title: 接入 Cinnox 的最小代码改动（去除所有调优）
date: 2026-04-28
owner: yaosh
status: 可执行（W2 开始）
supersedes: 06 文档（保留 06 作为"调优版本"参考）
companion: 07-deployment-cinnox-integration.md
---

# 最小接入代码改动（仅 Cinnox 接入，不调优）

> **范围**：让 Cinnox 测试号能拨进来、和 cc_pool 完成一整轮对话，仅此而已。
> **不做**：comfort 文本、barge-in、TTS 复用、ASR VAD 调优。
> **代价**：单 turn 延时多 ~1s（TTS 重连），用户不能打断 bot。
> **理由**：用户明确"暂时不调优"。功能跑通后再分阶段加优化。

## 0. 总览

| 文件 | 操作 | LOC | 必要性 |
|---|---|---|---|
| `channels/web/voice/sip_audio_route.py` | 新增 | ~70 | jambonz 接入点 |
| `channels/web/voice/sip_controller.py` | 新增 | **~100** | 简化版状态机（无 comfort/barge-in） |
| `channels/web/voice/cc_chat_client.py` | 新增 | ~50 | 调 cc_pool 拿业务回复 |
| `channels/web/voice/resample.py` | 新增 | ~30 | 24k↔16k 必须 |
| `channels/web/voice/config.py` | 修改 | **+3** | 只加 `SIP_GREETING` |
| `channels/web/app.py` | 修改 | +5 | 注册 `/sip-audio` |
| `tests/voice/test_resample.py` | 新增 | ~40 | |
| `tests/voice/test_cc_chat_client.py` | 新增 | ~40 | |
| `tests/voice/test_sip_audio_route.py` | 新增 | ~30 | |
| `tests/voice/test_sip_controller.py` | 新增 | ~50 | |
| **合计** | | **~408 LOC** | 6 业务 + 4 测试 |

**严格不动**：
- `asr_client.py` / `asr_route.py` / `tts_route.py` / `tts_client.py` / `doubao_client.py` / `protocol.py`
- 所有 frontend 代码
- `config.py` 现有的 `START_SESSION_CONFIG` / `GREETING_TEXT` / `COMFORT_TEXT`

> **特别注意**：`tts_client.py` 也**完全不动**——直接复用现有 `synthesize()`，
> 接受每次合成 300-500ms 的重连开销。这是和 06 文档最大的差异。

---

## 1. 文件级实现

### 1.1 `channels/web/voice/resample.py`（新增，~30 LOC）

与 06 文档 §1.1 完全一致：

```python
"""Audio resampling for SIP voice path.

Doubao TTS outputs 24kHz; jambonz audio_fork expects 16kHz mono on the
return leg. audioop.ratecv is fast enough for 16k↔24k mono.
"""
import audioop

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

与 06 文档 §1.2 完全一致：

```python
"""Internal client to AutoService /ws/chat (cc_pool LLM)."""
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

### 1.3 `channels/web/voice/config.py`（修改，+3 LOC）

只加一行（其余调优配置全部砍掉）：

```python
# ======================================================================
# SIP path config — see docs/discuss/note-autoservice/08
# ======================================================================
SIP_GREETING = "您好，欢迎致电 OpenClaw 客服，请问有什么可以帮您？"
```

### 1.4 `channels/web/voice/sip_controller.py`（新增，~100 LOC，**核心简化**）

```python
"""Server-side voice controller for SIP calls — MINIMAL VERSION.

Compared to 06 docs (the full version):
  - NO comfort text scheduling (sequential ASR final → cc_pool → TTS)
  - NO barge-in handling (user must wait for bot to finish)
  - NO TTS reconnect optimization (uses synthesize() with _reopen() cost)

State machine (simpler):
  IDLE → SPEAKING (greeting) → LISTENING
  LISTENING → THINKING → SPEAKING → LISTENING (loop per turn)

Performance budget:
  ~ASR final (400ms) + cc_pool (1000ms) + TTS reconnect (400ms) +
   TTS first byte (300ms) = ~2.1s e2e
  Acceptable for PoC integration. Optimize later (see 06 docs).
"""
import asyncio
import enum
import logging

from fastapi import WebSocket

from .asr_client import ASRClient
from .cc_chat_client import CCChatClient
from .config import SIP_GREETING
from .resample import reset as reset_resample, resample_24k_to_16k
from .tts_client import TTSClient

log = logging.getLogger(__name__)


class State(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


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

    async def run(self) -> None:
        # 1. Bring up upstream
        self.asr = ASRClient()
        await self.asr.connect()
        self.tts = TTSClient()
        await self.tts.connect()
        self.cc = CCChatClient(call_sid=self.call_sid, caller=self.caller)
        await self.cc.connect()

        # 2. Play greeting (blocking, sequential)
        await self._speak(SIP_GREETING)
        self.state = State.LISTENING

        # 3. Two concurrent loops: pump audio + handle ASR events
        in_task = asyncio.create_task(self._pump_jambonz_to_asr(), name="in")
        evt_task = asyncio.create_task(self._handle_asr_events(), name="evt")
        try:
            await asyncio.wait(
                {in_task, evt_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for t in (in_task, evt_task):
                if not t.done():
                    t.cancel()

    async def _pump_jambonz_to_asr(self) -> None:
        try:
            async for chunk in self.ws.iter_bytes():
                if self.asr:
                    await self.asr.send_audio(chunk)
        except Exception:
            log.exception("[%s] jambonz->asr failed", self.call_sid)

    async def _handle_asr_events(self) -> None:
        try:
            async for event in self.asr.receive():
                # Only react to ASR final. Ignore speech_started (no barge-in).
                if event.get("type") != "conversation.item.input_audio_transcription.completed":
                    continue
                text = event.get("transcript", "").strip()
                if not text:
                    continue
                log.info("[%s] user: %s", self.call_sid, text)

                self.state = State.THINKING
                try:
                    reply = await self.cc.send(text)
                except Exception:
                    log.exception("[%s] cc_pool error", self.call_sid)
                    reply = "抱歉，我这边出了点问题，请稍后再说。"
                log.info("[%s] bot: %s", self.call_sid, reply[:60])

                await self._speak(reply)
                self.state = State.LISTENING
        except Exception:
            log.exception("[%s] asr events failed", self.call_sid)

    async def _speak(self, text: str) -> None:
        """Synthesize text and stream PCM back to jambonz.

        Uses existing synthesize() which reconnects per call (~300-500ms cost).
        Acceptable for integration PoC; optimize later if needed.
        """
        self.state = State.SPEAKING
        try:
            async for pcm_24k in self.tts.synthesize(text):
                pcm_16k = resample_24k_to_16k(pcm_24k, key=self.call_sid)
                await self.ws.send_bytes(pcm_16k)
        except Exception:
            log.exception("[%s] tts failed", self.call_sid)

    async def shutdown(self) -> None:
        reset_resample(self.call_sid)
        for c in (self.asr, self.tts, self.cc):
            if c is None:
                continue
            try:
                await c.close()
            except Exception:
                log.exception("[%s] close error", self.call_sid)
```

**与 06 版本的差异**：

| 06 (调优版) | 08 (本版本) |
|---|---|
| `_tts_task: asyncio.Task` 字段 | 无（不需要 cancel） |
| `_speak()` 含 cancel-in-flight 逻辑 | 直接同步播完 |
| `_handle_asr_events` 监听 `speech_started` | 不监听（无 barge-in） |
| `_handle_asr_events` 触发 comfort fire-and-forget | 不触发 |
| 用 `synthesize_streaming` | 用现有 `synthesize` |
| `import COMFORT_POOL, random` | 不需要 |

### 1.5 `channels/web/voice/sip_audio_route.py`（新增，~70 LOC）

与 06 文档 §1.6 一致：

```python
"""SIP audio gateway — bridges jambonz audio_fork → AutoService voice pipeline.

Wire protocol (jambonz audio_fork):
  - Text frame (1st):  {"event":"start","callSid":"...","from":"...","to":"..."}
  - Binary frames in:  PCM 16-bit LE 16kHz mono
  - Binary frames out: PCM 16-bit LE 16kHz mono
  - Text frame (last): {"event":"stop"}

Auth: relies on Cloudflare Access service token; jambonz attaches
CF-Access-Client-Id / CF-Access-Client-Secret headers (validated at CF edge).
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

### 1.6 `channels/web/app.py`（修改，+5 LOC）

```python
# 在现有 import 之后追加
from channels.web.voice.sip_audio_route import sip_audio_endpoint

# 在现有 endpoint 之后追加
@app.websocket("/sip-audio")
async def sip_audio_ws(ws: WebSocket):
    await sip_audio_endpoint(ws)
```

---

## 2. 测试计划（精简版）

### 2.1 `tests/voice/test_resample.py`（~40 LOC）

```python
def test_24k_to_16k_basic_length():
    pcm_24k = b"\x00\x00" * 480
    out = resample_24k_to_16k(pcm_24k, key="t1")
    assert 300 <= len(out) // 2 <= 340

def test_state_preserved_across_chunks():
    chunk = b"\x10\x00" * 480
    out1 = resample_24k_to_16k(chunk, key="t2")
    out2 = resample_24k_to_16k(chunk, key="t2")
    last = int.from_bytes(out1[-2:], "little", signed=True)
    first = int.from_bytes(out2[:2], "little", signed=True)
    assert abs(last - first) < 100

def test_reset_clears_state():
    resample_24k_to_16k(b"\x00\x00" * 480, key="t3")
    reset("t3")
    from channels.web.voice.resample import _state
    assert "t3" not in _state
```

### 2.2 `tests/voice/test_cc_chat_client.py`（~40 LOC）

mock /ws/chat：发 user_text_submit → 收 bot_text_delta × N → done。

### 2.3 `tests/voice/test_sip_audio_route.py`（~30 LOC）

mock jambonz WS：
- 发非 JSON start → 返回 error
- 不发 start event → 返回 error
- 发正常 start → 进入 controller（mock controller.run）

### 2.4 `tests/voice/test_sip_controller.py`（~50 LOC，简化）

只测核心迁移（不测 barge-in/comfort）：
- `IDLE → SPEAKING (greeting) → LISTENING`
- `LISTENING → THINKING → SPEAKING → LISTENING`（一轮对话）
- ASR final 空字符串 → 状态不变
- cc_pool 抛异常 → 播 fallback 文本，不退出
- ASR 流结束 → controller `_handle_asr_events` 退出 → `run()` 返回
- shutdown 把 ASR/TTS/CC 三个 client 都关掉

**不测**（这些功能压根没实现）：
- ❌ barge-in
- ❌ comfort 与正式回复并发
- ❌ TTS reconnect 优化

---

## 3. PR 拆分（精简版）

| PR | 内容 | 依赖 | 大小 |
|---|---|---|---|
| **PR1** | `resample.py` + 测试 | 无 | ~70 LOC |
| **PR2** | `cc_chat_client.py` + 测试 | 无 | ~90 LOC |
| **PR3** | `sip_controller.py` + `config.py` SIP_GREETING + 测试 | PR1, PR2 | ~150 LOC |
| **PR4** | `sip_audio_route.py` + `app.py` 改动 + 测试 | PR3 | ~100 LOC |

总共 4 个 PR（06 是 5 个，少了"PR3 tts_client 优化"那个）。

PR1, PR2 可并行。PR3 等前两个合并。PR4 收尾。

---

## 4. 验收标准（精简版）

### 单元测试
- [ ] 4 个测试文件全部通过
- [ ] 总覆盖率 ≥ 80%
- [ ] mypy + ruff 通过

### 集成测试（需要 Doubao 凭据）
- [ ] `cc_chat_client` 能跑通同进程 `/ws/chat`
- [ ] `make run-gateway` + 软电话拨号 jambonz → 听到 greeting → 说话 → bot 回复

### 不破坏现有功能
- [ ] 浏览器 voice（`/asr` + `/tts`）回归测试通过
- [ ] customer-chat 前端 voice 用户路径手测通过

### 不要求（这一版不做）
- ❌ P50 延时 < 2.5s（08 版本预期 ~3s）
- ❌ barge-in 工作
- ❌ comfort 文本平滑
- ❌ 5 路并发性能压测

---

## 5. 性能预期（明确告知）

```
单 turn 完整时序（08 版本）：

t=0       用户结束说话
t=400ms   ASR final
t=400ms   state=THINKING（用户进入静默等待）
t=1400ms  cc_pool 首字（假设 1s）
          ↓
          (静默 1s — 用户感觉机器人在"想")
          ↓
t=1400ms  开始合成 TTS
t=1400ms  TTS reconnect (300-500ms)
t=1800ms  TTS 首块到达
t=1800ms  state=SPEAKING（用户听到回复）

  →  用户感知延时 ≈ 1.8s
  →  P95 ≈ 3-4s（cc_pool 慢的时候）
```

**对比 06 调优版**（带 comfort + streaming TTS）：
```
t=400ms   ASR final
t=500ms   comfort 开始播 ("稍等我查一下")
t=1400ms  cc_pool 首字
t=1700ms  comfort 结束 + 正式 TTS 首块到达
  →  用户感知延时 ≈ 1.5s + 几乎无感静默
```

**判断**：08 版本延时绝对值高 ~300ms，但**用户感知差异主要在静默体验**（08 版有 1s 静默，06 版被 comfort 掩盖）。功能上完全可用。

---

## 6. 后续调优路径（功能跑通后再做）

按 ROI 排序：

| 阶段 | 改动 | 工作量 | 用户体验提升 |
|---|---|---|---|
| 1 | 加 `tts_client.synthesize_streaming` | 1 天 | 单 turn 省 600-1000ms |
| 2 | 加 comfort 文本 | 半天 | 消除静默感 |
| 3 | 加 barge-in | 半天 | 用户能打断 bot |
| 4 | ASR `end_smooth_window_ms` 调到 800 | 5 分钟 | turn 切换快 200-400ms |

每个阶段独立 PR，独立验证。06 文档可作为这四步的实施参考。

---

## 7. 与 06/07 文档的关系

```
06 (完整版代码计划) ─── 后续调优阶段参考
                  └─── 不再作为当前 PoC 的代码基准

08 (本文档, 精简版) ─── ★ 当前 PoC 实施基准
       │
       │ 部署相关全部沿用
       ▼
07 (部署 + Cinnox 对接) ─── 不变
```

**07 文档完全不变**——部署/jambonz 配置/Cinnox 表单填法和 08 版本完全兼容。
你今天就可以按 07 的 W1 D1 开始注册火山云。
