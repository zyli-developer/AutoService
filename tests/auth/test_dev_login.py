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


# ── /auth/dev-mode — enabled path ─────────────────────────────────────────


def test_dev_mode_personas_fallback_when_config_missing(
    dev_mode_on, app_client
):
    """No config.local.yaml → single-element fallback persona list."""
    r = app_client.get("/api/auth/dev-mode")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["personas"] == ["admin@dev.local"]


def test_dev_mode_personas_from_config(
    dev_mode_on, app_client, write_config
):
    write_config(
        """\
auth:
  dev:
    personas:
      - alice@dev.local
      - bob@dev.local
"""
    )
    r = app_client.get("/api/auth/dev-mode")
    body = r.json()
    assert body["personas"] == ["alice@dev.local", "bob@dev.local"]


def test_dev_mode_tenants_include_master_and_scanned_plugins(
    dev_mode_on, app_client, tmp_path, write_config
):
    """Scans plugins/*/config.json (or directory name) for tenant_id; prepends
    _master; excludes _example by default."""
    write_config("auth:\n  dev: {}\n")

    plugins = tmp_path / "plugins"
    (plugins / "_local_admin").mkdir(parents=True)
    (plugins / "_local_admin" / "config.json").write_text(
        json.dumps({"tenant_id": "_local_admin"}), encoding="utf-8"
    )
    (plugins / "acme").mkdir(parents=True)
    (plugins / "acme" / "config.json").write_text(
        json.dumps({"tenant_id": "acme"}), encoding="utf-8"
    )
    (plugins / "_example").mkdir(parents=True)
    (plugins / "_example" / "config.json").write_text(
        json.dumps({"tenant_id": "_example"}), encoding="utf-8"
    )

    r = app_client.get("/api/auth/dev-mode")
    tenants = r.json()["tenants"]
    assert tenants[0] == "_master"  # always first
    assert "_local_admin" in tenants
    assert "acme" in tenants
    assert "_example" not in tenants  # excluded by default


def test_dev_mode_tenants_include_examples_when_flag_set(
    dev_mode_on, app_client, tmp_path, write_config
):
    write_config(
        """\
auth:
  dev:
    tenant_include_examples: true
"""
    )
    plugins = tmp_path / "plugins"
    (plugins / "_example").mkdir(parents=True)
    (plugins / "_example" / "config.json").write_text(
        json.dumps({"tenant_id": "_example"}), encoding="utf-8"
    )

    r = app_client.get("/api/auth/dev-mode")
    assert "_example" in r.json()["tenants"]


# ── /auth/dev-login — disabled path ───────────────────────────────────────


def test_dev_login_returns_404_when_env_unset(
    dev_mode_off, app_client, auth_conn
):
    r = app_client.post(
        "/api/auth/dev-login",
        json={"email": "admin@dev.local"},
    )
    assert r.status_code == 404
    # No session row created.
    rows = auth_conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()
    assert rows["c"] == 0
    # No cookie set.
    assert "auth_session" not in r.cookies


# ── /auth/dev-login — enabled path ────────────────────────────────────────


def test_dev_login_mints_tier0_session_when_tenant_null(
    dev_mode_on, app_client, auth_conn, tmp_path
):
    r = app_client.post(
        "/api/auth/dev-login",
        json={"email": "admin@dev.local", "tenant_id": None},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "redirect": "/admin"}

    rows = auth_conn.execute(
        "SELECT admin_email, tenant_id, revoked_at FROM sessions"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["admin_email"] == "admin@dev.local"
    assert rows[0]["tenant_id"] is None
    assert rows[0]["revoked_at"] is None

    # Cookie set with expected attributes.
    cookie_header = r.headers.get("set-cookie", "")
    assert "auth_session=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "samesite=lax" in cookie_header.lower()


def test_dev_login_mints_tier1_session_and_redirects_to_tenant_admin(
    dev_mode_on, app_client, auth_conn
):
    r = app_client.post(
        "/api/auth/dev-login",
        json={"email": "admin@dev.local", "tenant_id": "acme"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "redirect": "/tenant/acme/admin"}

    row = auth_conn.execute(
        "SELECT tenant_id FROM sessions"
    ).fetchone()
    assert row["tenant_id"] == "acme"


def test_dev_login_empty_tenant_id_treated_as_null(
    dev_mode_on, app_client, auth_conn
):
    r = app_client.post(
        "/api/auth/dev-login",
        json={"email": "admin@dev.local", "tenant_id": "   "},
    )
    assert r.status_code == 200
    assert r.json()["redirect"] == "/admin"
    row = auth_conn.execute("SELECT tenant_id FROM sessions").fetchone()
    assert row["tenant_id"] is None


def test_dev_login_empty_email_returns_400(dev_mode_on, app_client):
    r = app_client.post(
        "/api/auth/dev-login",
        json={"email": "   ", "tenant_id": None},
    )
    assert r.status_code == 400
    assert "email" in r.json()["error"]


def test_dev_login_missing_email_returns_400(dev_mode_on, app_client):
    r = app_client.post("/api/auth/dev-login", json={})
    assert r.status_code == 400


def test_dev_login_writes_audit_jsonl_entry(
    dev_mode_on, app_client, tmp_path
):
    r = app_client.post(
        "/api/auth/dev-login",
        json={"email": "admin@dev.local", "tenant_id": "acme"},
    )
    assert r.status_code == 200

    log_path = tmp_path / ".autoservice" / "logs" / "auth-devmail.jsonl"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == "dev_login"
    assert record["email"] == "admin@dev.local"
    assert record["tenant_id"] == "acme"
    assert "session_id_prefix" in record
    assert len(record["session_id_prefix"]) == 8
    # Full session id must NOT be in the log.
    assert "session_id" not in record
