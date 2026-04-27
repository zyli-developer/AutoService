"""FastAPI router with POST /chat/{tenant_id}. Spec §4.

Wires together: API-key auth → tenant resolver → conversation_engine →
turn_queue → stream_agent_reply → SSEStream / JSONSink.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from autoservice.conversation_engine.errors import ConversationNotFound
from autoservice.conversation_engine.types import Participant, ParticipantRole
from autoservice.gateway.message_router import _broadcast_to_squad
from autoservice.gateway.message_router import _message_frame
from autoservice.gateway.tenant_resolver import resolve_customer_tenant
from autoservice.gateway.turn_queue import QueueFullError
from autoservice.integrations.general_bot.auth import verify_api_key
from autoservice.integrations.general_bot.reply_pipeline import stream_agent_reply
from autoservice.integrations.general_bot.sse import (
    SSEStream, JSONSink,
)

logger = logging.getLogger("autoservice.general_bot.routes")

general_bot_router = APIRouter(tags=["general-bot"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_UNAUTHORIZED_BODY = {"error": "unauthorized"}


class _TenantMismatchError(Exception):
    """Raised by _persist_customer_message when conv reuse hits a tenant
    boundary mismatch (data corruption only)."""


def _extract_query(body: Any) -> str | None:
    """Accept both modern ({"query": ...}) and legacy ({"queryResult":{"queryText":...}}) shapes."""
    if not isinstance(body, dict):
        return None
    q = body.get("query")
    if isinstance(q, str) and q.strip():
        return q
    qr = body.get("queryResult")
    if isinstance(qr, dict):
        qt = qr.get("queryText")
        if isinstance(qt, str) and qt.strip():
            return qt
    return None


def _wants_streaming(accept_header: str | None) -> bool:
    if not accept_header:
        return False
    return "text/event-stream" in accept_header.lower()


def _bearer_token(auth_header: str | None) -> str | None:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


async def _persist_customer_message(
    engine, *, tenant_id: str, inquiry_id: str | None, query: str,
) -> tuple[str, Any]:
    """Idempotent conv create + customer message persist + squad broadcast.

    Returns (conv_id, customer_msg).
    """
    from autoservice.web_gateway import _get_squad_plugin

    if inquiry_id:
        external_id = f"{tenant_id}:{inquiry_id}"
        channel = "cinnox"
    else:
        external_id = str(uuid.uuid4())
        channel = "cinnox-oneshot"

    sp = _get_squad_plugin()
    squad_id = sp.choose_squad(channel="cinnox") if sp else None

    metadata = {
        "tenant_id": tenant_id,
        "passive_channel": True,
    }
    if inquiry_id:
        metadata["inquiry_id"] = inquiry_id
    if squad_id:
        metadata["squad_id"] = squad_id

    conv = await engine.create_conversation(
        channel=channel, external_id=external_id, metadata=metadata,
    )
    conv_id = conv.id

    # Defensive: on reuse, ensure tenant matches (only fails on data corruption)
    existing_tid = conv.metadata.get("tenant_id")
    if existing_tid and existing_tid != tenant_id:
        logger.error(
            "tenant mismatch on conv reuse: conv=%s expected=%s got=%s",
            conv_id, tenant_id, existing_tid,
        )
        raise _TenantMismatchError(conv_id)

    source = f"cinnox:{inquiry_id or 'anon'}"
    now = datetime.now(timezone.utc)
    # Auto-join the customer + agent participants on first turn
    try:
        await engine.join(
            conv_id,
            Participant(id=source, role=ParticipantRole.CUSTOMER, joined_at=now),
        )
    except Exception:
        pass  # already joined
    try:
        await engine.join(
            conv_id,
            Participant(id="agent", role=ParticipantRole.AGENT, joined_at=now),
        )
    except Exception:
        pass  # already joined

    msg = await engine.send_message(conv_id, source=source, content=query)

    # Broadcast customer message to operator squad (E1)
    try:
        frame = _message_frame(msg)
        frame["payload"]["source_display"] = {"id": source, "role": "customer"}
        if squad_id:
            frame["payload"]["squad_id"] = squad_id
        await _broadcast_to_squad(frame, conv_id)
    except Exception:
        logger.exception("customer broadcast failed conv=%s", conv_id)

    return conv_id, msg


@general_bot_router.post("/chat/{tenant_id}")
async def post_chat(tenant_id: str, request: Request):
    if os.getenv("GENERAL_BOT_ENABLED", "1") != "1":
        return JSONResponse(status_code=503, content={"error": "general_bot disabled"})

    # 1. Auth (verify Bearer key first; same body as 404 → no oracle)
    raw_key = _bearer_token(request.headers.get("authorization"))
    if not raw_key or not verify_api_key(tenant_id, raw_key):
        return JSONResponse(status_code=401, content=_UNAUTHORIZED_BODY)

    # 2. Tenant resolve (registration markers must exist)
    tid, reject_reason = resolve_customer_tenant({"tenant": tenant_id})
    if reject_reason is not None:
        return JSONResponse(status_code=401, content=_UNAUTHORIZED_BODY)

    # 3. Body parse
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(status_code=422, content={"error": "invalid JSON body"})
    query = _extract_query(body)
    if not query:
        return JSONResponse(status_code=422, content={"error": "query required"})
    inquiry_id = body.get("inquiryID") if isinstance(body, dict) else None
    if inquiry_id is not None and not isinstance(inquiry_id, str):
        return JSONResponse(status_code=422, content={"error": "inquiryID must be string"})

    engine = request.app.state.engine
    from autoservice.web_gateway import _get_pool
    pool = await _get_pool()
    if pool is None:
        return JSONResponse(status_code=503, content={"error": "cc_pool unavailable"})

    # 4. Persist customer message + squad broadcast
    try:
        conv_id, _customer_msg = await _persist_customer_message(
            engine, tenant_id=tid, inquiry_id=inquiry_id, query=query,
        )
    except _TenantMismatchError:
        return JSONResponse(status_code=401, content=_UNAUTHORIZED_BODY)

    # 5. Dispatch (streaming or JSON)
    streaming = _wants_streaming(request.headers.get("accept"))
    if streaming:
        return await _dispatch_streaming(
            engine=engine, pool=pool, conv_id=conv_id,
            query=query, tenant_id=tid,
        )
    else:
        return await _dispatch_json(
            engine=engine, pool=pool, conv_id=conv_id,
            query=query, tenant_id=tid,
        )


async def _dispatch_json(*, engine, pool, conv_id, query, tenant_id):
    sink = JSONSink()
    await stream_agent_reply(
        engine=engine, pool=pool, conv_id=conv_id,
        customer_text=query, tenant_id=tenant_id, sink=sink,
    )
    return JSONResponse(content=sink.body)


async def _dispatch_streaming(*, engine, pool, conv_id, query, tenant_id):
    """Bridge the runner → SSE wire via an asyncio.Queue (spec §8)."""
    queue: asyncio.Queue = asyncio.Queue()

    async def _send(line: bytes) -> None:
        await queue.put(line)

    sink = SSEStream(_send)

    async def _runner():
        try:
            await stream_agent_reply(
                engine=engine, pool=pool, conv_id=conv_id,
                customer_text=query, tenant_id=tenant_id, sink=sink,
            )
        except Exception:
            logger.exception("stream_agent_reply failed conv=%s", conv_id)
            try:
                await sink.emit_terminal("(抱歉,本次未能生成完整回复)")
            except Exception:
                pass
        finally:
            await sink.close()
            await queue.put(None)  # sentinel

    runner_task = asyncio.create_task(_runner(), name=f"general-bot-{conv_id}")

    async def _generator():
        # Initial keepalive: defeat LB idle while runner is starting
        yield b": keepalive\n\n"
        try:
            while True:
                line = await queue.get()
                if line is None:
                    return
                yield line
        finally:
            if not runner_task.done():
                runner_task.cancel()

    return StreamingResponse(
        _generator(), media_type="text/event-stream", headers=_SSE_HEADERS,
    )
