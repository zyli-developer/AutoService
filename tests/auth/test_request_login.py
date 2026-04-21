"""T5B.2 — POST /api/auth/request-login tests.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §5.2 + §5.6.

Harness pattern mirrors tests/api/test_dream_api.py: mount the ``api_router``
on a fresh FastAPI app, swap ``api_routes._get_auth_db`` for an in-memory
sqlite3 connection, and ``monkeypatch.chdir(tmp_path)`` so config.local.yaml +
dev log lookups land in a clean tree.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autoservice import api_routes, auth


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def auth_conn() -> sqlite3.Connection:
    """In-memory auth DB connection, installed into api_routes for the test."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    auth.apply_schema(conn)
    api_routes._reset_auth_db_for_tests(conn)
    yield conn
    api_routes._reset_auth_db_for_tests(None)
    conn.close()


@pytest.fixture()
def app_client(auth_conn, monkeypatch, tmp_path) -> TestClient:
    """TestClient mounting api_router with auth DB + clean CWD."""
    monkeypatch.chdir(tmp_path)
    app = FastAPI()
    app.include_router(api_routes.api_router)
    # Make sure bootstrap._load_local_config sees our tmp tree.
    from autoservice import bootstrap
    bootstrap._load_local_config.cache_clear() if hasattr(bootstrap._load_local_config, "cache_clear") else None
    return TestClient(app)


@pytest.fixture()
def write_config(tmp_path):
    """Helper: drop a .autoservice/config.local.yaml under tmp_path."""

    def _write(yaml_text: str) -> Path:
        cfg_dir = tmp_path / ".autoservice"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        path = cfg_dir / "config.local.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        return path

    return _write


# ── /request-login ────────────────────────────────────────────────────────


def test_allowlisted_email_persists_token_and_logs_link(
    app_client, auth_conn, write_config, tmp_path
):
    write_config(
        """\
auth:
  admin_emails:
    - admin@example.com
  smtp:
    host: ""
"""
    )

    r = app_client.post(
        "/api/auth/request-login",
        json={"email": "admin@example.com", "tenant_id": "acme"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "sent", "delivered": "log"}

    rows = auth_conn.execute(
        "SELECT admin_email, tenant_id, consumed_at FROM login_tokens"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["admin_email"] == "admin@example.com"
    assert rows[0]["tenant_id"] == "acme"
    assert rows[0]["consumed_at"] is None

    # Dev log captured the link.
    log_path = tmp_path / ".autoservice" / "logs" / "auth-devmail.jsonl"
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    assert entries[0]["email"] == "admin@example.com"
    assert entries[0]["tenant_id"] == "acme"
    assert "token=" in entries[0]["link"]


def test_non_allowlisted_email_returns_200_without_persisting(
    app_client, auth_conn, write_config, tmp_path
):
    """Anti-enumeration red line — response shape identical to allowlisted."""
    write_config(
        """\
auth:
  admin_emails:
    - admin@example.com
  smtp:
    host: ""
"""
    )

    r = app_client.post(
        "/api/auth/request-login",
        json={"email": "stranger@evil.com"},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "sent", "delivered": "log"}

    rows = auth_conn.execute("SELECT COUNT(*) AS c FROM login_tokens").fetchone()
    assert rows["c"] == 0

    log_path = tmp_path / ".autoservice" / "logs" / "auth-devmail.jsonl"
    assert not log_path.exists()


def test_missing_email_field_returns_422(app_client, write_config):
    write_config(
        """\
auth:
  admin_emails:
    - admin@example.com
  smtp:
    host: ""
"""
    )
    r = app_client.post("/api/auth/request-login", json={})
    assert r.status_code == 422
    assert "email" in r.json()["error"]


def test_smtp_empty_host_writes_devmail_jsonl(
    app_client, write_config, tmp_path
):
    write_config(
        """\
auth:
  admin_emails:
    - admin@example.com
  smtp:
    host: ""
"""
    )

    r = app_client.post(
        "/api/auth/request-login",
        json={"email": "admin@example.com"},
    )
    assert r.status_code == 200
    assert r.json()["delivered"] == "log"

    log_path = tmp_path / ".autoservice" / "logs" / "auth-devmail.jsonl"
    assert log_path.exists()
    line = log_path.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert set(record.keys()) >= {"ts", "email", "tenant_id", "token", "link"}


def test_two_rapid_requests_create_two_tokens(
    app_client, auth_conn, write_config
):
    """No rate limit in M2 — spec §5.7 defers to M3."""
    write_config(
        """\
auth:
  admin_emails:
    - admin@example.com
  smtp:
    host: ""
"""
    )

    r1 = app_client.post(
        "/api/auth/request-login",
        json={"email": "admin@example.com"},
    )
    r2 = app_client.post(
        "/api/auth/request-login",
        json={"email": "admin@example.com"},
    )
    assert r1.status_code == r2.status_code == 200

    rows = auth_conn.execute("SELECT token FROM login_tokens").fetchall()
    assert len(rows) == 2
    assert rows[0]["token"] != rows[1]["token"]
