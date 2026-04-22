# tests/kb/test_kb_store.py
"""Unit tests for autoservice.kb_core.KBStore."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from autoservice.kb_core import KBStore


class TestInit:
    def test_creates_kb_chunks_with_full_schema(self, tmp_path: Path):
        db = tmp_path / "kb.db"
        store = KBStore(db)
        store.close()

        conn = sqlite3.connect(str(db))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(kb_chunks)")}
        conn.close()

        # All 13 columns from the kb_ingest schema, not the minimal 6 from onboarding.
        assert cols == {
            "id", "source_id", "source_type", "source_name", "source_url",
            "file_path", "section", "content", "created_at",
            "domain", "region", "language", "page_number",
        }

    def test_fts_uses_trigram_tokenizer(self, tmp_path: Path):
        db = tmp_path / "kb.db"
        store = KBStore(db)
        store.close()

        conn = sqlite3.connect(str(db))
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='kb_fts'"
        ).fetchone()[0]
        conn.close()

        assert "tokenize" in sql and "trigram" in sql

    def test_migrates_legacy_unicode61_to_trigram(self, tmp_path: Path):
        """Opening an existing DB with the old unicode61 FTS should rebuild it."""
        db = tmp_path / "kb.db"
        # Create legacy schema (mirrors onboarding._init_sandbox_kb pre-migration)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE kb_chunks (id TEXT PRIMARY KEY, content TEXT NOT NULL, "
            "source_name TEXT, section TEXT, domain TEXT, created_at TEXT)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE kb_fts USING fts5(content, source_name, section, "
            "domain, content=kb_chunks, content_rowid=rowid, "
            "tokenize=\"unicode61 remove_diacritics 1\")"
        )
        conn.execute(
            "INSERT INTO kb_chunks (id, content, source_name, section, domain, created_at) "
            "VALUES ('legacy_1', 'CINNOX 提供什么服务的详细说明', '', '', '', '2026-04-22T00:00:00')"
        )
        # Manually populate FTS (legacy triggers wouldn't exist yet in this bare test)
        conn.execute(
            "INSERT INTO kb_fts(rowid, content, source_name, section, domain) "
            "SELECT rowid, content, source_name, section, domain FROM kb_chunks"
        )
        conn.commit()
        conn.close()

        store = KBStore(db)
        try:
            conn2 = sqlite3.connect(str(db))
            sql = conn2.execute(
                "SELECT sql FROM sqlite_master WHERE name='kb_fts'"
            ).fetchone()[0]
            # After migration, kb_fts should use trigram.
            assert "trigram" in sql
            # And the row should still be findable via substring match.
            # (Trigram needs ≥3 char windows; "提供什么" appears contiguously in seed.)
            rows = conn2.execute(
                "SELECT content FROM kb_fts WHERE kb_fts MATCH ?", ("提供什么",),
            ).fetchall()
            conn2.close()
            assert len(rows) == 1
        finally:
            store.close()
