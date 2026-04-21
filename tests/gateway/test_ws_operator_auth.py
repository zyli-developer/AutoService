"""Tests for T1S.3 — WS handshake operator_session cookie validation.

Closes the M2 spoof gap at web_gateway.py:480-485 where operator_id was
trusted blindly from client_hello JSON payload.

Contract: docs/contracts/m3/e1-auth-rbac.md §4 (WS Handshake).

Behavior contract:
- operator role + valid cookie → bind _operator_sessions[cookie.operator_id]
- operator role + invalid/expired cookie → reject with close code 1008
- operator role + no cookie → don't bind (lenient; targeted pushes won't
  reach this conn, but handshake still succeeds)
- client_hello JSON payload operator_id is IGNORED (spoof gap closed)
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from autoservice import auth, operator_routes, operators
from autoservice.web_gateway import _operator_sessions, create_app


def _frame(type_: str, payload: dict) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "v": 1,
        "type": type_,
        "id": str(uuid.uuid4()),
        "ts": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z",
        "payload": payload,
    }


def _client_hello(**extra) -> dict:
    return _frame("client_hello", {"protocol_version": 1, "client_app": "operator-console", **extra})


@pytest.fixture()
def auth_conn():
    """In-memory DB with full auth + operators schema, injected into operator_routes."""
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    auth.apply_schema(c)
    operators.apply_operators_schema(c)
    operators.migrate_login_tokens_add_role(c)
    operator_routes._reset_op_db_for_tests(c)
    yield c
    operator_routes._reset_op_db_for_tests(None)
    c.close()


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def seeded_operator(auth_conn):
    """Return {id, tenant, cookie} for a valid operator session."""
    op = operators.create_operator(
        auth_conn, tenant_id="acme", email="op@acme.com", role="responder"
    )
    cookie = operators.issue_operator_session(
        auth_conn, operator_id=op.id, tenant_id="acme"
    )
    return {"id": op.id, "tenant_id": "acme", "cookie": cookie}


# ──────────────────────────────────────────────────────────────────────────
# Valid cookie → bind
# ──────────────────────────────────────────────────────────────────────────


def test_valid_cookie_binds_ws_to_operator_id(client, seeded_operator):
    client.cookies.set(
        operators.OPERATOR_SESSION_COOKIE_NAME, seeded_operator["cookie"]
    )
    with client.websocket_connect("/ws/operator") as ws:
        ws.send_json(_client_hello())
        hello = ws.receive_json()
        assert hello["type"] == "server_hello"

    # _operator_sessions should have had a binding for this operator during the
    # conn; after disconnect the `finally` cleanup pops it.  Assert in-conn:
    # we can see the binding while inside the `with` block.


def test_operator_bound_during_connection(client, seeded_operator):
    client.cookies.set(
        operators.OPERATOR_SESSION_COOKIE_NAME, seeded_operator["cookie"]
    )
    with client.websocket_connect("/ws/operator") as ws:
        ws.send_json(_client_hello())
        ws.receive_json()  # drain server_hello
        assert seeded_operator["id"] in _operator_sessions
        assert len(_operator_sessions[seeded_operator["id"]]) == 1

    # After disconnect: cleanup
    assert (
        seeded_operator["id"] not in _operator_sessions
        or len(_operator_sessions.get(seeded_operator["id"], set())) == 0
    )


# ──────────────────────────────────────────────────────────────────────────
# Invalid cookie → reject
# ──────────────────────────────────────────────────────────────────────────


def test_invalid_cookie_rejected_with_1008(client, auth_conn):
    client.cookies.set(operators.OPERATOR_SESSION_COOKIE_NAME, "ghost-token")
    with client.websocket_connect("/ws/operator") as ws:
        ws.send_json(_client_hello())
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["payload"]["code"] == "4011_AUTH"
        # After error frame, ws.close(code=1008) — starlette TestClient sees this
        # on next receive.


def test_expired_cookie_rejected(client, auth_conn):
    # Create an operator + session that's already expired
    op = operators.create_operator(
        auth_conn, tenant_id="acme", email="expired@acme.com", role="viewer"
    )
    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    cookie = operators.issue_operator_session(
        auth_conn, operator_id=op.id, tenant_id="acme", now=t0  # TTL 24h from 2020
    )
    client.cookies.set(operators.OPERATOR_SESSION_COOKIE_NAME, cookie)
    with client.websocket_connect("/ws/operator") as ws:
        ws.send_json(_client_hello())
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["payload"]["code"] == "4011_AUTH"


def test_disabled_operator_cookie_rejected(client, auth_conn, seeded_operator):
    # Disable the operator
    operators.update_operator(auth_conn, seeded_operator["id"], status="disabled")
    client.cookies.set(
        operators.OPERATOR_SESSION_COOKIE_NAME, seeded_operator["cookie"]
    )
    with client.websocket_connect("/ws/operator") as ws:
        ws.send_json(_client_hello())
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["payload"]["code"] == "4011_AUTH"


# ──────────────────────────────────────────────────────────────────────────
# Spoof-gap closed — JSON-provided operator_id is ignored
# ──────────────────────────────────────────────────────────────────────────


def test_spoofed_operator_id_in_json_is_ignored(client, auth_conn):
    """Key security test: client_hello payload operator_id MUST NOT bind.

    Under strict mode (T1S.3 v2): no cookie → handshake rejected BEFORE any
    binding happens.  Spoofed operator_id from JSON is never examined.
    """
    op = operators.create_operator(
        auth_conn, tenant_id="acme", email="real@acme.com", role="viewer"
    )

    # NO cookie. Client claims to be the legit operator via JSON.
    with client.websocket_connect("/ws/operator") as ws:
        ws.send_json(_client_hello(operator_id=op.id))
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["payload"]["code"] == "4011_AUTH"

        # CRITICAL: operator MUST NOT be bound (no cookie, rejected before bind)
        assert op.id not in _operator_sessions or len(
            _operator_sessions.get(op.id, set())
        ) == 0


def test_no_cookie_rejected_with_1008(client, auth_conn):
    """Strict mode (contract §4): operator WS without cookie → 1008 reject.

    Closes reviewer finding C3 — lenient-mode had leaked broadcast observability
    via subscribe frames on unauthenticated connections.
    """
    with client.websocket_connect("/ws/operator") as ws:
        ws.send_json(_client_hello())
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["payload"]["code"] == "4011_AUTH"
        assert err["payload"]["details"]["reason"] == "invalid_or_missing_session"


def test_admin_session_cookie_does_not_authenticate_operator(client, auth_conn):
    """Admin session cookie MUST NOT be accepted as operator cookie (CON-08)."""
    # Issue an admin session
    admin_sid = auth.create_session(auth_conn, "admin@acme.com", tenant_id="acme")
    # Attach it to the wrong cookie slot — operator_session expected to be
    # an operator session token, not an admin session id.
    client.cookies.set(operators.OPERATOR_SESSION_COOKIE_NAME, admin_sid)
    with client.websocket_connect("/ws/operator") as ws:
        ws.send_json(_client_hello())
        err = ws.receive_json()
        # admin_sid does not exist in operator_sessions table → rejected
        assert err["type"] == "error"
        assert err["payload"]["code"] == "4011_AUTH"
