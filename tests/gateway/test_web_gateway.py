"""T0.5 WebSocket gateway skeleton tests (test-plan-002).

27 test cases covering 6 groups: app/routes, handshake, envelope validation,
engine error mapping, heartbeat/disconnect, CORS. (TC-027 contract regression
is a separate skill-4 invocation.)
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi import FastAPI
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient

from autoservice.conversation_engine import LocalEngine
from autoservice.web_gateway import create_app

from tests.gateway.conftest import (
    DummyEngine,
    handshake,
    make_frame,
    make_message,
)


HINT_RE = re.compile(r"T[12]A\.\d+")


# ---------- Group A: app build & routes ----------

def test_tc001_create_app_returns_fastapi():
    """TC-001: create_app returns a FastAPI instance."""
    app = create_app()
    assert isinstance(app, FastAPI)


def test_tc002_app_has_three_ws_routes():
    """TC-002: app registers /ws/customer, /ws/operator, /ws/admin."""
    app = create_app()
    ws_paths = {r.path for r in app.routes if isinstance(r, WebSocketRoute)}
    assert {"/ws/customer", "/ws/operator", "/ws/admin"} <= ws_paths


def test_tc003_engine_injection_is_respected():
    """TC-003: create_app(engine=X) uses X instead of LocalEngine."""
    dummy = DummyEngine()
    app = create_app(engine=dummy)
    assert app.state.engine is dummy


def test_tc004_default_engine_is_local_engine():
    """TC-004: create_app() defaults to LocalEngine."""
    app = create_app()
    assert isinstance(app.state.engine, LocalEngine)


# ---------- Group B: handshake ----------

@pytest.mark.parametrize(
    "endpoint,expected_role",
    [("/ws/customer", "customer"), ("/ws/operator", "operator"), ("/ws/admin", "admin")],
)
def test_tc005_006_007_handshake_viewer_role(
    local_engine_client, operator_session_cookie, endpoint, expected_role
):
    """TC-005/006/007: handshake returns server_hello with correct viewer_role."""
    from autoservice import operators as _ops
    if expected_role == "operator":
        local_engine_client.cookies.set(
            _ops.OPERATOR_SESSION_COOKIE_NAME, operator_session_cookie
        )
    with local_engine_client.websocket_connect(endpoint) as ws:
        reply = handshake(ws, viewer_role_expected=expected_role)
        payload = reply["payload"]
        assert payload["protocol_version"] == 1
        assert isinstance(payload["session_id"], str) and payload["session_id"]
        assert payload["accepted_subscriptions"] == []
        assert payload["server_capabilities"]
        assert payload["server_time"]


def test_tc008_business_frame_before_handshake_rejected(local_engine_client):
    """TC-008: sending a non-client_hello frame first fails handshake."""
    with local_engine_client.websocket_connect("/ws/customer") as ws:
        ws.send_json(make_frame("customer_message", {"conversation_id": "c", "content": "hi"}))
        reply = ws.receive_json()
        assert reply["type"] == "error"
        assert reply["payload"]["code"] == "4012_VALIDATION"


def test_tc009_handshake_version_incompatible(local_engine_client):
    """TC-009: client_hello with unsupported protocol_version → 4040."""
    with local_engine_client.websocket_connect("/ws/customer") as ws:
        ws.send_json(make_frame("client_hello", {"protocol_version": 2}))
        reply = ws.receive_json()
        assert reply["type"] == "error"
        assert reply["payload"]["code"] == "4040_VERSION_INCOMPATIBLE"


# ---------- Group C: envelope validation ----------

@pytest.mark.parametrize(
    "missing_field",
    ["id", "ts", "type", "payload"],
)
def test_tc010_011_envelope_missing_field(local_engine_client, missing_field):
    """TC-010/011: missing id/ts/type/payload → 4012 with `missing` in details."""
    with local_engine_client.websocket_connect("/ws/customer") as ws:
        handshake(ws, viewer_role_expected="customer")
        frame = make_frame("ping")
        del frame[missing_field]
        ws.send_json(frame)
        reply = ws.receive_json()
        assert reply["type"] == "error"
        assert reply["payload"]["code"] == "4012_VALIDATION"
        assert missing_field in reply["payload"].get("details", {}).get("missing", [])


def test_tc012_envelope_id_not_uuid4(local_engine_client):
    """TC-012: non-UUIDv4 id → 4012."""
    with local_engine_client.websocket_connect("/ws/customer") as ws:
        handshake(ws, viewer_role_expected="customer")
        frame = make_frame("ping", id_="not-a-uuid")
        ws.send_json(frame)
        reply = ws.receive_json()
        assert reply["type"] == "error"
        assert reply["payload"]["code"] == "4012_VALIDATION"


def test_tc013_envelope_ts_format_invalid(local_engine_client):
    """TC-013: ts not ISO8601 UTC ms → 4012."""
    with local_engine_client.websocket_connect("/ws/customer") as ws:
        handshake(ws, viewer_role_expected="customer")
        frame = make_frame("ping", ts="2026-04-15 10:30:00")
        ws.send_json(frame)
        reply = ws.receive_json()
        assert reply["type"] == "error"
        assert reply["payload"]["code"] == "4012_VALIDATION"


def test_tc014_envelope_v_not_accepted(local_engine_client):
    """TC-014: v != 1 → 4040."""
    with local_engine_client.websocket_connect("/ws/customer") as ws:
        handshake(ws, viewer_role_expected="customer")
        frame = make_frame("ping", v=2)
        ws.send_json(frame)
        reply = ws.receive_json()
        assert reply["type"] == "error"
        assert reply["payload"]["code"] == "4040_VERSION_INCOMPATIBLE"


def test_tc015_envelope_with_valid_ref_accepted(local_engine_client):
    """TC-015: legitimate ref does not fail validation."""
    with local_engine_client.websocket_connect("/ws/customer") as ws:
        handshake(ws, viewer_role_expected="customer")
        ref = str(uuid.uuid4())
        ws.send_json(make_frame("ping", ref=ref))
        reply = ws.receive_json()
        assert reply["type"] == "pong"  # validation passed; ping→pong path


def test_tc016_unknown_type(local_engine_client):
    """TC-016: unknown frame type → 4012 with unknown_type in details."""
    with local_engine_client.websocket_connect("/ws/customer") as ws:
        handshake(ws, viewer_role_expected="customer")
        ws.send_json(make_frame("no_such_type"))
        reply = ws.receive_json()
        assert reply["type"] == "error"
        assert reply["payload"]["code"] == "4012_VALIDATION"
        assert reply["payload"]["details"]["unknown_type"] == "no_such_type"


# ---------- Group D: engine error mapping ----------

def test_tc017_customer_message_auto_creates_conversation(local_engine_client):
    """TC-017: customer_message with unknown conv auto-creates conversation → ack + message."""
    with local_engine_client.websocket_connect("/ws/customer") as ws:
        handshake(ws, viewer_role_expected="customer")
        frame = make_frame(
            "customer_message",
            {"conversation_id": "nonexistent-conv", "content": "hi"},
        )
        ws.send_json(frame)
        ack = ws.receive_json()
        assert ack["type"] == "ack"
        assert ack["ref"] == frame["id"]
        msg = ws.receive_json()
        assert msg["type"] == "message_confirm"
        assert msg["payload"]["message_id"]
        assert msg["payload"]["conversation_id"]


def test_tc018_operator_command_not_implemented_returns_command_response(
    local_engine_client, operator_session_cookie
):
    """TC-018: /hijack NotImplementedError → command_response{ok:false}, NOT error frame."""
    from autoservice import operators as _ops
    local_engine_client.cookies.set(
        _ops.OPERATOR_SESSION_COOKIE_NAME, operator_session_cookie
    )
    with local_engine_client.websocket_connect("/ws/operator") as ws:
        handshake(ws, viewer_role_expected="operator")
        frame = make_frame(
            "operator_command",
            {"conversation_id": "c-1", "operator_id": "op1", "command": "/hijack"},
        )
        ws.send_json(frame)
        reply = ws.receive_json()
        assert reply["type"] == "command_response"
        assert reply["payload"]["ok"] is False
        assert reply["payload"]["error_code"] == "5010_INTERNAL"
        assert reply["payload"]["command"] == "/hijack"
        assert reply.get("ref") == frame["id"]


def test_tc019_admin_command_not_implemented_returns_command_response(local_engine_client):
    """TC-019: admin_command NotImplementedError also goes through command_response."""
    with local_engine_client.websocket_connect("/ws/admin") as ws:
        handshake(ws, viewer_role_expected="admin")
        frame = make_frame("admin_command", {"command": "/status", "args": {}})
        ws.send_json(frame)
        reply = ws.receive_json()
        assert reply["type"] == "command_response"
        assert reply["payload"]["ok"] is False
        assert reply["payload"]["error_code"] == "5010_INTERNAL"


def test_tc020_dummy_engine_success_returns_ack_and_message(dummy_engine, dummy_engine_client):
    """TC-020: DummyEngine.send_message returning a Message produces ack + message frame."""
    async def _send(conv_id, *, source, content, **_):
        return make_message(conversation_id=conv_id, source=source, content=content)

    dummy_engine.set_send_message(_send)
    dummy_engine._known_convs.add("c-1")  # pre-register so auto-create is skipped

    with dummy_engine_client.websocket_connect("/ws/customer") as ws:
        handshake(ws, viewer_role_expected="customer")
        frame = make_frame(
            "customer_message", {"conversation_id": "c-1", "content": "hello"}
        )
        ws.send_json(frame)
        ack = ws.receive_json()
        assert ack["type"] == "ack"
        assert ack["ref"] == frame["id"]
        msg = ws.receive_json()
        assert msg["type"] == "message_confirm"
        assert msg["payload"]["conversation_id"] == "c-1"
        assert msg["payload"]["message_id"]


def test_tc021_dummy_engine_unexpected_exception_returns_5010_error(
    dummy_engine, dummy_engine_client
):
    """TC-021: ValueError (non-NotImplementedError) → 5010_INTERNAL error."""
    async def _send(*_args, **_kwargs):
        raise ValueError("oops")

    dummy_engine.set_send_message(_send)

    with dummy_engine_client.websocket_connect("/ws/customer") as ws:
        handshake(ws, viewer_role_expected="customer")
        ws.send_json(
            make_frame("customer_message", {"conversation_id": "c-1", "content": "x"})
        )
        reply = ws.receive_json()
        assert reply["type"] == "error"
        assert reply["payload"]["code"] == "5010_INTERNAL"


def test_tc022_customer_frame_on_operator_endpoint_rejected(
    local_engine_client, operator_session_cookie
):
    """TC-022: customer_message on /ws/operator → 4012 (frame_not_allowed_on_endpoint)."""
    from autoservice import operators as _ops
    local_engine_client.cookies.set(
        _ops.OPERATOR_SESSION_COOKIE_NAME, operator_session_cookie
    )
    with local_engine_client.websocket_connect("/ws/operator") as ws:
        handshake(ws, viewer_role_expected="operator")
        ws.send_json(
            make_frame("customer_message", {"conversation_id": "c", "content": "x"})
        )
        reply = ws.receive_json()
        assert reply["type"] == "error"
        assert reply["payload"]["code"] == "4012_VALIDATION"
        assert reply["payload"]["details"]["reason"] == "frame_not_allowed_on_endpoint"


# ---------- Group E: heartbeat & disconnect ----------

def test_tc023_ping_pong(local_engine_client):
    """TC-023: ping → pong without ack."""
    with local_engine_client.websocket_connect("/ws/customer") as ws:
        handshake(ws, viewer_role_expected="customer")
        ws.send_json(make_frame("ping"))
        reply = ws.receive_json()
        assert reply["type"] == "pong"
        assert "server_time" in reply["payload"]


def test_tc024_pong_not_in_dispatch_ack_chain():
    """TC-024: message_router does not route ping/pong/ack/error through the ack chain.

    Code-inspection style: verify the dispatch module imports.
    """
    import autoservice.gateway.message_router as mr
    assert "ping" not in mr._COMMAND_FRAMES
    assert "pong" not in mr._KNOWN_FRAMES  # server-side only; not a FE→BE type


def test_tc025_clean_disconnect(local_engine_client):
    """TC-025: exiting websocket_connect context leaves the server cleanly."""
    with local_engine_client.websocket_connect("/ws/customer") as ws:
        handshake(ws, viewer_role_expected="customer")
    # second connect must still work, proving no lingering state
    with local_engine_client.websocket_connect("/ws/customer") as ws:
        handshake(ws, viewer_role_expected="customer")


# ---------- Group F: CORS ----------

@pytest.mark.parametrize(
    "origin",
    ["http://localhost:5173", "http://localhost:5174", "http://localhost:5175"],
)
def test_tc026_cors_allows_frontend_ports(local_engine_client, origin):
    """TC-026: CORS allows the 3 frontend dev ports."""
    resp = local_engine_client.options(
        "/ws/customer",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    # CORSMiddleware returns 200 for preflight; header echoes the origin
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == origin
