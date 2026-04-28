"""Server-side voice controller for SIP calls — MINIMAL version.

Tracks docs/sip-deploy/08-minimal-cinnox-integration-code.md §1.4.

Deliberately ships without:
  - comfort text scheduling   ── caller hears 1s of silence during cc_pool
  - barge-in                   ── caller cannot interrupt the bot
  - streaming TTS              ── pays the per-call _reopen() cost (~300-500ms)
  - tighter ASR VAD            ── stays on the default 1500ms end_smooth_window

These belong to the post-PoC tuning pass tracked in 06 docs.

State machine:
    IDLE → SPEAKING (greeting) → LISTENING
    LISTENING → THINKING → SPEAKING → LISTENING (per turn, sequential)

Per-turn budget at PoC quality (08 §5):
    ASR final (~400ms) + cc_pool (~1000ms) + TTS reconnect (~400ms)
    + TTS first byte (~300ms)  ≈  2.1s e2e P50
"""
from __future__ import annotations

import asyncio
import enum
import logging
from typing import Any

from .resample import resample_24k_to_16k, reset as resample_reset

log = logging.getLogger(__name__)

# Inlined here (rather than channels/web/voice/config.py) to keep all Cinnox-
# specific surface in this file. Other voice paths (browser /asr, /tts) are
# unaffected by changing this string.
SIP_GREETING = "您好，欢迎致电 OpenClaw 客服，请问有什么可以帮您？"

_FALLBACK_REPLY = "抱歉，我这边出了点问题，请稍后再说。"


class State(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class SipVoiceController:
    def __init__(
        self,
        *,
        call_sid: str,
        caller: str,
        callee: str,
        ws: Any,
        asr: Any = None,
        tts: Any = None,
        cc: Any = None,
        tenant_id: str | None = None,
    ):
        self.call_sid = call_sid
        self.caller = caller
        self.callee = callee
        self.ws = ws
        self.tenant_id = tenant_id
        self.state = State.IDLE
        self.asr = asr
        self.tts = tts
        self.cc = cc

    async def run(self) -> None:
        # Lazy default factories — unit tests inject fakes
        if self.asr is None:
            from .asr_client import ASRClient
            self.asr = ASRClient()
        if self.tts is None:
            from .tts_client import TTSClient
            self.tts = TTSClient()
        if self.cc is None:
            from .cc_chat_client import CCChatClient
            self.cc = CCChatClient(
                call_sid=self.call_sid,
                caller=self.caller,
                tenant_id=self.tenant_id,
            )

        await self.asr.connect()
        await self.tts.connect()
        await self.cc.connect()

        # Greeting — sequential (blocks until done)
        await self._speak(SIP_GREETING)
        self.state = State.LISTENING

        # Two concurrent loops: pump audio + handle ASR events
        in_task = asyncio.create_task(self._pump_jambonz_to_asr(), name="jambonz->asr")
        evt_task = asyncio.create_task(self._handle_asr_events(), name="asr-events")
        try:
            await asyncio.wait({in_task, evt_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in (in_task, evt_task):
                if not t.done():
                    t.cancel()
            for t in (in_task, evt_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    async def shutdown(self) -> None:
        for c in (self.asr, self.tts, self.cc):
            if c is None:
                continue
            try:
                await c.close()
            except Exception:
                log.warning("[%s] close error", self.call_sid, exc_info=True)
        resample_reset(self.call_sid)

    async def _pump_jambonz_to_asr(self) -> None:
        try:
            async for chunk in self.ws.iter_bytes():
                await self.asr.send_audio(chunk)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[%s] jambonz->asr pump failed", self.call_sid)

    async def _handle_asr_events(self) -> None:
        try:
            async for event in self.asr.receive():
                # 08 minimal: only react to ASR final. speech_started is
                # ignored (no barge-in). Everything else is logged-only.
                if event.get("type") != "conversation.item.input_audio_transcription.completed":
                    continue
                text = (event.get("transcript") or "").strip()
                if not text:
                    continue

                log.info("[%s] user: %s", self.call_sid, text)
                self.state = State.THINKING
                try:
                    reply = await self.cc.send(text)
                except Exception:
                    log.exception("[%s] cc_pool error", self.call_sid)
                    reply = _FALLBACK_REPLY

                log.info("[%s] bot: %s", self.call_sid, reply[:60])
                await self._speak(reply)
                self.state = State.LISTENING
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[%s] asr events handler crashed", self.call_sid)

    async def _speak(self, text: str) -> None:
        """Synthesize text and stream PCM back to jambonz.

        Uses legacy synthesize() which reconnects per call (~300-500ms cost).
        Acceptable for PoC; optimize later (see 06 doc §1.3 for streaming version).
        """
        self.state = State.SPEAKING
        try:
            async for pcm_24k in self.tts.synthesize(text):
                pcm_16k = resample_24k_to_16k(pcm_24k, key=self.call_sid)
                await self.ws.send_bytes(pcm_16k)
        except Exception:
            log.exception("[%s] tts failed", self.call_sid)
