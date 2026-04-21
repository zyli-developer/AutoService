"""T5B.6 — /api/session/mode auth-state extension tests.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §4.5 + §5.3.

The endpoint always returns 200 with the shape::

    {
      "mode": "master" | "tenant",
      "tenant_id": "<tid>" | null,
      "authenticated": bool,
      "authenticated_as": "<email>" | null,
      "tier": 0 | 1 | null,
      "brand_name": "<str>"
    }

- Anonymous → tier=null, authenticated=false, authenticated_as=null.
- Tier-0 session (NULL session.tenant_id) → tier=0.
- Tier-1 session (non-NULL tenant_id) → tier=1 + tenant_id matching session.
- brand_name falls back to "AutoService" (platform) in master mode and reads
  plugins/<tid>/config.json["brand_name"] in tenant mode.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autoservice import api_routes, auth, bootstrap


# ── Fixtures ──────────────────────────────────────────────────────────────


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
def clean_cwd(monkeypatch, tmp_path):
    """Switch CWD + clear bootstrap caches so each test gets a fresh config tree."""
    monkeypatch.chdir(tmp_path)
    # bootstrap uses @cache on get_deployment_mode / get_tenant_id / _load_local_config.
    for fn in (
        bootstrap.get_deployment_mode,
        bootstrap.get_tenant_id,
    ):
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()
    yield tmp_path
    for fn in (
        bootstrap.get_deployment_mode,
        bootstrap.get_tenant_id,
    ):
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()


@pytest.fixture()
def app_client(auth_conn, clean_cwd) -> TestClient:
    app = FastAPI()
    app.include_router(api_routes.api_router)
    return TestClient(app)


def _write_local_config(tmp_path: Path, yaml_text: str) -> Path:
    cfg_dir = tmp_path / ".autoservice"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "config.local.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return path


def _write_plugin_config(tmp_path: Path, tid: str, cfg: dict) -> Path:
    plugin_dir = tmp_path / "plugins" / tid
    plugin_dir.mkdir(parents=True, exist_ok=True)
    p = plugin_dir / "config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


# ── Tests ─────────────────────────────────────────────────────────────────


def test_session_mode_anon_master_returns_unauthenticated_shape(
    app_client, clean_cwd
):
    """No cookie, master mode → authenticated=false, tier=null, tenant_id=null."""
    _write_local_config(clean_cwd, "deployment_mode: master\n")

    r = app_client.get("/api/session/mode")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "master"
    assert body["tenant_id"] is None
    assert body["authenticated"] is False
    assert body["authenticated_as"] is None
    assert body["tier"] is None
    assert body["brand_name"] == "AutoService"


def test_session_mode_master_admin_tier_0(app_client, auth_conn, clean_cwd):
    """Authenticated with NULL session.tenant_id → tier=0, email returned."""
    _write_local_config(clean_cwd, "deployment_mode: master\n")

    sid = auth.create_session(auth_conn, "platform@ops.com", tenant_id=None)
    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, sid)

    r = app_client.get("/api/session/mode")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "master"
    assert body["authenticated"] is True
    assert body["authenticated_as"] == "platform@ops.com"
    assert body["tier"] == 0
    # Platform-admin in master mode still gets the platform brand.
    assert body["brand_name"] == "AutoService"


def test_session_mode_tenant_admin_tier_1(app_client, auth_conn, clean_cwd):
    """Authenticated with session.tenant_id='acme' in master mode → tier=1."""
    _write_local_config(clean_cwd, "deployment_mode: master\n")

    sid = auth.create_session(auth_conn, "admin@acme.com", tenant_id="acme")
    app_client.cookies.set(api_routes.AUTH_SESSION_COOKIE, sid)

    r = app_client.get("/api/session/mode")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["authenticated_as"] == "admin@acme.com"
    assert body["tier"] == 1
    # Session-level tenant_id surfaces even in master mode (tenant admin
    # visiting the master host via magic-link).
    assert body["tenant_id"] == "acme"


def test_session_mode_brand_name_platform_default_master(app_client, clean_cwd):
    """Master mode + anon → brand_name is 'AutoService'."""
    _write_local_config(clean_cwd, "deployment_mode: master\n")

    r = app_client.get("/api/session/mode")
    assert r.status_code == 200
    assert r.json()["brand_name"] == "AutoService"


def test_session_mode_brand_name_from_tenant_config(app_client, clean_cwd):
    """Tenant mode → brand_name read from plugins/<tid>/config.json."""
    _write_plugin_config(clean_cwd, "acme", {"tenant_id": "acme", "brand_name": "Acme Corp"})
    _write_local_config(
        clean_cwd,
        "deployment_mode: tenant\ntenant_id: acme\n",
    )

    r = app_client.get("/api/session/mode")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "tenant"
    assert body["tenant_id"] == "acme"
    assert body["brand_name"] == "Acme Corp"
    # Anonymous visitor to the fork still sees the fork's brand but is not
    # authenticated.
    assert body["authenticated"] is False
    assert body["tier"] is None
