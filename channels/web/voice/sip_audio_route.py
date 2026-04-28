"""SIP audio gateway — bridges jambonz audio_fork → AutoService voice pipeline.

Wire protocol (jambonz audio_fork):
  - Text frame (1st):  {"event":"start","callSid":"...","from":"...","to":"..."}
  - Binary frames in:  PCM 16-bit LE 16kHz mono
  - Binary frames out: PCM 16-bit LE 16kHz mono (jambonz resamples to PCMA 8k)
  - Text frame (last): {"event":"stop"}

Thin adapter. All conversation logic lives in
:class:`channels.web.voice.sip_controller.SipVoiceController`.

Auth: relies on Cloudflare Access service token. jambonz attaches
``CF-Access-Client-Id`` and ``CF-Access-Client-Secret`` headers on every
WS upgrade, and Cloudflare validates them at the edge before forwarding
to uvicorn. Token rotation lives in CF dashboard, not in this codebase.
See docs/sip-deploy/07-deployment-cinnox-integration.md §4.1.
"""
from __future__ import annotations

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
            log.warning("[/sip-audio] start frame is not JSON; closing")
            return
        if meta.get("event") != "start":
            log.warning("[/sip-audio] first frame event=%r != start; closing", meta.get("event"))
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
            try:
                await controller.shutdown()
            except Exception:
                log.exception("[/sip-audio] shutdown error")
        if ws.client_state != WebSocketState.DISCONNECTED:
            try:
                await ws.close()
            except Exception:
                pass
        log.info("[/sip-audio] cleanup done")
