"""T2B.1 — migration tests for the ``proposals.tenant_id`` column.

Spec: docs/superpowers/specs/2026-04-20-tenant-sandbox-m2-design.md §2.4

Guarantees covered:
  * Fresh DBs created via ``apply_schema`` expose a ``tenant_id`` column.
  * Legacy (M1-shape) DBs are migrated non-destructively; existing rows are
    backfilled to ``'_master'``.
  * ``apply_schema`` is idempotent — running it twice is a safe no-op.
  * ``_store_proposal`` respects an explicit ``tenant_id`` on the proposal
    dict and writes it through to the SQLite row.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from autoservice import proposal_pipeline
from autoservice.proposal_pipeline import ProposalPipeline, apply_schema


# ── helpers ────────────────────────────────────────────────────────────────

_LEGACY_SCHEMA = """
CREATE TABLE proposals (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    category TEXT
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(proposals)").fetchall()}


class _StubMemoryPool:
    """Minimal stand-in for ``MemoryPool`` — we only need ``_conn``.

    ``ProposalPipeline.__init__`` reuses ``memory_pool._conn`` when
    ``db_path`` is not provided; for tests we explicitly pass ``db_path``
    instead, so this stub is only a placeholder for the constructor
    signature.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_conversations_in_range(self, *_a, **_kw) -> list[str]:  # pragma: no cover
        return []

    def get_conversation(self, _cid: str) -> list[dict]:  # pragma: no cover
        return []


# ── tests ──────────────────────────────────────────────────────────────────


def test_fresh_db_has_tenant_id_column(tmp_path):
    """A freshly-created proposals DB must already carry the ``tenant_id`` column."""
    db_path = tmp_path / "proposals.db"
    conn = _connect(db_path)

    apply_schema(conn)

    cols = _columns(conn)
    assert "tenant_id" in cols, f"tenant_id missing from fresh DB (cols={cols})"
    # Sanity: the rest of the legacy columns still present.
    assert {"id", "created_at", "data", "status", "category"}.issubset(cols)
    conn.close()


def test_migration_upgrades_legacy_db(tmp_path):
    """An M1-shape table with existing rows should be migrated without data loss."""
    db_path = tmp_path / "legacy.db"

    # 1. Build an M1 legacy DB with one row and no tenant_id.
    conn = _connect(db_path)
    conn.executescript(_LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO proposals (id, created_at, data, status, category) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            "p_legacy",
            "2026-04-19T00:00:00+00:00",
            json.dumps({"id": "p_legacy", "title": "legacy row"}),
            "draft",
            "response_quality",
        ),
    )
    conn.commit()
    # Pre-migration: tenant_id must NOT yet exist.
    assert "tenant_id" not in _columns(conn)
    conn.close()

    # 2. Run the migration.
    conn = _connect(db_path)
    apply_schema(conn)

    # 3. Column exists, row preserved, tenant_id backfilled.
    cols = _columns(conn)
    assert "tenant_id" in cols

    rows = conn.execute(
        "SELECT id, tenant_id FROM proposals WHERE id = ?", ("p_legacy",)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == "p_legacy"
    assert rows[0]["tenant_id"] == "_master"
    conn.close()


def test_migration_idempotent(tmp_path):
    """Running the migration twice must not raise and must leave the schema stable."""
    db_path = tmp_path / "idempotent.db"

    conn = _connect(db_path)
    apply_schema(conn)
    cols_first = _columns(conn)
    conn.close()

    # Second pass on a fresh connection — should be a complete no-op.
    conn = _connect(db_path)
    apply_schema(conn)  # must not raise
    cols_second = _columns(conn)
    assert cols_first == cols_second
    assert "tenant_id" in cols_second

    # Third pass on the same already-migrated DB — again, no errors.
    apply_schema(conn)
    assert _columns(conn) == cols_second
    conn.close()


def test_insert_respects_tenant_id(tmp_path):
    """An explicit ``tenant_id`` on the proposal dict must be persisted to SQLite."""
    db_path = tmp_path / "insert.db"
    # Pre-create the schema on a shared DB so ProposalPipeline can attach.
    seed_conn = _connect(db_path)
    apply_schema(seed_conn)
    seed_conn.close()

    mp = _StubMemoryPool(_connect(tmp_path / "unused_mp.db"))
    pipeline = ProposalPipeline(memory_pool=mp, db_path=str(db_path))

    analysis = {
        "category": "response_quality",
        "title": "Acme-only finding",
        "description": "Observed in acme tenant traffic.",
        "suggestion": "Tighten the greeting.",
        "evidence": ["customer said hi"],
    }
    proposal = pipeline.create_proposal(
        analysis, source_conversations=["conv_acme_1"], tenant_id="acme"
    )
    assert proposal["tenant_id"] == "acme"

    pipeline._store_proposal(proposal)

    # Read back via the pipeline's connection.
    row = pipeline._conn.execute(
        "SELECT id, tenant_id, category FROM proposals WHERE id = ?",
        (proposal["id"],),
    ).fetchone()
    assert row is not None
    assert row["tenant_id"] == "acme"
    assert row["category"] == "response_quality"

    # And the JSON blob round-trips the tenant_id too.
    round_tripped = pipeline.get_proposal(proposal["id"])
    assert round_tripped is not None
    assert round_tripped["tenant_id"] == "acme"


def test_default_tenant_id_is_master(tmp_path):
    """Callers that omit ``tenant_id`` must get the ``_master`` default,
    preserving M1 behaviour end-to-end."""
    db_path = tmp_path / "default.db"
    apply_schema(_connect(db_path))

    mp = _StubMemoryPool(_connect(tmp_path / "unused_mp.db"))
    pipeline = ProposalPipeline(memory_pool=mp, db_path=str(db_path))

    analysis = {
        "category": "tone",
        "title": "Default tenant",
        "description": "",
        "suggestion": "",
        "evidence": [],
    }
    proposal = pipeline.create_proposal(analysis, source_conversations=["c1"])
    assert proposal["tenant_id"] == "_master"

    pipeline._store_proposal(proposal)
    row = pipeline._conn.execute(
        "SELECT tenant_id FROM proposals WHERE id = ?", (proposal["id"],)
    ).fetchone()
    assert row["tenant_id"] == "_master"


def test_apply_schema_module_exports():
    """``apply_schema`` must be importable from ``autoservice.proposal_pipeline``."""
    assert callable(proposal_pipeline.apply_schema)
