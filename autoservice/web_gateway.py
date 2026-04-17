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

from pathlib import Path

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
from autoservice.gateway.message_router import dispatch, get_subscription_registry, replay_messages
from autoservice.takeover_config import TakeoverConfig, load_takeover_config

logger = logging.getLogger("autoservice.gateway")

_CORS_ORIGINS = [
    f"http://localhost:{p}" for p in range(5173, 5180)
]

_CLOSE_CODE_VERSION = 4040

# Global WebSocket connection registry: session_id → WebSocket
_ws_connections: dict[str, WebSocket] = {}

# Admin WS connections for alert push (T6E.7): session_id → WebSocket
_admin_connections: dict[str, WebSocket] = {}

# Test-only override; production loads from .autoservice/config.local.yaml
_TAKEOVER_CONFIG_OVERRIDE: TakeoverConfig | None = None

# operator_id → set of session_ids (for targeted pushes)
_operator_sessions: dict[str, set[str]] = {}

# Global CCPool reference (lazily initialized)
_pool = None
_pool_lock = asyncio.Lock()


_squad_plugin_ref = None

def _get_squad_plugin():
    return _squad_plugin_ref


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


async def _send_to_operator(operator_id: str, frame: dict) -> None:
    """Push a frame to every session held by a given operator_id."""
    for session_id in list(_operator_sessions.get(operator_id, set())):
        ws = _ws_connections.get(session_id)
        if ws is None:
            continue
        try:
            await ws.send_json(frame)
        except Exception:
            pass


async def _broadcast_cancelled(conv_id: str, frame: dict) -> None:
    """Broadcast takeover_warning_cancelled to any session subscribed to the conv's squad."""
    from autoservice.gateway.message_router import _broadcast_to_squad
    await _broadcast_to_squad(frame, conv_id)


async def _push_alert_to_admins(alert) -> None:
    """Push a FiredAlert to all connected admin WebSocket sessions (T6E.7)."""
    from autoservice.gateway.connection import build_frame
    from dataclasses import asdict

    frame = build_frame("sla_alert", asdict(alert))
    stale: list[str] = []
    for sid, ws in list(_admin_connections.items()):
        try:
            await ws.send_json(frame)
        except Exception:
            logger.debug("admin ws %s unreachable, removing", sid)
            stale.append(sid)
    for sid in stale:
        _admin_connections.pop(sid, None)


def create_app(engine: ConversationEngine | None = None) -> FastAPI:
    """Build the FastAPI app with 3 WS endpoints + CORS."""
    app = FastAPI(title="autoservice-gateway", version="0.6.0")

    if engine is None:
        # Load takeover config (test hook wins, else YAML, else defaults)
        if _TAKEOVER_CONFIG_OVERRIDE is not None:
            takeover_cfg = _TAKEOVER_CONFIG_OVERRIDE
        else:
            takeover_cfg = load_takeover_config(Path(".autoservice/config.local.yaml"))
        engine = LocalEngine(config={"takeover": takeover_cfg})

    app.state.engine = engine

    # Wire takeover notifications to WS push
    def _push_takeover_warning(payload: dict) -> None:
        """Callback invoked from engine's _warning() coroutine; event loop is live."""
        operator_id = payload["operator_id"]
        frame = build_frame("takeover_warning", {
            "conversation_id": payload["conversation_id"],
            "remaining_ms": payload["remaining_ms"],
            "reason": payload["reason"],
        })
        async def _safe_push():
            try:
                await _send_to_operator(operator_id, frame)
            except Exception:
                logger.exception("failed to push takeover_warning to operator=%s", operator_id)
        asyncio.create_task(_safe_push())

    def _push_takeover_cancelled(payload: dict) -> None:
        """Callback invoked from engine's reset_takeover_timer; event loop is live."""
        frame = build_frame("takeover_warning_cancelled", {
            "conversation_id": payload["conversation_id"],
        })
        conv_id = payload["conversation_id"]
        async def _safe_push():
            try:
                await _broadcast_cancelled(conv_id, frame)
            except Exception:
                logger.exception("failed to broadcast takeover_warning_cancelled for conv=%s", conv_id)
        asyncio.create_task(_safe_push())

    if hasattr(engine, "on_takeover_warning"):
        engine.on_takeover_warning(_push_takeover_warning)
    if hasattr(engine, "on_takeover_warning_cancelled"):
        engine.on_takeover_warning_cancelled(_push_takeover_cancelled)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register squad plugin
    from autoservice.plugins.squad_plugin import SquadPlugin
    _squad_plugin = SquadPlugin(squad_config={
        "default_squad": "general",
        "channel_routing": {"web": "web-support", "feishu": "feishu-support"},
    })
    global _squad_plugin_ref
    app.state.squad_plugin = _squad_plugin
    _squad_plugin_ref = _squad_plugin
    try:
        app.state.engine.register_hook(_squad_plugin)
    except Exception:
        pass  # engine may not support register_hook

    # Mount REST APIs
    from autoservice.onboarding import onboard_router
    from autoservice.api_routes import api_router, _set_engine
    app.include_router(onboard_router)
    app.include_router(api_router)
    _set_engine(app.state.engine)

    # Wire SLA alert push to admin WebSocket connections (T6E.7)
    try:
        from autoservice.alert_engine import AlertEngine
        from autoservice.sla_aggregator import SLAAggregator

        aggregator = getattr(app.state, "sla_aggregator", None)
        if aggregator is None:
            aggregator = SLAAggregator()
            app.state.sla_aggregator = aggregator
        alert_engine = AlertEngine(aggregator)
        alert_engine.set_notify(_push_alert_to_admins)
        app.state.alert_engine = alert_engine
        logger.info("AlertEngine wired with admin WS push")
    except Exception:
        logger.warning("AlertEngine init failed, alerts disabled", exc_info=True)

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
    if viewer_role == "admin":
        _admin_connections[session_id] = ws

    # Track operator_id → sessions for targeted pushes
    client_operator_id = env.payload.get("operator_id")
    if viewer_role == "operator" and client_operator_id:
        _operator_sessions.setdefault(client_operator_id, set()).add(session_id)
        ws.state_operator_id = client_operator_id  # for finally cleanup

    await ws.send_json(
        build_frame(
            "server_hello",
            build_server_hello(viewer_role=viewer_role, session_id=session_id),
            ref=env.id,
        )
    )

    # --- Reconnect message replay (T6A.3) ---
    last_seen = env.payload.get("last_seen")
    if last_seen and isinstance(last_seen, dict):
        try:
            replayed = await replay_messages(ws, engine, last_seen)
            if replayed:
                logger.info(
                    "replayed %d message(s) for session %s", replayed, session_id,
                )
        except Exception:
            logger.warning("replay failed for session %s", session_id, exc_info=True)

    # --- Frame loop ---
    try:
        while True:
            raw = await ws.receive_json()
            frames = await _process_frame(
                raw, viewer_role=viewer_role, engine=engine, ws=ws,
                session_id=session_id,
            )
            for frame in frames:
                await ws.send_json(frame)
    except WebSocketDisconnect:
        logger.info("ws %s disconnected (session=%s)", viewer_role, session_id)
    finally:
        # Evict all subscriptions for this session (T6A.1)
        registry = get_subscription_registry()
        evicted = registry.evict_by_session(session_id)
        if evicted:
            logger.info(
                "evicted %d subscription(s) for session %s", len(evicted), session_id,
            )
        _ws_connections.pop(session_id, None)
        _admin_connections.pop(session_id, None)
        # Clean operator_sessions index
        op_id = getattr(ws, "state_operator_id", None)
        if op_id:
            sess_set = _operator_sessions.get(op_id)
            if sess_set and session_id in sess_set:
                sess_set.discard(session_id)
                if not sess_set:
                    _operator_sessions.pop(op_id, None)


async def _process_frame(
    raw: Any, *, viewer_role: str, engine: ConversationEngine, ws: WebSocket,
    session_id: str | None = None,
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

    return await dispatch(env, viewer_role=viewer_role, engine=engine, ws=ws, session_id=session_id)


# Module-level app for `uvicorn autoservice.web_gateway:app`
app = create_app()
