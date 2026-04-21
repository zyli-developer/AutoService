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
from autoservice.gateway.offline_watcher import OfflineWatcher
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
    sessions = list(_operator_sessions.get(operator_id, set()))
    logger.warning(
        "[TK] send_to_operator op=%s type=%s sessions=%d",
        operator_id, frame.get("type"), len(sessions),
    )
    for session_id in sessions:
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
    else:
        # Engine provided externally — extract its takeover config if available
        takeover_cfg = getattr(engine, "_takeover_config", None)
        if takeover_cfg is None:
            from autoservice.takeover_config import DEFAULT_TAKEOVER_CONFIG
            takeover_cfg = DEFAULT_TAKEOVER_CONFIG

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

    def _push_takeover_armed(payload: dict) -> None:
        """Callback when engine arms/re-arms a takeover timer; notify operator."""
        operator_id = payload["operator_id"]
        frame = build_frame("takeover_timer_armed", {
            "conversation_id": payload["conversation_id"],
            "armed_at": payload["armed_at"],
            "idle_timeout_ms": payload["idle_timeout_ms"],
            "warning_ms": payload["warning_ms"],
        })
        async def _safe_push():
            try:
                await _send_to_operator(operator_id, frame)
            except Exception:
                logger.exception("failed to push takeover_timer_armed op=%s", operator_id)
        asyncio.create_task(_safe_push())

    if hasattr(engine, "on_takeover_warning"):
        engine.on_takeover_warning(_push_takeover_warning)
    if hasattr(engine, "on_takeover_warning_cancelled"):
        engine.on_takeover_warning_cancelled(_push_takeover_cancelled)
    if hasattr(engine, "on_takeover_armed"):
        engine.on_takeover_armed(_push_takeover_armed)

    app.state.offline_watcher = OfflineWatcher(engine, grace_ms=takeover_cfg.offline_grace_ms)

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

        # Per-record breach → immediate sla_alert frame to admins (Issue 5).
        # Complements AlertEngine's window-based aggregate alerts.
        def _on_per_record_breach(info: dict) -> None:
            from autoservice.gateway.connection import build_frame
            frame = build_frame("sla_alert", {
                "severity": info["severity"],
                "message": (
                    f"SLA threshold breached: {info['metric']}={info['value']:.0f} "
                    f"({info['comparator']} {info['limit']})"
                ),
                "details": info,
                "source": "per_record",
            })
            async def _push():
                stale: list[str] = []
                for sid, ws in list(_admin_connections.items()):
                    try:
                        await ws.send_json(frame)
                    except Exception:
                        stale.append(sid)
                for sid in stale:
                    _admin_connections.pop(sid, None)
            try:
                asyncio.create_task(_push())
            except RuntimeError:
                pass
        aggregator.set_breach_callback(_on_per_record_breach)

        logger.info("AlertEngine wired with admin WS push (aggregate + per-record)")
    except Exception:
        logger.warning("AlertEngine init failed, alerts disabled", exc_info=True)

    for role in ("customer", "operator", "admin"):
        app.add_api_websocket_route(
            f"/ws/{role}",
            _make_endpoint(role),
            name=f"ws_{role}",
        )

    @app.on_event("startup")
    async def _bootstrap_internal_tenants() -> None:
        """M2 spec §2.7/§2.8 — ensure _master or _local_admin exists per mode."""
        try:
            from autoservice import bootstrap, master_tenant
            mode = bootstrap.get_deployment_mode()
            if mode == "master":
                created = master_tenant.ensure_master_tenant()
                logger.info(
                    "master-mode bootstrap: _master %s",
                    "provisioned" if created else "already present",
                )
            else:
                created = master_tenant.ensure_local_admin()
                logger.info(
                    "tenant-mode bootstrap: _local_admin %s",
                    "provisioned" if created else "already present",
                )
        except FileNotFoundError:
            # Absent config.local.yaml → non-fatal in dev (M1 default behavior);
            # later auth setup will fail loudly if actually needed.
            logger.warning(
                "skipping internal-tenant bootstrap: .autoservice/config.local.yaml not found",
            )
        except Exception:
            logger.warning("internal-tenant bootstrap failed", exc_info=True)

    @app.on_event("startup")
    async def _warm_cc_pool() -> None:
        # Eagerly init pool so .autoservice/cc_pool_status.json appears
        # right after `make start`, instead of waiting for the first message.
        try:
            await _get_pool()
        except Exception:
            logger.warning("eager CCPool warm-up failed", exc_info=True)

    @app.on_event("startup")
    async def _start_dream_scheduler() -> None:
        """T4B.2 — start the DreamScheduler background loop (spec §2.6).

        Registers the scheduler as the module-level singleton so the
        ``/dream-config`` confirm path (``on_config_confirmed``) can
        invalidate cached tenant config on the next tick.

        Disabled when ``DREAM_SCHEDULER_DISABLED=1`` — useful for CI and
        for the TestClient-based smoke tests that bring the app up
        without an event loop long enough to service real background work.
        """
        if os.environ.get("DREAM_SCHEDULER_DISABLED") == "1":
            return
        try:
            from autoservice.dream_scheduler import (
                DreamScheduler,
                set_scheduler,
            )
            sched = DreamScheduler()
            await sched.start()
            set_scheduler(sched)
            app.state.dream_scheduler = sched
            logger.info("DreamScheduler started")
        except Exception:
            logger.warning("DreamScheduler startup failed", exc_info=True)

    @app.on_event("shutdown")
    async def _stop_dream_scheduler() -> None:
        """Pair of :func:`_start_dream_scheduler` — cancel the loop cleanly."""
        try:
            sched = getattr(app.state, "dream_scheduler", None)
            if sched is None:
                return
            await sched.stop()
            from autoservice.dream_scheduler import set_scheduler
            set_scheduler(None)
        except Exception:
            logger.debug("DreamScheduler shutdown failed", exc_info=True)

    @app.on_event("shutdown")
    async def _shutdown_cc_pool() -> None:
        try:
            from autoservice.cc_pool import shutdown_pool
            await shutdown_pool()
        except Exception:
            logger.debug("CCPool shutdown failed", exc_info=True)

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
        # Tell the offline watcher this operator is online
        ws.app.state.offline_watcher.on_connect(client_operator_id)

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
                    # Operator has no remaining sessions → tell watcher they're offline
                    try:
                        ws.app.state.offline_watcher.on_disconnect(op_id)
                    except Exception:
                        pass


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
