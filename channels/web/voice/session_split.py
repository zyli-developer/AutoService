"""Voice split-mode session — separate ASR + (cc_pool) LLM + TTS.

Ported from cc-openclaw/voice_gateway/session_split.py (aiohttp) to
FastAPI, replacing ActorBridge with VoiceEngineBridge.

Unlike VoiceSession (E2E Doubao Realtime Dialogue), split mode
opens an ASR-only Doubao connection AND a TTS-only Doubao connection
underneath (via ASRClient/TTSClient adapters). The LLM live entirely
in cc_pool — Doubao's built-in dialog LLM is never engaged.

State machine pushed to browser:
    idle → connecting → greeting → talking → ending → idle

Same chat-history sync as VoiceSession: ASR finals and bot replies
are persisted to the conversation engine and pushed to the customer's
/ws/customer for chat bubbles.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .asr_client import ASRClient
from .config import GREETING_TEXT, COMFORT_TEXT
from .tts_client import TTSClient
from .voice_engine_bridge import VoiceEngineBridge

log = logging.getLogger(__name__)


# Volcengine/Doubao ASR event types emitted by ASRClient.receive()
_EV_PARTIAL = "conversation.item.input_audio_transcription.result"
_EV_FINAL = "conversation.item.input_audio_transcription.completed"
_EV_SPEECH_STARTED = "input_audio_buffer.speech_started"


class VoiceSplitSession:
    """Split-mode voice call session. One per /ws/voice connection in split mode."""

    def __init__(
        self,
        browser_ws: WebSocket,
        *,
        start_config: dict | None = None,
        conversation_id: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self.browser_ws = browser_ws
        self.conversation_id = conversation_id
        self.tenant_id = tenant_id
        self.asr = ASRClient()
        self.tts = TTSClient()
        self.state = "idle"
        self.asr_text = ""
        self._asr_task: asyncio.Task | None = None
        self._query_task: asyncio.Task | None = None
        self._bridge = VoiceEngineBridge(
            conversation_id=conversation_id or "split-anonymous",
            tenant_id=tenant_id,
        )
        self._customer_source: str | None = None

        start_config = start_config or {}
        self._greeting_text = start_config.get("greeting") or GREETING_TEXT
        self._comfort_text = start_config.get("comfortText") or COMFORT_TEXT

    # ---------------- Browser-facing helpers ----------------

    async def send_state(self, state: str) -> None:
        self.state = state
        try:
            await self.browser_ws.send_json({"type": "state", "state": state})
        except Exception:
            pass

    async def send_transcript(self, role: str, text: str, interim: bool) -> None:
        if not text:
            return
        try:
            await self.browser_ws.send_json({
                "type": "transcript",
                "role": role,
                "text": text,
                "interim": interim,
            })
        except Exception:
            pass

    async def send_error(self, message: str) -> None:
        try:
            await self.browser_ws.send_json({"type": "error", "message": message})
        except Exception:
            pass

    # ---------------- Lifecycle ----------------

    async def run(self) -> None:
        try:
            await self._ensure_conversation()
            await self.send_state("connecting")
            await self.asr.connect()
            await self.tts.connect()

            await self.send_state("greeting")
            await self._speak(self._greeting_text)
            await self.send_transcript("bot", self._greeting_text, False)
            await self._persist_agent_text(
                self._greeting_text, extra_metadata={"voice_greeting": True},
            )

            await self.send_state("talking")
            self._asr_task = asyncio.create_task(self._read_asr())
            await self._browser_loop()
        except Exception as e:
            log.exception("VoiceSplitSession error")
            await self.send_error(str(e))
        finally:
            await self._cleanup()

    async def _speak(self, text: str) -> None:
        async for audio_chunk in self.tts.synthesize(text):
            try:
                await self.browser_ws.send_bytes(audio_chunk)
            except Exception:
                return

    async def _read_asr(self) -> None:
        try:
            async for event in self.asr.receive():
                evt_type = event.get("type", "")
                if evt_type == _EV_PARTIAL:
                    text = event.get("transcript", "")
                    if text:
                        self.asr_text = text
                        await self.send_transcript("user", text, True)
                elif evt_type == _EV_FINAL:
                    text = event.get("transcript", "")
                    if text:
                        self.asr_text = text
                        await self.send_transcript("user", text, False)
                        await self._persist_user_text(text)
                        if self._query_task and not self._query_task.done():
                            self._query_task.cancel()
                        self._query_task = asyncio.create_task(
                            self._run_query(text),
                        )
                        self.asr_text = ""
                elif evt_type == _EV_SPEECH_STARTED:
                    # Barge-in: cancel in-flight query/TTS so the user
                    # can interrupt without queueing.
                    if self._query_task and not self._query_task.done():
                        self._query_task.cancel()
                    try:
                        await self.browser_ws.send_json({"type": "clear_audio"})
                    except Exception:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("Split ASR read error: %s", e)

    async def _browser_loop(self) -> None:
        try:
            while True:
                message = await self.browser_ws.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                if "bytes" in message and message["bytes"] is not None:
                    await self.asr.send_audio(message["bytes"])
                elif "text" in message and message["text"] is not None:
                    try:
                        data = json.loads(message["text"])
                    except json.JSONDecodeError:
                        continue
                    if data.get("type") == "stop":
                        await self._stop()
                        return
        except WebSocketDisconnect:
            return

    async def _stop(self) -> None:
        await self.send_state("ending")
        if self._query_task and not self._query_task.done():
            self._query_task.cancel()
        await self.send_state("idle")

    async def _run_query(self, text: str) -> None:
        try:
            # COMFORT_TEXT intentionally skipped per current product
            # decision — go straight to bridge query, then speak its
            # result. The user hears silence during the bridge window;
            # if/when comfort returns, restore self._speak(self._comfort_text)
            # before _bridge.query.
            result = await self._bridge.query(text, timeout=60.0)
            await self.send_transcript("bot", result, False)
            await self._persist_agent_text(result)
            await self._speak(result)
        except asyncio.CancelledError:
            log.info("Split query cancelled")
        except Exception as e:
            log.error("Split query error: %s", e)

    # ---------------- Engine sync ----------------

    async def _ensure_conversation(self) -> None:
        """Idempotent conversation create + join. See VoiceSession docstring
        — same contract: when conversation_id is None we skip silently;
        otherwise create_conversation + join customer + agent so engine
        send_message succeeds and chat WS can render bubbles."""
        if not self.conversation_id:
            return
        engine = getattr(self.browser_ws.app.state, "engine", None)
        if engine is None:
            return
        try:
            from datetime import datetime, timezone
            from autoservice.conversation_engine.types import (
                Participant, ParticipantRole,
            )
            now = datetime.now(timezone.utc)
            ext_id = self.conversation_id
            if ext_id.startswith("web_"):
                ext_id = ext_id[len("web_"):]
            meta = {"channel": "web"}
            if self.tenant_id:
                meta["tenant_id"] = self.tenant_id
            conv = await engine.create_conversation(
                channel="web", external_id=ext_id, metadata=meta,
            )
            self.conversation_id = conv.id
            self._customer_source = ext_id
            await engine.join(
                conv.id,
                Participant(
                    id=ext_id, role=ParticipantRole.CUSTOMER, joined_at=now,
                ),
            )
            await engine.join(
                conv.id,
                Participant(
                    id="agent", role=ParticipantRole.AGENT, joined_at=now,
                ),
            )
            log.info(
                "split _ensure_conversation: conv_id=%s tenant=%s",
                conv.id, self.tenant_id,
            )
        except Exception:
            log.exception(
                "split _ensure_conversation failed (conv=%s)",
                self.conversation_id,
            )


    async def _persist_user_text(self, text: str) -> None:
        if not self._customer_source:
            return
        # push_to_customer=False — frontend already has optimistic bubble.
        # See VoiceSession._persist_user_text for the rationale.
        await self._persist_to_engine(
            source=self._customer_source, content=text,
            extra_metadata={"voice": True},
            role="customer",
            push_to_customer=False,
        )

    async def _persist_agent_text(
        self, text: str,
        *, extra_metadata: dict | None = None,
    ) -> None:
        meta = {"voice": True}
        if extra_metadata:
            meta.update(extra_metadata)
        await self._persist_to_engine(
            source="agent", content=text, extra_metadata=meta,
        )

    async def _persist_to_engine(
        self, *, source: str, content: str, extra_metadata: dict,
        role: str = "agent",
        push_to_customer: bool = True,
    ) -> None:
        if not self.conversation_id or not content:
            return
        try:
            engine = getattr(self.browser_ws.app.state, "engine", None)
            if engine is None:
                return
            msg = await engine.send_message(
                self.conversation_id,
                source=source,
                content=content,
                metadata=extra_metadata,
            )
            if not push_to_customer:
                return
            from autoservice.gateway.message_router import (
                _customer_ws_by_conv,
                _message_frame,
            )
            cust_ws = _customer_ws_by_conv.get(self.conversation_id)
            if cust_ws is not None:
                frame = _message_frame(msg)
                frame["payload"]["source_display"] = {"id": source, "role": role}
                try:
                    await cust_ws.send_json(frame)
                except Exception:
                    pass
        except Exception:
            log.exception(
                "VoiceSplitSession engine persist failed (conv=%s, source=%s)",
                self.conversation_id, source,
            )

    # ---------------- Cleanup ----------------

    async def _cleanup(self) -> None:
        # See VoiceSession._cleanup for why we MUST await the cancelled
        # query_task — without it the SDK's receive_response generator
        # stays paused with leftover Claude messages, and the next voice
        # session reads them as if they were the new prompt's response.
        if self._query_task and not self._query_task.done():
            self._query_task.cancel()
            try:
                await asyncio.wait_for(self._query_task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
        if self._asr_task and not self._asr_task.done():
            self._asr_task.cancel()
            try:
                await self._asr_task
            except asyncio.CancelledError:
                pass
        try:
            await self.asr.close()
        except Exception:
            pass
        try:
            await self.tts.close()
        except Exception:
            pass
        try:
            await self._bridge.close()
        except Exception:
            pass
        if self.browser_ws.client_state != WebSocketState.DISCONNECTED:
            try:
                await self.browser_ws.close()
            except Exception:
                pass
