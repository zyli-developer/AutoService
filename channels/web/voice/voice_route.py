"""/ws/voice — full E2E / split-mode voice session endpoint.

Mirror of cc-openclaw/voice_gateway/server.py::ws_handler ported to
FastAPI. The browser opens one WebSocket and sends a JSON `start`
frame whose ``mode`` field selects the session type:

    {"type": "start", "mode": "e2e_session"}    → VoiceSession (default)
    {"type": "start", "mode": "split"}           → VoiceSplitSession
    {"type": "start", "mode": "e2e"}             → alias for e2e_session
                                                   (cc-openclaw compat)

Optional context comes from query params:

    /ws/voice?conversation_id=conv_xyz&tenant=acme

…and is used to bind the LLM bridge (cc_pool.session_query) to the
right tenant + conversation, and to persist user/agent voice text into
the conversation engine for chat-history sync.

The standalone ``/asr`` and ``/tts`` adapter endpoints in
`asr_route.py` / `tts_route.py` are unchanged — this is an additional
mode, not a replacement.
"""
from __future__ import annotations

import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

log = logging.getLogger(__name__)


_MODE_E2E_SESSION = {"e2e_session", "e2e"}
_MODE_SPLIT = {"split"}


async def voice_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    log.info("[/ws/voice] browser connected")

    conversation_id = ws.query_params.get("conversation_id")
    tenant_id = ws.query_params.get("tenant")

    try:
        first = await ws.receive_text()
    except WebSocketDisconnect:
        return
    except Exception as e:
        log.warning("[/ws/voice] failed to read start frame: %s", e)
        await _safe_close(ws)
        return

    try:
        data = json.loads(first)
    except json.JSONDecodeError:
        try:
            await ws.send_json({"type": "error", "message": "invalid start frame"})
        except Exception:
            pass
        await _safe_close(ws)
        return

    if data.get("type") != "start":
        try:
            await ws.send_json({
                "type": "error",
                "message": "first frame must be type=start",
            })
        except Exception:
            pass
        await _safe_close(ws)
        return

    mode = (data.get("mode") or "e2e_session").lower()
    log.info(
        "[/ws/voice] starting mode=%s conv=%s tenant=%s",
        mode, conversation_id, tenant_id,
    )

    if mode in _MODE_SPLIT:
        from .session_split import VoiceSplitSession
        session = VoiceSplitSession(
            ws,
            start_config=data,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
        )
    elif mode in _MODE_E2E_SESSION:
        from .session import VoiceSession
        session = VoiceSession(
            ws,
            start_config=data,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
        )
    else:
        try:
            await ws.send_json({
                "type": "error",
                "message": f"unknown mode: {mode}",
            })
        except Exception:
            pass
        await _safe_close(ws)
        return

    try:
        await session.run()
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("[/ws/voice] session crashed")
    finally:
        await _safe_close(ws)
        log.info("[/ws/voice] browser disconnected")


async def _safe_close(ws: WebSocket) -> None:
    if ws.client_state != WebSocketState.DISCONNECTED:
        try:
            await ws.close()
        except Exception:
            pass
