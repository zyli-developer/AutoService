"""POST /api/auth/dev-login + GET /api/auth/dev-mode tests.

Spec: docs/superpowers/specs/2026-04-21-dev-auto-login-design.md
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autoservice import api_routes, auth


# ── Fixtures (mirror tests/auth/test_request_login.py) ────────────────────


@pytest.fixture()
def auth_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    auth.apply_schema(conn)
    api_routes._reset_auth_db_for_tests(conn)
    yield conn
    api_routes._reset_auth_db_for_tests(None)
    conn.close()


@pytest.fixture()
def app_client(auth_conn, monkeypatch, tmp_path) -> TestClient:
    # Chdir so config.local.yaml / plugins/ / .autoservice/logs resolve to the
    # per-test tmpdir instead of the real project tree.
    monkeypatch.chdir(tmp_path)
    app = FastAPI()
    app.include_router(api_routes.api_router)
    return TestClient(app)


@pytest.fixture()
def dev_mode_off(monkeypatch):
    """Force ``DEV_MODE_ENABLED`` off via monkeypatched module attribute.

    We intentionally do NOT ``importlib.reload(api_routes)`` — reloading would
    wipe the in-memory ``_auth_db_conn`` that ``auth_conn`` injects.
    """
    monkeypatch.setattr(api_routes, "DEV_MODE_ENABLED", False)


@pytest.fixture()
def dev_mode_on(monkeypatch):
    """Force ``DEV_MODE_ENABLED`` on via monkeypatched module attribute."""
    monkeypatch.setattr(api_routes, "DEV_MODE_ENABLED", True)


@pytest.fixture()
def write_config(tmp_path):
    def _write(yaml_text: str) -> Path:
        cfg_dir = tmp_path / ".autoservice"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        path = cfg_dir / "config.local.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        return path
    return _write


# ── /auth/dev-mode — disabled path ────────────────────────────────────────


def test_dev_mode_endpoint_returns_disabled_when_env_unset(
    dev_mode_off, app_client
):
    r = app_client.get("/api/auth/dev-mode")
    assert r.status_code == 200
    assert r.json() == {"enabled": False}


def test_dev_mode_endpoint_does_not_leak_personas_when_disabled(
    dev_mode_off, app_client, write_config
):
    write_config(
        """\
auth:
  dev:
    personas:
      - secret@dev.local
"""
    )
    r = app_client.get("/api/auth/dev-mode")
    body = r.json()
    assert body == {"enabled": False}
    assert "personas" not in body
    assert "tenants" not in body
