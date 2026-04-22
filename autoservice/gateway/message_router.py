"""FE→BE frame router (T0.5 skeleton).

Dispatches parsed Envelope objects to Engine methods per T0.2 §7 mapping table.
Handles error mapping per T0.2 §6.1:
  - command frames (operator_command / admin_command) whose Engine call fails
    → S11 command_response{ok:false}
  - other frames that fail → S4 error frame
  - NotImplementedError (T0.4 skeleton state) → 5010_INTERNAL + details.engine_hint
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, TYPE_CHECKING

from datetime import datetime, timezone

from autoservice.cc_pool import StickyTenantMismatch
from autoservice.conversation_engine import ConversationEngine
from autoservice.conversation_engine.errors import ConversationNotFound
from autoservice.conversation_engine.types import MessageVisibility, Participant, ParticipantRole

from .connection import build_frame
from .errors import ERR_INTERNAL, ERR_NOT_FOUND, ERR_VALIDATION, make_error_payload
from .envelope import Envelope
from .subscription_registry import (
    SubscriptionEntry,
    SubscriptionRegistry,
    generate_subscription_id,
)

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger("autoservice.gateway")

_COMMAND_FRAMES = {"operator_command", "admin_command"}

# Per T0.2 §4: frames allowed on each endpoint (customer-visible frames only on /ws/customer, etc.)
_CUSTOMER_FRAMES = {"client_hello", "ping", "client_ack", "customer_message", "csat_response", "history_request"}
_OPERATOR_FRAMES = {
    "client_hello", "ping", "client_ack", "subscribe", "unsubscribe",
    "operator_join", "operator_leave", "operator_message", "operator_command",
    "history_request", "edit_request", "delete_request",
}
_ADMIN_FRAMES = {"client_hello", "ping", "client_ack", "subscribe", "unsubscribe", "admin_command"}

_FRAMES_BY_ROLE = {
    "customer": _CUSTOMER_FRAMES,
    "operator": _OPERATOR_FRAMES,
    "admin": _ADMIN_FRAMES,
}

# Known FE→BE types (T0.2 §4 F1-F15)
_KNOWN_FRAMES = _CUSTOMER_FRAMES | _OPERATOR_FRAMES | _ADMIN_FRAMES

# Global subscription registry (T6A.1) — shared across all connections
_registry = SubscriptionRegistry()


def get_subscription_registry() -> SubscriptionRegistry:
    """Access the global subscription registry."""
    return _registry


_HINT_RE = re.compile(r"T[12]A\.\d+")

# Track conversation creation timestamps for SLA first_reply_ms (T6D.1)
import time as _time
_conv_created_at: dict[str, float] = {}
_conv_first_reply_sent: set[str] = set()

# Track the customer WebSocket per conversation so operator/agent replies can
# be pushed back without the customer needing to subscribe explicitly.
# Populated on customer_message, cleaned lazily on failed send.
_customer_ws_by_conv: dict[str, Any] = {}


def _infer_operator_from_ws(ws) -> str | None:
    """Best-effort operator_id lookup from WS state (set in web_gateway).

    Only works for operator WS connections (set in _handle_connection). Customer
    and admin connections never have state_operator_id set, so this returns None.
    For client_ack frames from non-operator endpoints, an explicit operator_id
    in the payload is required — and should be rejected by upstream validation.
    """
    if ws is None:
        return None
    return getattr(ws, "state_operator_id", None)


def _extract_hint(exc: BaseException) -> str | None:
    msg = str(exc) if exc.args else ""
    return msg if _HINT_RE.search(msg) else None


async def dispatch(
    env: Envelope,
    *,
    viewer_role: str,
    engine: ConversationEngine,
    ws: WebSocket | None = None,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Dispatch a validated FE envelope; return frames to send back (0..N)."""
    frame_type = env.type

    # Unknown type → 4012
    if frame_type not in _KNOWN_FRAMES:
        return [
            build_frame(
                "error",
                make_error_payload(
                    ERR_VALIDATION,
                    "unknown frame type",
                    details={"unknown_type": frame_type},
                ),
                ref=env.id,
            )
        ]

    # Endpoint-scoped frame check (naive: deny if frame not in role's allowed set)
    allowed = _FRAMES_BY_ROLE.get(viewer_role, set())
    if frame_type not in allowed:
        return [
            build_frame(
                "error",
                make_error_payload(
                    ERR_VALIDATION,
                    f"frame {frame_type!r} not allowed on /ws/{viewer_role}",
                    details={
                        "reason": "frame_not_allowed_on_endpoint",
                        "frame_type": frame_type,
                        "endpoint": f"/ws/{viewer_role}",
                    },
                ),
                ref=env.id,
            )
        ]

    # ping → pong (no ack, no engine call)
    if frame_type == "ping":
        return [build_frame("pong", {"server_time": _now_iso_ms()}, ref=env.id)]

    # client_ack — ack; if action=continue, reset the takeover timer (operator only)
    if frame_type == "client_ack":
        payload = env.payload or {}
        if payload.get("action") == "continue":
            conv_id = payload.get("conversation_id")
            # Only operators can reset takeover timers (inferred from WS state or explicit payload)
            if viewer_role == "operator":
                actor_id = payload.get("operator_id") or _infer_operator_from_ws(ws)
                if conv_id and actor_id:
                    try:
                        await engine.reset_takeover_timer(conv_id, actor_id=actor_id)
                    except Exception:
                        logger.exception("client_ack continue reset failed")
        return [build_frame("ack", {}, ref=env.id)]

    # subscribe / unsubscribe — subscription registry (T6A.1)
    if frame_type == "subscribe":
        return await _handle_subscribe(env, viewer_role=viewer_role, engine=engine, ws=ws, session_id=session_id)
    if frame_type == "unsubscribe":
        return await _handle_unsubscribe(env, ref=env.id)

    # Command frames → command_response path (§6.1)
    if frame_type in _COMMAND_FRAMES:
        return await _dispatch_command(env, engine=engine)

    # Non-command frames → engine call → ack (+ maybe message frame)
    return await _dispatch_engine(env, frame_type=frame_type, viewer_role=viewer_role, engine=engine, ws=ws)


async def _dispatch_command(env: Envelope, *, engine: ConversationEngine) -> list[dict[str, Any]]:
    from autoservice.conversation_engine.errors import UnknownParticipant

    payload = env.payload
    command = payload.get("command", "")
    conversation_id = payload.get("conversation_id", "")
    actor_id = payload.get("operator_id") or payload.get("actor_id") or ""
    args = payload.get("args") or {}

    async def _call() -> None:
        await engine.handle_command(
            conversation_id, actor_id=actor_id, command=command, args=args,
        )

    try:
        try:
            await _call()
        except UnknownParticipant:
            # Auto-join the operator as a participant and retry once.
            # Mirrors the legacy REST endpoint behavior so operators can hijack
            # without an explicit operator_join handshake.
            logger.debug("[AUTOJOIN] actor=%r conv=%r command=%r", actor_id, conversation_id, command)
            if not (actor_id and conversation_id):
                raise
            try:
                await engine.join(
                    conversation_id,
                    Participant(
                        id=actor_id,
                        role=ParticipantRole.OPERATOR,
                        joined_at=datetime.now(timezone.utc),
                    ),
                )
                logger.debug("[AUTOJOIN] joined, retrying")
            except Exception as _jexc:
                logger.debug("[AUTOJOIN] join failed: %r", _jexc)
                raise
            try:
                await _call()
                logger.debug("[AUTOJOIN] retry succeeded")
            except Exception as _rexc:
                logger.debug("[AUTOJOIN] retry failed: %r", _rexc)
                raise
    except NotImplementedError as exc:
        hint = _extract_hint(exc) or str(exc)
        return [
            build_frame(
                "command_response",
                {
                    "command": command,
                    "ok": False,
                    "error_code": ERR_INTERNAL,
                    "error_message": f"not yet implemented ({hint})",
                },
                ref=env.id,
            )
        ]
    except Exception as exc:  # noqa: BLE001
        logger.exception("engine.handle_command failed")
        return [
            build_frame(
                "command_response",
                {
                    "command": command,
                    "ok": False,
                    "error_code": ERR_INTERNAL,
                    "error_message": str(exc),
                },
                ref=env.id,
            )
        ]
    # On /resolve or /abandon success, push csat_request to customer (T6C.1)
    if command in ("/resolve", "/abandon") and conversation_id:
        reason = "resolved" if command == "/resolve" else "abandoned"
        asyncio.create_task(
            _push_csat_request(conversation_id, reason=reason),
            name=f"csat-request-{conversation_id}",
        )
        # Record resolution_rate in SLAAggregator (1.0 = resolved, 0.0 = abandoned)
        try:
            from autoservice.api_routes import get_sla_aggregator
            from autoservice.sla_aggregator import MetricType
            sla = get_sla_aggregator()
            sla.record(MetricType.RESOLUTION_RATE, 1.0 if command == "/resolve" else 0.0)
        except Exception:
            logger.warning("Failed to record resolution SLA for conv=%s", conversation_id)

    # On /hijack success, record accept_ms in SLAAggregator (T6D.1)
    if command == "/hijack" and conversation_id:
        try:
            created_at = _conv_created_at.get(conversation_id)
            if created_at is not None:
                latency_ms = (_time.time() - created_at) * 1000
                from autoservice.api_routes import get_sla_aggregator
                from autoservice.sla_aggregator import MetricType
                sla = get_sla_aggregator()
                sla.record(MetricType.ACCEPT_MS, latency_ms)
        except Exception:
            logger.warning("Failed to record accept SLA for conv=%s", conversation_id)

    # On /release or /copilot (handing back to AI), auto-reply to any unanswered
    # customer question. Customer's message sent during TAKEOVER never got an AI
    # response — now that operator has released, the AI picks up.
    if command in ("/release", "/copilot") and conversation_id:
        await _trigger_ai_reply_if_pending(
            engine, conversation_id, log_reason=f"post-{command.lstrip('/')}",
        )

    return [
        build_frame(
            "command_response",
            {"command": command, "ok": True, "result": None},
            ref=env.id,
        )
    ]


async def _handle_subscribe(
    env: Envelope,
    *,
    viewer_role: str,
    engine: ConversationEngine,
    ws: WebSocket | None = None,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Handle F6 subscribe: create subscription, return S13 subscription_added."""
    logger.debug("[SUB] role=%s session=%s scope=%s", viewer_role, session_id, env.payload.get('scope'))
    payload = env.payload
    scope = payload.get("scope")
    if not scope or not isinstance(scope, dict):
        return [build_frame("error", make_error_payload(
            ERR_VALIDATION, "subscribe requires scope object",
            details={"reason": "missing_scope"},
        ), ref=env.id)]

    # Validate scope: exactly one of conversation_id, squad_id, global
    has_conv = bool(scope.get("conversation_id"))
    has_squad = bool(scope.get("squad_id"))
    has_global = bool(scope.get("global"))

    if sum([has_conv, has_squad, has_global]) != 1:
        return [build_frame("error", make_error_payload(
            ERR_VALIDATION,
            "scope must specify exactly one of: conversation_id, squad_id, global",
            details={"scope": scope},
        ), ref=env.id)]

    # global scope only allowed on /ws/admin
    if has_global and viewer_role != "admin":
        return [build_frame("error", make_error_payload(
            ERR_VALIDATION,
            "global subscription only allowed on /ws/admin",
            details={"endpoint": f"/ws/{viewer_role}"},
        ), ref=env.id)]

    subscription_id = generate_subscription_id()
    event_types = payload.get("event_types")
    since_sequence = payload.get("since_sequence")

    # Determine since_sequence for the response:
    # conv scope -> int, squad/global scope -> string (ULID)
    if has_conv:
        resp_since = int(since_sequence) if since_sequence is not None else 0
    else:
        resp_since = str(since_sequence) if since_sequence is not None else ""

    # Create engine subscription (async iterator for event fan-out)
    try:
        viewer_role_enum = None
        try:
            viewer_role_enum = ParticipantRole(viewer_role)
        except (ValueError, KeyError):
            pass  # admin is not in ParticipantRole enum

        iterator = engine.subscribe(
            conversation_id=scope.get("conversation_id"),
            squad_id=scope.get("squad_id"),
            event_types=event_types,
            since_sequence=since_sequence,
            viewer_role=viewer_role_enum,
        )
    except Exception as exc:
        logger.exception("engine.subscribe failed")
        return [build_frame("error", make_error_payload(
            ERR_INTERNAL, f"subscription failed: {exc}",
        ), ref=env.id)]

    entry = SubscriptionEntry(
        subscription_id=subscription_id,
        session_id=session_id or "",
        scope=scope,
        viewer_role=viewer_role,
        since_sequence=resp_since,
        event_types=event_types,
        _iterator=iterator,
    )

    # Start fan-out task: forward engine events to the WebSocket
    if ws is not None and iterator is not None:
        async def _fanout(it: Any, target_ws: WebSocket, sub_id: str) -> None:
            try:
                async for event in it:
                    frame = build_frame("event", {
                        "event": {
                            "id": event.id,
                            "type": event.type if isinstance(event.type, str) else event.type.value,
                            "conversation_id": event.conversation_id,
                            "data": event.data if isinstance(event.data, dict) else {},
                            "timestamp": event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else str(event.timestamp),
                            "sequence_number": event.sequence_number,
                        },
                    })
                    try:
                        await target_ws.send_json(frame)
                    except Exception:
                        break  # connection lost
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("fanout ended for subscription %s", sub_id)

        task = asyncio.create_task(
            _fanout(iterator, ws, subscription_id),
            name=f"sub-fanout-{subscription_id}",
        )
        entry._task = task

    _registry.add(entry)

    return [build_frame("subscription_added", {
        "subscription_id": subscription_id,
        "scope": scope,
        "since_sequence": resp_since,
    }, ref=env.id)]


async def _handle_unsubscribe(env: Envelope, *, ref: str) -> list[dict[str, Any]]:
    """Handle F7 unsubscribe: remove subscription, return S14 subscription_removed."""
    payload = env.payload
    subscription_id = payload.get("subscription_id")
    if not subscription_id:
        return [build_frame("error", make_error_payload(
            ERR_VALIDATION, "unsubscribe requires subscription_id",
        ), ref=ref)]

    entry = _registry.remove(subscription_id)
    if entry is None:
        return [build_frame("error", make_error_payload(
            ERR_NOT_FOUND, f"subscription {subscription_id!r} not found",
            details={"subscription_id": subscription_id},
        ), ref=ref)]

    return [build_frame("subscription_removed", {
        "subscription_id": subscription_id,
        "reason": "unsubscribed",
    }, ref=ref)]


async def _dispatch_engine(
    env: Envelope,
    *,
    frame_type: str,
    viewer_role: str,
    engine: ConversationEngine,
    ws: WebSocket | None = None,
) -> list[dict[str, Any]]:
    payload = env.payload
    try:
        result_frames = await _call_engine(engine, frame_type, payload, viewer_role, ws=ws)
    except NotImplementedError as exc:
        hint = _extract_hint(exc) or str(exc)
        return [
            build_frame(
                "error",
                make_error_payload(
                    ERR_INTERNAL,
                    "engine method not yet implemented",
                    recoverable=False,
                    details={"engine_hint": hint, "frame_type": frame_type},
                ),
                ref=env.id,
            )
        ]
    except Exception as exc:  # noqa: BLE001
        logger.exception("engine dispatch failed for %s", frame_type)
        return [
            build_frame(
                "error",
                make_error_payload(
                    ERR_INTERNAL,
                    "internal error during engine dispatch",
                    recoverable=False,
                    details={"exception_type": type(exc).__name__},
                ),
                ref=env.id,
            )
        ]
    # Success path: at minimum an ack; result_frames may add a message/history_snapshot
    return [build_frame("ack", {}, ref=env.id), *result_frames]


async def _call_engine(
    engine: ConversationEngine,
    frame_type: str,
    payload: dict[str, Any],
    viewer_role: str,
    *,
    ws: WebSocket | None = None,
) -> list[dict[str, Any]]:
    """Map a FE frame type to an Engine call; return BE→FE push frames (not including ack)."""
    if frame_type == "customer_message":
        conv_id = payload.get("conversation_id")
        source = payload.get("source", "customer")
        # Auto-create conversation + participant on first message
        if conv_id:
            try:
                await engine.get_conversation(conv_id)
            except ConversationNotFound:
                conv_id = None
        if not conv_id:
            # Compute squad BEFORE create_conversation so the squad_id lands
            # in conv.metadata before conversation.created is emitted. Fixes
            # the race where squad-scoped subscribers miss the first event.
            squad_id_hint: str | None = None
            try:
                from autoservice.web_gateway import _get_squad_plugin
                sp = _get_squad_plugin()
                if sp:
                    squad_id_hint = sp.choose_squad(channel="web")
            except Exception:
                pass
            meta: dict[str, Any] = {"channel": "web"}
            if squad_id_hint:
                meta["squad_id"] = squad_id_hint
            conv = await engine.create_conversation(
                channel="web", external_id=source, metadata=meta,
            )
            conv_id = conv.id
            now = datetime.now(timezone.utc)
            await engine.join(
                conv_id,
                Participant(id=source, role=ParticipantRole.CUSTOMER, joined_at=now),
            )
            await engine.join(
                conv_id,
                Participant(id="agent", role=ParticipantRole.AGENT, joined_at=now),
            )
            # Track creation time for SLA first_reply_ms (T6D.1)
            _conv_created_at[conv_id] = _time.time()
        msg = await engine.send_message(
            conv_id, source=source, content=payload["content"],
        )

        # Remember the customer's WS so operator/agent can push back without
        # the customer needing an explicit subscribe.
        if ws is not None:
            _customer_ws_by_conv[conv_id] = ws

        # Broadcast customer message to operator connections subscribed to this squad (T6A.2)
        customer_frame = _message_frame(msg)
        customer_frame["payload"]["source_display"] = {"id": source, "role": "customer"}
        try:
            from autoservice.web_gateway import _get_squad_plugin
            sp = _get_squad_plugin()
            if sp:
                squad = sp.get_squad(conv_id)
                if squad:
                    customer_frame["payload"]["squad_id"] = squad
        except Exception:
            pass
        await _broadcast_to_squad(customer_frame, conv_id, exclude_ws=ws)

        # Fire-and-forget: trigger agent response via CCPool.
        # In TAKEOVER, AI still generates a SIDE suggestion so the operator
        # sees a draft in the sidebar (Gate will downgrade agent PUBLIC → SIDE).
        # In AUTO/COPILOT, AI drives the reply as PUBLIC to customer.
        from autoservice.conversation_engine.types import ConversationMode
        try:
            conv_now = await engine.get_conversation(conv_id)
            current_mode = getattr(conv_now, "mode", None)
        except Exception:
            current_mode = None
        mode_name = current_mode.value if hasattr(current_mode, "value") else str(current_mode)
        if ws is None:
            logger.warning("[AI-trigger] skip: ws is None conv=%s", conv_id)
        else:
            logger.warning("[AI-trigger] firing conv=%s mode=%s", conv_id, mode_name)
            asyncio.create_task(
                _generate_agent_reply(engine, conv_id, payload["content"], ws),
                name=f"agent-reply-{conv_id}",
            )

        # Return confirmation data (not full message echo — FE has optimistic msg)
        return [build_frame("message_confirm", {
            "conversation_id": conv_id,
            "message_id": msg.id,
            "client_msg_id": payload.get("client_msg_id"),
            "sequence_number": msg.sequence_number,
            "timestamp": msg.timestamp.isoformat() if hasattr(msg.timestamp, "isoformat") else msg.timestamp,
        })]

    if frame_type == "operator_message":
        from autoservice.conversation_engine.errors import UnknownParticipant
        conv_id = payload["conversation_id"]
        operator_id = payload.get("operator_id", "operator")
        try:
            msg = await engine.send_message(
                conv_id, source=operator_id, content=payload["content"],
            )
        except UnknownParticipant:
            # Auto-join operator and retry (mirrors command auto-join)
            try:
                await engine.join(
                    conv_id,
                    Participant(id=operator_id, role=ParticipantRole.OPERATOR,
                                joined_at=datetime.now(timezone.utc)),
                )
            except Exception:
                pass
            msg = await engine.send_message(
                conv_id, source=operator_id, content=payload["content"],
            )
        frame = _message_frame(msg)
        frame["payload"]["source_display"] = {"id": operator_id, "role": "operator"}

        # Only PUBLIC messages reach the customer. SIDE messages (operator
        # suggestions in auto/copilot mode) stay inside the operator/admin
        # fan-out (see conversation-engine.md §4 Gate + Q9).
        is_public = msg.visibility == MessageVisibility.PUBLIC
        if is_public:
            cust_ws = _customer_ws_by_conv.get(conv_id)
            if cust_ws is not None and cust_ws is not ws:
                try:
                    await cust_ws.send_json(frame)
                except Exception:
                    _customer_ws_by_conv.pop(conv_id, None)

        # Broadcast to other operators/admin subscribed to this squad (excluding
        # the sender). Subscribers need SIDE drafts too — visibility is filtered
        # on the read path, not here.
        await _broadcast_to_squad(frame, conv_id, exclude_ws=ws)

        # If the operator just sent a SIDE instruction and there's an unanswered
        # customer question, auto-trigger AI so the instruction is acted on.
        if msg.visibility == MessageVisibility.SIDE:
            await _trigger_ai_reply_if_pending(
                engine, conv_id, log_reason="operator-SIDE",
            )

        # Do NOT echo the frame back to the sender: they already inserted it
        # optimistically (IMInput.tsx). Echoing would produce duplicate lines
        # with different IDs (server-assigned vs client random UUID).
        return []

    if frame_type == "csat_response":
        conv_id = payload["conversation_id"]
        score = int(payload["score"])
        await engine.set_csat(conv_id, score)
        # Record in BillingMetrics (T6C.1)
        try:
            from autoservice.api_routes import get_billing_metrics
            bm = get_billing_metrics()
            if bm is not None:
                bm.record_csat(conv_id, score)
        except Exception:
            logger.warning("Failed to record CSAT in BillingMetrics for conv=%s", conv_id)
        # Record in SLAAggregator (T6D.1)
        try:
            from autoservice.api_routes import get_sla_aggregator
            from autoservice.sla_aggregator import MetricType
            sla = get_sla_aggregator()
            sla.record(MetricType.CSAT_SCORE, float(score))
        except Exception:
            logger.warning("Failed to record CSAT in SLAAggregator for conv=%s", conv_id)
        return []

    if frame_type == "history_request":
        conv_id = payload["conversation_id"]
        msgs = await engine.get_messages(
            conv_id,
            since_sequence=payload.get("since_sequence"),
            before_sequence=payload.get("before_sequence"),
            limit=payload.get("limit", 50),
        )
        # Attach per-message source_display so replayed history carries the
        # same role tag that live `message` frames set (see operator_message
        # broadcast above). Without this, operator suggestions reload as
        # "agent" because msg.source is an opaque participant id.
        try:
            conv = await engine.get_conversation(conv_id)
            role_by_id = {p.id: p.role.value for p in conv.participants}
        except Exception:
            role_by_id = {}
        serialized_msgs: list[dict[str, Any]] = []
        for m in msgs:
            s = _serialize_message(m)
            s["source_display"] = {
                "id": m.source,
                "role": role_by_id.get(m.source, "agent"),
            }
            serialized_msgs.append(s)
        return [
            build_frame(
                "history_snapshot",
                {
                    "conversation_id": conv_id,
                    "messages": serialized_msgs,
                    "has_more": False,
                },
            )
        ]

    if frame_type == "operator_join":
        op_id = payload.get("operator_id") or payload.get("operator") or "operator"
        if isinstance(op_id, str):
            now = datetime.now(timezone.utc)
            participant = Participant(id=op_id, role=ParticipantRole.OPERATOR, joined_at=now)
        else:
            participant = op_id  # already a Participant-like object
        try:
            await engine.join(payload["conversation_id"], participant)
        except Exception as exc:
            logger.warning("operator_join failed: %s", exc)
        return []

    if frame_type == "operator_leave":
        await engine.leave(payload["conversation_id"], payload["operator_id"])
        return []

    if frame_type == "edit_request":
        msg = await engine.edit_message(
            payload["conversation_id"],
            payload["message_id"],
            new_content=payload["new_content"],
            edited_by=payload.get("edited_by", "operator"),
        )
        return [_message_frame(msg, event_type="message_edited")]

    if frame_type == "delete_request":
        await engine.delete_message(
            payload["conversation_id"],
            payload["message_id"],
            deleted_by=payload.get("deleted_by", "operator"),
        )
        return []

    # Shouldn't reach here — unknown frame type was filtered earlier
    raise RuntimeError(f"router fell through on {frame_type!r}")


def _serialize_message(msg: Any) -> dict[str, Any]:
    """Serialize a Message dataclass to JSON-safe dict."""
    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "source": msg.source,
        "content": msg.content,
        "visibility": msg.visibility.value if hasattr(msg.visibility, "value") else msg.visibility,
        "sequence_number": msg.sequence_number,
        "timestamp": msg.timestamp.isoformat() if hasattr(msg.timestamp, "isoformat") else msg.timestamp,
        "edit_of": msg.edit_of,
        "metadata": dict(msg.metadata),
    }


def _message_frame(msg: Any, *, event_type: str = "message") -> dict[str, Any]:
    """Build a BE→FE S5 message frame."""
    serialized = _serialize_message(msg)
    return build_frame(
        event_type,
        {
            "conversation_id": serialized["conversation_id"],
            "message": serialized,
            "source_display": {"id": serialized["source"], "role": "agent"},
        },
    )


async def _broadcast_to_squad(
    frame: dict[str, Any],
    conv_id: str,
    *,
    exclude_ws: WebSocket | None = None,
) -> int:
    """Broadcast a frame to operator/admin connections subscribed to the conversation's squad.

    Uses the subscription registry (T6A.1) to find connections that subscribed
    to the matching squad scope. Falls back to broadcasting to all connections
    if no squad is assigned (backward compatible).

    Returns the number of connections the frame was sent to.
    """
    from autoservice.web_gateway import _ws_connections, _get_squad_plugin

    # Determine squad for this conversation
    squad_id: str | None = None
    try:
        sp = _get_squad_plugin()
        if sp:
            squad_id = sp.get_squad(conv_id)
    except Exception:
        pass

    sent = 0
    logger.debug(
        "[BCAST] conv=%s squad=%s reg_count=%d ws_count=%d scopes=%s",
        conv_id, squad_id, _registry.count, len(_ws_connections), list(_registry._by_scope.keys()),
    )

    if squad_id:
        # Look up sessions subscribed to this squad
        squad_subs = _registry.get_by_scope(f"squad:{squad_id}")
        # Also include sessions subscribed to the specific conversation
        conv_subs = _registry.get_by_scope(f"conv:{conv_id}")
        # Also include global subscribers (admin)
        global_subs = _registry.get_by_scope("global")

        target_sessions = {
            e.session_id for e in (*squad_subs, *conv_subs, *global_subs)
        }
        logger.debug(
            "[BCAST] squad_subs=%d conv_subs=%d global_subs=%d targets=%d",
            len(squad_subs), len(conv_subs), len(global_subs), len(target_sessions),
        )

        for session_id in target_sessions:
            target_ws = _ws_connections.get(session_id)
            if target_ws is None or target_ws is exclude_ws:
                continue
            try:
                await target_ws.send_json(frame)
                sent += 1
            except Exception:
                pass
    else:
        # No squad assigned — fallback to broadcast to all (backward compatible)
        for sid, ows in list(_ws_connections.items()):
            if ows is not exclude_ws:
                try:
                    await ows.send_json(frame)
                    sent += 1
                except Exception:
                    pass

    return sent


# ---------------------------------------------------------------------------
# Reconnect message replay (T6A.3)
# ---------------------------------------------------------------------------

async def replay_messages(
    ws: WebSocket,
    engine: ConversationEngine,
    last_seen: dict[str, Any],
) -> int:
    """Replay missed messages after a reconnect.

    Args:
        ws: The WebSocket connection to send replay frames to.
        engine: The conversation engine for querying messages.
        last_seen: A LastSeenCursor dict, expected shape:
            {"conv_seq": {"conv_id": {"msg": <int>, "evt": <int>}}, ...}

    Returns:
        Total number of replayed messages.
    """
    conv_seq = last_seen.get("conv_seq")
    if not conv_seq or not isinstance(conv_seq, dict):
        # Nothing to replay — send replay_complete with count=0
        await ws.send_json(build_frame("replay_complete", {"count": 0, "until_sequence": 0}))
        return 0

    total = 0
    max_sequence = 0
    last_conv_id: str | None = None

    for conv_id, cursors in conv_seq.items():
        if not isinstance(cursors, dict):
            continue
        msg_seq = cursors.get("msg", 0)
        if not isinstance(msg_seq, (int, float)):
            continue
        msg_seq = int(msg_seq)

        try:
            msgs = await engine.get_messages(
                conv_id,
                since_sequence=msg_seq,
                limit=200,
            )
        except Exception:
            logger.warning("replay: failed to fetch messages for conv=%s", conv_id)
            continue

        for msg in msgs:
            frame = _message_frame(msg)
            frame["payload"]["replay"] = True
            try:
                await ws.send_json(frame)
                total += 1
                seq = getattr(msg, "sequence_number", 0) or 0
                if seq > max_sequence:
                    max_sequence = seq
                last_conv_id = conv_id
            except Exception:
                logger.warning("replay: send failed for conv=%s", conv_id)
                break

    payload: dict[str, Any] = {"count": total, "until_sequence": max_sequence}
    if last_conv_id is not None and len(conv_seq) == 1:
        payload["conversation_id"] = last_conv_id
    await ws.send_json(build_frame("replay_complete", payload))
    return total


def _now_iso_ms() -> str:
    from .connection import now_iso_ms
    return now_iso_ms()


async def _collect_operator_suggestions(
    engine: ConversationEngine, conv_id: str, limit: int = 5,
) -> str:
    """Collect SIDE-visibility operator instructions that arrived *after* the
    last agent PUBLIC reply. Each agent turn consumes the pending instructions;
    next turn only sees fresh ones. Prevents stale instructions from being
    re-injected into every prompt.
    """
    try:
        msgs = await engine.get_messages(conv_id, viewer_role="operator", limit=200)
        # Find the last agent PUBLIC message's sequence_number
        last_agent_seq = 0
        for m in msgs:
            if m.source == "agent" and m.visibility.value == "public":
                if m.sequence_number > last_agent_seq:
                    last_agent_seq = m.sequence_number
        side_msgs = [
            m for m in msgs
            if m.visibility.value == "side"
               and m.source != "agent"
               and m.sequence_number > last_agent_seq
        ][-limit:]
        if not side_msgs:
            return ""
        lines = []
        for m in side_msgs:
            ts = m.timestamp.strftime('%H:%M') if hasattr(m.timestamp, 'strftime') else ''
            lines.append(f"[{ts}] {m.source}: {m.content}")
        return "<operator_suggestions>\n" + "\n".join(lines) + "\n</operator_suggestions>"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# CSAT request push (T6C.1)
# ---------------------------------------------------------------------------

async def _trigger_ai_reply_if_pending(
    engine: ConversationEngine, conv_id: str, *, log_reason: str,
) -> None:
    """Trigger AI reply if the last customer PUBLIC message has no agent
    PUBLIC reply yet. Used for /release and operator-SIDE-instruction paths,
    where AI should respond to an unanswered customer question.

    Idempotent against concurrent triggers: if an agent-reply task with the
    same conversation's name is already running, skip.
    """
    # Dedup: don't double-fire if another reply task is in flight
    task_name = f"agent-reply-{conv_id}"
    for t in asyncio.all_tasks():
        if t.get_name() == task_name and not t.done():
            logger.debug("[AI-trigger] skip %s: task %s in flight", log_reason, task_name)
            return
    # Identify customer participant(s) so we don't mistake an operator's public
    # message for a customer question. Without this the AI would roleplay as
    # the customer after /release.
    from autoservice.conversation_engine.types import ParticipantRole
    try:
        conv = await engine.get_conversation(conv_id)
        customer_ids = {p.id for p in conv.participants if p.role == ParticipantRole.CUSTOMER}
    except Exception:
        logger.exception("[AI-trigger] get_conversation failed conv=%s", conv_id)
        return
    if not customer_ids:
        logger.debug("[AI-trigger] %s: no customer participant in conv=%s", log_reason, conv_id)
        return
    try:
        msgs = await engine.get_messages(conv_id, viewer_role="operator", limit=50)
    except Exception:
        logger.exception("[AI-trigger] get_messages failed conv=%s", conv_id)
        return
    # Find latest customer PUBLIC message (match by participant id, not by
    # excluding 'agent' — operator messages also have source != 'agent').
    last_customer = None
    for m in reversed(msgs):
        vis = m.visibility.value if hasattr(m.visibility, "value") else str(m.visibility)
        if vis == "public" and m.source in customer_ids:
            last_customer = m
            break
    if last_customer is None:
        return
    # Any later PUBLIC message from agent OR operator counts as a reply — if
    # the operator already answered during TAKEOVER, don't re-fire AI on
    # release.
    answered = any(
        n.source not in customer_ids
        and (n.visibility.value if hasattr(n.visibility, "value") else str(n.visibility)) == "public"
        and n.sequence_number > last_customer.sequence_number
        for n in msgs
    )
    if answered:
        return
    cust_ws = _customer_ws_by_conv.get(conv_id)
    if cust_ws is None:
        logger.warning("[AI-trigger] %s: no customer WS for conv=%s", log_reason, conv_id)
        return
    logger.warning(
        "[AI-trigger] %s conv=%s replying to pending: %.40s",
        log_reason, conv_id, last_customer.content,
    )
    asyncio.create_task(
        _generate_agent_reply(engine, conv_id, last_customer.content, cust_ws),
        name=task_name,
    )


_CSAT_PROMPTS = {
    "resolved": "How would you rate this conversation?",
    "abandoned": "We're sorry we couldn't fully resolve your issue. Would you mind rating your experience?",
}


async def _push_csat_request(
    conversation_id: str, *, reason: str = "resolved",
) -> None:
    """Push S10 csat_request frame to customer + subscribed operator connections.

    Called fire-and-forget after /resolve or /abandon succeeds. Prompt copy
    differs by reason. Uses squad-filtered broadcast (T6A.2).
    """
    try:
        frame = build_frame("csat_request", {
            "conversation_id": conversation_id,
            "prompt": _CSAT_PROMPTS.get(reason, _CSAT_PROMPTS["resolved"]),
            "options": [1, 2, 3, 4, 5],
            "reason": reason,
        })
        # Push to the customer's direct WS (subscription registry would miss it
        # since customers don't subscribe to squads).
        cust_ws = _customer_ws_by_conv.get(conversation_id)
        if cust_ws is not None:
            try:
                await cust_ws.send_json(frame)
            except Exception:
                _customer_ws_by_conv.pop(conversation_id, None)
        await _broadcast_to_squad(frame, conversation_id)
    except Exception:
        logger.debug("csat_request push failed for conv=%s", conversation_id)


# ---------------------------------------------------------------------------
# Agent response pipeline (CCPool integration)
# ---------------------------------------------------------------------------

async def _generate_agent_reply(
    engine: ConversationEngine,
    conv_id: str,
    customer_text: str,
    ws: WebSocket,
) -> None:
    """Call CCPool to generate an AI reply and push it to the customer via WS.

    Runs as a fire-and-forget task after the customer message is confirmed.
    Falls back gracefully if pool is unavailable.
    """
    try:
        logger.info("Agent reply: starting for conv=%s text=%.40s", conv_id, customer_text)
        from autoservice.web_gateway import _get_pool
        pool = await _get_pool()
        if pool is None:
            logger.warning("Agent reply: no CCPool available, skipping")
            return

        logger.info("Agent reply: pool ready, sending to CC SDK...")

        # --- Triage & route (spec 2026-04-21) ---
        from autoservice.triage_dispatch import (
            triage_and_route, _build_reseeded_prompt,
        )
        from autoservice.triage_config_loader import load_tenant_config_for_conv

        tenant_config = await load_tenant_config_for_conv(engine, conv_id)
        triage_enabled = getattr(tenant_config, "triage_dispatch_enabled", True)

        target_role = "customer"
        previous_role = None
        if triage_enabled:
            try:
                decision = await triage_and_route(
                    engine=engine, conv_id=conv_id,
                    customer_text=customer_text, tenant_config=tenant_config,
                )
                target_role = decision.role
                previous_role = decision.previous_role
            except Exception:
                logger.exception("triage_and_route failed; falling back to customer")

        # Re-seed history if role switched
        if previous_role and previous_role != target_role:
            customer_text_for_prompt = await _build_reseeded_prompt(
                engine, conv_id, customer_text,
                previous_role=previous_role, new_role=target_role,
                token_limit=getattr(tenant_config, "history_reseed_token_limit", 2000),
            )
        else:
            customer_text_for_prompt = customer_text

        # Build prompt
        suggestions = await _collect_operator_suggestions(engine, conv_id)
        tenant_id = getattr(tenant_config, "tenant_id", None)

        if target_role == "customer":
            from autoservice.triage_dispatch import _build_customer_prompt
            prompt = await _build_customer_prompt(
                tenant_id=tenant_id,
                customer_text=customer_text_for_prompt,
                operator_suggestions=suggestions,
            )
        else:
            prompt_parts: list[str] = []
            if suggestions:
                prompt_parts.append(suggestions)
                prompt_parts.append(
                    f"Customer message: {customer_text_for_prompt}\n\n"
                    "You are a customer service AI. The operator has given you instructions above — "
                    "follow them when replying to the customer. Reply in the same language as the customer."
                )
            else:
                prompt_parts.append(
                    f"Customer message: {customer_text_for_prompt}\n\nReply briefly in the same language as the customer."
                )
            prompt = "\n".join(prompt_parts)

        # Collect response
        reply_text = ""
        from claude_agent_sdk.types import AssistantMessage, ResultMessage

        async def _role_stream():
            """Yield Messages from a (role, tenant) sub-pool instance.

            On acquire failure, writes a SIDE warning and falls back to the
            customer sticky session (spec §6)."""
            from autoservice.conversation_engine.types import MessageVisibility
            try:
                async with pool.acquire(
                    role=target_role, tenant_id=tenant_id, timeout=2.0,
                ) as inst:
                    inst._sticky_conv_id = conv_id  # type: ignore[attr-defined]
                    await inst.client.query(prompt, session_id=f"{target_role}-{conv_id}")
                    first = True
                    async for m in inst.client.receive_response():
                        if first:
                            try:
                                await engine.update_triage_state(conv_id, cc_instance_id=inst.id)
                            except Exception:
                                logger.warning("failed to pin cc_instance_id for conv=%s", conv_id)
                            first = False
                        yield m
            except Exception:
                logger.exception(
                    "triage: role=%s sub-pool acquire/stream failed, falling back to customer",
                    target_role,
                )
                # Clear any stale instance pin.
                try:
                    await engine.update_triage_state(conv_id, cc_instance_id=None)
                except Exception:
                    pass
                try:
                    await engine.send_message(
                        conv_id, source="triage",
                        content=f"[分流警告] target_role={target_role} 池获取失败,降级到 customer",
                        requested_visibility=MessageVisibility.SIDE,
                        metadata={"type": "sla_warning", "failed_role": target_role},
                    )
                except Exception:
                    pass
                async for m in pool.session_query(conv_id, prompt):
                    yield m

        iterator = (
            pool.session_query(conv_id, prompt, tenant_id=tenant_id)
            if target_role == "customer"
            else _role_stream()
        )

        try:
            async for msg in iterator:
                cls = type(msg).__name__
                logger.debug("Agent reply: stream msg type=%s", cls)
                if isinstance(msg, AssistantMessage) and msg.content:
                    for block in msg.content:
                        if hasattr(block, "text"):
                            reply_text += block.text
                elif isinstance(msg, ResultMessage) and msg.result:
                    reply_text = msg.result
        except StickyTenantMismatch as exc:
            logger.warning("Sticky tenant mismatch conv=%s: %s", conv_id, exc)
            try:
                await engine.send_message(
                    conv_id, source="triage",
                    content=f"[系统] 会话 tenant 状态冲突（{exc}），本轮跳过 AI 回复。",
                    requested_visibility=MessageVisibility.SIDE,
                    metadata={"type": "sticky_tenant_mismatch"},
                )
            except Exception:
                logger.exception(
                    "Failed to write sticky_tenant_mismatch SIDE for conv=%s",
                    conv_id,
                )
            return

        if not reply_text.strip():
            logger.warning("Agent reply: empty response from CC SDK")
            return

        logger.info("Agent reply: got response len=%d, storing...", len(reply_text))

        # Re-check mode — operator may have hijacked while CC SDK was streaming.
        # If so, discard the reply: operator is now driving and customer should
        # see operator's message, not a stale AI reply.
        from autoservice.conversation_engine.types import ConversationMode
        try:
            conv_now = await engine.get_conversation(conv_id)
            current_mode = getattr(conv_now, "mode", None)
        except Exception:
            current_mode = None
        if current_mode == ConversationMode.TAKEOVER:
            logger.info("Agent reply discarded: conv=%s switched to TAKEOVER mid-flight", conv_id)
            return

        # Store agent reply in engine (PUBLIC visibility for customer)
        agent_msg = await engine.send_message(
            conv_id, source="agent", content=reply_text.strip(),
        )

        # Record SLA first_reply_ms (T6D.1)
        try:
            created_at = _conv_created_at.get(conv_id)
            if created_at is not None and conv_id not in _conv_first_reply_sent:
                _conv_first_reply_sent.add(conv_id)
                latency_ms = (_time.time() - created_at) * 1000
                from autoservice.api_routes import get_sla_aggregator
                from autoservice.sla_aggregator import MetricType
                sla = get_sla_aggregator()
                sla.record(MetricType.FIRST_REPLY_MS, latency_ms)
                sla.record(MetricType.TTFB_MS, latency_ms)
        except Exception:
            logger.warning("Failed to record first_reply SLA for conv=%s", conv_id)

        # Push to customer via WebSocket
        frame = _message_frame(agent_msg)
        await ws.send_json(frame)
        logger.info("Agent reply pushed: conv=%s len=%d", conv_id, len(reply_text))

        # Broadcast to operator connections subscribed to this squad (T6A.2)
        await _broadcast_to_squad(frame, conv_id, exclude_ws=ws)

    except Exception:
        logger.exception("Agent reply FAILED for conv=%s", conv_id)
