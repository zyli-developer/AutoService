"""Unit tests for socialware.pool observability metrics (M3 T2S.3).

Contract: docs/contracts/m3/e3-triage.md §1.2 PoolMetrics.
"""
from __future__ import annotations

import asyncio

import pytest

from socialware.pool import (
    AsyncPool,
    PoolConfig,
    PoolMetrics,
    WAIT_TIME_BUCKETS_MS,
    _bucket_for_wait_ms,
)


class _StubClient:
    def __init__(self) -> None:
        self._healthy = True

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    def is_healthy(self) -> bool:
        return self._healthy


async def _factory() -> _StubClient:
    c = _StubClient()
    await c.connect()
    return c


@pytest.fixture()
async def pool():
    p = AsyncPool(
        PoolConfig(min_size=2, max_size=2, warmup_count=2, checkout_timeout=1.0),
        factory=_factory,
        instance_prefix="test",
    )
    await p.start()
    yield p
    await p.shutdown()


# ──────────────────────────────────────────────────────────────────────────
# Histogram bucket classification
# ──────────────────────────────────────────────────────────────────────────


def test_bucket_boundaries():
    assert _bucket_for_wait_ms(0.0) == "0-100"
    assert _bucket_for_wait_ms(50.0) == "0-100"
    assert _bucket_for_wait_ms(100.0) == "100-500"
    assert _bucket_for_wait_ms(499.9) == "100-500"
    assert _bucket_for_wait_ms(500.0) == "500-1000"
    assert _bucket_for_wait_ms(1500.0) == "1000-5000"
    assert _bucket_for_wait_ms(9999.0) == "5000+"


def test_buckets_config_shape():
    labels = [label for (_upper, label) in WAIT_TIME_BUCKETS_MS]
    assert labels == ["0-100", "100-500", "500-1000", "1000-5000", "5000+"]


# ──────────────────────────────────────────────────────────────────────────
# Metrics snapshot
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metrics_initial_state(pool):
    m = pool.metrics()
    assert isinstance(m, PoolMetrics)
    assert m.available_count == 2
    assert m.busy_count == 0
    assert m.queue_length == 0
    assert m.total_checkouts == 0
    assert m.total_timeouts == 0
    assert sum(m.wait_time_histogram_ms.values()) == 0


@pytest.mark.asyncio
async def test_busy_count_reflects_checkouts(pool):
    async with pool.acquire() as inst1:
        m = pool.metrics()
        assert m.busy_count == 1
        assert m.available_count == 1

        async with pool.acquire() as inst2:
            m2 = pool.metrics()
            assert m2.busy_count == 2
            assert m2.available_count == 0
        # inst2 returned
        m3 = pool.metrics()
        assert m3.busy_count == 1
    # inst1 returned
    m4 = pool.metrics()
    assert m4.busy_count == 0


@pytest.mark.asyncio
async def test_checkouts_counted(pool):
    async with pool.acquire():
        pass
    async with pool.acquire():
        pass
    m = pool.metrics()
    assert m.total_checkouts == 2


@pytest.mark.asyncio
async def test_wait_histogram_populated_on_fast_checkout(pool):
    async with pool.acquire():
        pass
    m = pool.metrics()
    # Fast checkout from pre-warmed pool — should land in 0-100 bucket
    assert m.wait_time_histogram_ms["0-100"] >= 1


@pytest.mark.asyncio
async def test_queue_length_increments_when_pool_exhausted():
    """When pool is at max_size and all busy, concurrent checkouts queue up."""
    p = AsyncPool(
        PoolConfig(min_size=1, max_size=1, warmup_count=1, checkout_timeout=5.0),
        factory=_factory,
        instance_prefix="q",
    )
    await p.start()
    try:
        # Hold the only instance
        inst = await p.checkout()

        # Launch 3 concurrent checkouts that will block
        tasks = [asyncio.create_task(p.checkout()) for _ in range(3)]

        # Give them time to enter the wait path
        await asyncio.sleep(0.05)

        m = p.metrics()
        assert m.queue_length == 3, f"expected 3 waiters, got {m.queue_length}"
        assert m.busy_count == 1
        assert m.available_count == 0

        # Release the held instance → cascade-release the waiters
        await p.checkin(inst)
        # First waiter gets it; check it out and in to release the next
        released = await tasks[0]
        await p.checkin(released)
        released2 = await tasks[1]
        await p.checkin(released2)
        released3 = await tasks[2]
        await p.checkin(released3)

        m_final = p.metrics()
        assert m_final.queue_length == 0
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_timeout_counted():
    """Pool at max, no release → checkout timeout increments counter."""
    p = AsyncPool(
        PoolConfig(min_size=1, max_size=1, warmup_count=1, checkout_timeout=0.05),
        factory=_factory,
        instance_prefix="to",
    )
    await p.start()
    try:
        inst = await p.checkout()  # hold the only instance

        with pytest.raises(TimeoutError):
            await p.checkout()  # will time out after 50ms

        m = p.metrics()
        assert m.total_timeouts == 1
        assert m.total_checkouts >= 2  # both attempts counted

        await p.checkin(inst)
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_metrics_snapshot_is_immutable():
    """PoolMetrics is frozen dataclass — histogram dict is a copy, not the live one."""
    p = AsyncPool(
        PoolConfig(min_size=1, max_size=1, warmup_count=1),
        factory=_factory,
        instance_prefix="imm",
    )
    await p.start()
    try:
        async with p.acquire():
            pass
        m1 = p.metrics()
        # Mutating the snapshot dict must not affect live counters
        m1.wait_time_histogram_ms["0-100"] = 99999
        m2 = p.metrics()
        assert m2.wait_time_histogram_ms["0-100"] < 99999
    finally:
        await p.shutdown()
