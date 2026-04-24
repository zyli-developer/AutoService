"""Operator HTTP routes — magic-link login + session + CRUD.

Delivers T1S.2 (operator login / session / logout / me) and T1S.4
(per-tenant operator CRUD).

Contract: docs/contracts/m3/e1-auth-rbac.md §3.

Design choices (applying default OQ values):
- Magic-link only for M3 operator login (no password field).  Contract §3.1
  allowed ``{email, password}`` but M3 defers password auth — OQ-E1 path 1.
- Cookie ``operator_session`` separate from admin ``auth_session`` (CON-08).
- TTL 24h, idle-timeout 30min (OQ-E1-2).
- Admin CRUD endpoints reuse :func:`auth.require_tenant_access` for auth
  (admin session + tenant scope); RBAC 3-tier matrix comes with T2S.1.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import (
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from autoservice import auth, operators

logger = logging.getLogger("autoservice.operator_routes")

operator_router = APIRouter(tags=["operator"])

# Dev-only bypass toggle — read ONCE at import; flipping the env at runtime
# requires a process restart.  Mirrors api_routes.DEV_MODE_ENABLED.
DEV_MODE_ENABLED = os.environ.get("AUTH_DEV_MODE") == "1"

# Shared with admin /api/auth/dev-login.  Each entry is a single JSON line.
# Path is resolved at call time so tests can monkeypatch.chdir(tmp_path).
_DEV_MAIL_LOG = Path(".autoservice") / "logs" / "auth-devmail.jsonl"


# ──────────────────────────────────────────────────────────────────────────
# Shared DB handle (test-overridable)
# ──────────────────────────────────────────────────────────────────────────

_op_db_conn: sqlite3.Connection | None = None


_op_db_lock: Any = None   # set lazily to avoid importing threading at module load


def _get_op_db() -> sqlite3.Connection:
    """Return the shared operator-DB connection (lazy singleton).

    Uses the same ``auth.db`` file as admin auth (contract §2 DB location).
    Ensures operators + operator_sessions tables and migration applied.

    Reviewer finding C2 (2026-04-21): init is lock-guarded + connection is
    opened with ``check_same_thread=False`` so ASGI worker-thread dispatch
    does not trigger sqlite3 "created in thread X, used in thread Y" errors.
    """
    global _op_db_conn, _op_db_lock
    if _op_db_conn is not None:
        return _op_db_conn
    if _op_db_lock is None:
        import threading
        _op_db_lock = threading.Lock()
    with _op_db_lock:
        if _op_db_conn is None:
            # auth.open_connection doesn't expose check_same_thread — open here.
            import sqlite3 as _sqlite3
            from autoservice.auth import _DEFAULT_DB_PATH
            path = _DEFAULT_DB_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = _sqlite3.connect(
                str(path), check_same_thread=False
            )
            conn.row_factory = _sqlite3.Row
            auth.apply_schema(conn)
            operators.apply_operators_schema(conn)
            operators.migrate_login_tokens_add_role(conn)
            _op_db_conn = conn
    return _op_db_conn


def _reset_op_db_for_tests(conn: sqlite3.Connection | None = None) -> None:
    """Test-only hook: inject an in-memory sqlite3 connection."""
    global _op_db_conn
    _op_db_conn = conn


# ──────────────────────────────────────────────────────────────────────────
# Login flow — request-login → verify → logout (T1S.2)
# ──────────────────────────────────────────────────────────────────────────


@operator_router.post("/auth/operator/request-login")
async def operator_request_login(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> Any:
    """Issue a magic-link token for an operator email.

    Request body::

        {"email": "<op@example.com>", "tenant_id": "<tid>"}

    Response (always 200, anti-enumeration — contract "Don't Do" §4):

        {"status": "sent", "delivered": "log"}

    Behaviour:
    * If ``(tenant_id, email)`` is a known *active* operator a token with
      ``role='operator'`` is persisted; dev-mode logs the link.
    * Unknown / disabled operator → identical response, no token persisted.
    * Missing fields → 422.
    """
    email_raw = payload.get("email") if isinstance(payload, dict) else None
    tenant_raw = payload.get("tenant_id") if isinstance(payload, dict) else None
    if not isinstance(email_raw, str) or not email_raw.strip():
        return JSONResponse(
            status_code=422, content={"error": "email is required"}
        )
    if not isinstance(tenant_raw, str) or not tenant_raw.strip():
        return JSONResponse(
            status_code=422, content={"error": "tenant_id is required"}
        )

    email = email_raw.strip().lower()
    tenant_id = tenant_raw.strip()

    conn = _get_op_db()
    op = operators.get_operator_by_email(conn, tenant_id, email)

    # Anti-enumeration: identical response whether operator exists or not.
    if op is not None and op.status == "active":
        token = operators.issue_operator_login_token(
            conn, operator_email=email, tenant_id=tenant_id
        )
        logger.info(
            "[dev] operator magic-link issued tenant=%s email=%s token=%s",
            tenant_id,
            email,
            token,
        )

    return {"status": "sent", "delivered": "log"}


@operator_router.get("/auth/operator/verify")
async def operator_verify(
    request: Request,
    token: str | None = None,
    redirect: str = "/operator",
) -> Any:
    """Burn operator magic-link token and mint an ``operator_session`` cookie.

    Query params:
        token:    required — magic-link token issued by request-login.
        redirect: optional — path to land on after cookie set.  Defaults
                  to ``/operator`` (operator-console SPA).

    Response:
        * 302 to redirect with ``Set-Cookie: operator_session=…`` on success
        * 401 on unknown / expired / already-consumed / wrong-role tokens
        * 422 when token is missing / empty
    """
    if not token or not token.strip():
        return JSONResponse(
            status_code=422, content={"error": "token is required"}
        )

    conn = _get_op_db()
    result = operators.consume_operator_login_token(conn, token.strip())
    if result is None:
        return PlainTextResponse(
            "Invalid or expired operator login link", status_code=401
        )

    email, tenant_id, _invited_by = result
    op = operators.get_operator_by_email(conn, tenant_id, email)
    if op is None:
        # Edge case: operator was deleted between token issue and verify.
        return PlainTextResponse("Operator not found", status_code=401)
    if op.status != "active":
        return PlainTextResponse("Operator disabled", status_code=401)

    op_token = operators.issue_operator_session(
        conn,
        operator_id=op.id,
        tenant_id=tenant_id,
        ip_created=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    response = RedirectResponse(url=redirect, status_code=302)
    secure_flag = request.url.scheme == "https"
    response.set_cookie(
        key=operators.OPERATOR_SESSION_COOKIE_NAME,
        value=op_token,
        max_age=operators.DEFAULT_OPERATOR_SESSION_TTL_HOURS * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=secure_flag,
        path="/",
    )
    return response


@operator_router.post("/auth/operator/logout")
async def operator_logout(request: Request) -> Response:
    """Revoke current operator session and clear cookie.

    Always 204 — idempotent.  No cookie / unknown session / already-revoked
    all handled silently.
    """
    tok = request.cookies.get(operators.OPERATOR_SESSION_COOKIE_NAME)
    if tok:
        conn = _get_op_db()
        operators.revoke_operator_session(conn, tok)

    response = Response(status_code=204)
    secure_flag = request.url.scheme == "https"
    response.set_cookie(
        key=operators.OPERATOR_SESSION_COOKIE_NAME,
        value="",
        max_age=0,
        httponly=True,
        samesite="lax",
        secure=secure_flag,
        path="/",
    )
    return response


@operator_router.get("/auth/operator/me")
async def operator_me(request: Request) -> Any:
    """Return current operator session context.

    * 200 ``{operator_id, tenant_id, email, role, expires_at}`` when live.
    * 401 when cookie missing / session expired / idle-timed-out / operator disabled.
    """
    tok = request.cookies.get(operators.OPERATOR_SESSION_COOKIE_NAME)
    if not tok:
        raise HTTPException(status_code=401, detail={"error": "unauthenticated"})

    conn = _get_op_db()
    ctx = operators.lookup_operator_session(conn, tok)
    if ctx is None:
        raise HTTPException(status_code=401, detail={"error": "unauthenticated"})

    # Bump idle timestamp on successful lookup (activity marker).
    operators.touch_operator_session(conn, tok)
    return ctx


def _client_ip(request: Request) -> str | None:
    """Best-effort IP extraction for audit fields."""
    if request.client is None:
        return None
    return request.client.host


# ──────────────────────────────────────────────────────────────────────────
# Dev-only bypass (parallel to admin /api/auth/dev-login)
# ──────────────────────────────────────────────────────────────────────────
#
# Gated by AUTH_DEV_MODE=1.  Disabled → 404 (no endpoint surface advertised).
# When enabled:
#   * upserts an ``operators`` row if (tenant_id, email) is unknown — default
#     role=responder so the minted session matches an active operator
#   * mints an ``operator_session`` row + Set-Cookie (same attrs as /verify)
#   * appends an audit entry to ``.autoservice/logs/auth-devmail.jsonl``
#
# This closes the local-dev gap where T1S.3 (WS strict cookie validation)
# requires an operator_session cookie, but no in-repo flow could mint one
# without email delivery.  Production (AUTH_DEV_MODE unset) uses the
# magic-link flow (/request-login → /verify).


@operator_router.post("/auth/operator/dev-login")
async def operator_dev_login(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> Any:
    """Dev-only: mint an ``operator_session`` cookie without magic-link.

    Request body::

        {"email": "<op@dev.local>", "tenant_id": "<tid>"}

    Response (200)::

        {"ok": true, "redirect": "/operator",
         "operator_id": "...", "tenant_id": "...", "email": "..."}

    Errors:
      * 404 when ``AUTH_DEV_MODE`` is not set (endpoint existence hidden).
      * 400 when email or tenant_id is missing / blank.
      * 401 when an existing operator has ``status != 'active'``.
    """
    if not DEV_MODE_ENABLED:
        return JSONResponse(status_code=404, content={"error": "not found"})

    email_raw = payload.get("email") if isinstance(payload, dict) else None
    if not isinstance(email_raw, str) or not email_raw.strip():
        return JSONResponse(
            status_code=400, content={"error": "email is required"}
        )
    tenant_raw = payload.get("tenant_id") if isinstance(payload, dict) else None
    if not isinstance(tenant_raw, str) or not tenant_raw.strip():
        return JSONResponse(
            status_code=400, content={"error": "tenant_id is required"}
        )

    email = email_raw.strip().lower()
    tenant_id = tenant_raw.strip()

    conn = _get_op_db()
    op = operators.get_operator_by_email(conn, tenant_id, email)
    if op is None:
        op = operators.create_operator(
            conn, tenant_id=tenant_id, email=email, role="responder"
        )
    elif op.status != "active":
        return JSONResponse(
            status_code=401, content={"error": "operator disabled"}
        )

    token = operators.issue_operator_session(
        conn,
        operator_id=op.id,
        tenant_id=tenant_id,
        ip_created=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    tok_prefix = token[:8]
    logger.warning(
        "[operator-dev-login] minted session for %s (tenant=%s, op=%s, tok=%s…)",
        email, tenant_id, op.id, tok_prefix,
    )
    _DEV_MAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    audit = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "operator_dev_login",
        "email": email,
        "tenant_id": tenant_id,
        "operator_id": op.id,
        "session_token_prefix": tok_prefix,
    }
    with _DEV_MAIL_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(audit, ensure_ascii=False) + "\n")

    response = JSONResponse(
        content={
            "ok": True,
            "redirect": "/operator",
            "operator_id": op.id,
            "tenant_id": tenant_id,
            "email": email,
        }
    )
    secure_flag = request.url.scheme == "https"
    response.set_cookie(
        key=operators.OPERATOR_SESSION_COOKIE_NAME,
        value=token,
        max_age=operators.DEFAULT_OPERATOR_SESSION_TTL_HOURS * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=secure_flag,
        path="/",
    )
    return response


# ──────────────────────────────────────────────────────────────────────────
# Operator CRUD (T1S.4) — admin-authenticated, tenant-scoped
# ──────────────────────────────────────────────────────────────────────────
#
# Auth: :func:`auth.require_tenant_access` ensures the caller has a valid
# admin ``auth_session`` cookie AND is scoped to {tenant_id}.  The RBAC
# 3-tier matrix (T2S.1) will further restrict to role='admin' — for M3 P0
# the tenant-scope check is sufficient (only admins have sessions today).


@operator_router.get("/admin/{tenant_id}/operators")
async def list_operators(
    tenant_id: str,
    include_disabled: bool = False,
    ctx: auth.AuthContext = Depends(auth.require_tenant_access),
) -> Any:
    conn = _get_op_db()
    ops = operators.list_operators_by_tenant(
        conn, tenant_id, include_disabled=include_disabled
    )
    return {"operators": [_operator_to_dict(o) for o in ops]}


@operator_router.get("/admin/{tenant_id}/operators/{operator_id}")
async def get_one_operator(
    tenant_id: str,
    operator_id: str,
    ctx: auth.AuthContext = Depends(auth.require_tenant_access),
) -> Any:
    conn = _get_op_db()
    op = operators.get_operator(conn, operator_id)
    if op is None or op.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail={"error": "operator not found"})
    return {"operator": _operator_to_dict(op)}


@operator_router.post("/admin/{tenant_id}/operators")
async def create_one_operator(
    tenant_id: str,
    payload: dict[str, Any] = Body(...),
    ctx: auth.AuthContext = Depends(auth.require_tenant_access),
) -> Any:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail={"error": "body must be JSON"})
    email = payload.get("email")
    role = payload.get("role")
    display_name = payload.get("display_name")

    if not isinstance(email, str) or not email.strip():
        raise HTTPException(status_code=422, detail={"error": "email is required"})
    if role not in ("viewer", "responder", "admin"):
        raise HTTPException(
            status_code=422,
            detail={"error": "role must be viewer|responder|admin"},
        )

    conn = _get_op_db()
    try:
        op = operators.create_operator(
            conn,
            tenant_id=tenant_id,
            email=email,
            role=role,
            display_name=display_name if isinstance(display_name, str) else None,
            created_by=ctx.admin_email,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409, detail={"error": "operator email already exists"}
        )
    return JSONResponse(
        status_code=201, content={"operator": _operator_to_dict(op)}
    )


@operator_router.patch("/admin/{tenant_id}/operators/{operator_id}")
async def update_one_operator(
    tenant_id: str,
    operator_id: str,
    payload: dict[str, Any] = Body(...),
    ctx: auth.AuthContext = Depends(auth.require_tenant_access),
) -> Any:
    conn = _get_op_db()
    existing = operators.get_operator(conn, operator_id)
    if existing is None or existing.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail={"error": "operator not found"})

    role = payload.get("role") if isinstance(payload, dict) else None
    status_ = payload.get("status") if isinstance(payload, dict) else None
    display_name = (
        payload.get("display_name") if isinstance(payload, dict) else None
    )

    if role is not None and role not in ("viewer", "responder", "admin"):
        raise HTTPException(
            status_code=422,
            detail={"error": "role must be viewer|responder|admin"},
        )
    if status_ is not None and status_ not in ("active", "disabled"):
        raise HTTPException(
            status_code=422, detail={"error": "status must be active|disabled"}
        )

    updated = operators.update_operator(
        conn,
        operator_id,
        role=role,
        status=status_,
        display_name=display_name if isinstance(display_name, str) else None,
    )

    # Defensive: revoke sessions on disable (FK cascade triggers on DELETE, not UPDATE)
    if status_ == "disabled":
        operators.revoke_all_operator_sessions(conn, operator_id)

    return {"operator": _operator_to_dict(updated)}


@operator_router.delete("/admin/{tenant_id}/operators/{operator_id}")
async def delete_one_operator(
    tenant_id: str,
    operator_id: str,
    ctx: auth.AuthContext = Depends(auth.require_tenant_access),
) -> Response:
    conn = _get_op_db()
    existing = operators.get_operator(conn, operator_id)
    if existing is None or existing.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail={"error": "operator not found"})
    operators.delete_operator(conn, operator_id)
    return Response(status_code=204)


# ──────────────────────────────────────────────────────────────────────────
# Admin-to-admin invite accept (T3S.6 · E1.6)
# ──────────────────────────────────────────────────────────────────────────


@operator_router.get("/auth/admin/accept-invite")
async def accept_admin_invite(
    request: Request,
    token: str | None = None,
    redirect: str = "/admin",
) -> Any:
    """Consume a tenant_admin invite token; set auth_session cookie.

    T3S.6 · E1.6: existing admin issued an invite via POST /admin/{tid}/invites
    with role='tenant_admin' (T1S.5).  Invitee clicks link → this endpoint
    burns the token (role-gated on 'tenant_admin') + creates a sessions row
    + sets ``auth_session`` cookie.
    """
    if not token or not token.strip():
        return JSONResponse(
            status_code=422, content={"error": "token is required"}
        )

    conn = _get_op_db()
    from datetime import datetime, timezone
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    cur = conn.execute(
        """UPDATE login_tokens
              SET consumed_at = ?
            WHERE token = ?
              AND consumed_at IS NULL
              AND expires_at > ?
              AND role = 'tenant_admin'""",
        (now_iso, token.strip(), now_iso),
    )
    if cur.rowcount == 0:
        conn.commit()
        return PlainTextResponse(
            "Invalid or expired admin invite", status_code=401
        )

    row = conn.execute(
        "SELECT admin_email, tenant_id FROM login_tokens WHERE token = ?",
        (token.strip(),),
    ).fetchone()
    conn.commit()
    if row is None:  # pragma: no cover
        return PlainTextResponse("internal error", status_code=401)

    admin_email = row["admin_email"]
    tenant_id = row["tenant_id"]
    session_id = auth.create_session(conn, admin_email, tenant_id=tenant_id)

    response = RedirectResponse(url=redirect, status_code=302)
    secure_flag = request.url.scheme == "https"
    response.set_cookie(
        key=auth.AUTH_SESSION_COOKIE_NAME,
        value=session_id,
        max_age=auth.DEFAULT_SESSION_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=secure_flag,
        path="/",
    )
    return response


# ──────────────────────────────────────────────────────────────────────────
# Multi-admin per tenant (T2S.2 · E1.5)
# ──────────────────────────────────────────────────────────────────────────


@operator_router.get("/admin/{tenant_id}/admins")
async def list_admins(
    tenant_id: str,
    ctx: auth.AuthContext = Depends(auth.require_tenant_access),
) -> Any:
    """List all admins currently associated with a tenant.

    An admin is identified by having a live (un-revoked, un-expired) session
    scoped to this ``tenant_id``.  This reflects the PRD §2 E1.5 requirement:
    ≥2 admins per tenant with identical permissions.  Multiple active sessions
    for the same email count as ONE admin.
    """
    conn = _get_op_db()
    now_iso = _isoformat_now()
    rows = conn.execute(
        """SELECT DISTINCT admin_email, MIN(created_at) AS first_seen,
                  MAX(expires_at) AS latest_expires
             FROM sessions
            WHERE tenant_id = ?
              AND revoked_at IS NULL
              AND expires_at > ?
            GROUP BY admin_email
            ORDER BY first_seen""",
        (tenant_id, now_iso),
    ).fetchall()
    return {
        "admins": [
            {
                "email": r["admin_email"],
                "first_seen": r["first_seen"],
                "latest_expires": r["latest_expires"],
            }
            for r in rows
        ]
    }


@operator_router.delete("/admin/{tenant_id}/admins/{email}")
async def revoke_admin(
    tenant_id: str,
    email: str,
    ctx: auth.AuthContext = Depends(auth.require_tenant_access),
) -> Any:
    """Revoke all active sessions for an admin on this tenant.

    Guardrail: refuse if this would leave zero admins on the tenant
    (cannot orphan a tenant per contract §6 "Don't Do" list).  The caller
    (who is an admin) cannot revoke themselves as the last admin — must
    invite a co-admin first, then remove themselves.
    """
    conn = _get_op_db()
    now_iso = _isoformat_now()
    target_email = email.strip().lower()

    # Count distinct live admin emails on this tenant
    current = conn.execute(
        """SELECT COUNT(DISTINCT admin_email) AS n
             FROM sessions
            WHERE tenant_id = ?
              AND revoked_at IS NULL
              AND expires_at > ?""",
        (tenant_id, now_iso),
    ).fetchone()

    # Check target is actually an admin here
    target_row = conn.execute(
        """SELECT COUNT(*) AS n
             FROM sessions
            WHERE tenant_id = ?
              AND admin_email = ?
              AND revoked_at IS NULL
              AND expires_at > ?""",
        (tenant_id, target_email, now_iso),
    ).fetchone()
    if target_row["n"] == 0:
        raise HTTPException(
            status_code=404, detail={"error": "admin not found on this tenant"}
        )

    # Last-admin guard
    if current["n"] <= 1:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "cannot_revoke_last_admin",
                "message": (
                    "This would orphan the tenant. Invite another admin first."
                ),
            },
        )

    # Revoke all live sessions for that admin on this tenant
    conn.execute(
        """UPDATE sessions
              SET revoked_at = ?
            WHERE tenant_id = ?
              AND admin_email = ?
              AND revoked_at IS NULL""",
        (now_iso, tenant_id, target_email),
    )
    conn.commit()
    return {"ok": True, "revoked_email": target_email}


def _isoformat_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(tz=timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────────
# Invites (T1S.5 — admin creates operator invite; new operator accepts)
# ──────────────────────────────────────────────────────────────────────────


@operator_router.post("/admin/{tenant_id}/invites")
async def create_invite(
    tenant_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
    ctx: auth.AuthContext = Depends(auth.require_tenant_access),
) -> Any:
    """Create a magic-link invite token.

    Request body::
        {"email": "<new-op@example.com>", "role": "operator" | "tenant_admin"}

    Response:
        201 { "invite_url": "...", "expires_in_min": 10 }

    T1S.5 implements role='operator' fully; role='tenant_admin' is accepted
    and persists a token but the UI for admin-to-admin invite lands with
    E1.6 (batch-9).
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail={"error": "body must be JSON"})
    email = payload.get("email")
    role = payload.get("role")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(status_code=422, detail={"error": "email is required"})
    if role not in ("operator", "tenant_admin"):
        raise HTTPException(
            status_code=422,
            detail={"error": "role must be operator|tenant_admin"},
        )

    conn = _get_op_db()
    if role == "operator":
        token = operators.issue_operator_login_token(
            conn,
            operator_email=email,
            tenant_id=tenant_id,
            invited_by=ctx.admin_email,
        )
        accept_path = f"/api/auth/operator/accept-invite?token={token}"
    else:
        # tenant_admin path — write to login_tokens with role column set.
        # Full admin-to-admin flow (E1.6) will extend this; T1S.5 only
        # persists the token so audit trail is complete.
        from datetime import timedelta
        from autoservice.auth import _coerce_now, DEFAULT_LOGIN_TOKEN_TTL_MIN
        import secrets as _secrets

        created = _coerce_now(None)
        expires = created + timedelta(minutes=DEFAULT_LOGIN_TOKEN_TTL_MIN)
        token = _secrets.token_urlsafe(24)
        conn.execute(
            """INSERT INTO login_tokens
                 (token, admin_email, tenant_id, created_at, expires_at,
                  consumed_at, role, invited_by)
               VALUES (?, ?, ?, ?, ?, NULL, 'tenant_admin', ?)""",
            (
                token,
                email.strip().lower(),
                tenant_id,
                created.isoformat(),
                expires.isoformat(),
                ctx.admin_email,
            ),
        )
        conn.commit()
        accept_path = f"/api/auth/verify?token={token}"  # reuses admin verify

    # Build absolute invite URL using the request's origin.
    origin = f"{request.url.scheme}://{request.url.netloc}"
    invite_url = f"{origin}{accept_path}"

    return JSONResponse(
        status_code=201,
        content={
            "invite_url": invite_url,
            "role": role,
            "expires_in_min": 10,
        },
    )


@operator_router.get("/auth/operator/accept-invite")
async def accept_operator_invite(
    request: Request,
    token: str | None = None,
    redirect: str = "/operator",
) -> Any:
    """Consume an operator invite token; create operator on first use; set cookie.

    Differs from ``/auth/operator/verify`` which requires the operator to
    already exist.  Invite flow: the admin created the token but not the
    operator row — this endpoint creates the operator on first click.

    Default new-operator role: 'viewer' (OQ-E1 default — admin can promote
    via T1S.4 CRUD PATCH after acceptance).
    """
    if not token or not token.strip():
        return JSONResponse(
            status_code=422, content={"error": "token is required"}
        )

    conn = _get_op_db()
    result = operators.consume_operator_login_token(conn, token.strip())
    if result is None:
        return PlainTextResponse(
            "Invalid or expired invite link", status_code=401
        )

    email, tenant_id, invited_by = result

    # Create-if-missing: operator may or may not exist yet.
    op = operators.get_operator_by_email(conn, tenant_id, email)
    if op is None:
        op = operators.create_operator(
            conn,
            tenant_id=tenant_id,
            email=email,
            role="viewer",  # default; admin can promote via PATCH
            created_by=invited_by,
        )
    elif op.status != "active":
        return PlainTextResponse(
            "Operator account disabled", status_code=401
        )

    op_token = operators.issue_operator_session(
        conn,
        operator_id=op.id,
        tenant_id=tenant_id,
        ip_created=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    response = RedirectResponse(url=redirect, status_code=302)
    secure_flag = request.url.scheme == "https"
    response.set_cookie(
        key=operators.OPERATOR_SESSION_COOKIE_NAME,
        value=op_token,
        max_age=operators.DEFAULT_OPERATOR_SESSION_TTL_HOURS * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=secure_flag,
        path="/",
    )
    return response


# ──────────────────────────────────────────────────────────────────────────
# classify_intent CRUD (T3S.4) — admin-only; hot-reload via clear_tenant_cache
# ──────────────────────────────────────────────────────────────────────────


@operator_router.get("/admin/{tenant_id}/classify-intent")
async def list_classify_intents(
    tenant_id: str,
    ctx: auth.AuthContext = Depends(auth.require_tenant_access),
) -> Any:
    from autoservice import classify_intent_config as _cic
    conn = _get_op_db()
    # Ensure schema + defaults seeded (safe/idempotent on each call; cheap)
    _cic.apply_schema(conn)
    try:
        _cic.seed_defaults_from_yaml(conn)
    except FileNotFoundError:
        pass  # test env without YAML — fall through

    rows = _cic.list_intents(conn, tenant_id)
    return {
        "tenant_id": tenant_id,
        "intents": [
            {
                "tenant_id": r.tenant_id,  # _default means inherited, tenant_id means overridden
                "intent": r.intent,
                "keywords": r.keywords,
                "threshold": r.threshold,
                "model_tier": r.model_tier,
                "route_role": r.route_role,
                "priority": r.priority,
                "description": r.description,
                "updated_at": r.updated_at,
                "updated_by": r.updated_by,
            }
            for r in rows
        ],
    }


@operator_router.put("/admin/{tenant_id}/classify-intent/{intent}")
async def upsert_classify_intent(
    tenant_id: str,
    intent: str,
    payload: dict[str, Any] = Body(...),
    ctx: auth.AuthContext = Depends(auth.require_tenant_access),
) -> Any:
    from autoservice import classify_intent_config as _cic

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail={"error": "body must be JSON"})
    keywords = payload.get("keywords")
    if not isinstance(keywords, list) or not all(
        isinstance(k, str) for k in keywords
    ):
        raise HTTPException(
            status_code=422, detail={"error": "keywords must be list[str]"}
        )
    threshold = payload.get("threshold", 0.5)
    if not isinstance(threshold, (int, float)):
        raise HTTPException(
            status_code=422, detail={"error": "threshold must be number"}
        )

    conn = _get_op_db()
    _cic.apply_schema(conn)

    try:
        cfg = _cic.upsert_intent(
            conn,
            tenant_id=tenant_id,
            intent=intent,
            keywords=keywords,
            threshold=float(threshold),
            model_tier=payload.get("model_tier", "fast"),
            route_role=payload.get("route_role", "customer"),
            priority=payload.get("priority", "normal"),
            description=payload.get("description"),
            updated_by=ctx.admin_email,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"error": str(e)})

    # Hot-reload: invalidate the tenant's classifier cache so the next
    # classify call picks up the new keywords (model_router.py:91-114
    # already owns the per-tenant cache; we just clear it here).
    _invalidate_classifier_cache(tenant_id)

    return {
        "intent": cfg.intent,
        "keywords": cfg.keywords,
        "threshold": cfg.threshold,
        "model_tier": cfg.model_tier,
        "route_role": cfg.route_role,
        "priority": cfg.priority,
        "updated_at": cfg.updated_at,
        "updated_by": cfg.updated_by,
    }


@operator_router.delete("/admin/{tenant_id}/classify-intent/{intent}")
async def delete_classify_intent(
    tenant_id: str,
    intent: str,
    ctx: auth.AuthContext = Depends(auth.require_tenant_access),
) -> Response:
    from autoservice import classify_intent_config as _cic

    conn = _get_op_db()
    _cic.apply_schema(conn)

    try:
        removed = _cic.delete_tenant_override(conn, tenant_id, intent)
    except ValueError as e:
        # Attempt to delete _default
        raise HTTPException(status_code=422, detail={"error": str(e)})

    _invalidate_classifier_cache(tenant_id)
    return Response(status_code=204 if removed else 404)


def _invalidate_classifier_cache(tenant_id: str) -> None:
    """Call FastClassifier.clear_tenant_cache() on intent-config change.

    T3S.4 hot-reload: the cache in model_router is per-tenant but
    ``clear_tenant_cache`` takes no args (nukes all); we pass tenant_id
    for audit/log purposes only.  A future refactor can narrow to just
    the affected tenant.  Soft dependency — missing module is OK in tests.
    """
    try:
        from autoservice import model_router
        if hasattr(model_router, "FastClassifier") and hasattr(
            model_router.FastClassifier, "clear_tenant_cache"
        ):
            # Signature-tolerant call: some deployments may pass tenant_id,
            # upstream's doesn't.  Try with-arg first (if tests mock it to
            # capture the id), fall back to no-arg.
            try:
                model_router.FastClassifier.clear_tenant_cache(tenant_id)
            except TypeError:
                model_router.FastClassifier.clear_tenant_cache()
    except Exception:
        logger.debug(
            "classifier cache invalidation skipped (module not available)",
            exc_info=True,
        )


# ──────────────────────────────────────────────────────────────────────────
# Apply proposal (T4S.3) — HTTP layer over T4S.1 apply_proposal
# ──────────────────────────────────────────────────────────────────────────


@operator_router.post("/admin/proposals/{proposal_id}/apply")
async def apply_proposal_endpoint(
    proposal_id: str,
    ctx: auth.AuthContext = Depends(auth.require_tenant_access),
) -> Any:
    """🔒 Apply an accepted proposal (T4S.3).

    Uses the T4S.1 ``proposal_apply.apply_proposal`` as the sole writer
    of status='applied'.  HTTP-layer responsibilities:
    * Derive ``is_platform_admin`` from tier-0 session (tenant_id is None).
      Reviewer-mandated: tier-0 bit comes from the validated session,
      NEVER from request body.
    * Map exceptions to HTTP status codes per contract §2.6:
        ProposalNotFound → 404
        ProposalStateError → 409
        PermissionError → 403
        ValueError → 400
    * Return ApplyResult serialized via dataclasses.asdict.
    """
    from dataclasses import asdict

    from autoservice import proposal_apply
    from autoservice.proposal_pipeline import (
        ProposalNotFound,
        ProposalPipeline,
        ProposalStateError,
    )

    is_platform_admin = ctx.tier == 0  # derived from session, not client input

    # Build a ProposalPipeline over the shared auth DB connection.  Lazy-import
    # memory_pool to avoid circular costs in tests that don't use dream flow.
    pipeline = _build_proposal_pipeline()

    try:
        result = proposal_apply.apply_proposal(
            pipeline,
            proposal_id=proposal_id,
            admin_user_id=ctx.admin_email,
            is_platform_admin=is_platform_admin,
        )
    except ProposalNotFound:
        raise HTTPException(
            status_code=404, detail={"error": "proposal_not_found"}
        )
    except ProposalStateError as e:
        raise HTTPException(
            status_code=409,
            detail={"error": "invalid_state", "message": str(e)},
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=403,
            detail={"error": "permission_denied", "message": str(e)},
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail={"error": "bad_request", "message": str(e)}
        )

    return {"result": asdict(result)}


def _build_proposal_pipeline():
    """Build a :class:`ProposalPipeline`-like facade over the auth DB.

    For M3, we bypass the MemoryPool dependency by using the same stub
    pattern as the T4S.1 tests (_StubPipeline).  Keeps the HTTP layer
    hermetic and avoids pulling in dream-agent modules.
    """
    from autoservice.proposal_pipeline import ProposalPipeline, apply_schema

    conn = _get_op_db()
    apply_schema(conn)  # idempotent — ensures proposals + proposal_audit ready

    # Thin facade: mimics the minimum ProposalPipeline surface apply_proposal
    # expects (_conn, get_proposal, _mark_applied_internal).  This is
    # intentionally a local lightweight helper — not a registered singleton.
    class _HttpPipeline(ProposalPipeline):
        def __init__(self, conn_):
            self._memory_pool = None
            self._analyzer = None
            self._compliance_engine = None
            self._batch_size = 10
            self._conn = conn_
            self._conn.row_factory = __import__("sqlite3").Row

    return _HttpPipeline(conn)


def _operator_to_dict(op: operators.Operator | None) -> dict:
    if op is None:
        return {}
    return {
        "id": op.id,
        "tenant_id": op.tenant_id,
        "email": op.email,
        "display_name": op.display_name,
        "role": op.role,
        "status": op.status,
        "created_at": op.created_at,
        "created_by": op.created_by,
    }
