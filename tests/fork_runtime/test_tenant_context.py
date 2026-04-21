"""T7B.1 — TenantContext middleware (spec §3.2).

Verifies:
  - master mode: passes URLs through unchanged, populates request.state
  - tenant mode + self path: strips /t/<self>/ prefix (URL-flat routing)
  - tenant mode + other path: 403 JSON (cross-tenant refused)
  - tenant mode + URL-flat path: pass-through
  - request.state.deployment_mode + tenant_id set on every request
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from autoservice import bootstrap, master_tenant, web_gateway


@pytest.fixture(autouse=True)
def clear_bootstrap_cache():
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()
    yield
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()


@pytest.fixture(autouse=True)
def disable_background_jobs(monkeypatch):
    """DreamScheduler + CCPool both hook @app.on_event('startup') and touch the
    filesystem; neutralise them so TestClient startup is hermetic."""
    monkeypatch.setenv("DREAM_SCHEDULER_DISABLED", "1")
    monkeypatch.setenv("POOL_MODE", "0")


@pytest.fixture
def master_mode_cwd(tmp_path, monkeypatch):
    (tmp_path / ".autoservice").mkdir()
    (tmp_path / ".autoservice" / "config.local.yaml").write_text(
        "deployment_mode: master\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(master_tenant, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def tenant_mode_cwd(tmp_path, monkeypatch):
    (tmp_path / ".autoservice").mkdir()
    (tmp_path / ".autoservice" / "config.local.yaml").write_text(
        "deployment_mode: tenant\ntenant_id: acme\n", encoding="utf-8"
    )
    plugins = tmp_path / "plugins" / "acme"
    plugins.mkdir(parents=True)
    (plugins / "config.json").write_text(json.dumps({"tenant_id": "acme"}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(master_tenant, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _attach_echo_routes(app):
    """Install echo endpoints so we can observe the effective post-middleware
    path and request.state from inside a handler."""

    async def echo_root(request: Request):
        return {
            "path": request.url.path,
            "scope_path": request.scope["path"],
            "deployment_mode": getattr(request.state, "deployment_mode", None),
            "tenant_id": getattr(request.state, "tenant_id", None),
        }

    app.add_api_route("/chat", echo_root, methods=["GET"])
    app.add_api_route("/echo", echo_root, methods=["GET"])
    # /t/{tid}/echo is present so master-mode pass-through still has a target
    # to hit (rather than a 404 from missing route).
    app.add_api_route("/t/{tid}/echo", echo_root, methods=["GET"])
    app.add_api_route("/t/{tid}/chat", echo_root, methods=["GET"])
    return app


class TestMasterModePassThrough:
    def test_prefixed_path_is_not_rewritten(self, master_mode_cwd):
        app = _attach_echo_routes(web_gateway.create_app())
        with TestClient(app) as client:
            resp = client.get("/t/acme/chat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope_path"] == "/t/acme/chat"
        assert data["deployment_mode"] == "master"
        # Master mode never pins a single tenant; tenant_id is None.
        assert data["tenant_id"] is None

    def test_flat_path_is_not_rewritten(self, master_mode_cwd):
        app = _attach_echo_routes(web_gateway.create_app())
        with TestClient(app) as client:
            resp = client.get("/echo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope_path"] == "/echo"
        assert data["deployment_mode"] == "master"
        assert data["tenant_id"] is None


class TestTenantModeRewriting:
    def test_self_tenant_prefix_stripped(self, tenant_mode_cwd):
        """/t/acme/chat → /chat in tenant mode (URL-flat fork)."""
        app = _attach_echo_routes(web_gateway.create_app())
        with TestClient(app) as client:
            resp = client.get("/t/acme/chat")
        assert resp.status_code == 200
        data = resp.json()
        # Downstream echo_root sees the rewritten path.
        assert data["scope_path"] == "/chat"
        assert data["deployment_mode"] == "tenant"
        assert data["tenant_id"] == "acme"

    def test_cross_tenant_returns_403(self, tenant_mode_cwd):
        """/t/bob/chat in a tenant-mode acme fork → 403 JSON."""
        app = _attach_echo_routes(web_gateway.create_app())
        with TestClient(app) as client:
            resp = client.get("/t/bob/chat")
        assert resp.status_code == 403
        body = resp.json()
        assert "cross-tenant" in body["error"]

    def test_flat_url_passes_through(self, tenant_mode_cwd):
        """URL-flat /chat is the canonical tenant-mode entry; no rewrite."""
        app = _attach_echo_routes(web_gateway.create_app())
        with TestClient(app) as client:
            resp = client.get("/chat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope_path"] == "/chat"
        assert data["deployment_mode"] == "tenant"
        assert data["tenant_id"] == "acme"

    def test_request_state_populated_on_prefixed_path(self, tenant_mode_cwd):
        """request.state.deployment_mode + tenant_id are set before handler runs."""
        app = _attach_echo_routes(web_gateway.create_app())
        with TestClient(app) as client:
            resp = client.get("/t/acme/echo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deployment_mode"] == "tenant"
        assert data["tenant_id"] == "acme"
        # Echo path reflects the rewrite.
        assert data["scope_path"] == "/echo"

    def test_bare_self_tenant_rewrites_to_root(self, tenant_mode_cwd):
        """/t/acme (no trailing slash) → / in tenant mode."""
        app = _attach_echo_routes(web_gateway.create_app())
        # Mount a handler at "/" so we can observe the rewrite.
        async def root_echo(request: Request):
            return {"scope_path": request.scope["path"]}
        app.add_api_route("/", root_echo, methods=["GET"])
        with TestClient(app) as client:
            resp = client.get("/t/acme")
        assert resp.status_code == 200
        assert resp.json()["scope_path"] == "/"
