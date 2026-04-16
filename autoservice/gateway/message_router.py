"""FE→BE frame router (T0.5 skeleton).

Dispatches parsed Envelope objects to Engine methods per T0.2 §7 mapping table.
Handles error mapping per T0.2 §6.1:
  - command frames (operator_command / admin_command) whose Engine call fails
    → S11 command_response{ok:false}
  - other frames that fail → S4 error frame
  - NotImplementedError (T0.4 skeleton state) → 5000_INTERNAL + details.engine_hint
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, TYPE_CHECKING

from datetime import datetime, timezone

from autoservice.conversation_engine import ConversationEngine
from autoservice.conversation_engine.errors import ConversationNotFound
from autoservice.conversation_engine.types import Participant, ParticipantRole

from .connection import build_frame
from .errors import ERR_INTERNAL, ERR_VALIDATION, make_error_payload
from .envelope import Envelope

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

_HINT_RE = re.compile(r"T[12]A\.\d+")


def _extract_hint(exc: BaseException) -> str | None:
    msg = str(exc) if exc.args else ""
    return msg if _HINT_RE.search(msg) else None


async def dispatch(
    env: Envelope,
    *,
    viewer_role: str,
    engine: ConversationEngine,
    ws: WebSocket | None = None,
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
        return [build_frame("pong", {"server_time": _now_iso_ms()})]

    # client_ack / subscribe / unsubscribe — skeleton acks only (Phase 1+ implements)
    if frame_type in {"client_ack", "subscribe", "unsubscribe"}:
        return [build_frame("ack", {}, ref=env.id)]

    # Command frames → command_response path (§6.1)
    if frame_type in _COMMAND_FRAMES:
        return await _dispatch_command(env, engine=engine)

    # Non-command frames → engine call → ack (+ maybe message frame)
    return await _dispatch_engine(env, frame_type=frame_type, viewer_role=viewer_role, engine=engine, ws=ws)


async def _dispatch_command(env: Envelope, *, engine: ConversationEngine) -> list[dict[str, Any]]:
    payload = env.payload
    command = payload.get("command", "")
    conversation_id = payload.get("conversation_id", "")
    actor_id = payload.get("operator_id") or payload.get("actor_id") or ""
    args = payload.get("args") or {}
    try:
        await engine.handle_command(
            conversation_id,
            actor_id=actor_id,
            command=command,
            args=args,
        )
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
    # Skeleton never reaches "success" because no Engine implements handle_command yet.
    return [
        build_frame(
            "command_response",
            {"command": command, "ok": True, "result": None},
            ref=env.id,
        )
    ]


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
            conv = await engine.create_conversation(
                channel="web", external_id=source,
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
        msg = await engine.send_message(
            conv_id, source=source, content=payload["content"],
        )

        # Broadcast customer message to operator connections
        customer_frame = _message_frame(msg)
        customer_frame["payload"]["source_display"] = {"id": source, "role": "customer"}
        from autoservice.web_gateway import _ws_connections
        for sid, ows in list(_ws_connections.items()):
            if ows is not ws:
                try:
                    await ows.send_json(customer_frame)
                except Exception:
                    pass

        # Fire-and-forget: trigger agent response via CCPool
        if ws is not None:
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
        msg = await engine.send_message(
            payload["conversation_id"],
            source=payload.get("operator_id", "operator"),
            content=payload["content"],
        )
        return [_message_frame(msg)]

    if frame_type == "csat_response":
        await engine.set_csat(payload["conversation_id"], int(payload["score"]))
        return []

    if frame_type == "history_request":
        msgs = await engine.get_messages(
            payload["conversation_id"],
            since_sequence=payload.get("since_sequence"),
            before_sequence=payload.get("before_sequence"),
            limit=payload.get("limit", 50),
        )
        return [
            build_frame(
                "history_snapshot",
                {
                    "conversation_id": payload["conversation_id"],
                    "messages": [_serialize_message(m) for m in msgs],
                    "has_more": False,
                },
            )
        ]

    if frame_type == "operator_join":
        # Skeleton: will call Engine.join; Engine currently raises NotImplementedError
        await engine.join(payload["conversation_id"], payload.get("operator"))  # type: ignore[arg-type]
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


def _now_iso_ms() -> str:
    from .connection import now_iso_ms
    return now_iso_ms()


async def _collect_operator_suggestions(
    engine: ConversationEngine, conv_id: str, limit: int = 5,
) -> str:
    """Collect recent SIDE-visibility messages as operator suggestions for agent context."""
    try:
        msgs = await engine.get_messages(conv_id, viewer_role="operator", limit=20)
        side_msgs = [
            m for m in msgs
            if m.visibility.value == "side" and m.source != "agent"
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

        # Build prompt
        suggestions = await _collect_operator_suggestions(engine, conv_id)
        prompt_parts = []
        if suggestions:
            prompt_parts.append(suggestions)
        prompt_parts.append(f"Customer message: {customer_text}\n\nReply briefly in the same language as the customer.")
        prompt = "\n".join(prompt_parts)

        # Collect response
        reply_text = ""
        from claude_agent_sdk.types import AssistantMessage, ResultMessage
        async for msg in pool.session_query(conv_id, prompt):
            cls = type(msg).__name__
            logger.debug("Agent reply: stream msg type=%s", cls)
            if isinstance(msg, AssistantMessage) and msg.content:
                for block in msg.content:
                    if hasattr(block, "text"):
                        reply_text += block.text
            elif isinstance(msg, ResultMessage) and msg.result:
                reply_text = msg.result

        if not reply_text.strip():
            logger.warning("Agent reply: empty response from CC SDK")
            return

        logger.info("Agent reply: got response len=%d, storing...", len(reply_text))

        # Store agent reply in engine
        agent_msg = await engine.send_message(
            conv_id, source="agent", content=reply_text.strip(),
        )

        # Push to customer via WebSocket
        frame = _message_frame(agent_msg)
        await ws.send_json(frame)
        logger.info("Agent reply pushed: conv=%s len=%d", conv_id, len(reply_text))

        # Also broadcast to operator connections
        from autoservice.web_gateway import _ws_connections
        for sid, ows in list(_ws_connections.items()):
            if ows is not ws:
                try:
                    await ows.send_json(frame)
                except Exception:
                    pass

    except Exception:
        logger.exception("Agent reply FAILED for conv=%s", conv_id)
