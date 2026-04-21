"""Operator identity — operators + operator_sessions tables and migrations (M3 T1S.1).

Contract: docs/contracts/m3/e1-auth-rbac.md §2 (Session Storage).

Colocated under ``.autoservice/database/auth.db`` — same DB as
``autoservice.auth`` (admin login_tokens + sessions). M3 adds two new tables
(``operators``, ``operator_sessions``) and migrates the existing
``login_tokens`` table with a ``role`` column to distinguish operator invites
from admin magic-links (CON-08: cookie separation; contract §3.3).

Design notes / invariants:

* Follows the ``autoservice.auth`` pattern — every function takes an explicit
  :class:`sqlite3.Connection`.  No hidden singleton.  Tests use ``:memory:``.
* Schema strings use ``CREATE TABLE IF NOT EXISTS`` so apply is idempotent.
* Migration uses ``PRAGMA table_info`` to detect existing columns before
  ``ALTER TABLE ADD COLUMN`` — also idempotent.  SQLite's ALTER cannot add
  CHECK constraints retroactively, so role-value enforcement lives at the
  application layer (invite-issue path validates before INSERT).
* Timestamps use ISO-8601 TEXT (matches M2 convention in auth.py).
* CRUD helpers + session issuance / lookup land in T1S.2 / T1S.4; this
  module is schema-only so the schema task has a clean blast radius.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from autoservice.auth import _coerce_now


# ──────────────────────────────────────────────────────────────────────────
# Defaults (OQ-E1-2)
# ──────────────────────────────────────────────────────────────────────────

DEFAULT_OPERATOR_SESSION_TTL_HOURS = 24
DEFAULT_OPERATOR_SESSION_IDLE_MIN = 30

OperatorRole = Literal["viewer", "responder", "admin"]
OperatorStatus = Literal["active", "disabled"]


# ──────────────────────────────────────────────────────────────────────────
# Cookie names (CON-08 — MUST be separate from admin session cookie)
# ──────────────────────────────────────────────────────────────────────────

#: Operator session cookie name.  Separate from
#: :data:`autoservice.auth.AUTH_SESSION_COOKIE_NAME` (``auth_session``) to
#: prevent privilege confusion across role boundaries.
OPERATOR_SESSION_COOKIE_NAME = "operator_session"


# ──────────────────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────────────────

OPERATORS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS operators (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    email         TEXT NOT NULL,
    display_name  TEXT,
    role          TEXT NOT NULL CHECK(role IN ('viewer','responder','admin')),
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK(status IN ('active','disabled')),
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    UNIQUE(tenant_id, email)
);

CREATE TABLE IF NOT EXISTS operator_sessions (
    token        TEXT PRIMARY KEY,
    operator_id  TEXT NOT NULL
                 REFERENCES operators(id) ON DELETE CASCADE,
    tenant_id    TEXT NOT NULL,
    issued_at    TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    idle_at      TEXT NOT NULL,
    ip_created   TEXT,
    user_agent   TEXT
);

CREATE INDEX IF NOT EXISTS idx_operators_tenant
    ON operators(tenant_id, email);

CREATE INDEX IF NOT EXISTS idx_operator_sessions_operator
    ON operator_sessions(operator_id);

CREATE INDEX IF NOT EXISTS idx_operator_sessions_idle
    ON operator_sessions(idle_at);
"""


def apply_operators_schema(conn: sqlite3.Connection) -> None:
    """Create ``operators`` + ``operator_sessions`` tables and their indexes.

    Idempotent — safe to call repeatedly on the same connection (uses
    ``CREATE TABLE IF NOT EXISTS``).
    """
    conn.executescript(OPERATORS_SCHEMA)
    conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# login_tokens migration (contract §3.3 — operator invites reuse magic-link
# machinery but need role metadata to route to the right cookie on consume)
# ──────────────────────────────────────────────────────────────────────────


def migrate_login_tokens_add_role(conn: sqlite3.Connection) -> None:
    """Add ``role`` + ``invited_by`` columns to ``login_tokens`` if absent.

    Idempotent — uses ``PRAGMA table_info`` to detect existing columns.

    * ``role``: default ``'tenant_admin'`` so pre-M3 rows retain M2 semantics.
      Expected values are ``'tenant_admin'`` and ``'operator'``, enforced by
      the invite-issue code path (T1S.3 / T1S.5).  SQLite's ``ALTER TABLE``
      cannot attach a CHECK constraint retroactively, so value enforcement
      is application-layer.
    * ``invited_by``: nullable; stores the admin email that initiated the
      invite (contract §3.3).  NULL for self-service / legacy rows.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(login_tokens)")}

    if "role" not in cols:
        conn.execute(
            "ALTER TABLE login_tokens "
            "ADD COLUMN role TEXT NOT NULL DEFAULT 'tenant_admin'"
        )
    if "invited_by" not in cols:
        conn.execute("ALTER TABLE login_tokens ADD COLUMN invited_by TEXT")

    conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# Dataclass
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Operator:
    """Operator record — snapshot of a single ``operators`` row."""

    id: str
    tenant_id: str
    email: str
    display_name: str | None
    role: OperatorRole
    status: OperatorStatus
    created_at: str  # ISO 8601
    created_by: str | None


def _row_to_operator(row: sqlite3.Row) -> Operator:
    return Operator(
        id=row["id"],
        tenant_id=row["tenant_id"],
        email=row["email"],
        display_name=row["display_name"],
        role=row["role"],
        status=row["status"],
        created_at=row["created_at"],
        created_by=row["created_by"],
    )


# ──────────────────────────────────────────────────────────────────────────
# Operator CRUD (T1S.4)
# ──────────────────────────────────────────────────────────────────────────


def create_operator(
    conn: sqlite3.Connection,
    *,
    tenant_id: str,
    email: str,
    role: OperatorRole,
    display_name: str | None = None,
    created_by: str | None = None,
    now: datetime | None = None,
) -> Operator:
    """Insert a new ``operators`` row and return the :class:`Operator`.

    Raises :class:`sqlite3.IntegrityError` if ``(tenant_id, email)`` is not
    unique (contract §2.1 UNIQUE constraint).  ``role`` is application-layer
    validated (CHECK constraint also catches invalid strings).
    """
    if role not in ("viewer", "responder", "admin"):
        raise ValueError(f"role must be viewer|responder|admin, got {role!r}")
    created = _coerce_now(now)
    op_id = secrets.token_urlsafe(16)
    conn.execute(
        """INSERT INTO operators
             (id, tenant_id, email, display_name, role, status, created_at, created_by)
           VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
        (
            op_id,
            tenant_id,
            email.strip().lower(),
            display_name,
            role,
            created.isoformat(),
            created_by,
        ),
    )
    conn.commit()
    return get_operator(conn, op_id)  # type: ignore[return-value]  # just inserted


def get_operator(
    conn: sqlite3.Connection, operator_id: str
) -> Operator | None:
    row = conn.execute(
        "SELECT * FROM operators WHERE id = ?", (operator_id,)
    ).fetchone()
    return _row_to_operator(row) if row else None


def get_operator_by_email(
    conn: sqlite3.Connection, tenant_id: str, email: str
) -> Operator | None:
    """Return operator for (tenant_id, email) or ``None``.

    Email lookup is case-insensitive — the ``operators`` table stores lowercase.
    """
    row = conn.execute(
        "SELECT * FROM operators WHERE tenant_id = ? AND email = ?",
        (tenant_id, email.strip().lower()),
    ).fetchone()
    return _row_to_operator(row) if row else None


def list_operators_by_tenant(
    conn: sqlite3.Connection, tenant_id: str, *, include_disabled: bool = False
) -> list[Operator]:
    if include_disabled:
        rows = conn.execute(
            "SELECT * FROM operators WHERE tenant_id = ? ORDER BY created_at",
            (tenant_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM operators WHERE tenant_id = ? AND status = 'active' "
            "ORDER BY created_at",
            (tenant_id,),
        ).fetchall()
    return [_row_to_operator(r) for r in rows]


def update_operator(
    conn: sqlite3.Connection,
    operator_id: str,
    *,
    role: OperatorRole | None = None,
    status: OperatorStatus | None = None,
    display_name: str | None = None,
) -> Operator | None:
    """Patch operator fields.  Returns updated :class:`Operator` or ``None``.

    Only non-``None`` kwargs are written — pass only what you want to change.
    ``None`` kwargs are ignored (can't set display_name back to NULL this way;
    use an explicit empty string if needed).
    """
    sets: list[str] = []
    params: list[object] = []
    if role is not None:
        if role not in ("viewer", "responder", "admin"):
            raise ValueError(f"role must be viewer|responder|admin, got {role!r}")
        sets.append("role = ?")
        params.append(role)
    if status is not None:
        if status not in ("active", "disabled"):
            raise ValueError(f"status must be active|disabled, got {status!r}")
        sets.append("status = ?")
        params.append(status)
    if display_name is not None:
        sets.append("display_name = ?")
        params.append(display_name)

    if not sets:
        return get_operator(conn, operator_id)

    params.append(operator_id)
    cur = conn.execute(
        f"UPDATE operators SET {', '.join(sets)} WHERE id = ?", params
    )
    conn.commit()
    if cur.rowcount == 0:
        return None
    return get_operator(conn, operator_id)


def delete_operator(conn: sqlite3.Connection, operator_id: str) -> bool:
    """Delete operator.  Returns ``True`` if a row was deleted.

    Cascades to ``operator_sessions`` via the FK's ``ON DELETE CASCADE``
    (schema §operators_schema).
    """
    cur = conn.execute("DELETE FROM operators WHERE id = ?", (operator_id,))
    conn.commit()
    return cur.rowcount > 0


# ──────────────────────────────────────────────────────────────────────────
# Operator sessions (T1S.2)
# ──────────────────────────────────────────────────────────────────────────


def issue_operator_session(
    conn: sqlite3.Connection,
    *,
    operator_id: str,
    tenant_id: str,
    ttl_hours: int = DEFAULT_OPERATOR_SESSION_TTL_HOURS,
    ip_created: str | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> str:
    """Create an ``operator_sessions`` row and return the token (cookie value).

    Token: ``secrets.token_urlsafe(36)`` — 48 chars of URL-safe entropy
    (matches M2 session_id format in auth.create_session).
    """
    issued = _coerce_now(now)
    expires = issued + timedelta(hours=ttl_hours)
    token = secrets.token_urlsafe(36)
    conn.execute(
        """INSERT INTO operator_sessions
             (token, operator_id, tenant_id, issued_at, expires_at, idle_at,
              ip_created, user_agent)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            token,
            operator_id,
            tenant_id,
            issued.isoformat(),
            expires.isoformat(),
            issued.isoformat(),
            ip_created,
            user_agent,
        ),
    )
    conn.commit()
    return token


def lookup_operator_session(
    conn: sqlite3.Connection,
    token: str,
    *,
    idle_timeout_min: int = DEFAULT_OPERATOR_SESSION_IDLE_MIN,
    now: datetime | None = None,
) -> dict | None:
    """Return live session context or ``None``.

    Live means: exists, not expired, and (now - idle_at) ≤ idle_timeout_min.

    Returned dict: ``{operator_id, tenant_id, email, role, expires_at}``
    — enough for middleware to populate ``request.state`` and for ``/me``.
    """
    now_dt = _coerce_now(now)
    now_iso = now_dt.isoformat()
    row = conn.execute(
        """SELECT s.operator_id, s.tenant_id, s.expires_at, s.idle_at,
                  o.email, o.role, o.status
             FROM operator_sessions s
             JOIN operators o ON o.id = s.operator_id
            WHERE s.token = ?
              AND s.expires_at > ?""",
        (token, now_iso),
    ).fetchone()
    if row is None:
        return None
    if row["status"] != "active":
        return None  # operator disabled → session effectively dead

    idle_at = datetime.fromisoformat(row["idle_at"])
    if (now_dt - idle_at) > timedelta(minutes=idle_timeout_min):
        return None  # idle-timed-out

    return {
        "operator_id": row["operator_id"],
        "tenant_id": row["tenant_id"],
        "email": row["email"],
        "role": row["role"],
        "expires_at": row["expires_at"],
    }


def touch_operator_session(
    conn: sqlite3.Connection, token: str, *, now: datetime | None = None
) -> None:
    """Update ``idle_at`` to bump the session's idle-timeout window.

    Called on every inbound WS message / request.  Idempotent on missing
    token (no row → no-op).
    """
    now_iso = _coerce_now(now).isoformat()
    conn.execute(
        "UPDATE operator_sessions SET idle_at = ? WHERE token = ?",
        (now_iso, token),
    )
    conn.commit()


def revoke_operator_session(conn: sqlite3.Connection, token: str) -> None:
    """Delete the session row.  Idempotent on missing token."""
    conn.execute("DELETE FROM operator_sessions WHERE token = ?", (token,))
    conn.commit()


def revoke_all_operator_sessions(
    conn: sqlite3.Connection, operator_id: str
) -> int:
    """Delete all sessions for *operator_id*.  Returns count deleted.

    Called on operator disable / delete as defense-in-depth
    (FK CASCADE also handles the delete path).
    """
    cur = conn.execute(
        "DELETE FROM operator_sessions WHERE operator_id = ?", (operator_id,)
    )
    conn.commit()
    return cur.rowcount


# ──────────────────────────────────────────────────────────────────────────
# Magic-link for operator role (T1S.2 + T1S.5)
# ──────────────────────────────────────────────────────────────────────────


def issue_operator_login_token(
    conn: sqlite3.Connection,
    *,
    operator_email: str,
    tenant_id: str,
    invited_by: str | None = None,
    ttl_min: int = 10,
    now: datetime | None = None,
) -> str:
    """Issue a magic-link token with ``role='operator'`` metadata.

    Wraps :func:`auth.issue_login_token` but writes ``role='operator'`` and
    optional ``invited_by`` for audit.  Used by both login flow (T1S.2) and
    invite flow (T1S.5).
    """
    created = _coerce_now(now)
    expires = created + timedelta(minutes=ttl_min)
    token = secrets.token_urlsafe(24)
    conn.execute(
        """INSERT INTO login_tokens
             (token, admin_email, tenant_id, created_at, expires_at,
              consumed_at, role, invited_by)
           VALUES (?, ?, ?, ?, ?, NULL, 'operator', ?)""",
        (
            token,
            operator_email.strip().lower(),
            tenant_id,
            created.isoformat(),
            expires.isoformat(),
            invited_by,
        ),
    )
    conn.commit()
    return token


def consume_operator_login_token(
    conn: sqlite3.Connection,
    token: str,
    *,
    now: datetime | None = None,
) -> tuple[str, str, str | None] | None:
    """Atomically burn *token* and return ``(email, tenant_id, invited_by)``.

    Returns ``None`` for any failure mode: unknown token, expired, already
    consumed, OR **role mismatch** (token issued for admin cannot authenticate
    as operator).  Role mismatch is a silent ``None`` — do NOT leak which
    failure mode applied.

    Mirrors :func:`auth.consume_login_token` but role-gates the UPDATE
    WHERE clause so an admin magic-link cannot mint an operator session.
    """
    now_iso = _coerce_now(now).isoformat()

    # Atomic burn: token must be un-consumed AND un-expired AND role='operator'.
    cur = conn.execute(
        """UPDATE login_tokens
              SET consumed_at = ?
            WHERE token = ?
              AND consumed_at IS NULL
              AND expires_at > ?
              AND role = 'operator'""",
        (now_iso, token, now_iso),
    )
    if cur.rowcount == 0:
        conn.commit()
        return None

    row = conn.execute(
        "SELECT admin_email, tenant_id, invited_by FROM login_tokens WHERE token = ?",
        (token,),
    ).fetchone()
    conn.commit()
    if row is None:  # pragma: no cover
        return None
    return (row["admin_email"], row["tenant_id"], row["invited_by"])
