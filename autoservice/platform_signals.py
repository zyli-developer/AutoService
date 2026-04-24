"""Platform-level cross-tenant signal collection (M3 T4S.4).

Contract: docs/contracts/m3/e5-dream.md v1.1 §1.4.

**SCOPE — T4S.4**: establish the READ-ONLY cross-tenant signal
collection surface.  Consumers (master dream agent in T4S.4b+) will
inject this module's :func:`gather_platform_signals` into their
analysis loop.  M3 T4S.4 delivers:

* ``PlatformSignals`` frozen dataclass — aggregate counts/gauges only
* ``gather_platform_signals()`` pure read — no writes, no side-effects
* Privacy boundary: aggregate counts only, never raw PII / message content
* Optional ``cc_pool.metrics()`` integration (skeleton-tolerant)

**Decoupled from master_dream_agent**: this module is intentionally
independent so the CON-04 5-layer defense on master_dream_agent stays
focused on its audited scope.  T4S.4b will wire signal-driven LLM
suggestions into master_dream_agent via an explicit import of
``gather_platform_signals`` — at that point the integration gets its
own code-reviewer pass.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import asdict, dataclass


logger = logging.getLogger("autoservice.platform_signals")


@dataclass(frozen=True)
class PlatformSignals:
    """Read-only cross-tenant aggregate snapshot.

    Fields are counts/gauges, never raw messages or PII.  Adding a field
    requires the value producer to expose a counts-level API.
    """
    tenant_count: int
    active_tenants: list[str]          # tenant_ids with at least 1 proposal
    total_proposal_count: int
    per_tenant_proposal_counts: dict[str, int]  # tid → count
    pool_metrics: dict | None          # AsyncPool.metrics() snapshot or None
    emitted_at_ms: int


def gather_platform_signals(
    proposals_conn: sqlite3.Connection,
    cc_pool=None,
) -> PlatformSignals:
    """Collect cross-tenant aggregates into a :class:`PlatformSignals`.

    Args:
        proposals_conn: SQLite connection to the proposals DB (read-only
            use; no writes).
        cc_pool: optional object with a ``metrics()`` method returning
            a :class:`socialware.pool.PoolMetrics` dataclass.  Missing
            or broken → ``pool_metrics=None`` (soft dependency).

    Returns:
        :class:`PlatformSignals` snapshot.

    Privacy: aggregate counts only.  If future fields require message
    content access, that's a T4S.4b architectural question — reject the
    change at review time.
    """
    # Proposals: per-tenant counts
    per_tenant_counts: dict[str, int] = {}
    rows = proposals_conn.execute(
        "SELECT tenant_id, COUNT(*) AS n FROM proposals "
        "GROUP BY tenant_id ORDER BY tenant_id"
    ).fetchall()
    for r in rows:
        per_tenant_counts[r["tenant_id"]] = int(r["n"])

    total = sum(per_tenant_counts.values())
    active = sorted(per_tenant_counts.keys())

    # cc_pool.metrics() — optional
    pool_metrics_dict = None
    if cc_pool is not None:
        try:
            if hasattr(cc_pool, "metrics"):
                pool_metrics_dict = asdict(cc_pool.metrics())
        except Exception:  # noqa: BLE001
            logger.debug("cc_pool.metrics() unavailable", exc_info=True)

    return PlatformSignals(
        tenant_count=len(active),
        active_tenants=active,
        total_proposal_count=total,
        per_tenant_proposal_counts=per_tenant_counts,
        pool_metrics=pool_metrics_dict,
        emitted_at_ms=int(time.time() * 1000),
    )
