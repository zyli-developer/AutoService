"""T4B.1 — Unit tests for ``autoservice.dream_scheduler.should_trigger``.

The function is **yellow** — decision strategy that gates a cost-bearing
LLM call. We want exhaustive coverage of each decision path so reviewers
can verify rule ordering and default thresholds at a glance.

All tests use an in-memory dream_runs connection + a lightweight mempool
stub so no fixture depends on the real ``.autoservice/`` tree.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from autoservice import dream_runs
from autoservice.dream_scheduler import (
    DEFAULT_COOL_DOWN_MIN,
    DEFAULT_IDLE_THRESHOLD_MIN,
    should_trigger,
)


UTC = timezone.utc


# ── Fixtures ───────────────────────────────────────────────────────────────


class FakeMemPool:
    """Minimal MemoryPool stand-in — only ``last_message_at`` is exercised."""

    def __init__(self, last: datetime | None = None) -> None:
        self.last = last

    def last_message_at(self, tenant_id: str) -> datetime | None:  # noqa: ARG002
        return self.last


@pytest.fixture()
def runs_db() -> sqlite3.Connection:
    """In-memory ``dream_runs`` connection."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    dream_runs.init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def now() -> datetime:
    """A stable "now" so assertions involving arithmetic are predictable."""
    return datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)


def _insert_run(
    conn: sqlite3.Connection,
    tenant_id: str,
    *,
    status: str,
    started_at: datetime,
    ended_at: datetime | None = None,
    proposals_emitted: int = 0,
) -> None:
    """Bypass dream_runs' public API so tests can fabricate arbitrary rows."""
    import uuid
    conn.execute(
        "INSERT INTO dream_runs "
        "(id, tenant_id, started_at, ended_at, status, "
        " tool_calls, tokens_in, tokens_out, proposals_emitted) "
        "VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?)",
        (
            uuid.uuid4().hex,
            tenant_id,
            started_at.isoformat(),
            ended_at.isoformat() if ended_at else None,
            status,
            proposals_emitted,
        ),
    )
    conn.commit()


# ── Manual-mode blocks ─────────────────────────────────────────────────────


def test_manual_mode_always_blocks(runs_db, now):
    """trigger='manual' → (False, 'manual_only'), regardless of other state."""
    # Even with an old last-message (would normally trigger idle), manual
    # must always short-circuit.
    mempool = FakeMemPool(last=now - timedelta(hours=2))
    cfg = {"trigger": "manual"}

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is False
    assert reason == "manual_only"


# ── Scheduled-mode behaviour ───────────────────────────────────────────────


def test_scheduled_triggers_within_window(runs_db, now):
    """scheduled + scheduled_at within ±10min → fires."""
    # now is 12:00 — scheduled_at=12:05 is 5 minutes away (inside 10min window).
    cfg = {"trigger": "scheduled", "scheduled_at": "12:05"}
    mempool = FakeMemPool(last=now - timedelta(hours=1))

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is True
    assert reason == "scheduled_hit"


def test_scheduled_blocks_outside_window(runs_db, now):
    """scheduled + scheduled_at far from now → no fire."""
    cfg = {"trigger": "scheduled", "scheduled_at": "03:00"}
    mempool = FakeMemPool(last=now - timedelta(hours=1))

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is False
    assert reason == "scheduled_miss"


# ── Idle mode ──────────────────────────────────────────────────────────────


def test_idle_triggers_when_last_message_old_enough(runs_db, now):
    """idle + last_msg older than threshold → fires."""
    # Default threshold = 30min; last message 45min ago.
    mempool = FakeMemPool(last=now - timedelta(minutes=45))
    cfg = {"trigger": "idle"}

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is True
    assert reason == "idle"
    # Sanity: the default is what we expect — guards against accidental
    # drift of the threshold.
    assert DEFAULT_IDLE_THRESHOLD_MIN == 30


def test_idle_blocks_when_tenant_still_active(runs_db, now):
    """idle + last_msg within threshold → (False, 'not_idle')."""
    mempool = FakeMemPool(last=now - timedelta(minutes=5))
    cfg = {"trigger": "idle"}

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is False
    assert reason == "not_idle"


def test_low_peak_alias_treated_as_idle(runs_db, now):
    """The legacy dialog value 'low_peak' maps to idle semantics."""
    mempool = FakeMemPool(last=now - timedelta(minutes=60))
    cfg = {"trigger": "low_peak"}

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is True
    assert reason == "idle"


# ── Cool-down gate ─────────────────────────────────────────────────────────


def test_cool_down_blocks_for_60_minutes(runs_db, now):
    """A completed run ended 10min ago → cool_down_active."""
    # Seed a completed run ending 10 minutes ago — well within default
    # cool_down=60min.
    _insert_run(
        runs_db, "acme",
        status="completed",
        started_at=now - timedelta(minutes=15),
        ended_at=now - timedelta(minutes=10),
    )
    mempool = FakeMemPool(last=now - timedelta(hours=2))  # would otherwise fire
    cfg = {"trigger": "idle"}

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is False
    assert reason == "cool_down_active"
    # Same guard for the constant as on idle.
    assert DEFAULT_COOL_DOWN_MIN == 60


def test_cool_down_expired_allows_trigger(runs_db, now):
    """A run ended 2h ago → cool-down expired, idle fires normally."""
    _insert_run(
        runs_db, "acme",
        status="completed",
        started_at=now - timedelta(hours=2, minutes=10),
        ended_at=now - timedelta(hours=2),
    )
    mempool = FakeMemPool(last=now - timedelta(minutes=45))
    cfg = {"trigger": "idle"}

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is True
    assert reason == "idle"


# ── Active-run guard (ordering) ────────────────────────────────────────────


def test_active_running_row_blocks_immediately(runs_db, now):
    """A row with status='running' → always blocks, even if idle would fire."""
    _insert_run(
        runs_db, "acme",
        status="running",
        started_at=now - timedelta(minutes=5),
    )
    # Mempool says tenant is very idle — should be overridden.
    mempool = FakeMemPool(last=now - timedelta(hours=3))
    cfg = {"trigger": "idle"}

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is False
    assert reason == "already_running"


def test_running_check_runs_before_cool_down_check(runs_db, now):
    """Rule ordering: running-row takes precedence over cool-down reason.

    When a tenant has BOTH a 'running' row AND a recent terminal row, the
    response must be 'already_running' (not 'cool_down_active') so
    operators see the correct state in logs.
    """
    _insert_run(
        runs_db, "acme",
        status="running",
        started_at=now - timedelta(minutes=5),
    )
    _insert_run(
        runs_db, "acme",
        status="completed",
        started_at=now - timedelta(minutes=30),
        ended_at=now - timedelta(minutes=20),
    )
    mempool = FakeMemPool(last=now - timedelta(hours=2))
    cfg = {"trigger": "idle"}

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is False
    assert reason == "already_running"


# ── never_active ───────────────────────────────────────────────────────────


def test_never_active_tenant_blocks(runs_db, now):
    """A tenant with no memory turns at all → never_active."""
    mempool = FakeMemPool(last=None)
    cfg = {"trigger": "idle"}

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is False
    assert reason == "never_active"


# ── Coverage gate ──────────────────────────────────────────────────────────


def test_coverage_none_blocks(runs_db, now):
    """coverage='none' → coverage_disabled, even on an otherwise idle tenant."""
    mempool = FakeMemPool(last=now - timedelta(hours=2))
    cfg = {"trigger": "idle", "coverage": "none"}

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is False
    assert reason == "coverage_disabled"


# ── Risk/high soft gate ────────────────────────────────────────────────────


def test_risk_high_without_recent_signal_blocks(runs_db, now):
    """risk='high' + no proposals in lookback → insufficient_signal."""
    # No proposals_emitted > 0 rows in runs_db → heuristic blocks.
    mempool = FakeMemPool(last=now - timedelta(hours=2))
    cfg = {"trigger": "idle", "risk_threshold": "high"}

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is False
    assert reason == "insufficient_signal"


def test_risk_high_with_recent_signal_allows(runs_db, now):
    """risk='high' + at least one emitting run in lookback → fires normally."""
    _insert_run(
        runs_db, "acme",
        status="completed",
        started_at=now - timedelta(days=3),
        ended_at=now - timedelta(days=3) + timedelta(minutes=5),
        proposals_emitted=2,
    )
    mempool = FakeMemPool(last=now - timedelta(hours=2))
    cfg = {"trigger": "idle", "risk_threshold": "high"}

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is True
    assert reason == "idle"


# ── Reason-code exhaustiveness (meta-test) ─────────────────────────────────


EXPECTED_REASON_CODES = {
    "manual_only",
    "already_running",
    "cool_down_active",
    "coverage_disabled",
    "insufficient_signal",
    "never_active",
    "not_idle",
    "idle",
    "scheduled_hit",
    "scheduled_miss",
    "unknown_trigger",
}


def test_unknown_trigger_maps_to_safe_default(runs_db, now):
    """Config with a garbage trigger value → (False, 'unknown_trigger').

    Fail-safe: never auto-fire on an unrecognised mode. A config migration
    bug should not silently spawn dream runs.
    """
    mempool = FakeMemPool(last=now - timedelta(hours=2))
    cfg = {"trigger": "on_monday_mornings"}

    fired, reason = should_trigger("acme", cfg, mempool, runs_db, now=now)

    assert fired is False
    assert reason == "unknown_trigger"
    # And every reason we assert in this file is in the expected vocabulary.
    assert reason in EXPECTED_REASON_CODES


def test_all_emitted_reason_codes_are_in_the_expected_vocabulary(runs_db, now):
    """Smoke test: the union of reasons returned by the cases above is the
    documented vocabulary — if this fails, either a case stopped exercising
    a path or the vocabulary drifted."""
    mempool_idle = FakeMemPool(last=now - timedelta(minutes=45))
    mempool_active = FakeMemPool(last=now - timedelta(minutes=5))
    mempool_none = FakeMemPool(last=None)

    # Seed scenarios minimally sufficient to hit each branch.
    cases = [
        ("acme1", {"trigger": "manual"}, mempool_idle),
        ("acme2", {"trigger": "idle"}, mempool_idle),        # idle
        ("acme3", {"trigger": "idle"}, mempool_active),       # not_idle
        ("acme4", {"trigger": "idle"}, mempool_none),         # never_active
        ("acme5", {"trigger": "idle", "coverage": "none"}, mempool_idle),
        ("acme6", {"trigger": "scheduled", "scheduled_at": "12:05"}, mempool_idle),
        ("acme7", {"trigger": "scheduled", "scheduled_at": "03:00"}, mempool_idle),
        ("acme8", {"trigger": "unknown_mode"}, mempool_idle),
    ]
    emitted: set[str] = set()
    for tid, cfg, mp in cases:
        _, reason = should_trigger(tid, cfg, mp, runs_db, now=now)
        emitted.add(reason)

    # Add the two reason codes exercised in dedicated tests elsewhere above.
    emitted |= {"already_running", "cool_down_active", "insufficient_signal"}

    assert emitted == EXPECTED_REASON_CODES, (
        f"reason-code drift: emitted={sorted(emitted)} "
        f"expected={sorted(EXPECTED_REASON_CODES)}"
    )
