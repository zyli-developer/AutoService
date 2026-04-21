"""RBAC — coarse-grained 3-tier permission matrix (M3 T2S.1).

Contract: docs/contracts/m3/e1-auth-rbac.md §5.

Design invariants:
- Roles are ``viewer | responder | admin`` (strictly 3-tier per CON-02)
- PERMISSIONS matrix is HARDCODED in this module — NOT runtime config (CON-02)
- check() is O(1) frozenset lookup — NFR-02 requires P95 decision < 5ms
- FastAPI dependency :func:`require` gates routes; returns a dependency
  function (not a decorator) so it composes with other Depends()
- Role extraction order per request:
    1. operator_session cookie → operators.role (if live)
    2. auth_session cookie → always 'admin' (tenant_admin sessions are admin-tier)
    3. Neither → 401
- Tier-0 sessions (platform admin, tenant_id=NULL) bypass tenant scope but still
  carry role='admin' — they can do anything in the matrix
"""
from __future__ import annotations

import sqlite3
from typing import Literal

import logging

from fastapi import HTTPException, Request

from autoservice import auth, operator_routes, operators

logger = logging.getLogger("autoservice.rbac")


RoleT = Literal["viewer", "responder", "admin"]


# ──────────────────────────────────────────────────────────────────────────
# Permission matrix (contract §5)
# ──────────────────────────────────────────────────────────────────────────
#
# A single frozenset of (role, action) tuples.  Membership test is O(1) on
# CPython's set.  Benchmarked at <1µs per check in CI — well under NFR-02's
# 5ms P95 budget even for request-hot paths.

PERMISSIONS: frozenset[tuple[str, str]] = frozenset({
    # --- read-only actions: everyone can observe own tenant ---
    ("viewer", "view_conversations"),
    ("responder", "view_conversations"),
    ("admin", "view_conversations"),

    ("viewer", "view_sla_dashboard"),
    ("responder", "view_sla_dashboard"),
    ("admin", "view_sla_dashboard"),

    ("responder", "view_compliance_scan"),
    ("admin", "view_compliance_scan"),

    # --- operator conversational actions: responder + admin ---
    ("responder", "send_copilot_suggestion"),
    ("admin", "send_copilot_suggestion"),

    ("responder", "hijack"),
    ("admin", "hijack"),

    ("responder", "release"),
    ("admin", "release"),

    # --- admin-only tenant management ---
    ("admin", "crud_operators"),
    ("admin", "send_invites"),
    ("admin", "edit_classify_intent"),
    ("admin", "approve_proposal"),
    ("admin", "reject_proposal"),
    ("admin", "apply_proposal"),
    ("admin", "edit_tenant_config"),
})


# Canonical action name registry — exported for discoverability / doc generation.
ACTIONS: frozenset[str] = frozenset({
    action for (_role, action) in PERMISSIONS
})


def check(role: str, action: str) -> bool:
    """Return True if *role* is permitted to perform *action*.

    O(1) frozenset lookup.  Unknown role / unknown action → False.
    No exceptions raised — plain boolean for composition in hot paths.
    """
    return (role, action) in PERMISSIONS


# ──────────────────────────────────────────────────────────────────────────
# FastAPI dependency factory
# ──────────────────────────────────────────────────────────────────────────


def _extract_role_and_context(
    request: Request,
) -> tuple[str, dict]:
    """Resolve caller's role + session context.  Raises HTTPException on fail.

    Order:
        1. operator_session cookie → operators.lookup_operator_session
           (role comes from operators.role column; tenant_id from session row)
        2. auth_session cookie → auth.lookup_session (role='admin' implicit)

    Caches the resolution on ``request.state.rbac_ctx`` so repeated ``require()``
    dependencies in the same request make exactly one DB lookup.

    Returns ``(role, ctx)`` where ctx has keys ``tenant_id``, ``actor_id``,
    ``actor_kind`` ('operator' | 'admin').
    """
    # Per-request cache (NFR-02: many-Depends-per-route must not re-query DB)
    cached = getattr(request.state, "rbac_ctx", None)
    if cached is not None:
        return cached["role"], cached

    op_cookie = request.cookies.get(operators.OPERATOR_SESSION_COOKIE_NAME)
    auth_cookie = request.cookies.get(auth.AUTH_SESSION_COOKIE_NAME)

    # Reviewer finding C2 (2026-04-21): log when both cookies are present
    # so privilege-confusion attempts are observable in audit logs.  Operator
    # cookie wins by precedence below (least-privilege-first).
    if op_cookie and auth_cookie:
        logger.warning(
            "rbac: client sent BOTH operator_session + auth_session cookies "
            "— using operator path (least-privilege-first). "
            "Review client behaviour; operators should not hold admin sessions."
        )

    # Shared DB handle — note that operator_routes._get_op_db() applies BOTH
    # auth.apply_schema + operators.apply_operators_schema on init (see
    # operator_routes.py:63).  Both admin login_tokens/sessions and operator
    # tables live in .autoservice/database/auth.db, so one connection serves
    # both subsystems.  Reviewer finding C1 (2026-04-21): this invariant
    # is load-bearing; if _get_op_db ever drops auth schema application,
    # auth.lookup_session below will fail at runtime.  Test fixture validates.
    if op_cookie:
        conn = operator_routes._get_op_db()
        op_ctx = operators.lookup_operator_session(conn, op_cookie)
        if op_ctx is not None:
            ctx = {
                "role": op_ctx["role"],
                "tenant_id": op_ctx["tenant_id"],
                "actor_id": op_ctx["operator_id"],
                "actor_kind": "operator",
                "email": op_ctx.get("email"),
            }
            request.state.rbac_ctx = ctx
            return ctx["role"], ctx

    if auth_cookie:
        conn = operator_routes._get_op_db()
        session_row = auth.lookup_session(conn, auth_cookie)
        if session_row is not None:
            ctx = {
                "role": "admin",  # tenant_admin / platform_admin both map to admin
                "tenant_id": session_row.get("tenant_id"),
                "actor_id": session_row["admin_email"],
                "actor_kind": "admin",
                "email": session_row["admin_email"],
            }
            request.state.rbac_ctx = ctx
            return ctx["role"], ctx

    raise HTTPException(
        status_code=401, detail={"error": "unauthenticated"}
    )


def require(action: str):
    """FastAPI dependency factory: gate a route on the caller having *action*.

    Usage::

        @router.post("/api/admin/{tenant_id}/operators",
                     dependencies=[Depends(rbac.require("crud_operators"))])
        async def create_operator(...): ...

    Or, to also receive the :class:`RBACContext`::

        ctx: rbac.RBACContext = Depends(rbac.resolve_ctx)
        # then inside handler: rbac.ensure(ctx, "crud_operators")

    On failure: 401 (no session) or 403 (session ok, role insufficient).
    """
    if action not in ACTIONS:
        # Fail loudly at app startup / first-use rather than silently at
        # request time — catches typos in route decorators.
        raise ValueError(
            f"rbac.require({action!r}): unknown action. "
            f"Known: {sorted(ACTIONS)}"
        )

    def dep(request: Request) -> dict:
        role, ctx = _extract_role_and_context(request)
        if not check(role, action):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "permission_denied",
                    "action": action,
                    "role": role,
                },
            )
        return ctx

    dep.__name__ = f"require_{action}"
    return dep


def resolve_ctx(request: Request) -> dict:
    """Dependency that returns the :class:`dict` context without gating on role.

    Useful for handlers that need the caller's identity + tenant but do
    authorization themselves (e.g. custom checks not expressible in the matrix).
    """
    _role, ctx = _extract_role_and_context(request)
    return ctx


def ensure(ctx: dict, action: str) -> None:
    """Programmatic check inside a handler.  Raises 403 on deny."""
    if not check(ctx["role"], action):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "permission_denied",
                "action": action,
                "role": ctx["role"],
            },
        )
