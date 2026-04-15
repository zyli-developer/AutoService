"""FastAPI WebSocket gateway app factory (T0.5 skeleton).

Launch:
    uvicorn autoservice.web_gateway:app

Test:
    from autoservice.web_gateway import create_app
    from starlette.testclient import TestClient
    client = TestClient(create_app())
"""

from __future__ import annotations

import logging
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
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
]

_CLOSE_CODE_VERSION = 4040


def create_app(engine: ConversationEngine | None = None) -> FastAPI:
    """Build the FastAPI app with 3 WS endpoints + CORS.

    Args:
        engine: ConversationEngine implementation. Defaults to LocalEngine().

    Returns:
        FastAPI app with /ws/customer, /ws/operator, /ws/admin routes.
    """
    app = FastAPI(title="autoservice-gateway", version="0.5.0")
    app.state.engine = engine or LocalEngine()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
            frames = await _process_frame(raw, viewer_role=viewer_role, engine=engine)
            for frame in frames:
                await ws.send_json(frame)
    except WebSocketDisconnect:
        logger.info("ws %s disconnected (session=%s)", viewer_role, session_id)


async def _process_frame(
    raw: Any, *, viewer_role: str, engine: ConversationEngine
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

    return await dispatch(env, viewer_role=viewer_role, engine=engine)


# Module-level app for `uvicorn autoservice.web_gateway:app`
app = create_app()
