"""Integration tests for /ws/customer tenant query binding + 1008 rejection.

Verifies that _handle_connection wires gateway.tenant_resolver into the
customer WS handshake:
  - valid query / fallback → connection accepted, ws.state_customer_tenant_id set
  - invalid query → error frame (4011_AUTH family) + close 1008
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from autoservice import bootstrap
from autoservice.web_gateway import create_app

from .conftest import make_frame


@pytest.fixture(autouse=True)
def _clear_bootstrap_caches():
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()
    yield
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()


def _write_local_cfg(tmp_path: Path, content: str) -> None:
    (tmp_path / ".autoservice").mkdir(exist_ok=True)
    (tmp_path / ".autoservice" / "config.local.yaml").write_text(content, encoding="utf-8")


def _seed_sandbox_tenant(tmp_path: Path, tid: str) -> None:
    d = tmp_path / ".autoservice" / "sandbox" / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps({"tenant_id": tid}), encoding="utf-8")


@pytest.fixture
def master_client(tmp_path, monkeypatch):
    """Master-mode TestClient with a seeded `mystore` sandbox tenant."""
    _write_local_cfg(tmp_path, "deployment_mode: master\n")
    _seed_sandbox_tenant(tmp_path, "mystore")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)
    app = create_app()
    return TestClient(app)


def _hello() -> dict:
    return make_frame("client_hello", {"protocol_version": 1, "client_app": "web"})


def test_no_query_accepts_and_server_hello_returned(master_client):
    """Master-mode no query → falls back to _master, handshake succeeds."""
    with master_client.websocket_connect("/ws/customer") as ws:
        ws.send_json(_hello())
        reply = ws.receive_json()
        assert reply["type"] == "server_hello"


def test_registered_tenant_query_accepts(master_client):
    with master_client.websocket_connect("/ws/customer?tenant=mystore") as ws:
        ws.send_json(_hello())
        reply = ws.receive_json()
        assert reply["type"] == "server_hello"


def test_unregistered_tenant_query_rejected_with_error_frame(master_client):
    with master_client.websocket_connect("/ws/customer?tenant=acme") as ws:
        ws.send_json(_hello())
        reply = ws.receive_json()
        assert reply["type"] == "error"
        # Gateway ERR_AUTH code family matches operator path for consistency.
        assert reply["payload"]["code"] == "4011_AUTH"
        assert reply["payload"]["details"]["reason"] == "unknown_tenant"


def test_local_admin_query_rejected(master_client):
    with master_client.websocket_connect("/ws/customer?tenant=_local_admin") as ws:
        ws.send_json(_hello())
        reply = ws.receive_json()
        assert reply["type"] == "error"
        assert reply["payload"]["code"] == "4011_AUTH"
        assert reply["payload"]["details"]["reason"] == "unknown_tenant"


def test_tenant_mode_mismatch_rejected(tmp_path, monkeypatch):
    """Tenant-mode deployment: query tenant ≠ self → 1008 (snooping defense)."""
    _write_local_cfg(tmp_path, "deployment_mode: tenant\ntenant_id: mystore\n")
    # bootstrap.get_deployment_mode cross-checks plugins/<tid>/config.json
    d = tmp_path / "plugins" / "mystore"
    d.mkdir(parents=True)
    (d / "config.json").write_text(json.dumps({"tenant_id": "mystore"}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)
    client = TestClient(create_app())

    with client.websocket_connect("/ws/customer?tenant=acme") as ws:
        ws.send_json(_hello())
        reply = ws.receive_json()
        assert reply["type"] == "error"
        assert reply["payload"]["code"] == "4011_AUTH"
        assert reply["payload"]["details"]["reason"] == "tenant_mismatch"
