"""DB-backed classify_intent config (M3 T3S.3).

Contract: docs/contracts/m3/e3-triage.md §3.

Migrates the existing ``autoservice/classify_intent.yaml`` from a read-only
module-load-time YAML into a per-tenant SQLite table that admin-portal can
edit (T3S.5) with hot-reload via ``FastClassifier.clear_tenant_cache``
(existing infra at model_router.py:91-114).

Design invariants:
- Per-tenant rows; ``tenant_id='_default'`` seeds from YAML on first run
- 5 intents expected: product_inquiry / complaint / purchase_intent /
  language_barrier / general_question
- Keywords stored as JSON array in TEXT column (SQLite has no native list)
- Migration is idempotent: re-running on a populated table is a no-op
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_TENANT_KEY = "_default"


# ──────────────────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────────────────


SCHEMA = """\
CREATE TABLE IF NOT EXISTS classify_intent_config (
    tenant_id    TEXT NOT NULL,
    intent       TEXT NOT NULL,
    keywords     TEXT NOT NULL,        -- JSON array of strings
    threshold    REAL NOT NULL DEFAULT 0.5,
    model_tier   TEXT NOT NULL CHECK(model_tier IN ('fast', 'slow')),
    route_role   TEXT NOT NULL,        -- AgentRole value
    priority     TEXT NOT NULL DEFAULT 'normal'
                 CHECK(priority IN ('high', 'normal', 'low')),
    description  TEXT,
    updated_at   TEXT NOT NULL,
    updated_by   TEXT,                 -- admin email on last write
    PRIMARY KEY (tenant_id, intent)
);

CREATE INDEX IF NOT EXISTS idx_classify_intent_tenant
    ON classify_intent_config(tenant_id);
"""


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create the ``classify_intent_config`` table (idempotent)."""
    conn.executescript(SCHEMA)
    conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# Dataclass + row mapping
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IntentConfig:
    tenant_id: str
    intent: str
    keywords: list[str]
    threshold: float
    model_tier: str
    route_role: str
    priority: str
    description: str | None
    updated_at: str
    updated_by: str | None


def _row_to_config(row: sqlite3.Row) -> IntentConfig:
    return IntentConfig(
        tenant_id=row["tenant_id"],
        intent=row["intent"],
        keywords=json.loads(row["keywords"]),
        threshold=row["threshold"],
        model_tier=row["model_tier"],
        route_role=row["route_role"],
        priority=row["priority"],
        description=row["description"],
        updated_at=row["updated_at"],
        updated_by=row["updated_by"],
    )


# ──────────────────────────────────────────────────────────────────────────
# Migration from YAML
# ──────────────────────────────────────────────────────────────────────────


_DEFAULT_YAML_PATH = (
    Path(__file__).resolve().parent / "classify_intent.yaml"
)


def seed_defaults_from_yaml(
    conn: sqlite3.Connection,
    yaml_path: Path | None = None,
    *,
    now: str | None = None,
) -> int:
    """Idempotent seed of the ``_default`` tenant from ``classify_intent.yaml``.

    Returns the number of rows inserted (0 if already seeded).

    Invariants:
    * Only writes rows where ``(tenant_id=_default, intent)`` does NOT yet exist.
    * Never overwrites existing rows — admin edits via T3S.4 are preserved.
    * YAML missing → raises FileNotFoundError (fail-loud; don't silently seed empty).
    """
    from datetime import datetime, timezone

    path = yaml_path or _DEFAULT_YAML_PATH
    if not path.exists():
        raise FileNotFoundError(f"classify_intent YAML not found at {path}")

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    intents = data.get("intents") or {}

    ts = now or datetime.now(tz=timezone.utc).isoformat()
    inserted = 0
    for intent_name, cfg in intents.items():
        # Skip if already present (preserves admin overrides)
        existing = conn.execute(
            "SELECT 1 FROM classify_intent_config "
            "WHERE tenant_id = ? AND intent = ?",
            (DEFAULT_TENANT_KEY, intent_name),
        ).fetchone()
        if existing is not None:
            continue

        keywords = cfg.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []

        conn.execute(
            """INSERT INTO classify_intent_config
                 (tenant_id, intent, keywords, threshold, model_tier,
                  route_role, priority, description, updated_at, updated_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
            (
                DEFAULT_TENANT_KEY,
                intent_name,
                json.dumps(keywords, ensure_ascii=False),
                float(cfg.get("threshold", 0.5)),
                cfg.get("model_tier", "fast"),
                cfg.get("route_to", "customer"),
                cfg.get("priority", "normal"),
                cfg.get("description"),
                ts,
            ),
        )
        inserted += 1
    conn.commit()
    return inserted


# ──────────────────────────────────────────────────────────────────────────
# CRUD helpers (used by T3S.4 routes)
# ──────────────────────────────────────────────────────────────────────────


def list_intents(
    conn: sqlite3.Connection, tenant_id: str
) -> list[IntentConfig]:
    """Return tenant's intent configs, with fallback to _default for gaps.

    For a given intent, tenant override (if present) wins over _default.
    Returns union of (tenant-specific intents) ∪ (_default intents not
    overridden by tenant).
    """
    rows = conn.execute(
        "SELECT * FROM classify_intent_config "
        "WHERE tenant_id IN (?, ?) "
        "ORDER BY intent, CASE tenant_id WHEN ? THEN 0 ELSE 1 END",
        (tenant_id, DEFAULT_TENANT_KEY, tenant_id),
    ).fetchall()

    # Dedupe: first row per intent wins (tenant's, since ORDER BY puts it first)
    seen: set[str] = set()
    out: list[IntentConfig] = []
    for r in rows:
        if r["intent"] in seen:
            continue
        seen.add(r["intent"])
        out.append(_row_to_config(r))
    return out


def get_intent(
    conn: sqlite3.Connection, tenant_id: str, intent: str
) -> IntentConfig | None:
    """Return tenant's override (if any) else the _default config."""
    row = conn.execute(
        "SELECT * FROM classify_intent_config "
        "WHERE tenant_id = ? AND intent = ?",
        (tenant_id, intent),
    ).fetchone()
    if row is not None:
        return _row_to_config(row)
    # Fall back to _default
    row = conn.execute(
        "SELECT * FROM classify_intent_config "
        "WHERE tenant_id = ? AND intent = ?",
        (DEFAULT_TENANT_KEY, intent),
    ).fetchone()
    return _row_to_config(row) if row else None


def upsert_intent(
    conn: sqlite3.Connection,
    *,
    tenant_id: str,
    intent: str,
    keywords: list[str],
    threshold: float = 0.5,
    model_tier: str = "fast",
    route_role: str = "customer",
    priority: str = "normal",
    description: str | None = None,
    updated_by: str | None = None,
    now: str | None = None,
) -> IntentConfig:
    """Upsert a per-tenant intent config.  Returns the persisted row."""
    from datetime import datetime, timezone

    if model_tier not in ("fast", "slow"):
        raise ValueError(f"model_tier must be fast|slow, got {model_tier!r}")
    if priority not in ("high", "normal", "low"):
        raise ValueError(
            f"priority must be high|normal|low, got {priority!r}"
        )

    ts = now or datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO classify_intent_config
             (tenant_id, intent, keywords, threshold, model_tier,
              route_role, priority, description, updated_at, updated_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(tenant_id, intent) DO UPDATE SET
             keywords = excluded.keywords,
             threshold = excluded.threshold,
             model_tier = excluded.model_tier,
             route_role = excluded.route_role,
             priority = excluded.priority,
             description = excluded.description,
             updated_at = excluded.updated_at,
             updated_by = excluded.updated_by""",
        (
            tenant_id, intent,
            json.dumps(keywords, ensure_ascii=False),
            threshold, model_tier, route_role, priority,
            description, ts, updated_by,
        ),
    )
    conn.commit()
    return get_intent(conn, tenant_id, intent)  # type: ignore[return-value]


def delete_tenant_override(
    conn: sqlite3.Connection, tenant_id: str, intent: str
) -> bool:
    """Remove a tenant-specific row, restoring the _default.

    Returns True iff a row was deleted.  Never deletes _default rows
    (protective — that would wipe the fallback).
    """
    if tenant_id == DEFAULT_TENANT_KEY:
        raise ValueError(
            f"Cannot delete _default rows via this helper. "
            f"Modify via upsert or reseed from YAML."
        )
    cur = conn.execute(
        "DELETE FROM classify_intent_config "
        "WHERE tenant_id = ? AND intent = ?",
        (tenant_id, intent),
    )
    conn.commit()
    return cur.rowcount > 0
