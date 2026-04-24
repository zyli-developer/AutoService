"""Stateless ASR WebSocket endpoint — proxies browser PCM → Doubao ASR → text frames.

Ported from cc-openclaw/voice_gateway/asr_route.py (aiohttp) to FastAPI.
Logical flow unchanged:
  1. Accept WebSocket.
  2. Wait for {"type": "start"} text frame.
  3. Connect ASRClient to Doubao.
  4. Concurrently:
     - Forward binary PCM frames from browser → Doubao.
     - Forward normalized ASR events from Doubao → browser as
       {"type": "speech_started"|"partial"|"final", ...}.
  5. Stop on {"type": "stop"} text frame, WS close, or ASR error.
"""
import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .asr_client import ASRClient

log = logging.getLogger(__name__)


# Volcengine/Doubao event types emitted by ASRClient.receive()
_EV_PARTIAL = "conversation.item.input_audio_transcription.result"
_EV_FINAL = "conversation.item.input_audio_transcription.completed"
_EV_SPEECH_STARTED = "input_audio_buffer.speech_started"


async def asr_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    log.info("[/asr] browser connected")

    asr = ASRClient()
    try:
        first = await ws.receive_text()
        try:
            data = json.loads(first)
        except json.JSONDecodeError:
            await ws.send_json({"type": "error", "message": "invalid start frame"})
            return
        if data.get("type") != "start":
            await ws.send_json({"type": "error", "message": "first frame must be type=start"})
            return

        await asr.connect()

        reader_task = asyncio.create_task(_forward_asr_events(asr, ws))
        browser_task = asyncio.create_task(_forward_browser_audio(ws, asr))

        done, pending = await asyncio.wait(
            {reader_task, browser_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("[/asr] error")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await asr.close()
        except Exception:
            pass
        if ws.client_state != WebSocketState.DISCONNECTED:
            try:
                await ws.close()
            except Exception:
                pass
        log.info("[/asr] browser disconnected")


async def _forward_asr_events(asr: ASRClient, ws: WebSocket) -> None:
    async for event in asr.receive():
        evt_type = event.get("type", "")
        text = event.get("transcript", "")

        if evt_type == _EV_PARTIAL and text:
            await ws.send_json({"type": "partial", "text": text})
        elif evt_type == _EV_FINAL and text:
            await ws.send_json({"type": "final", "text": text})
        elif evt_type == _EV_SPEECH_STARTED:
            await ws.send_json({"type": "speech_started"})
        elif evt_type.startswith("error") or "error" in event:
            await ws.send_json({
                "type": "error",
                "message": event.get("error", {}).get("message", "ASR error"),
            })


async def _forward_browser_audio(ws: WebSocket, asr: ASRClient) -> None:
    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                return
            if "bytes" in message and message["bytes"] is not None:
                await asr.send_audio(message["bytes"])
            elif "text" in message and message["text"] is not None:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "stop":
                    return
    except WebSocketDisconnect:
        return
