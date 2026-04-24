#!/usr/bin/env python3
"""Reset Dream Engine data (proposals + runs) for testing.

Clears the two SQLite stores that back the admin-portal DreamTab:
  - `.autoservice/data/proposals.db`       (proposals, proposal_audit)
  - `.autoservice/database/dream_runs.db`  (dream_runs)

Schemas are preserved; only rows are deleted. Files are left in place so
the web server's cached connections (`_proposal_pipeline`, `_dream_runs_db_conn`
in autoservice.api_routes) keep working — no restart required.

Examples:
    python scripts/reset_dream.py                 # wipe all tenants
    python scripts/reset_dream.py --tenant cinnox # wipe one tenant
    python scripts/reset_dream.py --dry-run       # show counts, delete nothing
    python scripts/reset_dream.py --include-turns # also wipe memory_pool turns

Note: `--include-turns` deletes conversation history from
`.autoservice/data/memory_pool.db` (memory_turns). Dream runs use turns as
signals, so clearing them stops [dev stub] proposals from regenerating off
stale conversation state. Skip unless you want to reset customer chats too.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PROPOSALS_DB = REPO_ROOT / ".autoservice" / "data" / "proposals.db"
DREAM_RUNS_DB = REPO_ROOT / ".autoservice" / "database" / "dream_runs.db"
MEMORY_POOL_DB = REPO_ROOT / ".autoservice" / "data" / "memory_pool.db"


def _count(conn: sqlite3.Connection, table: str, where: str = "", params: tuple = ()) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else ""),
        params,
    ).fetchone()
    return row[0] if row else 0


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def reset_proposals(tenant: str | None, dry_run: bool) -> tuple[int, int]:
    """Return (proposals_deleted, audit_deleted)."""
    if not PROPOSALS_DB.exists():
        print(f"  [skip] {PROPOSALS_DB} does not exist")
        return (0, 0)

    conn = sqlite3.connect(str(PROPOSALS_DB))
    try:
        if not _has_table(conn, "proposals"):
            print(f"  [skip] {PROPOSALS_DB} has no 'proposals' table")
            return (0, 0)

        if tenant:
            prop_count = _count(conn, "proposals", "tenant_id = ?", (tenant,))
            audit_sql = (
                "DELETE FROM proposal_audit WHERE proposal_id IN "
                "(SELECT id FROM proposals WHERE tenant_id = ?)"
            )
            audit_count = _count(
                conn,
                "proposal_audit",
                "proposal_id IN (SELECT id FROM proposals WHERE tenant_id = ?)",
                (tenant,),
            ) if _has_table(conn, "proposal_audit") else 0
            prop_sql = "DELETE FROM proposals WHERE tenant_id = ?"
            params: tuple = (tenant,)
        else:
            prop_count = _count(conn, "proposals")
            audit_count = _count(conn, "proposal_audit") if _has_table(conn, "proposal_audit") else 0
            audit_sql = "DELETE FROM proposal_audit"
            prop_sql = "DELETE FROM proposals"
            params = ()

        if dry_run:
            return (prop_count, audit_count)

        if _has_table(conn, "proposal_audit"):
            conn.execute(audit_sql, params)
        conn.execute(prop_sql, params)
        conn.commit()
        return (prop_count, audit_count)
    finally:
        conn.close()


def reset_dream_runs(tenant: str | None, dry_run: bool) -> int:
    if not DREAM_RUNS_DB.exists():
        print(f"  [skip] {DREAM_RUNS_DB} does not exist")
        return 0

    conn = sqlite3.connect(str(DREAM_RUNS_DB))
    try:
        if not _has_table(conn, "dream_runs"):
            print(f"  [skip] {DREAM_RUNS_DB} has no 'dream_runs' table")
            return 0

        if tenant:
            count = _count(conn, "dream_runs", "tenant_id = ?", (tenant,))
            sql = "DELETE FROM dream_runs WHERE tenant_id = ?"
            params: tuple = (tenant,)
        else:
            count = _count(conn, "dream_runs")
            sql = "DELETE FROM dream_runs"
            params = ()

        if dry_run:
            return count

        conn.execute(sql, params)
        conn.commit()
        return count
    finally:
        conn.close()


def reset_memory_turns(tenant: str | None, dry_run: bool) -> int:
    if not MEMORY_POOL_DB.exists():
        print(f"  [skip] {MEMORY_POOL_DB} does not exist")
        return 0

    conn = sqlite3.connect(str(MEMORY_POOL_DB))
    try:
        if not _has_table(conn, "memory_turns"):
            print(f"  [skip] {MEMORY_POOL_DB} has no 'memory_turns' table")
            return 0

        has_tenant_col = any(
            row[1] == "tenant_id"
            for row in conn.execute("PRAGMA table_info(memory_turns)").fetchall()
        )

        if tenant and has_tenant_col:
            count = _count(conn, "memory_turns", "tenant_id = ?", (tenant,))
            sql = "DELETE FROM memory_turns WHERE tenant_id = ?"
            params: tuple = (tenant,)
        elif tenant and not has_tenant_col:
            print("  [warn] memory_turns has no tenant_id column; --tenant ignored for turns")
            count = _count(conn, "memory_turns")
            sql = "DELETE FROM memory_turns"
            params = ()
        else:
            count = _count(conn, "memory_turns")
            sql = "DELETE FROM memory_turns"
            params = ()

        if dry_run:
            return count

        conn.execute(sql, params)
        conn.commit()
        return count
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--tenant",
        help="Only wipe rows for this tenant_id. Default: wipe all tenants.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting anything.",
    )
    parser.add_argument(
        "--include-turns",
        action="store_true",
        help="Also wipe memory_pool.memory_turns (conversation history).",
    )
    args = parser.parse_args()

    scope = f"tenant={args.tenant!r}" if args.tenant else "all tenants"
    mode = "DRY-RUN" if args.dry_run else "DELETE"
    print(f"[reset-dream] mode={mode} scope={scope}")

    print("\n[1/2] proposals.db")
    prop_n, audit_n = reset_proposals(args.tenant, args.dry_run)
    print(f"  proposals:       {prop_n}")
    print(f"  proposal_audit:  {audit_n}")

    print("\n[2/2] dream_runs.db")
    runs_n = reset_dream_runs(args.tenant, args.dry_run)
    print(f"  dream_runs:      {runs_n}")

    if args.include_turns:
        print("\n[3/3] memory_pool.db (memory_turns)")
        turns_n = reset_memory_turns(args.tenant, args.dry_run)
        print(f"  memory_turns:    {turns_n}")

    if args.dry_run:
        print("\n[reset-dream] dry-run complete. Re-run without --dry-run to apply.")
    else:
        print("\n[reset-dream] done. No server restart needed — cached connections see fresh state.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
