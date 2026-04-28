"""Stateless TTS WebSocket endpoint — accepts speak/abort, streams PCM back.

Ported from cc-openclaw/voice_gateway/tts_route.py (aiohttp) to FastAPI.
Cancels in-flight synthesize on abort or on new speak, waits for the
cancelled task to finish before starting the next one to prevent PCM
interleave on the wire.

Hardening applied preemptively (same lessons as /asr T3 review):
  - TTSClient() is constructed inside the try, AFTER ws.accept(); if
    accept() ever failed we would leak nothing.
  - _do_speak exceptions are surfaced to the browser as error frames
    (already present in aiohttp source; preserved verbatim here).
"""
import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .config import GREETING_TEXT
from .tts_client import TTSClient

log = logging.getLogger(__name__)


async def _cancel_and_wait(task: asyncio.Task | None) -> None:
    if task and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def _persist_greeting_in_chat(
    app: Any, conversation_id: str, text: str
) -> None:
    """Persist the voice greeting as an `agent` message and push the
    resulting `message` frame to the customer's /ws/customer connection so
    the bubble appears in chat history alongside the audio playback.

    The frontend's voice-forward useEffect skips messages whose metadata
    contains ``voice_greeting: True`` so this bubble doesn't get re-spoken.
    """
    try:
        engine = getattr(app.state, "engine", None)
        if engine is None:
            log.warning(
                "[/tts] greeting persist skipped: no engine in app.state "
                "(conv=%s)", conversation_id,
            )
            return
        msg = await engine.send_message(
            conversation_id,
            source="agent",
            content=text,
            metadata={"voice_greeting": True},
        )
        # Look up the customer's chat WS in the gateway-owned registry and
        # push the frame directly. engine.send_message also fires a
        # MESSAGE_SENT event, but the customer endpoint reads from
        # _customer_ws_by_conv (not the subscription fan-out) for its
        # message frames, so we mirror that path here.
        from autoservice.gateway.message_router import (
            _customer_ws_by_conv,
            _message_frame,
        )
        cust_ws = _customer_ws_by_conv.get(conversation_id)
        if cust_ws is None:
            log.info(
                "[/tts] greeting persisted but no customer WS to push "
                "(conv=%s)", conversation_id,
            )
            return
        try:
            await cust_ws.send_json(_message_frame(msg))
        except Exception:
            log.warning(
                "[/tts] greeting frame push failed conv=%s", conversation_id,
            )
    except Exception:
        log.exception(
            "[/tts] greeting persist failed conv=%s", conversation_id,
        )


async def tts_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    log.info("[/tts] browser connected")

    tts: TTSClient | None = None
    current_task: asyncio.Task | None = None

    # Optional context for chat-side greeting bubble. Frontend appends
    # ?conversation_id=... once it has the id from server_hello. Missing
    # conversation_id ⇒ voice still plays, just no chat bubble persistence.
    conversation_id = ws.query_params.get("conversation_id")

    try:
        tts = TTSClient()
        await tts.connect()

        # Backend-driven greeting: now that the TTS upstream is established,
        # speak the configured greeting before handling any client frames.
        # The frontend transitions to 'speaking' on /tts open and falls back
        # to 'listening' on the matching {type:"done"} this task emits.
        if GREETING_TEXT:
            log.info(
                "[/tts] auto-greet on connect (conv=%s)", conversation_id,
            )
            current_task = asyncio.create_task(_do_speak(tts, ws, GREETING_TEXT))
            if conversation_id:
                # Fire-and-forget: persist + push chat bubble in parallel
                # with audio synthesis. Errors are logged inside the helper.
                asyncio.create_task(
                    _persist_greeting_in_chat(
                        ws.app, conversation_id, GREETING_TEXT,
                    ),
                    name=f"voice-greeting-persist-{conversation_id}",
                )

        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
            text = message.get("text")
            if text is None:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue

            action = data.get("type")
            if action == "speak":
                utterance = data.get("text", "")
                await _cancel_and_wait(current_task)
                current_task = asyncio.create_task(_do_speak(tts, ws, utterance))
            elif action == "abort":
                await _cancel_and_wait(current_task)
                current_task = None
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("[/tts] error")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        await _cancel_and_wait(current_task)
        if tts is not None:
            try:
                await tts.close()
            except Exception:
                pass
        if ws.client_state != WebSocketState.DISCONNECTED:
            try:
                await ws.close()
            except Exception:
                pass
        log.info("[/tts] browser disconnected")


async def _do_speak(tts: TTSClient, ws: WebSocket, text: str) -> None:
    try:
        async for chunk in tts.synthesize(text):
            await ws.send_bytes(chunk)
        await ws.send_json({"type": "done"})
    except asyncio.CancelledError:
        log.info("[/tts] speak cancelled")
        raise
    except Exception as e:
        log.error("[/tts] speak error: %s", e)
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
