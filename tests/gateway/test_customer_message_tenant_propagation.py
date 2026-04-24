"""Integration: customer_message → conv.metadata["tenant_id"] inherits the
resolved customer tenant.

This closes the full chain the tenant-soul+KB feature depended on:
  /ws/customer?tenant=X  →  ws.state_customer_tenant_id=X
                         →  conv.metadata["tenant_id"]=X on create
                         →  triage_config_loader picks it up
                         →  KB pre-fetch + session_query(tenant_id=X) wire up
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from autoservice import bootstrap
from autoservice.web_gateway import create_app

from .conftest import DummyEngine, make_frame, make_message


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


class _SpyEngine(DummyEngine):
    """DummyEngine that records create_conversation kwargs."""

    def __init__(self) -> None:
        super().__init__()
        self.create_calls: list[dict] = []

    async def create_conversation(self, **kwargs):
        self.create_calls.append(dict(kwargs))
        return await super().create_conversation(**kwargs)


def _run_customer_message(client: TestClient, query: str, content: str = "hi"):
    path = f"/ws/customer{query}"
    with client.websocket_connect(path) as ws:
        ws.send_json(make_frame("client_hello", {"protocol_version": 1, "client_app": "web"}))
        # server_hello
        ws.receive_json()
        ws.send_json(
            make_frame(
                "customer_message",
                {"content": content, "source": "cust_test", "client_msg_id": "msg1"},
            )
        )
        # ack, then message_confirm — receive both so send_message fires
        ws.receive_json()
        ws.receive_json()


def test_master_mode_with_tenant_query_propagates_to_metadata(tmp_path, monkeypatch):
    _write_local_cfg(tmp_path, "deployment_mode: master\n")
    _seed_sandbox_tenant(tmp_path, "mystore")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

    engine = _SpyEngine()
    engine.set_send_message(lambda *a, **kw: _coro(make_message(content=kw.get("content", ""))))
    app = create_app(engine=engine)
    client = TestClient(app)

    _run_customer_message(client, "?tenant=mystore")

    assert engine.create_calls, "create_conversation was not invoked"
    meta = engine.create_calls[0].get("metadata", {})
    assert meta.get("tenant_id") == "mystore"


def test_master_mode_without_query_falls_back_to_master_tenant_id(tmp_path, monkeypatch):
    _write_local_cfg(tmp_path, "deployment_mode: master\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

    engine = _SpyEngine()
    engine.set_send_message(lambda *a, **kw: _coro(make_message(content=kw.get("content", ""))))
    app = create_app(engine=engine)
    client = TestClient(app)

    _run_customer_message(client, "")

    meta = engine.create_calls[0].get("metadata", {})
    assert meta.get("tenant_id") == "_master"


async def _coro(val):
    return val
