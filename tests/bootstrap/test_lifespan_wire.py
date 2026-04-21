"""T1B.5 — web_gateway lifespan dispatches to correct bootstrap per mode.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §1.3
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from autoservice import bootstrap, master_tenant, web_gateway


@pytest.fixture(autouse=True)
def clear_bootstrap_cache():
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()
    yield
    bootstrap.get_deployment_mode.cache_clear()
    bootstrap.get_tenant_id.cache_clear()


@pytest.fixture
def master_mode_cwd(tmp_path, monkeypatch):
    (tmp_path / ".autoservice").mkdir()
    (tmp_path / ".autoservice" / "config.local.yaml").write_text(
        "deployment_mode: master\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(master_tenant, "PROJECT_ROOT", tmp_path)
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
    return tmp_path


class TestLifespanBootstrap:
    def test_master_mode_calls_ensure_master_tenant(self, master_mode_cwd):
        with patch.object(
            master_tenant, "ensure_master_tenant", wraps=master_tenant.ensure_master_tenant
        ) as m, patch.object(
            master_tenant, "ensure_local_admin"
        ) as la:
            app = web_gateway.create_app()
            with TestClient(app):
                pass  # startup/shutdown runs inside the context
            assert m.called
            assert not la.called

    def test_tenant_mode_calls_ensure_local_admin(self, tenant_mode_cwd):
        with patch.object(
            master_tenant, "ensure_local_admin", wraps=master_tenant.ensure_local_admin
        ) as la, patch.object(
            master_tenant, "ensure_master_tenant"
        ) as m:
            app = web_gateway.create_app()
            with TestClient(app):
                pass
            assert la.called
            assert not m.called

    def test_missing_config_is_non_fatal(self, tmp_path, monkeypatch):
        """If .autoservice/config.local.yaml is absent, lifespan logs and continues."""
        monkeypatch.chdir(tmp_path)
        app = web_gateway.create_app()
        # TestClient raising would signal a crash — successful context = OK
        with TestClient(app):
            pass
