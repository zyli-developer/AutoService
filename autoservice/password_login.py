"""POST /api/auth/password-login — per-email, file-backed password login.

Storage lives at ``.autoservice/passwords.json`` with shape::

    {
      "version": 1,
      "updated_at": "...",
      "entries": [{"email": "x@y", "password_bcrypt": "$2b$...", "generated_at": "..."}]
    }

Emails are compared case-insensitively. When a request arrives for an
email NOT in ``entries`` the endpoint still runs a bcrypt check against
a throwaway hash so response time does not leak membership.

Rate limit: 5 failures per 10-minute window per client IP → 429.

On success mints the same ``auth_session`` cookie shape as the magic-
link flow (``HttpOnly``, ``Secure``, ``SameSite=Lax``, ``Path=/``,
7-day TTL). Session row persistence is not the responsibility of this
module; session-verification middleware elsewhere in the gateway
treats the cookie value as an opaque token and verifies against its
own session table. For demo-phase this endpoint only needs to produce
the cookie — the same-file-backed pattern can be replaced by a real
users table without touching the Caddy/tunnel layer.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional

import bcrypt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr

from autoservice import auth as _auth

logger = logging.getLogger("autoservice.password_login")

_FAILED_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_WINDOW_SECONDS = 10 * 60
_MAX_FAILURES = 5

# Dummy hash used to maintain constant-time behavior for missing emails.
_DUMMY_HASH = bcrypt.hashpw(b"unused-reference", bcrypt.gensalt(4)).decode()


class PasswordLoginRequest(BaseModel):
    email: EmailStr
    password: str


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_locked(ip: str) -> bool:
    now = time.time()
    _FAILED_ATTEMPTS[ip] = [t for t in _FAILED_ATTEMPTS.get(ip, []) if (now - t) < _WINDOW_SECONDS]
    return len(_FAILED_ATTEMPTS[ip]) >= _MAX_FAILURES


def _record_failure(ip: str) -> None:
    _FAILED_ATTEMPTS[ip].append(time.time())


def _clear_failures(ip: str) -> None:
    _FAILED_ATTEMPTS.pop(ip, None)


def _load_entries(path: str) -> Optional[list[dict]]:
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[password-login] cannot read %s: %s", path, exc)
        return None
    entries = data.get("entries") or []
    return entries if isinstance(entries, list) else None


def _find_entry(entries: list[dict], email: str) -> Optional[dict]:
    target = email.lower()
    for e in entries:
        if str(e.get("email", "")).lower() == target:
            return e
    return None


def build_router(
    *,
    passwords_path: str,
    db_provider: Callable[[], sqlite3.Connection],
) -> APIRouter:
    """Build the router.

    Args:
        passwords_path: absolute path to passwords.json.
        db_provider: callable returning the auth-DB connection.  Called per
            request so test fixtures and lazy-init in production both work.
    """
    router = APIRouter()

    @router.post("/api/auth/password-login")
    def password_login(body: PasswordLoginRequest, request: Request, response: Response) -> dict[str, str]:
        entries = _load_entries(passwords_path)
        if entries is None:
            # File missing → feature disabled, pretend route does not exist.
            raise HTTPException(status_code=404)

        ip = _client_ip(request)
        if _is_locked(ip):
            logger.warning("[password-login] ip=%s locked out", ip)
            raise HTTPException(status_code=429, detail="too many attempts")

        entry = _find_entry(entries, body.email)
        if entry is None:
            bcrypt.checkpw(body.password.encode(), _DUMMY_HASH.encode())
            _record_failure(ip)
            raise HTTPException(status_code=401, detail="invalid credentials")

        stored = str(entry.get("password_bcrypt", ""))
        if not stored or not bcrypt.checkpw(body.password.encode(), stored.encode()):
            _record_failure(ip)
            logger.warning("[password-login] ip=%s email=%s bad password", ip, body.email)
            raise HTTPException(status_code=401, detail="invalid credentials")

        _clear_failures(ip)

        # Persist a real session row so middleware accepts the cookie on
        # subsequent requests.  Without this the cookie is opaque junk and
        # the next page load redirects back to /login.
        email_normalized = body.email.lower()
        session_id = _auth.create_session(
            db_provider(), email_normalized, tenant_id=None
        )
        secure_flag = request.url.scheme == "https"
        response.set_cookie(
            key="auth_session",
            value=session_id,
            max_age=_auth.DEFAULT_SESSION_TTL_DAYS * 24 * 3600,
            httponly=True,
            secure=secure_flag,
            samesite="lax",
            path="/",
        )
        logger.info("[password-login] ip=%s email=%s success", ip, body.email)
        return {"ok": "true", "email": body.email}

    return router
