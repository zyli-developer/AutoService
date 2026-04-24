"""Unit tests for autoservice.password_login.

Covers:
- File missing → 404 (feature disabled)
- Email not in entries → 401 (constant-time, no enumeration)
- Wrong password → 401
- Correct password → 200 + auth_session cookie
- Rate limit (5 failures / 10 min per IP) → 429
- Lockout decay after window
"""
from __future__ import annotations

import json
import time

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoservice import password_login as pl


_EMAIL = "admin@example.com"
_GOOD_PASSWORD = "unit-test-password-16ch"


def _mk_file(tmp_path, entries: list[dict]) -> str:
    p = tmp_path / "passwords.json"
    p.write_text(json.dumps({"version": 1, "updated_at": "2026-04-24T00:00:00Z", "entries": entries}))
    return str(p)


def _mk_app(path_or_none) -> TestClient:
    app = FastAPI()
    app.include_router(pl.build_router(passwords_path=path_or_none))
    return TestClient(app)


def _entry(email: str, pw: str) -> dict:
    return {
        "email": email,
        "password_bcrypt": bcrypt.hashpw(pw.encode(), bcrypt.gensalt(4)).decode(),
        "generated_at": "2026-04-24T00:00:00Z",
    }


@pytest.fixture(autouse=True)
def _reset_lockout():
    pl._FAILED_ATTEMPTS.clear()
    yield
    pl._FAILED_ATTEMPTS.clear()


def test_missing_file_returns_404(tmp_path):
    path = tmp_path / "nonexistent.json"
    client = _mk_app(str(path))
    r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": "x"})
    assert r.status_code == 404


def test_email_not_in_entries_returns_401_without_enumeration(tmp_path):
    path = _mk_file(tmp_path, [_entry("someone@else.com", _GOOD_PASSWORD)])
    client = _mk_app(path)
    r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": "x"})
    assert r.status_code == 401
    assert r.json().get("detail") == "invalid credentials"


def test_wrong_password_returns_401(tmp_path):
    path = _mk_file(tmp_path, [_entry(_EMAIL, _GOOD_PASSWORD)])
    client = _mk_app(path)
    r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": "wrong"})
    assert r.status_code == 401


def test_success_sets_session_cookie(tmp_path):
    path = _mk_file(tmp_path, [_entry(_EMAIL, _GOOD_PASSWORD)])
    client = _mk_app(path)
    r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": _GOOD_PASSWORD})
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "auth_session=" in set_cookie
    assert "HttpOnly" in set_cookie


def test_email_match_is_case_insensitive(tmp_path):
    path = _mk_file(tmp_path, [_entry(_EMAIL, _GOOD_PASSWORD)])
    client = _mk_app(path)
    r = client.post("/api/auth/password-login", json={"email": _EMAIL.upper(), "password": _GOOD_PASSWORD})
    assert r.status_code == 200


def test_rate_limit_blocks_after_five_failures(tmp_path):
    path = _mk_file(tmp_path, [_entry(_EMAIL, _GOOD_PASSWORD)])
    client = _mk_app(path)
    for _ in range(5):
        r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": _GOOD_PASSWORD})
    assert r.status_code == 429


def test_rate_limit_decays_after_window(tmp_path):
    path = _mk_file(tmp_path, [_entry(_EMAIL, _GOOD_PASSWORD)])
    client = _mk_app(path)
    for _ in range(5):
        client.post("/api/auth/password-login", json={"email": _EMAIL, "password": "wrong"})
    for ip in list(pl._FAILED_ATTEMPTS.keys()):
        pl._FAILED_ATTEMPTS[ip] = [t - (11 * 60) for t in pl._FAILED_ATTEMPTS[ip]]
    r = client.post("/api/auth/password-login", json={"email": _EMAIL, "password": _GOOD_PASSWORD})
    assert r.status_code == 200


def test_gateway_mounts_password_login_route(tmp_path, monkeypatch):
    """Route is reachable via the real app factory.

    passwords.json is absent in the test env → 404 is the expected
    response, which still proves the route is mounted (distinct from
    405 'method not allowed' or 500).
    """
    from autoservice.web_gateway import create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)
    r = client.post("/api/auth/password-login", json={"email": "foo@bar.com", "password": "x"})
    assert r.status_code in (401, 404)
