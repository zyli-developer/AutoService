#!/usr/bin/env python3
"""Reset conversation persistence for testing / demo resets.

Clears the SQLite store that backs LocalEngine's operator-visible history:
  - `.autoservice/database/conversations.db`
      tables: conversations, participants, messages, events, sequences

Schema is preserved; only rows are deleted so the gateway's cached connection
keeps working — no restart required. If the DB file does not exist yet
(gateway never booted with CONV_PERSIST=1), the script is a no-op.

The legacy JSON session dir `.autoservice/database/sessions/` (the old
cinnox `/ws/chat` + session_persistence flow, see
docs/legacy-code-inventory.md) is unrelated to operator-console history,
but `--include-legacy-json` will wipe it too for a clean slate.

Examples:
    python scripts/reset_conversations.py                    # wipe all convs
    python scripts/reset_conversations.py --dry-run          # show counts
    python scripts/reset_conversations.py --conv conv_id     # wipe one conv
    python scripts/reset_conversations.py --include-legacy-json  # also drop JSON dir
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONV_DB = REPO_ROOT / ".autoservice" / "database" / "conversations.db"
LEGACY_JSON_DIR = REPO_ROOT / ".autoservice" / "database" / "sessions"

# In child-to-parent order so FK cascades don't complain under manual delete.
TABLES = ("events", "messages", "participants", "sequences", "conversations")


def _count(conn: sqlite3.Connection, table: str, where: str = "", params: tuple = ()) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else ""),
        params,
    ).fetchone()
    return row[0] if row else 0


def reset(conv_id: str | None, dry_run: bool) -> dict[str, int]:
    if not CONV_DB.exists():
        print(f"  [skip] {CONV_DB} does not exist — nothing to clear")
        return {}

    conn = sqlite3.connect(str(CONV_DB))
    conn.execute("PRAGMA foreign_keys = ON")

    counts: dict[str, int] = {}
    try:
        for table in TABLES:
            if conv_id:
                col = "id" if table == "conversations" else "conv_id"
                counts[table] = _count(conn, table, f"{col} = ?", (conv_id,))
            else:
                counts[table] = _count(conn, table)

        for table, n in counts.items():
            scope = f" for conv {conv_id!r}" if conv_id else ""
            print(f"  {table}{scope}: {n} row(s)")

        if dry_run:
            print("  [dry-run] no rows deleted")
            return counts

        # FK cascade: deleting from `conversations` drops child rows, but
        # scoped deletes (--conv <id>) still need per-table DELETE because
        # `sequences` has its own PK on conv_id.
        if conv_id:
            for table in TABLES:
                col = "id" if table == "conversations" else "conv_id"
                conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (conv_id,))
        else:
            for table in TABLES:
                conn.execute(f"DELETE FROM {table}")
        conn.commit()
        print("  [ok] deleted")
    finally:
        conn.close()
    return counts


def reset_legacy_json(dry_run: bool) -> int:
    if not LEGACY_JSON_DIR.exists():
        print(f"  [skip] {LEGACY_JSON_DIR} does not exist")
        return 0
    files = list(LEGACY_JSON_DIR.rglob("*.json"))
    print(f"  legacy JSON sessions: {len(files)} file(s) under {LEGACY_JSON_DIR}")
    if dry_run:
        print("  [dry-run] no files removed")
        return len(files)
    shutil.rmtree(LEGACY_JSON_DIR)
    print("  [ok] removed directory")
    return len(files)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--conv", dest="conv_id", default=None,
        help="Reset only this conversation id (default: all)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show counts but do not delete",
    )
    parser.add_argument(
        "--include-legacy-json", action="store_true",
        help=(
            "Also remove .autoservice/database/sessions/ (old cinnox "
            "/ws/chat JSON sessions; unrelated to operator history)"
        ),
    )
    args = parser.parse_args(argv)

    print(f"Conversation store: {CONV_DB}")
    reset(args.conv_id, args.dry_run)

    if args.include_legacy_json:
        print(f"\nLegacy JSON sessions: {LEGACY_JSON_DIR}")
        reset_legacy_json(args.dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
