"""POST /api/auth/operator/password-login tests.

Mirrors tests/auth/test_operator_dev_login.py — exercises the production
fallback that lets operators log in with email + password + tenant_id
without AUTH_DEV_MODE.

Activated by the presence of ``.autoservice/operator_passwords.json``;
absence → 404 (feature disabled, no surface advertised).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import bcrypt
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from autoservice import api_routes, auth, operator_routes, operators


def _bcrypt(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(4)).decode()


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    auth.apply_schema(c)
    operators.apply_operators_schema(c)
    operators.migrate_login_tokens_add_role(c)
    yield c
    c.close()


@pytest.fixture()
def app_client(db_conn, monkeypatch, tmp_path) -> TestClient:
    monkeypatch.chdir(tmp_path)
    operator_routes._reset_op_db_for_tests(db_conn)
    api_routes._reset_auth_db_for_tests(db_conn)
    # Reset rate-limit state between tests so 429 doesn't leak.
    operator_routes._PW_FAILED_ATTEMPTS.clear()
    app = FastAPI()
    app.include_router(api_routes.api_router)
    yield TestClient(app)
    operator_routes._reset_op_db_for_tests(None)
    api_routes._reset_auth_db_for_tests(None)


def _write_passwords(tmp_path: Path, entries: list[dict]) -> None:
    p = tmp_path / ".autoservice"
    p.mkdir(parents=True, exist_ok=True)
    (p / "operator_passwords.json").write_text(
        json.dumps({"version": 1, "updated_at": "", "entries": entries}),
        encoding="utf-8",
    )


# ── Disabled path ─────────────────────────────────────────────────────────


def test_returns_404_when_passwords_file_missing(app_client):
    r = app_client.post(
        "/api/auth/operator/password-login",
        json={"email": "op@x.com", "password": "pw", "tenant_id": "acme"},
    )
    assert r.status_code == 404


def test_returns_404_when_passwords_file_malformed(app_client, tmp_path):
    p = tmp_path / ".autoservice"
    p.mkdir(parents=True, exist_ok=True)
    (p / "operator_passwords.json").write_text("{not json", encoding="utf-8")
    r = app_client.post(
        "/api/auth/operator/password-login",
        json={"email": "op@x.com", "password": "pw", "tenant_id": "acme"},
    )
    assert r.status_code == 404


# ── Validation ────────────────────────────────────────────────────────────


def test_requires_email(app_client, tmp_path):
    _write_passwords(tmp_path, [])
    r = app_client.post(
        "/api/auth/operator/password-login",
        json={"password": "pw", "tenant_id": "acme"},
    )
    assert r.status_code == 400


def test_requires_password(app_client, tmp_path):
    _write_passwords(tmp_path, [])
    r = app_client.post(
        "/api/auth/operator/password-login",
        json={"email": "op@x.com", "tenant_id": "acme"},
    )
    assert r.status_code == 400


def test_requires_tenant_id(app_client, tmp_path):
    _write_passwords(tmp_path, [])
    r = app_client.post(
        "/api/auth/operator/password-login",
        json={"email": "op@x.com", "password": "pw"},
    )
    assert r.status_code == 400


# ── Auth ──────────────────────────────────────────────────────────────────


def test_unknown_email_returns_401(app_client, tmp_path):
    _write_passwords(tmp_path, [])
    r = app_client.post(
        "/api/auth/operator/password-login",
        json={"email": "ghost@x.com", "password": "pw", "tenant_id": "acme"},
    )
    assert r.status_code == 401


def test_wrong_password_returns_401(app_client, tmp_path):
    _write_passwords(
        tmp_path,
        [{"email": "op@x.com", "password_bcrypt": _bcrypt("right")}],
    )
    r = app_client.post(
        "/api/auth/operator/password-login",
        json={"email": "op@x.com", "password": "wrong", "tenant_id": "acme"},
    )
    assert r.status_code == 401


def test_correct_password_mints_session_and_autocreates_operator(
    app_client, db_conn, tmp_path
):
    _write_passwords(
        tmp_path,
        [{"email": "op@x.com", "password_bcrypt": _bcrypt("s3cret")}],
    )
    r = app_client.post(
        "/api/auth/operator/password-login",
        json={"email": "op@x.com", "password": "s3cret", "tenant_id": "acme"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["tenant_id"] == "acme"
    assert body["email"] == "op@x.com"
    assert body["operator_id"]
    # operator row created, session row created, cookie set
    rows = db_conn.execute("SELECT COUNT(*) AS c FROM operators").fetchone()
    assert rows["c"] == 1
    rows = db_conn.execute(
        "SELECT COUNT(*) AS c FROM operator_sessions"
    ).fetchone()
    assert rows["c"] == 1
    assert operators.OPERATOR_SESSION_COOKIE_NAME in r.cookies


def test_email_match_is_case_insensitive(app_client, tmp_path):
    _write_passwords(
        tmp_path,
        [{"email": "Op@X.Com", "password_bcrypt": _bcrypt("pw")}],
    )
    r = app_client.post(
        "/api/auth/operator/password-login",
        json={"email": "OP@x.com", "password": "pw", "tenant_id": "acme"},
    )
    assert r.status_code == 200


def test_disabled_operator_returns_401_even_with_valid_password(
    app_client, db_conn, tmp_path
):
    _write_passwords(
        tmp_path,
        [{"email": "op@x.com", "password_bcrypt": _bcrypt("pw")}],
    )
    op = operators.create_operator(
        db_conn, tenant_id="acme", email="op@x.com", role="responder"
    )
    db_conn.execute(
        "UPDATE operators SET status='disabled' WHERE id=?", (op.id,)
    )
    db_conn.commit()
    r = app_client.post(
        "/api/auth/operator/password-login",
        json={"email": "op@x.com", "password": "pw", "tenant_id": "acme"},
    )
    assert r.status_code == 401
    assert "disabled" in r.json().get("error", "").lower()


def test_rate_limit_after_5_failures(app_client, tmp_path):
    _write_passwords(tmp_path, [])
    for _ in range(5):
        r = app_client.post(
            "/api/auth/operator/password-login",
            json={"email": "op@x.com", "password": "x", "tenant_id": "acme"},
        )
        assert r.status_code == 401
    r = app_client.post(
        "/api/auth/operator/password-login",
        json={"email": "op@x.com", "password": "x", "tenant_id": "acme"},
    )
    assert r.status_code == 429
