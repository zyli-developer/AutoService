"""Voice E2E session — Doubao Realtime Dialogue + AutoService LLM bridge.

Ported from cc-openclaw/voice_gateway/session.py (aiohttp) to FastAPI,
replacing ActorBridge with VoiceEngineBridge so the LLM source is
AutoService's own cc_pool (same pipeline as /ws/customer).

One Session per /ws/voice connection in mode="e2e_session". The
Doubao Realtime Dialogue session does ASR + TTS; the agent's text
reply per turn is fetched from cc_pool and injected back into Doubao
via send_chat_rag_text so Doubao speaks it.

State machine pushed to the browser via {type:"state", state:"..."}:
    idle → connecting → greeting → talking → ending → idle

User and agent text are also persisted to the conversation engine and
broadcast to the customer's /ws/customer connection (when one exists)
so voice utterances appear as bubbles in chat history alongside text
chat.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .config import START_SESSION_CONFIG, GREETING_TEXT, COMFORT_TEXT
from .doubao_client import DoubaoClient
from .protocol import (
    EVENT_CONNECTION_STARTED, EVENT_CONNECTION_FAILED,
    EVENT_SESSION_STARTED, EVENT_SESSION_FAILED, EVENT_SESSION_FINISHED,
    EVENT_CONNECTION_FINISHED,
    EVENT_TTS_SENTENCE_START,
    EVENT_TTS_RESPONSE, EVENT_TTS_ENDED,
    EVENT_ASR_INFO, EVENT_ASR_RESPONSE, EVENT_ASR_ENDED,
    EVENT_CHAT_RESPONSE, EVENT_CHAT_ENDED,
)
from .voice_engine_bridge import VoiceEngineBridge

log = logging.getLogger(__name__)


class VoiceSession:
    """E2E voice call session. One per /ws/voice connection in e2e_session mode."""

    def __init__(
        self,
        browser_ws: WebSocket,
        *,
        start_config: dict | None = None,
        conversation_id: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self.browser_ws = browser_ws
        self.session_id = str(uuid.uuid4())
        self.conversation_id = conversation_id
        self.tenant_id = tenant_id
        self.doubao = DoubaoClient(self.session_id)
        self.state = "idle"
        self.is_user_querying = False
        self.is_sending_custom_tts = False
        self.asr_text = ""
        self.bot_text_accumulator = ""
        self._query_task: asyncio.Task | None = None
        self._doubao_task: asyncio.Task | None = None
        self._event_waiters: dict[int, asyncio.Event] = {}
        self._last_waited_frame: dict = {}
        self._bridge = VoiceEngineBridge(
            conversation_id=conversation_id or self.session_id,
            tenant_id=tenant_id,
        )
        # Customer participant id used for engine.send_message(source=...).
        # Set in _ensure_conversation; literal "customer" was used earlier
        # but engine raises UnknownParticipant because join() was done with
        # the actual customer id (e.g. cust_xyz from the conv_id).
        self._customer_source: str | None = None

        start_config = start_config or {}
        self._session_config = copy.deepcopy(START_SESSION_CONFIG)
        if start_config.get("systemRole"):
            self._session_config["dialog"]["system_role"] = start_config["systemRole"]
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
            await self.doubao.connect()
            self._doubao_task = asyncio.create_task(self._read_doubao())

            await self._connect_and_greet()
            if self.state == "talking":
                await self._talking_loop()
        except Exception as e:
            log.exception("VoiceSession error")
            await self.send_error(str(e))
        finally:
            await self._cleanup()

    async def _ensure_conversation(self) -> None:
        """Idempotent — create the conversation in the engine if missing,
        join customer + agent participants. Safe to call when the chat
        side has already created the conv (engine.create_conversation
        returns the existing record). When conversation_id is None we
        skip silently — voice still plays, just no chat history sync."""
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
            # external_id derives the deterministic conv_id format
            # `web_{external_id}` — match what /ws/customer's customer_message
            # handler uses, so chat and voice converge on the same conv.
            ext_id = self.conversation_id
            if ext_id.startswith("web_"):
                ext_id = ext_id[len("web_"):]
            meta = {"channel": "web"}
            if self.tenant_id:
                meta["tenant_id"] = self.tenant_id
            conv = await engine.create_conversation(
                channel="web", external_id=ext_id, metadata=meta,
            )
            # The conv id from engine may differ from what frontend passed
            # if frontend used a non-`web_*` shape. Realign for downstream
            # _persist_to_engine + customer ws lookup.
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
                "voice _ensure_conversation: conv_id=%s tenant=%s source=%s",
                conv.id, self.tenant_id, ext_id,
            )
        except Exception:
            log.exception(
                "voice _ensure_conversation failed (conv=%s)",
                self.conversation_id,
            )

    async def _connect_and_greet(self) -> None:
        await self.send_state("connecting")

        await self.doubao.send_start_connection()
        frame = await self._wait_for_event(
            EVENT_CONNECTION_STARTED,
            error_event=EVENT_CONNECTION_FAILED,
            timeout=10.0,
        )
        if frame.get("event") == EVENT_CONNECTION_FAILED:
            raise ConnectionError(
                f"ConnectionFailed: {frame.get('payload_msg')}",
            )

        await self.doubao.send_start_session(self._session_config)
        frame = await self._wait_for_event(
            EVENT_SESSION_STARTED,
            error_event=EVENT_SESSION_FAILED,
            timeout=10.0,
        )
        if frame.get("event") == EVENT_SESSION_FAILED:
            raise ConnectionError(
                f"SessionFailed: {frame.get('payload_msg')}",
            )

        await self.send_state("greeting")
        await self.doubao.send_say_hello(self._greeting_text)
        # Persist greeting bubble in chat history (frontend dedupes via
        # metadata.voice_greeting). Mirrors the /tts auto-greet path so
        # both modes show the bubble.
        await self._persist_agent_text(
            self._greeting_text, extra_metadata={"voice_greeting": True},
        )
        await self._wait_for_event(EVENT_TTS_ENDED, timeout=30.0)
        await self.send_state("talking")

    async def _talking_loop(self) -> None:
        try:
            while True:
                message = await self.browser_ws.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                if "bytes" in message and message["bytes"] is not None:
                    await self.doubao.send_audio(message["bytes"])
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
        try:
            await self.doubao.send_finish_session()
            await self._wait_for_event(EVENT_SESSION_FINISHED, timeout=3.0)
        except (asyncio.TimeoutError, Exception):
            pass
        try:
            await self.doubao.send_finish_connection()
            await self._wait_for_event(EVENT_CONNECTION_FINISHED, timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            pass
        await self.send_state("idle")

    # ---------------- Doubao consumer ----------------

    async def _read_doubao(self) -> None:
        try:
            async for frame in self.doubao.receive():
                event = frame.get("event")
                if event in self._event_waiters:
                    self._last_waited_frame = frame
                    self._event_waiters[event].set()
                await self._dispatch_doubao_event(frame)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("Doubao read error: %s", e)

    async def _wait_for_event(
        self,
        target_event: int,
        timeout: float = 10.0,
        error_event: int | None = None,
    ) -> dict:
        evt = asyncio.Event()
        self._event_waiters[target_event] = evt
        if error_event:
            self._event_waiters[error_event] = evt
        try:
            await asyncio.wait_for(evt.wait(), timeout=timeout)
        finally:
            self._event_waiters.pop(target_event, None)
            if error_event:
                self._event_waiters.pop(error_event, None)
        return self._last_waited_frame

    async def _dispatch_doubao_event(self, frame: dict) -> None:
        event = frame.get("event")
        payload = frame.get("payload_msg")
        msg_type = frame.get("message_type")

        # Diagnostic: log every non-audio event with a short payload preview so
        # we can see what Doubao is producing across the connect → greet →
        # talk → custom-tts → external-rag lifecycle. Audio (TTS_RESPONSE) is
        # excluded because it's a binary payload and very chatty.
        if event != EVENT_TTS_RESPONSE:
            log.info(
                "doubao event=%s msg_type=%s flag=%s payload=%s",
                event, msg_type, self.is_sending_custom_tts,
                str(payload)[:200] if payload else None,
            )

        # TTS audio → forward to browser (suppress during custom-TTS injection
        # window so Doubao's auto-LLM TTS doesn't leak through).
        if event == EVENT_TTS_RESPONSE and isinstance(payload, bytes):
            self._tts_chunks_seen = getattr(self, "_tts_chunks_seen", 0) + 1
            self._tts_bytes_seen = getattr(self, "_tts_bytes_seen", 0) + len(payload)
            self._tts_bytes_forwarded = getattr(self, "_tts_bytes_forwarded", 0)
            forward = not self.is_sending_custom_tts
            if forward:
                self._tts_bytes_forwarded += len(payload)
            log.info(
                "doubao TTS_RESPONSE #%d (%d bytes) flag=%s → %s "
                "[total seen=%d forwarded=%d]",
                self._tts_chunks_seen, len(payload),
                self.is_sending_custom_tts,
                "forwarded" if forward else "suppressed",
                self._tts_bytes_seen, self._tts_bytes_forwarded,
            )
            if forward:
                try:
                    await self.browser_ws.send_bytes(payload)
                except Exception:
                    log.exception("doubao audio forward to browser failed")
            return

        if event == EVENT_TTS_SENTENCE_START and isinstance(payload, dict):
            tts_type = payload.get("tts_type", "")
            log.info(
                "doubao TTS_SENTENCE_START tts_type=%r → flag will be %s",
                tts_type,
                False if tts_type in ("chat_tts_text", "external_rag")
                else self.is_sending_custom_tts,
            )
            if tts_type in ("chat_tts_text", "external_rag"):
                self.is_sending_custom_tts = False
                if payload.get("text"):
                    await self.send_transcript("bot", payload["text"], False)
                # Signal the browser that a NEW bot utterance is starting
                # NOW. Frontend uses this to release any in-effect local
                # barge-in mute so the new sentence plays from its first
                # PCM chunk. Without this, a fast bridge.query (< 1.5 s)
                # can land while frontend's debounce timer is still
                # holding mute, which drops the leading chunks of the
                # new reply and the user hears mid-sentence.
                try:
                    await self.browser_ws.send_json({"type": "tts_resume"})
                except Exception:
                    pass
            return

        if event == EVENT_ASR_RESPONSE and isinstance(payload, dict):
            results = payload.get("results", [])
            if results:
                last = results[-1]
                text = last.get("text", "")
                is_interim = last.get("is_interim", True)
                if not is_interim:
                    self.asr_text = text
                await self.send_transcript("user", text, is_interim)
            return

        if event == EVENT_ASR_INFO:
            # User started speaking — interrupt any in-flight LLM/TTS.
            self.is_user_querying = True
            self.is_sending_custom_tts = False
            if self._query_task and not self._query_task.done():
                self._query_task.cancel()
            try:
                await self.browser_ws.send_json({"type": "clear_audio"})
            except Exception:
                pass
            return

        if event == EVENT_ASR_ENDED:
            self.is_user_querying = False
            log.info(
                "voice ASR_ENDED: conv=%s asr_text=%r",
                self.conversation_id, self.asr_text,
            )
            if self.asr_text:
                # Persist user voice utterance so it appears as a bubble.
                await self._persist_user_text(self.asr_text)
                self._query_task = asyncio.create_task(
                    self._run_query(self.asr_text),
                )
                self.asr_text = ""
            else:
                log.info(
                    "voice ASR_ENDED skipped query: empty asr_text",
                )
            return

        if event == EVENT_CHAT_RESPONSE and isinstance(payload, dict):
            if self.is_sending_custom_tts:
                return
            token = payload.get("content", "")
            if token:
                self.bot_text_accumulator += token
                await self.send_transcript(
                    "bot", self.bot_text_accumulator, True,
                )
            return

        if event == EVENT_CHAT_ENDED:
            if self.is_sending_custom_tts:
                self.bot_text_accumulator = ""
                return
            if self.bot_text_accumulator:
                await self.send_transcript(
                    "bot", self.bot_text_accumulator, False,
                )
                # Persist final bot text iff this is Doubao's *own* LLM.
                # When we run our own bridge, _run_query already persists.
                # Reaching here means we DIDN'T inject chat_rag_text, so
                # Doubao spoke its default LLM — persist that too.
                await self._persist_agent_text(self.bot_text_accumulator)
            self.bot_text_accumulator = ""
            return

        if event in (EVENT_CONNECTION_FAILED, EVENT_SESSION_FAILED):
            error_msg = (
                payload.get("error", f"Event {event} failed")
                if isinstance(payload, dict) else str(payload)
            )
            await self.send_error(error_msg)
            return

        if msg_type == "SERVER_ERROR":
            await self.send_error(
                f"Server error {frame.get('code')}: {payload}",
            )
            return

    # ---------------- Query orchestration ----------------

    async def _run_query(self, text: str) -> None:
        """Bridge result is spoken via a single ``chat_tts_text`` call so
        Doubao synthesizes the full reply continuously (no inter-sentence
        gaps from chunked streaming).

        ``state="thinking"`` is sent up front so the UI shows a
        thinking indicator while we wait for cc_pool.

        The frontend renders the agent bubble with a client-side
        typewriter animation (see MessageBubble) — the chat-side message
        is still sent in one shot here; visual streaming is purely a
        rendering effect.
        """
        try:
            log.info(
                "voice _run_query start: conv=%s text=%r",
                self.conversation_id, text,
            )
            await self.send_state("thinking")
            self.is_sending_custom_tts = True

            result = await self._bridge.query(text, timeout=60.0)
            log.info(
                "voice _run_query bridge returned len=%d preview=%r",
                len(result), result[:120],
            )

            if self.is_user_querying:
                log.info("voice _run_query aborted: user re-queried during bridge")
                self.is_sending_custom_tts = False
                return

            if not result.strip():
                log.warning("voice _run_query: empty bridge result, skipping TTS")
                return

            # Re-arm suppression in case Doubao default LLM races a few
            # frames in just before our chat_tts_text takes over.
            self.is_sending_custom_tts = True

            await self.doubao.send_chat_tts_text(
                result, start=True, end=False,
            )
            await self.doubao.send_chat_tts_text(
                "", start=False, end=True,
            )
            log.info(
                "voice _run_query bridge result sent as single "
                "chat_tts_text (len=%d)", len(result),
            )
            await self._persist_agent_text(result)
        except asyncio.CancelledError:
            log.info("voice _run_query cancelled")
            self.is_sending_custom_tts = False
        except Exception as e:
            self.is_sending_custom_tts = False
            log.error("VoiceSession query error: %s", e)

    # ---------------- Engine sync ----------------

    async def _persist_user_text(self, text: str) -> None:
        # Use the actual customer participant id (set by _ensure_conversation).
        # Falling back to "customer" would raise UnknownParticipant since
        # we joined with the customer's external_id.
        if not self._customer_source:
            return
        # push_to_customer=False — frontend's voice path already inserts an
        # optimistic right-side user bubble on the ASR final transcript
        # (see VoiceCallController._onTranscript → onUserMessage). Pushing
        # the engine-persisted message back as a `message` frame would
        # render a *second* bubble for the same utterance.
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
        """Persist a message to the conversation engine, optionally pushing
        the resulting frame to the customer's chat WS.

        ``role`` is written into ``source_display.role`` on the pushed
        frame (overrides ``_message_frame``'s hard-coded "agent").

        ``push_to_customer`` controls whether the customer's own chat WS
        receives the frame. Set False for customer voice utterances —
        the frontend already inserted an optimistic bubble locally and a
        push would duplicate. Always True for agent text.
        """
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
                "VoiceSession engine persist failed (conv=%s, source=%s)",
                self.conversation_id, source,
            )

    # ---------------- Cleanup ----------------

    async def _cleanup(self) -> None:
        # CRITICAL: await cancelled _query_task. Without await, the
        # cancellation never propagates into bridge.query's drain loop,
        # so the SDK's receive_response generator stays paused with
        # pending Claude response messages buffered. On the NEXT
        # /ws/voice connect (same conv_id → same sticky instance), the
        # next session_query reads those leftover messages first,
        # producing the symptom "the bot replays the previous turn's
        # unfinished reply" or "responses lag by one turn".
        if self._query_task and not self._query_task.done():
            self._query_task.cancel()
            try:
                await asyncio.wait_for(self._query_task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
        if self._doubao_task and not self._doubao_task.done():
            self._doubao_task.cancel()
            try:
                await self._doubao_task
            except asyncio.CancelledError:
                pass
        try:
            await self.doubao.close()
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
