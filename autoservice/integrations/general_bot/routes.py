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

RUNNER_TIMEOUT_S = 120.0  # spec §8 total response time cap

import time as _time

# Track conv creation timestamps for SLA first_reply_ms (mirrors message_router)
_conv_created_at: dict[str, float] = {}
_conv_first_reply_sent: set[str] = set()


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


async def _submit_runner(conv_id: str, runner) -> bool:
    """Submit runner via turn_queue (default) or fire-and-forget if QUEUE_ENABLED=0.

    Returns True on success, raises QueueFullError on full queue. Mirrors
    autoservice/gateway/message_router.py's QUEUE_ENABLED gate for parity.
    """
    if os.getenv("QUEUE_ENABLED", "1") == "1":
        from autoservice.gateway.message_router import get_turn_queue
        await get_turn_queue().submit(conv_id, runner)
    else:
        # Legacy concurrent path: each request gets its own task, no FIFO
        asyncio.create_task(runner(), name=f"general-bot-runner-{conv_id}")
    return True


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
    if conv_id not in _conv_created_at:
        _conv_created_at[conv_id] = _time.time()

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


async def _dispatch_streaming(*, engine, pool, conv_id, query, tenant_id):
    """Submit runner to turn_queue + bridge to SSE wire via asyncio.Queue."""
    sse_queue: asyncio.Queue = asyncio.Queue()

    async def _send(line: bytes) -> None:
        await sse_queue.put(line)

    sink = SSEStream(_send)

    async def _runner() -> None:
        try:
            await asyncio.wait_for(
                stream_agent_reply(
                    engine=engine, pool=pool, conv_id=conv_id,
                    customer_text=query, tenant_id=tenant_id, sink=sink,
                ),
                timeout=RUNNER_TIMEOUT_S,
            )
            _record_first_reply_sla(conv_id)
        except asyncio.TimeoutError:
            logger.warning("stream_agent_reply timeout conv=%s", conv_id)
            try:
                await sink.emit_terminal("(超时未生成完整回复)")
            except Exception:
                pass
            try:
                from autoservice.integrations.general_bot.reply_pipeline import (
                    _persist_agent_message,
                )
                await _persist_agent_message(
                    engine, conv_id, "(超时未生成完整回复)",
                    metadata={"is_fallback": True, "is_timeout": True},
                )
            except Exception:
                logger.exception("timeout fallback persist failed conv=%s", conv_id)
        except Exception:
            logger.exception("stream_agent_reply failed conv=%s", conv_id)
            try:
                await sink.emit_terminal("(抱歉,本次未能生成完整回复)")
            except Exception:
                pass
            try:
                from autoservice.integrations.general_bot.reply_pipeline import (
                    _persist_agent_message,
                )
                await _persist_agent_message(
                    engine, conv_id, "(抱歉,本次未能生成完整回复)",
                    metadata={"is_fallback": True},
                )
            except Exception:
                logger.exception("fallback persist failed conv=%s", conv_id)
        finally:
            await sink.close()
            await sse_queue.put(None)

    try:
        await _submit_runner(conv_id, _runner)
    except QueueFullError:
        return JSONResponse(status_code=429, content={"error": "queue full"})

    async def _generator():
        yield b": keepalive\n\n"
        try:
            while True:
                line = await sse_queue.get()
                if line is None:
                    return
                yield line
        finally:
            # Client disconnected mid-stream: close the sink so subsequent
            # runner emits become no-ops and the keepalive task cancels.
            # We can't cancel the runner itself (turn_queue is fire-and-forget),
            # but Task 9's 120s watchdog will bound any orphaned execution.
            await sink.close()

    return StreamingResponse(
        _generator(), media_type="text/event-stream", headers=_SSE_HEADERS,
    )


async def _dispatch_json(*, engine, pool, conv_id, query, tenant_id):
    """JSON path also routes through turn_queue for per-conv FIFO."""
    done = asyncio.Event()
    sink = JSONSink()
    runner_exc: list[Exception] = []

    async def _runner() -> None:
        try:
            await asyncio.wait_for(
                stream_agent_reply(
                    engine=engine, pool=pool, conv_id=conv_id,
                    customer_text=query, tenant_id=tenant_id, sink=sink,
                ),
                timeout=RUNNER_TIMEOUT_S,
            )
            _record_first_reply_sla(conv_id)
        except asyncio.TimeoutError:
            try:
                await sink.emit_terminal("(超时未生成完整回复)")
            except Exception:
                pass
            try:
                from autoservice.integrations.general_bot.reply_pipeline import (
                    _persist_agent_message,
                )
                await _persist_agent_message(
                    engine, conv_id, "(超时未生成完整回复)",
                    metadata={"is_fallback": True, "is_timeout": True},
                )
            except Exception:
                logger.exception("timeout fallback persist failed conv=%s", conv_id)
        except Exception as exc:
            runner_exc.append(exc)
            try:
                await sink.emit_terminal("(抱歉,本次未能生成完整回复)")
            except Exception:
                pass
            try:
                from autoservice.integrations.general_bot.reply_pipeline import (
                    _persist_agent_message,
                )
                await _persist_agent_message(
                    engine, conv_id, "(抱歉,本次未能生成完整回复)",
                    metadata={"is_fallback": True},
                )
            except Exception:
                logger.exception("fallback persist failed conv=%s", conv_id)
        finally:
            await sink.close()
            done.set()

    try:
        await _submit_runner(conv_id, _runner)
    except QueueFullError:
        return JSONResponse(status_code=429, content={"error": "queue full"})

    await done.wait()
    if runner_exc:
        logger.exception("json runner failed", exc_info=runner_exc[0])
        return JSONResponse(
            status_code=500,
            content={"error": "internal"},
        )
    return JSONResponse(content=sink.body)


def _record_first_reply_sla(conv_id: str) -> None:
    """Record SLA first_reply_ms / TTFB_MS once per conv (mirrors WS path)."""
    if conv_id in _conv_first_reply_sent:
        return
    started = _conv_created_at.get(conv_id)
    if started is None:
        return
    _conv_first_reply_sent.add(conv_id)
    latency_ms = (_time.time() - started) * 1000.0
    try:
        from autoservice.api_routes import get_sla_aggregator
        from autoservice.sla_aggregator import MetricType
        sla = get_sla_aggregator()
        sla.record(MetricType.FIRST_REPLY_MS, latency_ms)
        sla.record(MetricType.TTFB_MS, latency_ms)
    except Exception:
        logger.warning("SLA record failed conv=%s", conv_id, exc_info=True)
