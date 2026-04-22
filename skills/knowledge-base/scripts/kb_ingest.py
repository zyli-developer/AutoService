#!/usr/bin/env python3
"""KB Ingestion CLI — thin wrapper over autoservice.kb_core.KBStore.

Usage:
    uv run skills/knowledge-base/scripts/kb_ingest.py --all
    uv run skills/knowledge-base/scripts/kb_ingest.py --source files
    uv run skills/knowledge-base/scripts/kb_ingest.py --source web
    uv run skills/knowledge-base/scripts/kb_ingest.py --file "path/to/file.xlsx"
    uv run skills/knowledge-base/scripts/kb_ingest.py --url "https://example.com"

Target DB defaults to the global KB (.autoservice/database/knowledge_base/kb.db);
override with env var KB_DIR_OVERRIDE for tests.

All actual ingestion work (PDF semantic chunking, XLSX rate-table handling,
web crawling, trigram FTS5 index) lives in :mod:`autoservice.kb_core`. This
script is just argparse + sources.json dispatch.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path.cwd()
sys.path.insert(0, str(PROJECT_ROOT))

from autoservice.kb_core import KBStore  # noqa: E402

DEFAULT_KB_DIR = PROJECT_ROOT / ".autoservice" / "database" / "knowledge_base"
SOURCES_FILE = Path(__file__).parent.parent / "references" / "sources.json"


def _resolve_kb_dir() -> Path:
    override = os.environ.get("KB_DIR_OVERRIDE")
    return Path(override) if override else DEFAULT_KB_DIR


def load_sources() -> dict:
    if not SOURCES_FILE.exists():
        print(f"ERROR: sources.json not found at {SOURCES_FILE}")
        sys.exit(1)
    return json.loads(SOURCES_FILE.read_text(encoding="utf-8"))


def _ingest_file(store: KBStore, src: dict, debug_root: Path) -> int:
    ftype = (src.get("type") or "").lower()
    debug = debug_root / src["id"]
    path = PROJECT_ROOT / src["path"]
    common = dict(
        source_id=src["id"],
        source_name=src["name"],
        domain=src.get("domain", ""),
        region=src.get("region", ""),
        language=src.get("language", "en"),
        debug_dir=debug,
    )
    if ftype == "pdf":
        return store.ingest_pdf(path, **common)
    if ftype == "xlsx":
        return store.ingest_xlsx(
            path, is_rate_table=src.get("is_rate_table", False), **common,
        )
    # Default: treat as plain text (markdown, json, etc.).
    text = path.read_text(encoding="utf-8", errors="replace")
    return store.ingest_text(
        text,
        source_type=ftype or "text",
        file_path=src["path"],
        **common,
    )


def _ingest_web(store: KBStore, src: dict, debug_root: Path) -> int:
    return store.ingest_web(
        src["url"],
        source_id=src["id"],
        source_name=src["name"],
        max_pages=src.get("max_pages", 20),
        crawl_depth=src.get("crawl_depth", 1),
        domain=src.get("domain", ""),
        region=src.get("region", ""),
        language=src.get("language", "en"),
        debug_dir=debug_root / src["id"],
    )


def main():
    parser = argparse.ArgumentParser(description="Build KB from web and file sources")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Ingest all sources")
    group.add_argument("--source", choices=["web", "files"], help="Ingest by type")
    group.add_argument("--url", help="Ingest a single URL")
    group.add_argument("--file", help="Ingest a single local file path")
    args = parser.parse_args()

    kb_dir = _resolve_kb_dir()
    db_path = kb_dir / "kb.db"
    debug_root = kb_dir / "chunks"

    # --file and --url are adhoc; others read sources.json.
    if args.file or args.url:
        sources = {"files": [], "web": []}
    else:
        sources = load_sources()

    total = 0
    with KBStore(db_path) as store:
        if args.all or args.source == "files" or args.file:
            file_sources = sources.get("files", [])
            if args.file:
                ext = Path(args.file).suffix.lower().lstrip(".")
                file_sources = [{
                    "id": "adhoc",
                    "path": args.file,
                    "name": Path(args.file).stem,
                    "type": ext or "text",
                }]
            for src in file_sources:
                print(f"\n[KB Ingest] {(src.get('type') or '').upper()}: {src['name']}")
                try:
                    n = _ingest_file(store, src, debug_root)
                    print(f"  -> {n} chunks")
                    total += n
                except Exception as exc:
                    print(f"  ERROR: {exc}")

        if args.all or args.source == "web" or args.url:
            web_sources = sources.get("web", [])
            if args.url:
                web_sources = [{
                    "id": "adhoc_web",
                    "url": args.url,
                    "name": args.url,
                    "max_pages": 10,
                    "crawl_depth": 1,
                }]
            for src in web_sources:
                print(f"\n[KB Ingest] WEB: {src['name']} ({src['url']})")
                try:
                    n = _ingest_web(store, src, debug_root)
                    print(f"  -> {n} chunks")
                    total += n
                except Exception as exc:
                    print(f"  ERROR: {exc}")

    # Write a sources_meta.json summary (preserves the old CLI's behaviour).
    meta = {}
    now = datetime.now().isoformat()
    for s in sources.get("files", []):
        meta[s["id"]] = {
            "name": s["name"], "type": s.get("type", ""),
            "domain": s.get("domain", ""), "region": s.get("region", ""),
            "updated_at": now,
        }
    for s in sources.get("web", []):
        meta[s["id"]] = {
            "name": s["name"], "url": s["url"],
            "domain": s.get("domain", ""), "region": s.get("region", ""),
            "updated_at": now,
        }
    if meta:
        (kb_dir / "sources_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(f"\n[KB Ingest] Done. Total chunks written: {total}")
    print(f"[KB Ingest] Database: {db_path}")


if __name__ == "__main__":
    main()
