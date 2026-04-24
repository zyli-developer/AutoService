"""Smoke test: kb_ingest.py CLI produces expected output via KBStore."""
from __future__ import annotations

import os
import subprocess
import sys
import sqlite3
from pathlib import Path


def test_cli_ingests_adhoc_file(tmp_path: Path):
    """`--file <path>` on a plain text file should write chunks via KBStore."""
    src = tmp_path / "notes.md"
    src.write_text(
        "# Intro\n\nParagraph with enough characters to pass the minimum threshold. " * 5,
        encoding="utf-8",
    )
    # Override KB_DIR via env so the test doesn't touch the real global KB.
    env = {**os.environ, "KB_DIR_OVERRIDE": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "skills/knowledge-base/scripts/kb_ingest.py",
         "--file", str(src)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "Total chunks written" in result.stdout

    # KB file should exist and have at least one row.
    db = tmp_path / "kb.db"
    assert db.exists()
    conn = sqlite3.connect(str(db))
    n = conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0]
    conn.close()
    assert n >= 1


def test_cli_shows_help(tmp_path: Path):
    """Basic sanity — --help exits cleanly."""
    result = subprocess.run(
        [sys.executable, "skills/knowledge-base/scripts/kb_ingest.py", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--all" in result.stdout
    assert "--source" in result.stdout
    assert "--url" in result.stdout
    assert "--file" in result.stdout
