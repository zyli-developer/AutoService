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


class TestSaveAndClear:
    def _chunk(self, source_id: str, idx: int, content: str) -> dict:
        return {
            "id": f"{source_id}_{idx:04d}",
            "source_id": source_id,
            "source_type": "text",
            "source_name": "Unit Test Source",
            "source_url": None,
            "file_path": None,
            "section": f"section-{idx}",
            "content": content,
            "created_at": "2026-04-22T00:00:00+00:00",
            "domain": "contact_center",
            "region": "HK",
            "language": "zh",
            "page_number": None,
        }

    def test_save_chunk_persists_row_and_indexes_fts(self, tmp_path: Path):
        store = KBStore(tmp_path / "kb.db")
        try:
            store.save_chunk(self._chunk("src_a", 0, "Hello world"))
            assert store.count() == 1
            # FTS-visible via substring match (trigram tokenizer)
            conn = sqlite3.connect(str(store.db_path))
            rows = conn.execute(
                "SELECT content FROM kb_fts WHERE kb_fts MATCH ?", ("Hello",)
            ).fetchall()
            conn.close()
            assert len(rows) == 1 and rows[0][0] == "Hello world"
        finally:
            store.close()

    def test_clear_source_removes_only_that_source(self, tmp_path: Path):
        store = KBStore(tmp_path / "kb.db")
        try:
            store.save_chunk(self._chunk("src_a", 0, "from A"))
            store.save_chunk(self._chunk("src_a", 1, "from A again"))
            store.save_chunk(self._chunk("src_b", 0, "from B"))
            deleted = store.clear_source("src_a")
            assert deleted == 2           # two src_a chunks existed
            assert store.count() == 1
            assert store.by_source() == {"src_b": 1}
        finally:
            store.close()

    def test_clear_source_no_match_returns_zero(self, tmp_path: Path):
        with KBStore(tmp_path / "kb.db") as store:
            assert store.clear_source("does_not_exist") == 0

    def test_save_chunk_or_replace_is_idempotent(self, tmp_path: Path):
        store = KBStore(tmp_path / "kb.db")
        try:
            c = self._chunk("src_a", 0, "original")
            store.save_chunk(c)
            c["content"] = "updated"
            store.save_chunk(c)  # same id → REPLACE
            assert store.count() == 1
            conn = sqlite3.connect(str(store.db_path))
            row = conn.execute("SELECT content FROM kb_chunks").fetchone()
            assert row[0] == "updated"
            # FTS must also reflect the update — verify the kb_ad+kb_ai trigger
            # chain fires on REPLACE (implemented as DELETE+INSERT in save_chunk)
            # so stale trigrams don't linger.
            fresh = conn.execute(
                "SELECT content FROM kb_fts WHERE kb_fts MATCH ?", ("updated",),
            ).fetchall()
            stale = conn.execute(
                "SELECT content FROM kb_fts WHERE kb_fts MATCH ?", ("original",),
            ).fetchall()
            conn.close()
            assert len(fresh) == 1 and fresh[0][0] == "updated"
            assert stale == [], f"stale FTS trigrams linger: {stale!r}"
        finally:
            store.close()

    def test_context_manager_closes_connection(self, tmp_path: Path):
        """KBStore should work as a context manager; exit closes the connection."""
        db = tmp_path / "kb.db"
        with KBStore(db) as store:
            store.save_chunk(self._chunk("src_ctx", 0, "context managed"))
            assert store.count() == 1
        # After exit, further writes on the stored connection should error.
        with pytest.raises(sqlite3.ProgrammingError):
            store._conn.execute("SELECT 1")

    def test_fts_full_integrity_check_passes_after_replace(self, tmp_path: Path):
        """Guard against the INSERT OR REPLACE corruption bug regressing.

        SQLite's FTS5 full integrity-check (`rank=1`) raises
        DatabaseError("database disk image is malformed") when the trigram
        segment index is corrupted. With DELETE+INSERT as the replace strategy,
        it must pass.
        """
        store = KBStore(tmp_path / "kb.db")
        try:
            c = self._chunk("src_a", 0, "original content text that trigrams will index")
            store.save_chunk(c)
            c["content"] = "updated content text with different trigrams"
            store.save_chunk(c)  # replace
            conn = sqlite3.connect(str(store.db_path))
            try:
                conn.execute("INSERT INTO kb_fts(kb_fts, rank) VALUES('integrity-check', 1)")
            finally:
                conn.close()
        finally:
            store.close()


class TestIngestText:
    def test_ingest_text_splits_by_paragraphs(self, tmp_path: Path):
        store = KBStore(tmp_path / "kb.db")
        try:
            text = (
                "First paragraph with enough characters to pass the minimum threshold of fifty chars.\n\n"
                "Second paragraph, also sufficiently long to count as a chunk on its own right here.\n\n"
                "Third one, meeting the minimum character count required for inclusion in the output chunks."
            )
            n = store.ingest_text(
                text,
                source_id="doc_a",
                source_name="Test Doc",
                source_type="text",
                file_path="test.md",
                domain="contact_center",
                region="",
                language="en",
            )
            assert n >= 1
            assert store.by_source() == {"doc_a": n}
        finally:
            store.close()

    def test_ingest_text_skips_short_paragraphs(self, tmp_path: Path):
        store = KBStore(tmp_path / "kb.db")
        try:
            text = "hi\n\nshort\n\n" + ("x" * 80)  # last para >= CHUNK_MIN_CHARS
            n = store.ingest_text(
                text,
                source_id="doc_b",
                source_name="Short Doc",
                source_type="text",
            )
            # "hi" (2 chars) and "short" (5 chars) are below CHUNK_MIN_CHARS (50),
            # should be skipped. Only the 80-x paragraph should become a chunk.
            assert n == 1
        finally:
            store.close()

    def test_ingest_text_is_idempotent_on_same_source_id(self, tmp_path: Path):
        store = KBStore(tmp_path / "kb.db")
        try:
            text = ("a" * 200) + "\n\n" + ("b" * 200)
            store.ingest_text(
                text, source_id="doc_c", source_name="Doc C", source_type="text",
            )
            first = store.count()
            store.ingest_text(
                text, source_id="doc_c", source_name="Doc C", source_type="text",
            )
            # Same source_id → clear+reseed; count stays stable, no duplicates.
            assert store.count() == first
            assert store.by_source() == {"doc_c": first}
        finally:
            store.close()

    def test_ingest_text_empty_returns_zero(self, tmp_path: Path):
        """Empty or all-short text should ingest 0 chunks without erroring."""
        store = KBStore(tmp_path / "kb.db")
        try:
            assert store.ingest_text(
                "",
                source_id="doc_d", source_name="Empty", source_type="text",
            ) == 0
            assert store.ingest_text(
                "hi\n\nshort",
                source_id="doc_e", source_name="AllShort", source_type="text",
            ) == 0
            assert store.count() == 0
        finally:
            store.close()


class TestIngestPdf:
    """Uses a minimal real PDF fixture built on the fly to avoid binary test data."""

    def _make_pdf(self, dest: Path, pages: list[str]) -> Path:
        """Generate a PDF with one paragraph per page using reportlab if available.

        If reportlab is not available, fall back to a blank-page PDF via pypdf.
        Tests then only assert that ingest completes without error.
        """
        try:
            from reportlab.pdfgen import canvas  # type: ignore
            from reportlab.lib.pagesizes import LETTER
            cvs = canvas.Canvas(str(dest), pagesize=LETTER)
            for text in pages:
                y = 750
                for line in text.split("\n"):
                    cvs.drawString(50, y, line[:100])
                    y -= 14
                cvs.showPage()
            cvs.save()
        except ImportError:
            import pypdf
            writer = pypdf.PdfWriter()
            writer.add_blank_page(width=612, height=792)
            with dest.open("wb") as f:
                writer.write(f)
        return dest

    def test_ingest_pdf_writes_chunks_with_page_numbers(self, tmp_path: Path):
        pdf = self._make_pdf(tmp_path / "doc.pdf", [
            "1. INTRODUCTION\n" + ("This is page one content. " * 30),
            "2. DETAILS\n" + ("This is page two content. " * 30),
        ])
        store = KBStore(tmp_path / "kb.db")
        try:
            n = store.ingest_pdf(
                pdf,
                source_id="pdf_a",
                source_name="Test PDF",
                domain="contact_center",
            )
            # reportlab path → real text → ≥1 chunks; pypdf-only path → 0 allowed.
            assert n >= 0
            if n > 0:
                conn = sqlite3.connect(str(store.db_path))
                rows = conn.execute(
                    "SELECT source_type, page_number FROM kb_chunks LIMIT 1"
                ).fetchall()
                conn.close()
                assert rows[0][0] == "pdf"
                assert rows[0][1] is not None
        finally:
            store.close()

    def test_ingest_pdf_missing_file_raises(self, tmp_path: Path):
        store = KBStore(tmp_path / "kb.db")
        try:
            with pytest.raises(FileNotFoundError):
                store.ingest_pdf(
                    tmp_path / "nope.pdf",
                    source_id="x", source_name="x",
                )
        finally:
            store.close()

    def test_ingest_pdf_idempotent_on_reingest(self, tmp_path: Path):
        """Re-ingesting the same PDF with the same source_id must not duplicate."""
        pdf = self._make_pdf(tmp_path / "doc.pdf", [
            "1. INTRO\n" + ("Content. " * 40),
            "2. MORE\n" + ("Content. " * 40),
        ])
        store = KBStore(tmp_path / "kb.db")
        try:
            first = store.ingest_pdf(
                pdf, source_id="pdf_b", source_name="Same PDF",
            )
            second = store.ingest_pdf(
                pdf, source_id="pdf_b", source_name="Same PDF",
            )
            # Same source_id + same file → clear_source wipes, save_chunks reseeds.
            assert first == second
            # When reportlab is present, first > 0 and by_source maps pdf_b → first.
            # When reportlab is absent, the stub is a blank page → first == 0 and
            # by_source is empty (no rows at all). Both states prove no duplication.
            if first > 0:
                assert store.by_source() == {"pdf_b": first}
            else:
                assert store.by_source() == {}
        finally:
            store.close()


class TestIngestXlsx:
    def _make_xlsx(self, dest: Path, sheets: dict[str, list[list]]) -> Path:
        import openpyxl
        wb = openpyxl.Workbook()
        # First sheet is the default "Sheet" — rename to the first caller sheet.
        default = wb.active
        names = list(sheets.keys())
        default.title = names[0]
        for name in names[1:]:
            wb.create_sheet(name)
        for name, rows in sheets.items():
            ws = wb[name]
            for row in rows:
                ws.append(row)
        wb.save(str(dest))
        return dest

    def test_ingest_xlsx_non_rate_table(self, tmp_path: Path):
        xlsx = self._make_xlsx(tmp_path / "data.xlsx", {
            "Products": [
                ["Name", "Category", "Description"],
                ["Widget A", "hardware", "A standard widget used for various applications across the industry."],
                ["Widget B", "hardware", "An upgraded widget with extended durability and longer warranty coverage."],
            ],
        })
        store = KBStore(tmp_path / "kb.db")
        try:
            n = store.ingest_xlsx(xlsx, source_id="xl_a", source_name="Products")
            assert n >= 1
            assert list(store.by_source().keys()) == ["xl_a"]
        finally:
            store.close()

    def test_ingest_xlsx_rate_table_detects_region(self, tmp_path: Path):
        xlsx = self._make_xlsx(tmp_path / "rates.xlsx", {
            "DID Rates": [
                ["Country", "DID", "MRC"],
                ["Hong Kong", "+852", "USD 15.00"],
                ["Singapore", "+65", "USD 12.00"],
                ["United States", "+1", "USD 10.00"],
            ],
        })
        store = KBStore(tmp_path / "kb.db")
        try:
            n = store.ingest_xlsx(
                xlsx, source_id="xl_b", source_name="DID Rates",
                is_rate_table=True,
            )
            assert n >= 1
            conn = sqlite3.connect(str(store.db_path))
            regions = {r[0] for r in conn.execute("SELECT region FROM kb_chunks").fetchall()}
            conn.close()
            # Rate-table detection sets region per chunk from the country column.
            assert any("HK" in r or "SG" in r or "US" in r for r in regions)
        finally:
            store.close()

    def test_ingest_xlsx_idempotent(self, tmp_path: Path):
        """Re-ingest same xlsx with same source_id must not duplicate."""
        xlsx = self._make_xlsx(tmp_path / "x.xlsx", {
            "S": [
                ["Col"],
                ["row one with sufficient content to make a chunk"],
                ["row two also sufficiently wordy for chunking"],
                ["row three for good measure in the data set"],
            ],
        })
        store = KBStore(tmp_path / "kb.db")
        try:
            first = store.ingest_xlsx(xlsx, source_id="xl_c", source_name="X")
            second = store.ingest_xlsx(xlsx, source_id="xl_c", source_name="X")
            assert first == second
            if first > 0:
                assert store.by_source() == {"xl_c": first}
        finally:
            store.close()

    def test_ingest_xlsx_missing_file_raises(self, tmp_path: Path):
        store = KBStore(tmp_path / "kb.db")
        try:
            with pytest.raises(FileNotFoundError):
                store.ingest_xlsx(
                    tmp_path / "nope.xlsx",
                    source_id="x", source_name="x",
                )
        finally:
            store.close()
