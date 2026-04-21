"""Magic-link auth — sessions, login tokens, and helpers.

T5B.1 / T5B.2 / T5B.3 / T5B.4 · 2026-04-21

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §5.

Two SQLite tables colocated under ``.autoservice/database/auth.db``:

* ``login_tokens`` — short-TTL (10 min default), single-use magic-link tokens
  emitted by ``POST /api/auth/request-login`` and burned by
  ``GET /api/auth/verify``.
* ``sessions`` — long-TTL (30 day default) HttpOnly cookie sessions created on
  successful verify and revoked by ``POST /api/auth/logout``.

Design notes / invariants:

* Following the ``autoservice.dream_runs`` pattern, every repository function
  takes an **explicit** :class:`sqlite3.Connection`.  No hidden singleton.  Tests
  use an in-memory connection; production opens the default path via
  :func:`open_connection`.
* ``consume_login_token`` is the *only* path that sets ``consumed_at``; the
  UPDATE's WHERE clause includes ``consumed_at IS NULL AND expires_at > now`` so
  a concurrent double-verify cannot mint two sessions from one token (spec §5.2
  "一次性消费" red line).
* Expired tokens are *not* burned — ``consume_login_token`` returns ``None`` but
  leaves ``consumed_at`` NULL so operators debugging expiry bugs can distinguish
  "expired" from "used".
* ``tenant_id`` is nullable — ``_master`` (tier 0) sessions have NULL tenant_id.
* Tokens: ``secrets.token_urlsafe(24)``.  Session ids: ``secrets.token_urlsafe(36)``.
  Both are URL-safe and high-entropy (spec §5.7).
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from fastapi import HTTPException, Request

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_DB_PATH = PROJECT_ROOT / ".autoservice" / "database" / "auth.db"


# Default TTLs per spec §5.1.  Callers can override at the call site for tests.
DEFAULT_LOGIN_TOKEN_TTL_MIN = 10
DEFAULT_SESSION_TTL_DAYS = 30


SCHEMA = """\
CREATE TABLE IF NOT EXISTS login_tokens (
    token        TEXT PRIMARY KEY,
    admin_email  TEXT NOT NULL,
    tenant_id    TEXT,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    consumed_at  TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    admin_email  TEXT NOT NULL,
    tenant_id    TEXT,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    revoked_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_login_tokens_email
    ON login_tokens(admin_email, expires_at);

CREATE INDEX IF NOT EXISTS idx_sessions_email
    ON sessions(admin_email, expires_at);
"""


# ──────────────────────────────────────────────────────────────────────────
# Schema / connection helpers
# ──────────────────────────────────────────────────────────────────────────


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create the ``login_tokens`` and ``sessions`` tables (+ indexes).

    Idempotent — safe to call repeatedly on the same connection.
    """
    conn.executescript(SCHEMA)
    conn.commit()


def open_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a :class:`sqlite3.Connection` for the auth DB, applying schema.

    If *db_path* is ``None`` the default location
    ``.autoservice/database/auth.db`` (relative to project root) is used.  The
    parent directory is created if missing.  Row factory is ``sqlite3.Row`` for
    dict-like access.
    """
    path = db_path or _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    apply_schema(conn)
    return conn


# ──────────────────────────────────────────────────────────────────────────
# Login tokens
# ──────────────────────────────────────────────────────────────────────────


def issue_login_token(
    conn: sqlite3.Connection,
    admin_email: str,
    tenant_id: str | None = None,
    ttl_min: int = DEFAULT_LOGIN_TOKEN_TTL_MIN,
    *,
    now: datetime | None = None,
) -> str:
    """Emit a fresh single-use login token for *admin_email* and persist it.

    Returns the token string.  The caller is responsible for deciding who sees
    it (email send / dev log).  Duplicate calls create distinct tokens — M2
    does not rate-limit (spec §5.7 defers to M3).
    """
    created = _coerce_now(now)
    expires = created + timedelta(minutes=ttl_min)
    token = secrets.token_urlsafe(24)
    conn.execute(
        """INSERT INTO login_tokens
             (token, admin_email, tenant_id, created_at, expires_at, consumed_at)
           VALUES (?, ?, ?, ?, ?, NULL)""",
        (token, admin_email, tenant_id, created.isoformat(), expires.isoformat()),
    )
    conn.commit()
    return token


def consume_login_token(
    conn: sqlite3.Connection,
    token: str,
    now: datetime | None = None,
) -> tuple[str, str | None] | None:
    """Atomically burn *token* and return ``(admin_email, tenant_id)`` on success.

    Returns ``None`` for any failure mode (unknown / already consumed / expired).

    The UPDATE guards on ``consumed_at IS NULL`` AND ``expires_at > now`` inside
    a single statement so a concurrent double-verify cannot both succeed.
    Expired tokens are *not* burned — a subsequent lookup can still see
    ``consumed_at IS NULL`` (intentional for debugging; spec §5.2).
    """
    now_dt = _coerce_now(now)
    now_iso = now_dt.isoformat()

    # Atomic burn: only tokens that are un-consumed AND un-expired advance.
    cur = conn.execute(
        """UPDATE login_tokens
              SET consumed_at = ?
            WHERE token = ?
              AND consumed_at IS NULL
              AND expires_at > ?""",
        (now_iso, token, now_iso),
    )
    if cur.rowcount == 0:
        conn.commit()  # no-op but release any write lock
        return None

    row = conn.execute(
        "SELECT admin_email, tenant_id FROM login_tokens WHERE token = ?",
        (token,),
    ).fetchone()
    conn.commit()
    if row is None:  # pragma: no cover — rowcount said we updated 1 row
        return None
    return (row["admin_email"], row["tenant_id"])


# ──────────────────────────────────────────────────────────────────────────
# Sessions
# ──────────────────────────────────────────────────────────────────────────


def create_session(
    conn: sqlite3.Connection,
    admin_email: str,
    tenant_id: str | None = None,
    ttl_days: int = DEFAULT_SESSION_TTL_DAYS,
    *,
    now: datetime | None = None,
) -> str:
    """Create a new session row and return the session id (cookie value).

    The id is ``secrets.token_urlsafe(36)`` (spec §5.7).
    """
    created = _coerce_now(now)
    expires = created + timedelta(days=ttl_days)
    session_id = secrets.token_urlsafe(36)
    conn.execute(
        """INSERT INTO sessions
             (session_id, admin_email, tenant_id, created_at, expires_at, revoked_at)
           VALUES (?, ?, ?, ?, ?, NULL)""",
        (
            session_id,
            admin_email,
            tenant_id,
            created.isoformat(),
            expires.isoformat(),
        ),
    )
    conn.commit()
    return session_id


def lookup_session(
    conn: sqlite3.Connection,
    session_id: str,
    now: datetime | None = None,
) -> dict | None:
    """Return a live session's core fields, or ``None``.

    A session is "live" when it exists, has not been revoked, and has not
    expired.  The returned dict contains ``admin_email``, ``tenant_id`` and
    ``expires_at`` — enough for the middleware to populate ``request.state``.
    """
    now_iso = _coerce_now(now).isoformat()
    row = conn.execute(
        """SELECT admin_email, tenant_id, expires_at
             FROM sessions
            WHERE session_id = ?
              AND revoked_at IS NULL
              AND expires_at > ?""",
        (session_id, now_iso),
    ).fetchone()
    if row is None:
        return None
    return {
        "admin_email": row["admin_email"],
        "tenant_id": row["tenant_id"],
        "expires_at": row["expires_at"],
    }


def revoke_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    now: datetime | None = None,
) -> None:
    """Mark *session_id* revoked.

    Idempotent — calling on a missing or already-revoked session is a no-op.
    """
    now_iso = _coerce_now(now).isoformat()
    conn.execute(
        """UPDATE sessions
              SET revoked_at = ?
            WHERE session_id = ?
              AND revoked_at IS NULL""",
        (now_iso, session_id),
    )
    conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────


def _coerce_now(now: datetime | None) -> datetime:
    """Return *now* if provided, else current UTC time.

    Tests pass explicit ``now`` so expiry / TTL logic is deterministic.
    """
    if now is None:
        return datetime.now(tz=timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now


# ──────────────────────────────────────────────────────────────────────────
# Middleware — require_tenant_access (T5B.5)
# ──────────────────────────────────────────────────────────────────────────
#
# Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §5.3 + §5.4.
#
# Rules applied in order:
#   1. No / invalid session cookie → 401 {"error": "unauthenticated"}.
#   2. Session.tenant_id IS NULL (tier-0 / _master / _local_admin internal admin)
#      → bypass: allow any target.
#   3. Session.tenant_id == target_tenant_id → allow.
#   4. target_tenant_id starts with INTERNAL_TENANT_PREFIX ("_") → allow.  This
#      is how a tier-1 fork admin reaches ``_local_admin`` in ChatTab.
#   5. Otherwise → 403 {"error": "cross-tenant access denied"}.

INTERNAL_TENANT_PREFIX = "_"

# Cookie name — kept in sync with ``autoservice.api_routes.AUTH_SESSION_COOKIE``.
# Spec §5.2 uses ``adm_s``; batch-7 picked the more-readable ``auth_session``.
# The frontend AuthGate (T6F.2) will read this same value — no callers yet
# depend on ``adm_s``, so the rename cost is deferred.
AUTH_SESSION_COOKIE_NAME = "auth_session"


@dataclass(frozen=True)
class AuthContext:
    """Session-derived context passed to route handlers.

    Attributes:
        admin_email: The admin's email address from the session row.
        tenant_id:   The session's tenant scope; ``None`` for tier-0 sessions
                     (``_master`` / ``_local_admin`` internal admins).
        tier:        0 when ``tenant_id is None``, else 1.  M2 does not use
                     tier 2 (subtenant reserved per CON-05).
    """

    admin_email: str
    tenant_id: str | None
    tier: int


def _tier_of(session_tenant_id: str | None) -> int:
    """Derive tier from a session row's ``tenant_id``.

    NULL → 0 (tier-0 reserved per CON-05).  Non-NULL → 1.  M2 never returns
    2 (subtenant reserved).
    """
    return 0 if session_tenant_id is None else 1


def _extract_target_tenant_id(request) -> str | None:
    """Read ``tenant_id`` from the request's path params or query string.

    Route handlers may embed the target tenant in either the path
    (``/something/{tenant_id}``) or the query string.  We check both in
    that order; if neither is present the caller is treated as
    auth-only (no scope check) and the middleware simply returns the
    session's own context.
    """
    path = getattr(request, "path_params", None) or {}
    tid = path.get("tenant_id")
    if tid:
        return str(tid)
    qp = request.query_params.get("tenant_id") if hasattr(request, "query_params") else None
    if qp:
        return str(qp)
    return None


def _enforce_scope(
    session: dict,
    target_tenant_id: str | None,
) -> AuthContext:
    """Apply the §5.3 scoping rules to a live session + optional target.

    Returns an :class:`AuthContext` when access is granted; raises
    :class:`fastapi.HTTPException` with a documented payload otherwise.
    """
    session_tid = session["tenant_id"]
    ctx = AuthContext(
        admin_email=session["admin_email"],
        tenant_id=session_tid,
        tier=_tier_of(session_tid),
    )

    # Rule 1 (no target): nothing to check beyond authentication.
    if target_tenant_id is None:
        return ctx

    # Rule 2: tier-0 bypass — internal admins can touch any tenant.
    if session_tid is None:
        return ctx

    # Rule 3: same-tenant self-service.
    if target_tenant_id == session_tid:
        return ctx

    # Rule 4: deployment-internal tenants (underscore-prefixed) are
    # reachable by any authenticated admin — spec §5.3 Rule 3.
    if target_tenant_id.startswith(INTERNAL_TENANT_PREFIX):
        return ctx

    # Rule 5: everything else is cross-tenant → deny.
    raise HTTPException(
        status_code=403,
        detail={"error": "cross-tenant access denied"},
    )


def _load_session_from_request(
    request: Request,
    conn_factory: Callable[[], sqlite3.Connection] | None,
    now: datetime | None,
) -> dict:
    """Shared prologue — read cookie, lookup session, 401 on any miss.

    Raises ``HTTPException(401)`` with the documented ``{"error":
    "unauthenticated"}`` detail for any of: missing cookie, unknown
    session id, revoked session, expired session.  Returns the live
    session row dict otherwise.
    """
    sid = request.cookies.get(AUTH_SESSION_COOKIE_NAME)
    if not sid:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthenticated"},
        )

    if conn_factory is None:
        # Defer the import so ``auth.py`` stays free of a circular
        # dependency on ``api_routes`` at module-load time.
        from autoservice import api_routes
        conn = api_routes._get_auth_db()
    else:
        conn = conn_factory()

    session = lookup_session(conn, sid, now=now)
    if session is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthenticated"},
        )
    return session


def require_tenant_access(request: Request) -> AuthContext:
    """FastAPI dependency: enforce authenticated + in-scope session.

    Typical usage::

        @router.get("/admin/{tenant_id}/proposals")
        async def list_props(
            tenant_id: str,
            ctx: AuthContext = Depends(auth.require_tenant_access),
        ):
            ...

    The target ``tenant_id`` is lifted from ``request.path_params``
    (or the query string).  When neither is present the dependency acts
    as an auth-only check — returns the session's own context.  For
    routes where the target is known at route-definition time use
    :func:`require_tenant_access_for` instead.

    Raises:
        HTTPException(401): missing / unknown / expired / revoked session.
        HTTPException(403): session exists but does not cover the target tenant.

    Side effect: ``request.state.auth`` is set to the returned
    :class:`AuthContext` so downstream code can read it without
    re-querying.
    """
    session = _load_session_from_request(request, conn_factory=None, now=None)
    target = _extract_target_tenant_id(request)
    ctx = _enforce_scope(session, target)
    try:
        request.state.auth = ctx
    except Exception:  # pragma: no cover
        pass
    return ctx


def require_tenant_access_for(
    target_tenant_id: str,
) -> Callable[[Request], AuthContext]:
    """Factory: return a ``Depends``-compatible helper that checks a static tenant.

    Use when the tenant id is known at route definition time (not in the
    path).  Example::

        @router.get("/admin/proposals")
        async def list_props(
            ctx: AuthContext = Depends(auth.require_tenant_access_for("acme")),
        ):
            ...
    """

    def _dep(request: Request) -> AuthContext:
        session = _load_session_from_request(request, conn_factory=None, now=None)
        ctx = _enforce_scope(session, target_tenant_id)
        try:
            request.state.auth = ctx
        except Exception:  # pragma: no cover
            pass
        return ctx

    _dep.__name__ = f"require_tenant_access_for[{target_tenant_id}]"
    return _dep
