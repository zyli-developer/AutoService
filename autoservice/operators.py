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

import sqlite3


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
