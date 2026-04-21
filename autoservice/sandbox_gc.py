"""Sandbox GC — archive stale unpublished sandboxes (M3 T4S.5).

Contract: docs/contracts/m3/e6-ops-gc-playwright.md §2.1.

Policy:
* TTL default: 30 days (from mtime of ``.autoservice/sandbox/<tid>/``)
* Per-tenant override: ``config.json.sandbox_ttl_days`` (int, >=1)
* Invariant: only sandboxes where ``config.json.status != 'published'``
  (i.e. still sandbox-phase) are eligible.  Published tenants NEVER
  get archived by GC.
* Archive via existing :func:`autoservice.publish.archive_sandbox` —
  same move semantics as explicit publish path.
* Permanent storage of ``.autoservice/archived/`` in M3 (OQ-E6-1).
  Second-tier purge is a M4+ decision.

Callers:
* Background scheduler (to be wired in web_gateway startup) — hourly tick
* CLI / admin endpoint for manual trigger + dry-run

Design invariants:
* Idempotent: re-running on the same state is a no-op.
* Safe on missing sandbox dir (nothing to scan).
* Clock injected via ``now`` arg so tests are deterministic.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autoservice.publish import ARCHIVED_ROOT, SANDBOX_ROOT, archive_sandbox

logger = logging.getLogger("autoservice.sandbox_gc")


DEFAULT_TTL_DAYS = 30
MIN_TTL_DAYS = 1


# ──────────────────────────────────────────────────────────────────────────
# Report
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GCReport:
    """Summary of a single GC run — return for logs + admin endpoint."""
    scanned_count: int
    archived: list[str]           # tenant_ids successfully archived
    skipped_published: list[str]  # tenant_ids skipped because status='published'
    skipped_fresh: list[str]      # tenant_ids skipped because mtime < TTL
    errors: list[tuple[str, str]] # (tenant_id, error_msg)
    run_at: str                   # ISO timestamp
    dry_run: bool


# ──────────────────────────────────────────────────────────────────────────
# Core
# ──────────────────────────────────────────────────────────────────────────


def run_gc(
    *,
    now: datetime | None = None,
    default_ttl_days: int = DEFAULT_TTL_DAYS,
    dry_run: bool = False,
    sandbox_root: Path | None = None,
) -> GCReport:
    """Scan sandbox dir and archive stale unpublished sandboxes.

    Args:
        now: evaluation time (UTC).  Defaults to ``datetime.now(tz=UTC)``.
        default_ttl_days: fallback TTL when a tenant's config.json has
            no ``sandbox_ttl_days`` override.
        dry_run: if True, scan + decide but DO NOT call archive_sandbox.
        sandbox_root: override sandbox dir (defaults to SANDBOX_ROOT).
            Tests inject a tmp_path.

    Returns:
        :class:`GCReport` summarizing the run.  Errors per-tenant are
        captured (never propagate) — a single bad tenant does NOT halt
        the full scan.
    """
    eval_time = now or datetime.now(tz=timezone.utc)
    root = sandbox_root or SANDBOX_ROOT

    report_archived: list[str] = []
    skipped_published: list[str] = []
    skipped_fresh: list[str] = []
    errors: list[tuple[str, str]] = []
    scanned = 0

    if not root.exists():
        return GCReport(
            scanned_count=0, archived=[], skipped_published=[],
            skipped_fresh=[], errors=[],
            run_at=eval_time.isoformat(), dry_run=dry_run,
        )

    for sandbox_dir in sorted(root.iterdir()):
        if not sandbox_dir.is_dir():
            continue
        tenant_id = sandbox_dir.name
        # Skip dunder / internal (already-system tenants)
        if tenant_id.startswith("."):
            continue
        scanned += 1

        try:
            config_path = sandbox_dir / "config.json"
            if not config_path.exists():
                skipped_fresh.append(tenant_id)  # no config → treat as incomplete setup, don't GC
                continue

            cfg = json.loads(config_path.read_text(encoding="utf-8"))

            # Skip published tenants unconditionally
            if cfg.get("status") == "published":
                skipped_published.append(tenant_id)
                continue

            # Per-tenant TTL override
            ttl_days = cfg.get("sandbox_ttl_days")
            if ttl_days is None:
                ttl_days = default_ttl_days
            else:
                try:
                    ttl_days = int(ttl_days)
                except (TypeError, ValueError):
                    errors.append((tenant_id, f"invalid sandbox_ttl_days: {ttl_days!r}"))
                    continue
            if ttl_days < MIN_TTL_DAYS:
                errors.append((tenant_id, f"sandbox_ttl_days < {MIN_TTL_DAYS}: {ttl_days}"))
                continue

            # Age check (mtime of the sandbox dir itself)
            mtime = datetime.fromtimestamp(
                sandbox_dir.stat().st_mtime, tz=timezone.utc
            )
            age = eval_time - mtime
            if age < timedelta(days=ttl_days):
                skipped_fresh.append(tenant_id)
                continue

            # Archive (unless dry-run)
            if dry_run:
                report_archived.append(tenant_id)
                logger.info(
                    "sandbox_gc[dry-run]: would archive %s (age=%dd, ttl=%dd)",
                    tenant_id, age.days, ttl_days,
                )
            else:
                try:
                    dest = archive_sandbox(tenant_id)
                    report_archived.append(tenant_id)
                    logger.info(
                        "sandbox_gc: archived %s → %s (age=%dd, ttl=%dd)",
                        tenant_id, dest, age.days, ttl_days,
                    )
                except Exception as e:  # noqa: BLE001
                    errors.append((tenant_id, f"archive failed: {e}"))

        except Exception as e:  # noqa: BLE001
            errors.append((tenant_id, f"scan error: {e}"))

    return GCReport(
        scanned_count=scanned,
        archived=report_archived,
        skipped_published=skipped_published,
        skipped_fresh=skipped_fresh,
        errors=errors,
        run_at=eval_time.isoformat(),
        dry_run=dry_run,
    )
