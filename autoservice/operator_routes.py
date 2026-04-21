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

import logging
import sqlite3
from typing import Any

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


# ──────────────────────────────────────────────────────────────────────────
# Shared DB handle (test-overridable)
# ──────────────────────────────────────────────────────────────────────────

_op_db_conn: sqlite3.Connection | None = None


def _get_op_db() -> sqlite3.Connection:
    """Return the shared operator-DB connection (lazy singleton).

    Uses the same ``auth.db`` file as admin auth (contract §2 DB location).
    Ensures operators + operator_sessions tables and migration applied.
    """
    global _op_db_conn
    if _op_db_conn is None:
        conn = auth.open_connection()
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
