"""FastAPI WebSocket gateway app factory.

Launch:
    uvicorn autoservice.web_gateway:create_app --factory

Test:
    from autoservice.web_gateway import create_app
    from starlette.testclient import TestClient
    client = TestClient(create_app())
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from autoservice.conversation_engine import ConversationEngine, LocalEngine
from autoservice.gateway.connection import (
    build_frame,
    build_server_hello,
    generate_session_id,
)
from autoservice.gateway.envelope import ACCEPTED_VERSIONS, parse_envelope
from autoservice.gateway.errors import (
    ERR_VALIDATION,
    ERR_VERSION_INCOMPATIBLE,
    make_error_payload,
)
from autoservice.gateway.message_router import dispatch

logger = logging.getLogger("autoservice.gateway")

_CORS_ORIGINS = [
    f"http://localhost:{p}" for p in range(5173, 5180)
]

_CLOSE_CODE_VERSION = 4040

# Global WebSocket connection registry: session_id → WebSocket
_ws_connections: dict[str, WebSocket] = {}

# Global CCPool reference (lazily initialized)
_pool = None
_pool_lock = asyncio.Lock()


async def _get_pool():
    """Lazy-init the CCPool singleton. Returns None if pool_mode is off."""
    global _pool
    if _pool is not None:
        return _pool
    if not os.environ.get("POOL_MODE", "1") == "1":
        return None
    async with _pool_lock:
        if _pool is not None:
            return _pool
        try:
            from autoservice.cc_pool import get_pool
            _pool = await get_pool()
            logger.info("CCPool started for web gateway")
            return _pool
        except Exception as exc:
            logger.warning("CCPool init failed, running without AI agent: %s", exc)
            return None


def create_app(engine: ConversationEngine | None = None) -> FastAPI:
    """Build the FastAPI app with 3 WS endpoints + CORS."""
    app = FastAPI(title="autoservice-gateway", version="0.6.0")
    app.state.engine = engine or LocalEngine()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount REST APIs
    from autoservice.onboarding import onboard_router
    from autoservice.api_routes import api_router, _set_engine
    app.include_router(onboard_router)
    app.include_router(api_router)
    _set_engine(app.state.engine)

    for role in ("customer", "operator", "admin"):
        app.add_api_websocket_route(
            f"/ws/{role}",
            _make_endpoint(role),
            name=f"ws_{role}",
        )

    return app


def _make_endpoint(viewer_role: str):
    async def endpoint(ws: WebSocket) -> None:
        await _handle_connection(ws, viewer_role=viewer_role)

    endpoint.__name__ = f"ws_{viewer_role}_endpoint"
    return endpoint


async def _handle_connection(ws: WebSocket, *, viewer_role: str) -> None:
    await ws.accept()
    engine: ConversationEngine = ws.app.state.engine

    # --- Handshake: expect client_hello ---
    try:
        first_raw = await ws.receive_json()
    except WebSocketDisconnect:
        return

    env, err_details = parse_envelope(first_raw)
    if env is None or env.type != "client_hello":
        await ws.send_json(
            build_frame(
                "error",
                make_error_payload(
                    ERR_VALIDATION,
                    "handshake required: expected client_hello",
                    details=err_details or {"reason": "handshake_required"},
                ),
                ref=(env.id if env else None),
            )
        )
        await ws.close(code=1002)
        return

    client_version = env.payload.get("protocol_version")
    if client_version not in ACCEPTED_VERSIONS:
        await ws.send_json(
            build_frame(
                "error",
                make_error_payload(
                    ERR_VERSION_INCOMPATIBLE,
                    f"protocol version {client_version!r} not supported",
                    details={"accepted": sorted(ACCEPTED_VERSIONS)},
                ),
                ref=env.id,
            )
        )
        await ws.close(code=_CLOSE_CODE_VERSION)
        return

    session_id = generate_session_id()
    _ws_connections[session_id] = ws

    await ws.send_json(
        build_frame(
            "server_hello",
            build_server_hello(viewer_role=viewer_role, session_id=session_id),
            ref=env.id,
        )
    )

    # --- Frame loop ---
    try:
        while True:
            raw = await ws.receive_json()
            frames = await _process_frame(
                raw, viewer_role=viewer_role, engine=engine, ws=ws,
            )
            for frame in frames:
                await ws.send_json(frame)
    except WebSocketDisconnect:
        logger.info("ws %s disconnected (session=%s)", viewer_role, session_id)
    finally:
        _ws_connections.pop(session_id, None)


async def _process_frame(
    raw: Any, *, viewer_role: str, engine: ConversationEngine, ws: WebSocket,
) -> list[dict[str, Any]]:
    env, err_details = parse_envelope(raw)
    if env is None:
        return [
            build_frame(
                "error",
                make_error_payload(
                    ERR_VALIDATION,
                    "envelope validation failed",
                    details=err_details or {},
                ),
            )
        ]

    if env.v not in ACCEPTED_VERSIONS:
        return [
            build_frame(
                "error",
                make_error_payload(
                    ERR_VERSION_INCOMPATIBLE,
                    f"protocol version {env.v!r} not supported",
                    details={"accepted": sorted(ACCEPTED_VERSIONS)},
                ),
                ref=env.id,
            )
        ]

    return await dispatch(env, viewer_role=viewer_role, engine=engine, ws=ws)


# Module-level app for `uvicorn autoservice.web_gateway:app`
app = create_app()
