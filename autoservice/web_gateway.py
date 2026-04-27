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

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from autoservice.conversation_engine import ConversationEngine, LocalEngine
from autoservice.conversation_engine.sqlite_store import (
    DEFAULT_DB_PATH as _CONV_DB_DEFAULT_PATH,
    ConversationStore,
)
from autoservice.gateway.connection import (
    build_frame,
    build_server_hello,
    generate_session_id,
)
from autoservice.gateway.envelope import ACCEPTED_VERSIONS, parse_envelope
from autoservice import operator_routes, operators
from autoservice import password_login as _password_login
from autoservice.gateway.errors import (
    ERR_AUTH,
    ERR_VALIDATION,
    ERR_VERSION_INCOMPATIBLE,
    make_error_payload,
)
from autoservice.gateway.message_router import dispatch, get_subscription_registry, replay_messages
from autoservice.gateway.offline_watcher import OfflineWatcher
from autoservice.gateway.tenant_resolver import resolve_customer_tenant
from autoservice.takeover_config import TakeoverConfig, load_takeover_config

logger = logging.getLogger("autoservice.gateway")
# Promote to INFO so per-request timing / reply-pipeline progress surfaces in
# gateway.log. Default root is WARNING and this logger ships no handler, so
# logger.info() calls from message_router (Agent reply: starting / timing /
# pushed) were silently dropped. Propagates up to uvicorn's root handler.
logger.setLevel(logging.INFO)
if not logger.handlers and not logging.getLogger().handlers:
    logger.addHandler(logging.StreamHandler())

_CORS_ORIGINS = [f"http://localhost:{p}" for p in range(5173, 5180)]
_extra_origins = os.environ.get("CORS_EXTRA_ORIGINS", "").strip()
if _extra_origins:
    _CORS_ORIGINS.extend(
        o.strip() for o in _extra_origins.split(",") if o.strip()
    )

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


async def _push_alert_to_operators(alert) -> None:
    """T2S.5: Push a FiredAlert to operator WS scoped to alert.tenant_id.

    Contract docs/contracts/m3/e3-triage.md §1.4.  Reviewer finding
    (corrected) in original gap-analysis: AlertEngine was already wired
    to _admin_connections; T2S.5 adds a PARALLEL path for operators.

    Tenant-scope filter (CRITICAL — no cross-tenant leak):
      * alert.tenant_id is None  → platform-wide alert, skip operators
      * alert.tenant_id == X     → push to operators whose
                                    ws.state_operator_tenant_id == X
    Operator's tenant is set at T1S.3 WS handshake from a validated
    operator_session cookie — it's the DB-sourced ground truth, not
    client-claimable.
    """
    from autoservice.gateway.connection import build_frame
    from dataclasses import asdict

    alert_tenant = getattr(alert, "tenant_id", None)
    if alert_tenant is None:
        # Platform-wide alert — operators don't see platform-level events.
        return

    frame = build_frame("sla_alert", asdict(alert))
    stale_ops: list[tuple[str, str]] = []

    # _operator_sessions: dict[operator_id, set[session_id]]
    # _ws_connections:    dict[session_id, WebSocket]
    for op_id, session_ids in list(_operator_sessions.items()):
        for sid in list(session_ids):
            ws = _ws_connections.get(sid)
            if ws is None:
                stale_ops.append((op_id, sid))
                continue
            # Tenant-scope enforcement: only push to operators bound to alert's tenant
            op_tenant = getattr(ws, "state_operator_tenant_id", None)
            if op_tenant != alert_tenant:
                continue
            try:
                await ws.send_json(frame)
            except Exception:
                logger.debug("operator ws %s unreachable, removing", sid)
                stale_ops.append((op_id, sid))

    for op_id, sid in stale_ops:
        session_set = _operator_sessions.get(op_id)
        if session_set is not None:
            session_set.discard(sid)
            if not session_set:
                _operator_sessions.pop(op_id, None)


async def _push_alert_to_all_subscribers(alert) -> None:
    """Combined notify chain: admin path (existing) + operator path (T2S.5).

    Reviewer fix C2 (2026-04-21): dispatch both paths CONCURRENTLY via
    asyncio.gather — a single slow admin WS must NOT block operator push
    (prior sequential-await implementation would head-of-line-block the
    AlertEngine notify loop under admin connectivity issues).
    """
    results = await asyncio.gather(
        _push_alert_to_admins(alert),
        _push_alert_to_operators(alert),
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, Exception):
            logger.warning("alert dispatch arm failed", exc_info=r)


def create_app(engine: ConversationEngine | None = None) -> FastAPI:
    """Build the FastAPI app with 3 WS endpoints + CORS."""
    app = FastAPI(title="autoservice-gateway", version="0.6.0")

    if engine is None:
        # Load takeover config (test hook wins, else YAML, else defaults)
        if _TAKEOVER_CONFIG_OVERRIDE is not None:
            takeover_cfg = _TAKEOVER_CONFIG_OVERRIDE
        else:
            takeover_cfg = load_takeover_config(Path(".autoservice/config.local.yaml"))
        # Conversation persistence — ON by default so `make run-gateway`
        # keeps operator-visible history across restarts. Pytest runs are
        # detected via `pytest in sys.modules` and default to OFF so the
        # many tests that call `create_app()` don't write to the real
        # .autoservice/database/conversations.db. Explicit env wins in all
        # cases: set CONV_PERSIST=1/0 to force either way, CONV_DB_PATH to
        # relocate the file.
        import sys
        persist_default = "0" if "pytest" in sys.modules else "1"
        store: ConversationStore | None = None
        if os.environ.get("CONV_PERSIST", persist_default) == "1":
            db_path = Path(
                os.environ.get("CONV_DB_PATH", str(_CONV_DB_DEFAULT_PATH))
            )
            try:
                store = ConversationStore(db_path=db_path)
                logger.info("[conv-store] persistence enabled at %s", db_path)
            except Exception:
                logger.exception(
                    "[conv-store] failed to open %s — falling back to in-memory",
                    db_path,
                )
                store = None
        engine = LocalEngine(config={"takeover": takeover_cfg}, store=store)
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

    # T7B.1 — TenantContext middleware (spec §3.2).
    #
    # Populates request.state.deployment_mode + request.state.tenant_id and
    # — in tenant mode — rewrites /tenant/<self>/* to /* (URL-flat fork routing)
    # while refusing cross-tenant paths /tenant/<other>/* with 403.
    #
    # Placement: registered AFTER the CORSMiddleware add_middleware call so
    # Starlette wraps it INSIDE CORS (Starlette chains in reverse registration
    # order). That is the desired order — CORS headers attach to our 403
    # responses, and CORS-only preflight OPTIONS requests still reach us
    # unchanged.
    @app.middleware("http")
    async def tenant_context_middleware(request: Request, call_next):
        from autoservice import bootstrap

        try:
            mode = bootstrap.get_deployment_mode()
        except (FileNotFoundError, ImportError):
            # Missing config.local.yaml in dev/test → act as master mode.
            mode = "master"

        request.state.deployment_mode = mode
        request.state.tenant_id = (
            bootstrap.get_tenant_id() if mode == "tenant" else None
        )

        if mode == "tenant":
            self_tid = request.state.tenant_id
            path = request.url.path
            if self_tid and path.startswith(f"/tenant/{self_tid}/"):
                # Strip the /tenant/<self> prefix so the fork's URL-flat routes
                # receive the request (spec §3.2 "fork 模式 URL-flat").
                request.scope["path"] = path[len(f"/tenant/{self_tid}"):] or "/"
            elif self_tid and path == f"/tenant/{self_tid}":
                # Trailing-slash-less variant.
                request.scope["path"] = "/"
            elif path.startswith("/tenant/"):
                # Cross-tenant attempt in single-tenant fork → refuse.
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": (
                            "cross-tenant access denied "
                            "(tenant-mode single-tenant fork)"
                        ),
                    },
                )

        return await call_next(request)

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
    from autoservice.integrations.general_bot.routes import general_bot_router
    app.include_router(general_bot_router)
    _set_engine(app.state.engine)

    # Path to the per-email password file; same convention as auth.db etc.
    _PASSWORDS_FILE = Path(__file__).resolve().parent.parent / ".autoservice" / "passwords.json"
    from autoservice.api_routes import _get_auth_db as _get_auth_db_for_pw_login
    app.include_router(
        _password_login.build_router(
            passwords_path=str(_PASSWORDS_FILE),
            db_provider=_get_auth_db_for_pw_login,
        )
    )

    # Wire SLA alert push to admin WebSocket connections (T6E.7)
    try:
        from autoservice.alert_engine import AlertEngine
        from autoservice.sla_aggregator import SLAAggregator

        aggregator = getattr(app.state, "sla_aggregator", None)
        if aggregator is None:
            aggregator = SLAAggregator()
            app.state.sla_aggregator = aggregator
        alert_engine = AlertEngine(aggregator)
        alert_engine.set_notify(_push_alert_to_all_subscribers)  # T2S.5: admin + operator
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
    async def _dump_runtime_config() -> None:
        """Print every env-driven runtime flag + key cc_pool settings at
        startup so operators can see at a glance what the current
        process is configured with. Grouped for readability; unset
        values shown as ``<unset>`` with the effective default the
        code falls back to.

        Docs: docs/environment-config.md for full semantics of each entry.
        """
        import os

        def _e(name: str, fallback_default: str | None = None) -> str:
            v = os.environ.get(name)
            if v is None:
                return f"<unset -> {fallback_default}>" if fallback_default else "<unset>"
            return v

        # Deprecation: PLACEHOLDER_ENABLED → INSTANT_ACK_ENABLED.
        # Spec: 2026-04-26-instant-ack-multi-bubble-queue-design.md §11.
        _legacy_val = os.environ.get("PLACEHOLDER_ENABLED")
        if _legacy_val is not None and os.environ.get("INSTANT_ACK_ENABLED") is None:
            logger.warning(
                "PLACEHOLDER_ENABLED=%s is deprecated; honoring as INSTANT_ACK_ENABLED. "
                "Please rename the variable; the alias will be removed in a future release.",
                _legacy_val,
            )

        # Layer 1: runtime feature flags
        flags = [
            ("INSTANT_ACK_ENABLED",        _e("INSTANT_ACK_ENABLED", "1")),
            ("MULTI_BUBBLE_ENABLED",       _e("MULTI_BUBBLE_ENABLED", "1")),
            ("QUEUE_ENABLED",              _e("QUEUE_ENABLED", "1")),
            ("GENERAL_BOT_ENABLED",        _e("GENERAL_BOT_ENABLED", "1")),
            ("PLACEHOLDER_ENABLED",        _e("PLACEHOLDER_ENABLED", "(deprecated alias)")),
            ("SOOTHE_PLACEHOLDER_ENABLED", _e("SOOTHE_PLACEHOLDER_ENABLED", "(deprecated, ignored)")),
            ("TRIAGE_AGENT_ENABLED",       _e("TRIAGE_AGENT_ENABLED", "0")),
            ("TRIAGE_AGENT_TIMEOUT_S",     _e("TRIAGE_AGENT_TIMEOUT_S", "15.0")),
            ("AUTH_DEV_MODE",              _e("AUTH_DEV_MODE", "(disabled)")),
            ("DREAM_DEV_STUB",             _e("DREAM_DEV_STUB", "(disabled)")),
            ("DREAM_SCHEDULER_DISABLED",   _e("DREAM_SCHEDULER_DISABLED", "(enabled)")),
            ("POOL_MODE",                  _e("POOL_MODE", "1")),
        ]
        # Layer 2: web / URL config
        web = [
            ("DEMO_PORT",                  _e("DEMO_PORT", "8000")),
            ("WEB_SCHEME",                 _e("WEB_SCHEME", "http")),
            ("WEB_HOST",                   _e("WEB_HOST", "localhost")),
            ("IDLE_TIMEOUT_MINUTES",       _e("IDLE_TIMEOUT_MINUTES", "15")),
        ]
        # Layer 3: budgets + external APIs
        cost = [
            ("COMPRESSION_DAILY_BUDGET_CENTS", _e("COMPRESSION_DAILY_BUDGET_CENTS", "1000")),
            ("ANTHROPIC_API_KEY",          "<set>" if os.environ.get("ANTHROPIC_API_KEY") else "<unset>"),
        ]
        # Layer 4: cc_pool config (loaded from config.local.yaml + env overrides)
        try:
            from autoservice.cc_pool import load_pool_config
            cfg = load_pool_config()
            pool = [
                ("min_size",                cfg.min_size),
                ("max_size",                cfg.max_size),
                ("warmup_count",            cfg.warmup_count),
                ("max_queries_per_instance", cfg.max_queries_per_instance),
                ("permission_mode",         cfg.permission_mode),
                ("model",                   cfg.model or "<unset>"),
                ("fast_model",              cfg.fast_model or "<unset>"),
                ("slow_model",              cfg.slow_model or "<unset>"),
                ("dream_model",             cfg.dream_model or "<unset>"),
                ("include_partial_messages", cfg.include_partial_messages),
                ("warmup_tenant_id",        cfg.warmup_tenant_id or "<unset>"),
                ("warmup_roles",            cfg.warmup_roles),
            ]
        except Exception:
            logger.warning("cc_pool config load failed during startup dump", exc_info=True)
            pool = []

        sep = "=" * 72
        logger.info(sep)
        logger.info("=== Runtime configuration snapshot ===")
        logger.info("[env flags]")
        for k, v in flags:
            logger.info("  %-32s = %s", k, v)
        logger.info("[web / urls]")
        for k, v in web:
            logger.info("  %-32s = %s", k, v)
        logger.info("[cost / api keys]")
        for k, v in cost:
            logger.info("  %-32s = %s", k, v)
        if pool:
            logger.info("[cc_pool (config.local.yaml + CC_POOL_* env)]")
            for k, v in pool:
                logger.info("  %-32s = %s", k, v)
        logger.info(sep)
        logger.info("Docs: docs/environment-config.md  for full semantics.")

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

    # T1S.3 — operator role: STRICT cookie validation per contract §4
    # (docs/contracts/m3/e1-auth-rbac.md).  Closes the M2 spoof gap where
    # operator_id was trusted blindly from client_hello JSON payload.
    #   * Valid cookie → bind to session's operator_id / tenant_id, refresh idle_at
    #   * Cookie missing / invalid / expired / disabled-operator → reject with 1008
    #   * Any operator_id in the JSON payload is IGNORED (spoof gap closed)
    # Reviewer finding C3: lenient-mode (no-cookie → accept-no-bind) was closed
    # because subscribe frames bypass _operator_sessions and leaked broadcast
    # observability to unauthenticated connections.  Strict-mode default now.
    validated_operator_id: str | None = None
    validated_operator_tenant_id: str | None = None
    op_cookie_for_touch: str | None = None
    if viewer_role == "operator":
        op_cookie = ws.cookies.get(operators.OPERATOR_SESSION_COOKIE_NAME)
        op_ctx = None
        if op_cookie:
            op_conn = operator_routes._get_op_db()
            op_ctx = operators.lookup_operator_session(op_conn, op_cookie)
        if op_ctx is None:
            # Identical payload for missing/invalid/expired/disabled — no oracle
            await ws.send_json(
                build_frame(
                    "error",
                    make_error_payload(
                        ERR_AUTH,
                        "operator_session cookie required",
                        details={"reason": "invalid_or_missing_session"},
                    ),
                    ref=env.id,
                )
            )
            await ws.close(code=1008)  # policy violation
            return
        validated_operator_id = op_ctx["operator_id"]
        validated_operator_tenant_id = op_ctx["tenant_id"]
        op_cookie_for_touch = op_cookie
        operators.touch_operator_session(op_conn, op_cookie)

    # Customer role: resolve + validate tenant from URL query. tenant-mode
    # deployments reject cross-tenant snooping (query ≠ self); master-mode
    # rejects queries for unregistered tenants. Successful resolution pins
    # ws.state_customer_tenant_id, which message_router then forwards into
    # conv.metadata["tenant_id"] so downstream KB pre-fetch + tenant-soul
    # recycle fire on the right tenant.
    validated_customer_tenant_id: str | None = None
    if viewer_role == "customer":
        tid, reject_reason = resolve_customer_tenant(ws.query_params)
        if reject_reason is not None:
            await ws.send_json(
                build_frame(
                    "error",
                    make_error_payload(
                        ERR_AUTH,
                        f"tenant resolution failed: {reject_reason}",
                        details={"reason": reject_reason},
                    ),
                    ref=env.id,
                )
            )
            await ws.close(code=1008)
            return
        validated_customer_tenant_id = tid

    session_id = generate_session_id()
    _ws_connections[session_id] = ws
    if viewer_role == "admin":
        _admin_connections[session_id] = ws

    # Track operator_id → sessions for targeted pushes (authenticated only)
    if viewer_role == "operator" and validated_operator_id:
        _operator_sessions.setdefault(validated_operator_id, set()).add(session_id)
        ws.state_operator_id = validated_operator_id  # for finally cleanup
        ws.state_operator_tenant_id = validated_operator_tenant_id
        # Tell the offline watcher this operator is online
        ws.app.state.offline_watcher.on_connect(validated_operator_id)

    if viewer_role == "customer":
        ws.state_customer_tenant_id = validated_customer_tenant_id

    # Resolve brand_name for customer role so the widget can show
    # tenant-scoped branding without a separate HTTP fetch.  We emit only
    # when a brand is actually configured — an unset tenant yields None
    # and the widget falls back to its own i18n default (rather than
    # surfacing "AutoService" as if it were the merchant's brand).
    hello_brand_name: str | None = None
    if viewer_role == "customer" and validated_customer_tenant_id:
        from autoservice.api_routes import _try_resolve_brand_name
        try:
            hello_brand_name = _try_resolve_brand_name(
                validated_customer_tenant_id,
            )
        except Exception:
            logger.warning(
                "brand_name resolution failed for customer tenant %s",
                validated_customer_tenant_id,
                exc_info=True,
            )

    await ws.send_json(
        build_frame(
            "server_hello",
            build_server_hello(
                viewer_role=viewer_role,
                session_id=session_id,
                brand_name=hello_brand_name,
            ),
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
    # Reviewer finding C1: touch idle_at on every inbound frame (contract §4
    # "updates operator_sessions.idle_at on every inbound message"). Without
    # this an idle operator session silently outlives its idle_timeout_min.
    try:
        while True:
            raw = await ws.receive_json()
            if op_cookie_for_touch is not None:
                operators.touch_operator_session(
                    operator_routes._get_op_db(), op_cookie_for_touch
                )
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
