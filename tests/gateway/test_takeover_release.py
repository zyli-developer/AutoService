"""E2E-ish gateway test for takeover auto-release flow via WebSocket."""
import sqlite3
import time
import uuid
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from autoservice import auth, operator_routes, operators
from autoservice.takeover_config import TakeoverConfig
from autoservice.web_gateway import create_app


def _setup_operator_auth(operator_id: str = "op42", tenant_id: str = "acme") -> str:
    """Seed operator + session into operator_routes DB, return cookie value.

    T1S.3 requires a valid operator_session cookie for WS operator binding.
    This helper prepares the minimal auth state so existing takeover tests
    can connect as an authenticated operator with the expected ID.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    auth.apply_schema(conn)
    operators.apply_operators_schema(conn)
    operators.migrate_login_tokens_add_role(conn)

    # Insert operator directly with the fixed ID the tests expect
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO operators (id, tenant_id, email, role, status, created_at) "
        "VALUES (?, ?, ?, 'responder', 'active', ?)",
        (operator_id, tenant_id, f"{operator_id}@{tenant_id}", now_iso),
    )
    conn.commit()

    operator_routes._reset_op_db_for_tests(conn)
    return operators.issue_operator_session(
        conn, operator_id=operator_id, tenant_id=tenant_id
    )


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
    yield create_app()
    operator_routes._reset_op_db_for_tests(None)


@pytest.fixture
def operator_cookie() -> str:
    """Seeded operator session cookie (T1S.3 — required for operator WS binding)."""
    return _setup_operator_auth()


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
def test_warning_frame_pushed_to_operator_after_hijack(fast_takeover_app, operator_cookie):
    with TestClient(fast_takeover_app) as client:
        client.cookies.set(operators.OPERATOR_SESSION_COOKIE_NAME, operator_cookie)
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


def test_client_ack_continue_resets_timer(fast_takeover_app, operator_cookie):
    with TestClient(fast_takeover_app) as client:
        client.cookies.set(operators.OPERATOR_SESSION_COOKIE_NAME, operator_cookie)
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


def test_client_ack_continue_from_customer_does_not_reset(fast_takeover_app, operator_cookie):
    """Customer WS client_ack continue cannot reset the operator's takeover timer.

    The actor_id inference only works for operator connections (state_operator_id
    is only set for viewer_role=='operator'). Even if the customer supplies an
    explicit operator_id in the payload, reset_takeover_timer's mode/owner guards
    should prevent any mode state leakage.
    """
    with TestClient(fast_takeover_app) as client:
        client.cookies.set(operators.OPERATOR_SESSION_COOKIE_NAME, operator_cookie)
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


@pytest.fixture
def offline_watcher_app(monkeypatch):
    """App with a long idle timeout so the offline grace fires before idle release."""
    import autoservice.web_gateway as wg
    # offline_grace_ms (100) << idle_timeout_ms (2000), so WS disconnect → AUTO
    # before the takeover idle timer has a chance to flip to COPILOT.
    cfg = TakeoverConfig(idle_timeout_ms=2000, warning_ms=200, offline_grace_ms=100)
    monkeypatch.setattr(wg, "_TAKEOVER_CONFIG_OVERRIDE", cfg, raising=False)
    return create_app()


def test_operator_disconnect_after_grace_switches_conv_to_auto(offline_watcher_app, operator_cookie):
    """Closing the operator WS causes all their TAKEOVER conversations to go AUTO after grace."""
    import asyncio

    with TestClient(offline_watcher_app) as client:
        client.cookies.set(operators.OPERATOR_SESSION_COOKIE_NAME, operator_cookie)
        with client.websocket_connect("/ws/customer") as cws:
            with client.websocket_connect("/ws/operator") as ows:
                _setup(cws, ows)
                conv_id = _customer_start_conv(cws)
                _operator_join(ows, conv_id, "op42")
                _send_cmd(ows, conv_id, "/hijack", "op42")
            # Operator WS closed here → offline grace begins (100ms)
            # idle_timeout is 2000ms so won't fire before grace expires
            time.sleep(0.3)  # wait past grace (100ms)

        # TestClient context exited — ASGI lifespan shut down cleanly.

    eng = getattr(offline_watcher_app.state, "engine", None)
    assert eng is not None, "app.state.engine must be set for this test"

    conv = asyncio.run(eng.get_conversation(conv_id))
    assert conv.mode.value == "auto"
    assert conv.takeover_operator_id is None


def test_takeover_timer_armed_frame_sent_after_hijack(fast_takeover_app, operator_cookie):
    """Operator receives takeover_timer_armed frame immediately after /hijack."""
    with TestClient(fast_takeover_app) as client:
        client.cookies.set(operators.OPERATOR_SESSION_COOKIE_NAME, operator_cookie)
        with client.websocket_connect("/ws/customer") as cws, \
             client.websocket_connect("/ws/operator") as ows:
            _setup(cws, ows)
            conv_id = _customer_start_conv(cws)
            _operator_join(ows, conv_id, "op42")
            _send_cmd(ows, conv_id, "/hijack", "op42")

            armed = _wait_frame(ows, "takeover_timer_armed", timeout=1.0)
            assert armed is not None
            p = armed["payload"]
            assert p["conversation_id"] == conv_id
            assert p["idle_timeout_ms"] == 150  # fast_takeover_app config
            assert p["warning_ms"] == 50
            assert p["armed_at"]


def test_operator_message_in_copilot_mode_does_not_reach_customer(fast_takeover_app, operator_cookie):
    """Before /hijack the conversation is COPILOT (auto-flipped on operator_join).
    In that state operator_message is a SIDE suggestion for the agent — it must
    NOT be pushed to the customer WS (conversation-engine.md §4 Gate + Q9).

    Regression: the router used to push the frame to cust_ws unconditionally,
    leaking coaching/drafts into the customer chat window.
    """
    with TestClient(fast_takeover_app) as client:
        client.cookies.set(operators.OPERATOR_SESSION_COOKIE_NAME, operator_cookie)
        with client.websocket_connect("/ws/customer") as cws, \
             client.websocket_connect("/ws/operator") as ows:
            _setup(cws, ows)
            conv_id = _customer_start_conv(cws)
            _operator_join(ows, conv_id, "op42")
            # No /hijack → conv stays in COPILOT after operator_join

            ows.send_json(_frame("operator_message", {
                "conversation_id": conv_id,
                "operator_id": "op42",
                "content": "coach the customer carefully",
            }))

            # Customer must NOT see this SIDE message within a short window.
            leaked = _wait_frame(cws, "message", timeout=0.3)
            assert leaked is None, (
                "operator SIDE suggestion leaked to customer: "
                f"{leaked and leaked.get('payload')}"
            )


def test_history_snapshot_carries_per_message_source_display(fast_takeover_app, operator_cookie):
    """history_request must attach source_display.role to each message so
    reloaded conversations render with the same badges as live broadcasts
    (customer / operator / agent).

    Regression: _serialize_message() drops role info. Without per-message
    source_display, operator suggestions re-rendered as "AUTO" on refresh
    because msg.source is an opaque participant id (e.g. "op42", "李"), and
    the frontend's substring heuristic misclassified them as "agent".
    """
    with TestClient(fast_takeover_app) as client:
        client.cookies.set(operators.OPERATOR_SESSION_COOKIE_NAME, operator_cookie)
        with client.websocket_connect("/ws/customer") as cws, \
             client.websocket_connect("/ws/operator") as ows:
            _setup(cws, ows)
            conv_id = _customer_start_conv(cws)
            _operator_join(ows, conv_id, "op42")

            ows.send_json(_frame("operator_message", {
                "conversation_id": conv_id,
                "operator_id": "op42",
                "content": "coach: ask about package size",
            }))
            # Drain broadcast so state is quiescent.
            _wait_frame(ows, "message", timeout=0.5)

            ows.send_json(_frame("history_request", {
                "conversation_id": conv_id,
                "limit": 50,
            }))
            snap = _wait_frame(ows, "history_snapshot", timeout=1.0)
            assert snap is not None, "history_snapshot never arrived"

            messages = snap["payload"]["messages"]
            by_source = {m["source"]: m for m in messages}

            assert "cust1" in by_source, "customer message missing from history"
            assert by_source["cust1"]["source_display"]["role"] == "customer"
            assert by_source["cust1"]["source_display"]["id"] == "cust1"

            assert "op42" in by_source, "operator suggestion missing from history"
            assert by_source["op42"]["source_display"]["role"] == "operator"
            assert by_source["op42"]["source_display"]["id"] == "op42"


def test_operator_message_reaches_customer_ws(fast_takeover_app, operator_cookie):
    """After hijack, operator_message frames must push to the customer WS.

    Regression: the handler used to only echo back to the sender; customer
    never saw the operator's reply during TAKEOVER.
    """
    with TestClient(fast_takeover_app) as client:
        client.cookies.set(operators.OPERATOR_SESSION_COOKIE_NAME, operator_cookie)
        with client.websocket_connect("/ws/customer") as cws, \
             client.websocket_connect("/ws/operator") as ows:
            _setup(cws, ows)
            conv_id = _customer_start_conv(cws)
            _operator_join(ows, conv_id, "op42")
            _send_cmd(ows, conv_id, "/hijack", "op42")
            # Confirm hijack succeeded
            resp = _wait_frame(ows, "command_response", timeout=1.0)
            assert resp is not None and resp["payload"]["ok"] is True

            # Operator sends a message
            ows.send_json(_frame("operator_message", {
                "conversation_id": conv_id,
                "operator_id": "op42",
                "content": "hello from operator",
            }))

            # Customer should receive a 'message' frame with the operator's text
            frame = _wait_frame(cws, "message", timeout=1.0)
            assert frame is not None, "customer never received operator message"
            assert frame["payload"]["message"]["content"] == "hello from operator"
            assert frame["payload"]["source_display"]["role"] == "operator"
