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
        """Insert (or replace via DELETE+INSERT) one chunk; FTS stays in sync via triggers.

        Uses explicit ``DELETE WHERE id=?`` then ``INSERT`` instead of
        ``INSERT OR REPLACE`` because the latter causes SQLite to assign a
        new rowid on replacement, which leaves the trigram FTS5 external-
        content segment index in a malformed state. Explicit delete reuses
        the same rowid slot and keeps the FTS index coherent. Verified:
        ``MATCH 'old-term'`` returns [] after replace, and the FTS5 full
        integrity-check passes — with INSERT OR REPLACE it raises
        ``sqlite3.DatabaseError: database disk image is malformed``.
        """
        c = self._conn
        c.execute("DELETE FROM kb_chunks WHERE id = ?", (chunk["id"],))
        c.execute(
            """
            INSERT INTO kb_chunks
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
        """Insert (or replace) many chunks as a single SQLite transaction.

        Much faster than calling :meth:`save_chunk` in a loop because there is
        exactly one commit (and thus one WAL fsync) for the whole batch. Uses
        explicit ``DELETE WHERE id=?`` before each ``INSERT`` — see
        :meth:`save_chunk` for why ``INSERT OR REPLACE`` is unsafe with the
        trigram FTS external-content index. On any per-chunk error, rolls back
        the whole batch — partial batch state never lands. Returns the number
        of rows written.
        """
        chunks_list = list(chunks)
        c = self._conn
        try:
            for chunk in chunks_list:
                c.execute("DELETE FROM kb_chunks WHERE id = ?", (chunk["id"],))
                c.execute(
                    """
                    INSERT INTO kb_chunks
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

    # ── text ingestion ─────────────────────────────────────────────────

    @staticmethod
    def _chunk_paragraphs(text: str) -> list[str]:
        """Paragraph-based chunker (port of kb_ingest.chunk_paragraphs).

        Joins short paragraphs into chunks up to CHUNK_MAX_CHARS; skips
        paragraphs below CHUNK_MIN_CHARS. No overlap.
        """
        import re
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for para in paragraphs:
            if len(para) < CHUNK_MIN_CHARS:
                continue
            if current and current_len + len(para) > CHUNK_MAX_CHARS:
                chunks.append("\n\n".join(current))
                current = [para]
                current_len = len(para)
            else:
                current.append(para)
                current_len += len(para)
        if current:
            chunks.append("\n\n".join(current))
        return chunks

    def ingest_text(
        self,
        text: str,
        *,
        source_id: str,
        source_name: str,
        source_type: str = "text",
        source_url: str | None = None,
        file_path: str | None = None,
        domain: str = "",
        region: str = "",
        language: str = "en",
        debug_dir: Path | None = None,
    ) -> int:
        """Chunk plain text by paragraphs and insert. Returns # chunks written.

        Clears existing rows for *source_id* first (idempotent re-ingest).
        Writes all chunks in one transaction via :meth:`save_chunks`.
        """
        self.clear_source(source_id)
        texts = self._chunk_paragraphs(text)
        if not texts:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        chunks = [
            {
                "id": f"{source_id}_{i:04d}",
                "source_id": source_id,
                "source_type": source_type,
                "source_name": source_name,
                "source_url": source_url,
                "file_path": file_path,
                "section": "",
                "content": chunk_text,
                "created_at": now,
                "domain": domain,
                "region": region,
                "language": language,
                "page_number": None,
            }
            for i, chunk_text in enumerate(texts)
        ]
        return self.save_chunks(chunks, debug_dir=debug_dir)

    # ── PDF ingestion (port of kb_ingest.ingest_pdf + _semantic_chunk_pages) ─

    @staticmethod
    def _is_heading(line: str) -> bool:
        import re
        stripped = line.strip()
        if not stripped or len(stripped) > 120:
            return False
        if stripped.isupper() and len(stripped) >= 3 and re.search(r"[A-Z]{3}", stripped):
            return True
        if re.match(r"^\d+(\.\d+)*\.?\s+\S", stripped):
            return True
        return False

    @staticmethod
    def _is_table_line(line: str) -> bool:
        return line.count("|") >= 2 or line.count("\t") >= 2

    @classmethod
    def _semantic_chunk_pages(
        cls, pages: list[tuple[int, str]], max_chars: int
    ) -> list[dict]:
        segments: list[dict] = []
        current_section = ""
        current_lines: list[str] = []
        current_page_start = 1
        current_page_end = 1
        in_table = False

        for page_num, page_text in pages:
            for raw_line in page_text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if cls._is_heading(line) and not in_table:
                    if current_lines:
                        segments.append({
                            "text": "\n".join(current_lines),
                            "section": current_section,
                            "page_start": current_page_start,
                            "page_end": current_page_end,
                            "is_table": False,
                        })
                    current_section = line
                    current_lines = []
                    current_page_start = page_num
                    current_page_end = page_num
                    continue
                if cls._is_table_line(line):
                    if not in_table and current_lines:
                        segments.append({
                            "text": "\n".join(current_lines),
                            "section": current_section,
                            "page_start": current_page_start,
                            "page_end": current_page_end,
                            "is_table": False,
                        })
                        current_lines = []
                        current_page_start = page_num
                    in_table = True
                    current_lines.append(line)
                    current_page_end = page_num
                else:
                    if in_table and current_lines:
                        segments.append({
                            "text": "\n".join(current_lines),
                            "section": current_section,
                            "page_start": current_page_start,
                            "page_end": current_page_end,
                            "is_table": True,
                        })
                        current_lines = []
                        current_page_start = page_num
                        in_table = False
                    current_lines.append(line)
                    current_page_end = page_num

        if current_lines:
            segments.append({
                "text": "\n".join(current_lines),
                "section": current_section,
                "page_start": current_page_start,
                "page_end": current_page_end,
                "is_table": in_table,
            })

        if sum(1 for s in segments if s["section"]) == 0:
            return []  # no headings found — caller will fall back to page-buffered

        result: list[dict] = []
        for seg in segments:
            if len(seg["text"]) <= max_chars:
                if len(seg["text"].strip()) >= CHUNK_MIN_CHARS:
                    result.append({
                        "text": seg["text"],
                        "section": seg["section"],
                        "page_start": seg["page_start"],
                        "page_end": seg["page_end"],
                    })
            else:
                for sub in cls._chunk_paragraphs(seg["text"]):
                    result.append({
                        "text": sub,
                        "section": seg["section"],
                        "page_start": seg["page_start"],
                        "page_end": seg["page_end"],
                    })
        return result

    def ingest_pdf(
        self,
        file_path: Path,
        *,
        source_id: str,
        source_name: str,
        domain: str = "",
        region: str = "",
        language: str = "en",
        debug_dir: Path | None = None,
    ) -> int:
        """Extract, semantic-chunk (or page-buffer fallback), and persist.

        Uses pypdf for extraction. Tries heading/table-aware semantic chunking
        first; falls back to page-buffered ``CHUNK_MAX_CHARS`` slicing when
        no headings are detected. Returns # chunks written. Clears existing
        rows for *source_id* first for idempotent re-ingest.
        """
        import pypdf

        fp = Path(file_path)
        if not fp.exists():
            raise FileNotFoundError(file_path)

        self.clear_source(source_id)
        now = datetime.now(timezone.utc).isoformat()
        reader = pypdf.PdfReader(str(fp))

        pages: list[tuple[int, str]] = []
        for page_num, page in enumerate(reader.pages, start=1):
            t = (page.extract_text() or "").strip()
            if t:
                pages.append((page_num, t))

        semantic = self._semantic_chunk_pages(pages, CHUNK_MAX_CHARS)
        chunks_to_save: list[dict] = []

        if semantic:
            for i, sc in enumerate(semantic):
                section = sc["section"] or f"Page {sc['page_start']}"
                if sc["page_end"] != sc["page_start"]:
                    section += f" (p{sc['page_start']}–{sc['page_end']})"
                chunks_to_save.append({
                    "id": f"{source_id}_{i:04d}",
                    "source_id": source_id,
                    "source_type": "pdf",
                    "source_name": source_name,
                    "source_url": None,
                    "file_path": str(fp),
                    "section": section,
                    "content": sc["text"],
                    "created_at": now,
                    "domain": domain,
                    "region": region,
                    "language": language,
                    "page_number": sc["page_start"],
                })
        else:
            # Page-buffered fallback when no headings detected.
            buffer = ""
            buffer_start: int | None = None
            idx = 0
            for page_num, text in pages:
                if buffer_start is None:
                    buffer_start = page_num
                buffer += f"\n\n{text}"
                if len(buffer) >= CHUNK_MAX_CHARS:
                    section = f"Page {buffer_start}"
                    if page_num != buffer_start:
                        section += f"–{page_num}"
                    chunks_to_save.append({
                        "id": f"{source_id}_{idx:04d}",
                        "source_id": source_id,
                        "source_type": "pdf",
                        "source_name": source_name,
                        "source_url": None,
                        "file_path": str(fp),
                        "section": section,
                        "content": buffer.strip(),
                        "created_at": now,
                        "domain": domain,
                        "region": region,
                        "language": language,
                        "page_number": buffer_start,
                    })
                    idx += 1
                    buffer = ""
                    buffer_start = None
            if buffer.strip():
                section = f"Page {buffer_start}" if buffer_start else "Document"
                chunks_to_save.append({
                    "id": f"{source_id}_{idx:04d}",
                    "source_id": source_id,
                    "source_type": "pdf",
                    "source_name": source_name,
                    "source_url": None,
                    "file_path": str(fp),
                    "section": section,
                    "content": buffer.strip(),
                    "created_at": now,
                    "domain": domain,
                    "region": region,
                    "language": language,
                    "page_number": buffer_start,
                })

        if not chunks_to_save:
            return 0
        return self.save_chunks(chunks_to_save, debug_dir=debug_dir)

    # ── XLSX ingestion (port of kb_ingest.ingest_xlsx) ──────────────────

    RATE_TABLE_SIGNALS: set[str] = {
        "country", "did", "mrc", "rate", "dial-in", "dial-out", "leg1", "leg2",
    }
    COUNTRY_REGION_MAP: dict[str, str] = {
        "united states": "US", "usa": "US", "us": "US",
        "united kingdom": "UK", "uk": "UK", "great britain": "UK",
        "hong kong": "HK", "hk": "HK",
        "singapore": "SG", "sg": "SG",
        "japan": "JP", "jp": "JP",
        "australia": "AU", "au": "AU",
        "germany": "DE", "de": "DE",
        "france": "FR", "fr": "FR",
        "canada": "CA", "ca": "CA",
        "china": "CN", "cn": "CN", "mainland china": "CN",
        "taiwan": "TW", "tw": "TW",
        "south korea": "KR", "korea": "KR", "kr": "KR",
        "india": "IN", "in": "IN",
        "indonesia": "ID", "id": "ID",
        "malaysia": "MY", "my": "MY",
        "thailand": "TH", "th": "TH",
        "philippines": "PH", "ph": "PH",
        "vietnam": "VN", "vn": "VN",
    }
    ROWS_PER_XLSX_CHUNK: int = 15
    ROWS_PER_RATE_TABLE_CHUNK: int = 3

    @classmethod
    def _extract_country_region(cls, row_text: str, headers: list[str]) -> str:
        for i, h in enumerate(headers):
            if h.lower().strip() in ("country", "country/region", "destination"):
                break
        else:
            return ""
        for part in row_text.split(" | "):
            if ":" in part:
                key, val = part.split(":", 1)
                if key.strip().lower() in ("country", "country/region", "destination"):
                    name = val.strip().lower()
                    if name in cls.COUNTRY_REGION_MAP:
                        return cls.COUNTRY_REGION_MAP[name]
                    for nm, code in cls.COUNTRY_REGION_MAP.items():
                        if nm in name or name in nm:
                            return code
        return ""

    @staticmethod
    def _detect_service_type(sheet_name: str, headers: list[str]) -> str:
        combined = (sheet_name + " " + " ".join(headers)).lower()
        if "toll-free" in combined or "tollfree" in combined or "toll free" in combined:
            return "toll-free"
        if "did" in combined:
            return "DID"
        if "local" in combined:
            return "local"
        return ""

    def ingest_xlsx(
        self,
        file_path: Path,
        *,
        source_id: str,
        source_name: str,
        is_rate_table: bool = False,
        domain: str = "",
        region: str = "",
        language: str = "en",
        debug_dir: Path | None = None,
    ) -> int:
        """Ingest an XLSX workbook via openpyxl.

        Groups rows into chunks by both row count and character limit. Auto-
        detects rate/pricing tables by header names (``country`` / ``did`` /
        ``mrc`` / ``rate`` / ``dial-in`` / ``dial-out`` / ``leg1`` / ``leg2``)
        and switches to smaller chunk sizes for those. When *is_rate_table*
        is True AND a country column exists, per-chunk ``region`` is derived
        from the rows in that chunk.

        Returns # chunks written. Clears existing rows for *source_id* first
        for idempotent re-ingest.
        """
        import openpyxl

        fp = Path(file_path)
        if not fp.exists():
            raise FileNotFoundError(file_path)

        self.clear_source(source_id)
        now = datetime.now(timezone.utc).isoformat()
        wb = openpyxl.load_workbook(str(fp), data_only=True)
        chunks_to_save: list[dict] = []
        idx = 0

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows: list[str] = []
            headers: list[str] = []
            for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
                cells = [str(v).strip() if v is not None else "" for v in row]
                if not any(cells):
                    continue
                if row_idx == 0:
                    headers = cells
                else:
                    if headers:
                        row_dict = {h: v for h, v in zip(headers, cells) if h and v}
                        row_text = " | ".join(f"{k}: {v}" for k, v in row_dict.items())
                    else:
                        row_text = " | ".join(v for v in cells if v)
                    if row_text.strip():
                        rows.append(row_text)

            header_lower = {h.lower() for h in headers}
            detected_rate = bool(header_lower & self.RATE_TABLE_SIGNALS)
            chunk_size = (
                self.ROWS_PER_RATE_TABLE_CHUNK if detected_rate else self.ROWS_PER_XLSX_CHUNK
            )
            service_type = self._detect_service_type(sheet_name, headers)
            has_country_col = is_rate_table and any(
                h.lower().strip() in ("country", "country/region", "destination")
                for h in headers
            )

            batches: list[list[str]] = []
            current: list[str] = []
            current_chars = 0
            for row in rows:
                row_len = len(row) + 1
                if current and (
                    len(current) >= chunk_size or current_chars + row_len > CHUNK_MAX_CHARS
                ):
                    batches.append(current)
                    current = [row]
                    current_chars = row_len
                else:
                    current.append(row)
                    current_chars += row_len
            if current:
                batches.append(current)

            for batch in batches:
                content = f"[Sheet: {sheet_name}]\n" + "\n".join(batch)
                if len(content.strip()) < CHUNK_MIN_CHARS:
                    continue
                chunk_region = region
                if has_country_col:
                    regions_in_batch: set[str] = set()
                    for rt in batch:
                        r = self._extract_country_region(rt, headers)
                        if r:
                            regions_in_batch.add(r)
                    if regions_in_batch:
                        chunk_region = "/".join(sorted(regions_in_batch))
                        if service_type:
                            chunk_region += f"/{service_type}"

                chunks_to_save.append({
                    "id": f"{source_id}_{idx:04d}",
                    "source_id": source_id,
                    "source_type": "xlsx",
                    "source_name": source_name,
                    "source_url": None,
                    "file_path": str(fp),
                    "section": sheet_name,
                    "content": content,
                    "created_at": now,
                    "domain": domain,
                    "region": chunk_region,
                    "language": language,
                    "page_number": None,
                })
                idx += 1

        if not chunks_to_save:
            return 0
        return self.save_chunks(chunks_to_save, debug_dir=debug_dir)
