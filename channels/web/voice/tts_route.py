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

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .tts_client import TTSClient

log = logging.getLogger(__name__)


async def _cancel_and_wait(task: asyncio.Task | None) -> None:
    if task and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def tts_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    log.info("[/tts] browser connected")

    tts: TTSClient | None = None
    current_task: asyncio.Task | None = None

    try:
        tts = TTSClient()
        await tts.connect()

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
