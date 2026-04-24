"""Tests for ``autoservice.platform_signals`` (M3 T4S.4).

Contract: docs/contracts/m3/e5-dream.md v1.1 §1.4.

T4S.4 is intentionally decoupled from master_dream_agent per T2S.8 reviewer
pref (keeps CON-04 audit surface minimal).  T4S.4b wires these signals
into the master dream LLM loop.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

import pytest

from autoservice import platform_signals, proposal_pipeline


@pytest.fixture()
def proposals_conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    proposal_pipeline.apply_schema(c)
    yield c
    c.close()


def _seed(conn, tenant_id: str, *, n: int):
    for i in range(n):
        pid = f"{tenant_id}-p-{i}"
        conn.execute(
            "INSERT INTO proposals (id, created_at, data, status, category, tenant_id) "
            "VALUES (?, ?, ?, 'draft', 'workflow', ?)",
            (pid, "2026-04-21T00:00:00", json.dumps({"id": pid}), tenant_id),
        )
    conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# Empty DB
# ──────────────────────────────────────────────────────────────────────────


def test_empty_db_returns_zero_counts(proposals_conn):
    s = platform_signals.gather_platform_signals(proposals_conn)
    assert s.tenant_count == 0
    assert s.active_tenants == []
    assert s.total_proposal_count == 0
    assert s.per_tenant_proposal_counts == {}
    assert s.pool_metrics is None
    assert s.emitted_at_ms > 0


# ──────────────────────────────────────────────────────────────────────────
# Per-tenant aggregation
# ──────────────────────────────────────────────────────────────────────────


def test_counts_proposals_per_tenant(proposals_conn):
    _seed(proposals_conn, "acme", n=2)
    _seed(proposals_conn, "beta-corp", n=3)

    s = platform_signals.gather_platform_signals(proposals_conn)
    assert s.tenant_count == 2
    assert set(s.active_tenants) == {"acme", "beta-corp"}
    assert s.total_proposal_count == 5
    assert s.per_tenant_proposal_counts == {"acme": 2, "beta-corp": 3}


def test_active_tenants_sorted_alphabetically(proposals_conn):
    for tid in ("zulu-co", "alpha-co", "mike-co"):
        _seed(proposals_conn, tid, n=1)
    s = platform_signals.gather_platform_signals(proposals_conn)
    assert s.active_tenants == ["alpha-co", "mike-co", "zulu-co"]


# ──────────────────────────────────────────────────────────────────────────
# cc_pool integration (optional)
# ──────────────────────────────────────────────────────────────────────────


def test_includes_pool_metrics_when_provided(proposals_conn):
    @dataclass(frozen=True)
    class _M:
        available_count: int = 3
        busy_count: int = 1
        queue_length: int = 0
        wait_time_histogram_ms: dict = None  # type: ignore[assignment]
        total_checkouts: int = 10
        total_timeouts: int = 0
        emitted_at_ms: int = 0

    class _FakePool:
        def metrics(self):
            return _M(wait_time_histogram_ms={"0-100": 10})

    s = platform_signals.gather_platform_signals(
        proposals_conn, cc_pool=_FakePool()
    )
    assert s.pool_metrics is not None
    assert s.pool_metrics["available_count"] == 3
    assert s.pool_metrics["busy_count"] == 1


def test_tolerates_broken_pool(proposals_conn):
    class _BadPool:
        def metrics(self):
            raise RuntimeError("pool down")

    s = platform_signals.gather_platform_signals(
        proposals_conn, cc_pool=_BadPool()
    )
    assert s.pool_metrics is None  # soft dep: error swallowed, returns None


def test_pool_without_metrics_method_accepted(proposals_conn):
    """Any object is fine; only attempts .metrics() if method present."""
    class _NoMetricsPool:
        pass

    s = platform_signals.gather_platform_signals(
        proposals_conn, cc_pool=_NoMetricsPool()
    )
    assert s.pool_metrics is None


# ──────────────────────────────────────────────────────────────────────────
# Privacy boundary — aggregate counts only, no content
# ──────────────────────────────────────────────────────────────────────────


def test_signals_dataclass_has_no_content_fields():
    """Regression guard: PlatformSignals must not accidentally grow a
    field that carries message content or PII.  Defensive schema check."""
    field_names = {f.name for f in platform_signals.PlatformSignals.__dataclass_fields__.values()}
    forbidden = {"messages", "content", "conversations", "emails", "pii"}
    assert not (field_names & forbidden), (
        f"PlatformSignals grew content fields: {field_names & forbidden}. "
        "Privacy boundary violation."
    )


def test_signals_are_frozen():
    s = platform_signals.PlatformSignals(
        tenant_count=0, active_tenants=[], total_proposal_count=0,
        per_tenant_proposal_counts={}, pool_metrics=None, emitted_at_ms=0,
    )
    with pytest.raises(Exception):
        s.tenant_count = 99  # type: ignore[misc]
