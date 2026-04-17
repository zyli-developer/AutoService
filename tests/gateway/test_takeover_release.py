"""E2E-ish gateway test for takeover auto-release flow via WebSocket."""
import time
import uuid
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from autoservice.web_gateway import create_app
from autoservice.takeover_config import TakeoverConfig


def _ts() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _frame(type_: str, payload: dict) -> dict:
    return {"v": 1, "type": type_, "id": str(uuid.uuid4()), "ts": _ts(), "payload": payload}


def _hello(client_app="operator-console", operator_id=None):
    payload = {"protocol_version": 1, "client_app": client_app}
    if operator_id:
        payload["operator_id"] = operator_id
    return _frame("client_hello", payload)


@pytest.fixture
def fast_takeover_app(monkeypatch):
    """App configured with a tiny takeover timer so tests are fast."""
    import autoservice.web_gateway as wg
    fast = TakeoverConfig(idle_timeout_ms=150, warning_ms=50, offline_grace_ms=200)
    monkeypatch.setattr(wg, "_TAKEOVER_CONFIG_OVERRIDE", fast, raising=False)
    return create_app()


# ── Helpers ────────────────────────────────────────────────
def _setup(cws, ows, operator_id="op42"):
    cws.send_json(_hello("customer-chat"))
    ows.send_json(_hello("operator-console", operator_id=operator_id))
    cws.receive_json(); ows.receive_json()
    ows.send_json(_frame("subscribe", {"scope": {"squad_id": "web-support"}}))
    while ows.receive_json()["type"] != "subscription_added":
        pass


def _customer_start_conv(cws):
    cws.send_json(_frame("customer_message", {"source": "cust1", "content": "hi"}))
    while True:
        f = cws.receive_json()
        if f["type"] == "message_confirm":
            return f["payload"]["conversation_id"]


def _operator_join(ws, conv_id, op_id):
    """Join an operator participant to a conversation."""
    ws.send_json(_frame("operator_join", {
        "conversation_id": conv_id,
        "operator_id": op_id,
    }))
    # Drain the ack frame
    _wait_frame(ws, "ack", timeout=0.5)


def _send_cmd(ws, conv_id, cmd, op_id):
    ws.send_json(_frame("operator_command", {
        "conversation_id": conv_id,
        "command": cmd,
        "operator_id": op_id,
    }))


def _wait_frame(ws, frame_type, timeout=1.0):
    """Receive frames in a background thread until we see frame_type or timeout."""
    import queue
    import threading

    result_q: queue.Queue = queue.Queue()

    def _recv_loop():
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                f = ws.receive_json()
            except Exception:
                return
            if f["type"] == frame_type:
                result_q.put(f)
                return
            # Keep looping on other frame types

    t = threading.Thread(target=_recv_loop, daemon=True)
    t.start()
    try:
        return result_q.get(timeout=timeout + 0.2)
    except queue.Empty:
        return None


# ── Tests ──────────────────────────────────────────────────
def test_warning_frame_pushed_to_operator_after_hijack(fast_takeover_app):
    with TestClient(fast_takeover_app) as client:
        with client.websocket_connect("/ws/customer") as cws, \
             client.websocket_connect("/ws/operator") as ows:
            _setup(cws, ows)
            conv_id = _customer_start_conv(cws)
            _operator_join(ows, conv_id, "op42")
            _send_cmd(ows, conv_id, "/hijack", "op42")

            warning = _wait_frame(ows, "takeover_warning", timeout=1.0)
            assert warning is not None
            assert warning["payload"]["conversation_id"] == conv_id
            assert warning["payload"]["reason"] == "idle"


def test_client_ack_continue_resets_timer(fast_takeover_app):
    with TestClient(fast_takeover_app) as client:
        with client.websocket_connect("/ws/customer") as cws, \
             client.websocket_connect("/ws/operator") as ows:
            _setup(cws, ows)
            conv_id = _customer_start_conv(cws)
            _operator_join(ows, conv_id, "op42")
            _send_cmd(ows, conv_id, "/hijack", "op42")

            warning = _wait_frame(ows, "takeover_warning", timeout=1.0)
            assert warning is not None

            ows.send_json(_frame("client_ack", {
                "action": "continue",
                "conversation_id": conv_id,
                "operator_id": "op42",
            }))
            cancelled = _wait_frame(ows, "takeover_warning_cancelled", timeout=0.5)
            assert cancelled is not None


def test_client_ack_continue_from_customer_does_not_reset(fast_takeover_app):
    """Customer WS client_ack continue cannot reset the operator's takeover timer.

    The actor_id inference only works for operator connections (state_operator_id
    is only set for viewer_role=='operator'). Even if the customer supplies an
    explicit operator_id in the payload, reset_takeover_timer's mode/owner guards
    should prevent any mode state leakage.
    """
    with TestClient(fast_takeover_app) as client:
        with client.websocket_connect("/ws/customer") as cws, \
             client.websocket_connect("/ws/operator") as ows:
            _setup(cws, ows)
            conv_id = _customer_start_conv(cws)
            _operator_join(ows, conv_id, "op42")
            _send_cmd(ows, conv_id, "/hijack", "op42")

            warning = _wait_frame(ows, "takeover_warning", timeout=1.0)
            assert warning is not None

            # Customer attempts to reset — should not produce a cancelled frame
            cws.send_json(_frame("client_ack", {
                "action": "continue",
                "conversation_id": conv_id,
                "operator_id": "op42",
            }))

            # Within a short window (less than 50ms release delay), there should
            # be NO takeover_warning_cancelled frame. Wait 40ms to be well within
            # the window but before auto-release would occur.
            cancelled = _wait_frame(ows, "takeover_warning_cancelled", timeout=0.04)
            assert cancelled is None, "customer should not be able to reset operator's timer"
