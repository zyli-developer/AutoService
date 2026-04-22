"""Unified KB store — single write path for wizard upload + CLI ingestion.

One class, two callers:
  - autoservice/onboarding.py:/api/onboard/upload  → KBStore(sandbox/<tid>/kb/kb.db)
  - skills/knowledge-base/scripts/kb_ingest.py     → KBStore(.autoservice/database/knowledge_base/kb.db)

Schema is the richer 13-column form (mirrors kb_ingest) so the two code
paths produce identical row layouts. FTS5 uses the trigram tokenizer so
CJK substring queries work without a Chinese segmenter — a limitation
unicode61 could not overcome for customer-facing Chinese chat.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

CHUNK_MAX_CHARS = 600
CHUNK_MIN_CHARS = 50


class KBStore:
    """Thin wrapper around a per-KB SQLite FTS5 database."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()
        self._migrate_fts_tokenizer()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "KBStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ── schema ──────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        c = self._conn
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS kb_chunks (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL DEFAULT '',
                source_url TEXT,
                file_path TEXT,
                section TEXT,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        # ALTER TABLE migrations for EVERY column that may be absent on legacy DBs.
        # Two legacy variants to handle:
        #   * onboarding._init_sandbox_kb (pre-refactor) created only
        #     (id, content, source_name, section, domain, created_at) — missing 7 cols.
        #   * kb_ingest.init_db originally had the 9 CREATE TABLE columns above but
        #     lacked domain/region/language/page_number, which it added later via a
        #     similar ALTER loop. Reproducing the full set here lets KBStore open
        #     either legacy file and reach the unified 13-col shape.
        # On fresh DBs, CREATE TABLE already added all 13, so every ALTER below
        # raises "duplicate column name" and is silently skipped.
        for col_def in [
            "source_id TEXT NOT NULL DEFAULT ''",
            "source_type TEXT NOT NULL DEFAULT ''",
            "source_url TEXT",
            "file_path TEXT",
            "domain TEXT DEFAULT ''",
            "region TEXT DEFAULT ''",
            "language TEXT DEFAULT 'en'",
            "page_number INTEGER",
        ]:
            try:
                c.execute(f"ALTER TABLE kb_chunks ADD COLUMN {col_def}")
            except sqlite3.OperationalError as e:
                # Only expected error here is the idempotent no-op when the column
                # already exists (fresh DB from CREATE, or previously migrated).
                # Anything else (I/O error, lock, SQL typo in col_def) should bubble.
                if "duplicate column name" not in str(e).lower():
                    raise
        c.execute("CREATE INDEX IF NOT EXISTS idx_kb_source_id ON kb_chunks(source_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_kb_domain ON kb_chunks(domain)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_kb_region ON kb_chunks(region)")
        c.commit()

    def _migrate_fts_tokenizer(self) -> None:
        """If kb_fts exists with a non-trigram tokenizer, drop & recreate.

        SQLite ≥ 3.34 supports the trigram tokenizer. We rebuild rather than
        migrate in place because there is no DDL to change an FTS5 tokenizer.
        The content table (kb_chunks) is untouched — only the virtual index
        and its triggers are recreated, then repopulated via rebuild().
        """
        c = self._conn
        existing = c.execute(
            "SELECT sql FROM sqlite_master WHERE name='kb_fts'"
        ).fetchone()
        if existing and "trigram" in (existing[0] or ""):
            return  # already trigram

        if existing:
            c.execute("DROP TRIGGER IF EXISTS kb_ai")
            c.execute("DROP TRIGGER IF EXISTS kb_ad")
            c.execute("DROP TABLE kb_fts")

        # NOTE: FTS has NO chunk_id column. External-content FTS (content=kb_chunks)
        # requires every FTS column to exist in the content table; kb_chunks' PK is
        # `id`, not `chunk_id`. Callers join search results by rowid instead.
        # Dropping chunk_id also lets `INSERT INTO kb_fts(kb_fts) VALUES('rebuild')`
        # succeed — with chunk_id present, rebuild errors with "SQL logic error".
        c.execute(
            """
            CREATE VIRTUAL TABLE kb_fts USING fts5(
                source_name,
                section,
                content,
                content=kb_chunks,
                content_rowid=rowid,
                tokenize="trigram"
            )
            """
        )
        c.execute(
            """
            CREATE TRIGGER kb_ai AFTER INSERT ON kb_chunks BEGIN
                INSERT INTO kb_fts(rowid, source_name, section, content)
                VALUES (new.rowid, new.source_name, new.section, new.content);
            END
            """
        )
        c.execute(
            """
            CREATE TRIGGER kb_ad AFTER DELETE ON kb_chunks BEGIN
                INSERT INTO kb_fts(kb_fts, rowid, source_name, section, content)
                VALUES ('delete', old.rowid, old.source_name, old.section, old.content);
            END
            """
        )
        # Populate FTS index from existing kb_chunks (no-op on empty DBs).
        c.execute("INSERT INTO kb_fts(kb_fts) VALUES('rebuild')")
        c.commit()

    # ── writes ─────────────────────────────────────────────────────────

    def save_chunk(self, chunk: dict, *, debug_dir: Path | None = None) -> None:
        """Insert-or-replace one chunk row; FTS is kept in sync via trigger."""
        c = self._conn
        c.execute(
            """
            INSERT OR REPLACE INTO kb_chunks
                (id, source_id, source_type, source_name, source_url, file_path,
                 section, content, created_at, domain, region, language, page_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk["id"], chunk.get("source_id", ""), chunk.get("source_type", ""),
                chunk.get("source_name", ""), chunk.get("source_url"),
                chunk.get("file_path"), chunk.get("section", ""),
                chunk["content"], chunk["created_at"],
                chunk.get("domain", ""), chunk.get("region", ""),
                chunk.get("language", "en"), chunk.get("page_number"),
            ),
        )
        c.commit()
        if debug_dir is not None:
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / f"{chunk['id']}.json").write_text(
                json.dumps(chunk, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def save_chunks(
        self,
        chunks: Iterable[dict],
        *,
        debug_dir: Path | None = None,
    ) -> int:
        """Insert-or-replace many chunks as a single SQLite transaction.

        Much faster than calling :meth:`save_chunk` in a loop because there is
        exactly one commit (and thus one WAL fsync) for the whole batch. On any
        per-chunk error, rolls back the whole batch — partial batch state never
        lands. Returns the number of rows written.
        """
        chunks_list = list(chunks)
        c = self._conn
        try:
            for chunk in chunks_list:
                c.execute(
                    """
                    INSERT OR REPLACE INTO kb_chunks
                        (id, source_id, source_type, source_name, source_url, file_path,
                         section, content, created_at, domain, region, language, page_number)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk["id"], chunk.get("source_id", ""), chunk.get("source_type", ""),
                        chunk.get("source_name", ""), chunk.get("source_url"),
                        chunk.get("file_path"), chunk.get("section", ""),
                        chunk["content"], chunk["created_at"],
                        chunk.get("domain", ""), chunk.get("region", ""),
                        chunk.get("language", "en"), chunk.get("page_number"),
                    ),
                )
                if debug_dir is not None:
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    (debug_dir / f"{chunk['id']}.json").write_text(
                        json.dumps(chunk, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
            c.commit()
        except Exception:
            c.rollback()
            raise
        return len(chunks_list)

    def clear_source(self, source_id: str) -> int:
        """Remove all chunks for a given source_id (for idempotent re-ingest).

        Returns the number of rows deleted.
        """
        cur = self._conn.execute(
            "DELETE FROM kb_chunks WHERE source_id = ?", (source_id,),
        )
        self._conn.commit()
        return cur.rowcount

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0]

    def by_source(self) -> dict[str, int]:
        return dict(
            self._conn.execute(
                "SELECT source_id, COUNT(*) FROM kb_chunks GROUP BY source_id"
            ).fetchall()
        )
